"""In-process anchor failure/race tests; no live providers or trading requests."""

import asyncio
import copy
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import httpx
import pytest

from sidecar import main
from sidecar.anchor import AnchorResult, AnchorService
from sidecar.merkle import MerkleTree


SECRET = "synthetic-anchor-test-secret"
HEADERS = {"X-VCP-Webhook-Secret": SECRET}


def result_for(root, outcome="success"):
    if outcome == "exception":
        raise RuntimeError("synthetic provider failure")
    if outcome == "missing":
        return None
    return AnchorResult(
        success=1 if outcome == "non_boolean" else outcome != "false",
        provider="synthetic",
        merkle_root=(b"\xff" * 32).hex() if outcome == "wrong_root" else root.hex(),
        timestamp="2026-11-02T00:00:00Z",
        anchor_id="synthetic-only",
    )


@pytest.fixture
def runtime(monkeypatch):
    settings = copy.deepcopy(main.config)
    settings["server"]["webhook_secret"] = SECRET
    monkeypatch.setattr(main, "config", settings)
    stored = {}

    async def store(event):
        stored[event.event_id] = event

    signer = Mock()
    signer.sign.return_value = b"\x11" * 64
    signer.verify.return_value = True
    event_store = SimpleNamespace(store=AsyncMock(side_effect=store),
                                  get=AsyncMock(side_effect=stored.get))
    anchor = SimpleNamespace(anchor=AsyncMock(side_effect=result_for),
                             get_status=AsyncMock(return_value="not_anchored"),
                             get_proof=AsyncMock(return_value=None),
                             last_anchor_time=None, next_anchor_time=None)
    monkeypatch.setattr(main, "event_store", event_store)
    monkeypatch.setattr(main, "signer", signer)
    monkeypatch.setattr(main, "anchor_service", anchor)
    monkeypatch.setattr(main, "merkle_tree", MerkleTree())
    monkeypatch.setattr(main, "_pending_anchor_tree", None)
    monkeypatch.setattr(main, "_anchor_lock", asyncio.Lock())
    return SimpleNamespace(anchor=anchor, stored=stored)


def client():
    # ASGITransport calls the app directly, without TCP sockets or startup I/O.
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),
                             base_url="http://in-process", headers=HEADERS)


async def submit(api, event_id):
    response = await api.post("/vcp/event", json={
        "vcp_version": "1.1", "event_id": event_id,
        "timestamp": "2026-11-02T00:00:00Z", "event_type": "ORDER_NEW",
        "policy_id": "urn:synthetic:test", "system_id": "synthetic",
        "account_id": "example", "payload": {"symbol": "TEST"},
    })
    assert response.status_code == 200
    return response.json()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["false", "exception", "wrong_root", "non_boolean", "missing"])
async def test_force_failure_never_reports_success_or_discards_batch(runtime, outcome, caplog):
    caplog.set_level(logging.INFO, logger="vcp-sidecar")
    async with client() as api:
        await submit(api, "original")
        original_tree = main.merkle_tree
        original_bytes = original_tree.to_dict()
        runtime.anchor.anchor.side_effect = lambda root: result_for(root, outcome)

        response = await api.post("/vcp/anchor/force")

        assert response.status_code == 502
        assert response.json().get("success") is not True
        assert "retained" in response.json()["detail"]
        assert main._pending_anchor_tree is original_tree
        assert original_tree.to_dict() == original_bytes
        assert main.pending_event_count() == 1
        assert (await api.get("/health")).json()["events_pending"] == 1
        assert "Anchor provider confirmed" not in caplog.text


@pytest.mark.asyncio
async def test_force_empty_batch_does_not_call_provider(runtime):
    async with client() as api:
        response = await api.post("/vcp/anchor/force")
    assert response.status_code == 400
    runtime.anchor.anchor.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["opentimestamps", "bitcoin", "tsa"])
async def test_bundled_external_stubs_cannot_clear_pending_events(runtime, monkeypatch, tmp_path, provider):
    # These bundled provider methods only simulate responses; no outbound I/O.
    service = AnchorService(provider=provider, storage_path=str(tmp_path))
    monkeypatch.setattr(main, "anchor_service", service)
    async with client() as api:
        await submit(api, "stub-event")
        original_root = main.merkle_tree.get_root()
        response = await api.post("/vcp/anchor/force")
    assert response.status_code == 502
    assert main.pending_event_count() == 1
    assert main._pending_anchor_tree.get_root() == original_root
    assert service.last_anchor_time is None
    assert service.next_anchor_time is None
    assert not service._anchor_records
    assert not (tmp_path / "records.json").exists()


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["success", "false", "exception", "cancelled"])
async def test_arrivals_survive_inflight_anchor_and_retry(runtime, outcome):
    started, release = asyncio.Event(), asyncio.Event()

    async def provider(root):
        started.set()
        await release.wait()
        return result_for(root, outcome)

    async with client() as api:
        for event_id in ("old-0", "old-1"):
            await submit(api, event_id)
        old_tree = main.merkle_tree
        old_root = old_tree.get_root()
        old_bytes = old_tree.to_dict()
        runtime.anchor.anchor.side_effect = provider
        attempt = asyncio.create_task(api.post("/vcp/anchor/force"))
        await asyncio.wait_for(started.wait(), timeout=2)

        for index in range(2):
            new_event = await submit(api, f"new-{index}")
            assert new_event["merkle_index"] == index
        active_tree = main.merkle_tree
        active_root = active_tree.get_root()
        active_bytes = active_tree.to_dict()
        recorded_before = {key: value.to_dict() for key, value in runtime.stored.items()}
        status = (await api.get("/vcp/anchor/status")).json()
        assert status["pending_events"] == 4
        assert status["merkle_root"] == old_root.hex()
        assert (await api.get("/health")).json()["events_pending"] == 4

        # Reused batch-local indices must select the event's own tree.
        for event_id, expected_root in (("old-0", old_root), ("new-0", active_root)):
            proof = (await api.get(f"/vcp/proof/{event_id}")).json()
            assert proof["merkle_root"] == expected_root.hex()
            assert MerkleTree.verify_proof(
                bytes.fromhex(proof["event_hash"]),
                [(node["position"], bytes.fromhex(node["hash"])) for node in proof["proof"]],
                expected_root,
            )
            verification = (await api.get(f"/vcp/verify/{event_id}")).json()
            assert verification["merkle_proof_valid"] is True

        if outcome == "cancelled":
            attempt.cancel()
            with pytest.raises(asyncio.CancelledError):
                await attempt
        else:
            release.set()
            response = await asyncio.wait_for(attempt, timeout=2)
            assert response.status_code == (200 if outcome == "success" else 502)

        assert old_tree.to_dict() == old_bytes
        assert main.merkle_tree is active_tree
        assert active_tree.to_dict() == active_bytes
        assert main.pending_event_count() == (2 if outcome == "success" else 4)
        if outcome == "success":
            assert (await api.get("/vcp/proof/old-0")).status_code == 409

        # A failed or cancelled request retries the same root first. The new
        # batch stays intact and is anchored by the subsequent request.
        runtime.anchor.anchor.side_effect = result_for
        expected_roots = [active_root] if outcome == "success" else [old_root, active_root]
        for expected_root in expected_roots:
            response = await api.post("/vcp/anchor/force")
            assert response.status_code == 200
            assert response.json()["success"] is True
            assert response.json()["merkle_root"] == expected_root.hex()
        assert [call.args[0] for call in runtime.anchor.anchor.await_args_list] == [old_root, *expected_roots]
        assert main.pending_event_count() == 0
        assert {key: value.to_dict() for key, value in runtime.stored.items()} == recorded_before
        # Retired proofs are unavailable; they must not be fabricated from a
        # later batch that happens to reuse the same index.
        assert (await api.get("/vcp/proof/old-0")).status_code == 409


@pytest.mark.asyncio
async def test_concurrent_force_requests_serialize_batches_without_losing_next_arrival(runtime):
    started = [asyncio.Event(), asyncio.Event()]
    release = [asyncio.Event(), asyncio.Event()]
    roots = []
    active_calls = 0
    max_active_calls = 0

    async def provider(root):
        nonlocal active_calls, max_active_calls
        index = len(roots)
        roots.append(root)
        active_calls += 1
        max_active_calls = max(max_active_calls, active_calls)
        started[index].set()
        try:
            await release[index].wait()
            return result_for(root)
        finally:
            active_calls -= 1

    runtime.anchor.anchor.side_effect = provider
    async with client() as api:
        await submit(api, "batch-one")
        root_one = main.merkle_tree.get_root()
        first = asyncio.create_task(api.post("/vcp/anchor/force"))
        await asyncio.wait_for(started[0].wait(), timeout=2)
        second = asyncio.create_task(api.post("/vcp/anchor/force"))
        await asyncio.sleep(0)
        assert runtime.anchor.anchor.await_count == 1
        assert not second.done()
        await submit(api, "batch-two")
        root_two = main.merkle_tree.get_root()
        release[0].set()
        assert (await asyncio.wait_for(first, timeout=2)).status_code == 200
        await asyncio.wait_for(started[1].wait(), timeout=2)
        await submit(api, "batch-three")
        root_three = main.merkle_tree.get_root()
        release[1].set()
        assert (await asyncio.wait_for(second, timeout=2)).status_code == 200

    assert roots == [root_one, root_two]
    assert max_active_calls == 1
    assert main.pending_event_count() == 1
    assert main.merkle_tree.get_root() == root_three
    assert runtime.stored["batch-three"].merkle_index == 0


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["false", "exception", "wrong_root"])
async def test_periodic_failure_retains_batch_without_success_log(runtime, monkeypatch, outcome, caplog):
    caplog.set_level(logging.INFO, logger="vcp-sidecar")
    main.merkle_tree.add_leaf(b"\x01" * 32)
    original_tree = main.merkle_tree
    original_root = original_tree.get_root()
    runtime.anchor.anchor.side_effect = lambda root: result_for(root, outcome)
    sleep = AsyncMock(side_effect=[None, asyncio.CancelledError()])
    monkeypatch.setattr(main.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await main.periodic_anchor()

    assert main._pending_anchor_tree is original_tree
    assert main.pending_event_count() == 1
    runtime.anchor.anchor.assert_awaited_once_with(original_root)
    assert "pending batch retained" in caplog.text
    assert "Anchor provider confirmed" not in caplog.text


@pytest.mark.asyncio
async def test_periodic_success_preserves_arrivals_during_provider_call(runtime, monkeypatch, caplog):
    caplog.set_level(logging.INFO, logger="vcp-sidecar")
    main.merkle_tree.add_leaf(b"\x01" * 32)
    original_root = main.merkle_tree.get_root()

    async def provider(root):
        async with client() as api:
            await submit(api, "arrived-during-periodic")
        return result_for(root)

    runtime.anchor.anchor.side_effect = provider
    monkeypatch.setattr(main.asyncio, "sleep", AsyncMock(side_effect=[None, asyncio.CancelledError()]))
    with pytest.raises(asyncio.CancelledError):
        await main.periodic_anchor()

    assert main._pending_anchor_tree is None
    assert main.pending_event_count() == 1
    assert main.merkle_tree.get_root() != original_root
    assert runtime.stored["arrived-during-periodic"].merkle_index == 0
    assert "Anchor provider confirmed" in caplog.text
