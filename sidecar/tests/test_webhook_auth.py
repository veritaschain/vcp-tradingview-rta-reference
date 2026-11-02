"""Synthetic in-process requests; no live trading, network calls or key files."""

import asyncio
import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient

from sidecar import main


SECRET = "synthetic-test-credential-only"
PAYLOAD = {
    "vcp_version": "1.1", "event_id": "synthetic-001",
    "timestamp": "2026-11-02T00:00:00Z", "event_type": "ORDER_NEW",
    "policy_id": "urn:synthetic:test", "system_id": "synthetic",
    "account_id": "example", "payload": {"symbol": "TEST"},
}


@pytest.fixture
def runtime(monkeypatch):
    settings = copy.deepcopy(main.config)
    settings["server"]["webhook_secret"] = SECRET
    monkeypatch.setattr(main, "config", settings)
    store = SimpleNamespace(store=AsyncMock(), get=AsyncMock(), list=AsyncMock(), count=AsyncMock())
    signer = Mock()
    signer.sign.return_value = b"\x01" * 64
    tree = Mock()
    tree.add_leaf.return_value = 0
    tree.size = 1
    anchor = SimpleNamespace(anchor=AsyncMock())
    monkeypatch.setattr(main, "event_store", store)
    monkeypatch.setattr(main, "signer", signer)
    monkeypatch.setattr(main, "merkle_tree", tree)
    monkeypatch.setattr(main, "anchor_service", anchor)
    return store, signer, tree, anchor


def assert_no_side_effects(runtime):
    store, signer, tree, anchor = runtime
    signer.sign.assert_not_called()
    tree.add_leaf.assert_not_called()
    tree.reset.assert_not_called()
    store.store.assert_not_awaited()
    store.get.assert_not_awaited()
    store.list.assert_not_awaited()
    anchor.anchor.assert_not_awaited()


@pytest.mark.parametrize("value", [None, "", "  ", 42])
def test_invalid_secret_refuses_startup_before_initialization(monkeypatch, value):
    monkeypatch.setattr(main, "config", {"server": {"webhook_secret": value}})
    constructors = [Mock(), Mock(), Mock()]
    for name, constructor in zip(("VCPEventStore", "MerkleTree", "AnchorService"), constructors):
        monkeypatch.setattr(main, name, constructor)
    with pytest.raises(ValueError, match="nonempty"):
        asyncio.run(main.startup_event())
    for constructor in constructors:
        constructor.assert_not_called()


def test_explicit_empty_environment_secret_does_not_fall_back(monkeypatch, tmp_path):
    config_file = tmp_path / "settings.yaml"
    config_file.write_text("server:\n  webhook_secret: yaml-credential\n")
    monkeypatch.setattr(main, "CONFIG_PATH", config_file)
    monkeypatch.setenv("VCP_WEBHOOK_SECRET", "")
    loaded = main.load_config()
    assert loaded["server"]["webhook_secret"] == ""
    monkeypatch.setattr(main, "config", loaded)
    with pytest.raises(ValueError):
        main.configured_webhook_secret()
    monkeypatch.setenv("VCP_WEBHOOK_SECRET", SECRET)
    assert main.load_config()["server"]["webhook_secret"] == SECRET


@pytest.mark.parametrize("headers,body_secret", [
    ({}, None), ({}, ""), ({}, "wrong"),
    ({"X-VCP-Webhook-Secret": "wrong"}, None),
    ({"X-VCP-Webhook-Secret": SECRET}, "wrong"),
    ({"X-VCP-Webhook-Secret": "wrong"}, SECRET),
    ([("X-VCP-Webhook-Secret", SECRET), ("X-VCP-Webhook-Secret", "wrong")], None),
])
def test_unauthorized_event_has_no_processing_effects(runtime, headers, body_secret):
    payload = dict(PAYLOAD)
    if body_secret is not None:
        payload["webhook_secret"] = body_secret
    response = TestClient(main.app).post("/vcp/event", headers=headers, json=payload)
    assert response.status_code == 401
    assert SECRET not in response.text
    assert_no_side_effects(runtime)


@pytest.mark.parametrize("mode", ["header", "body", "both"])
def test_authenticated_event_excludes_transport_secret(runtime, mode, caplog):
    payload = dict(PAYLOAD)
    headers = {"X-VCP-Webhook-Secret": SECRET} if mode != "body" else {}
    if mode != "header":
        payload["webhook_secret"] = SECRET
    response = TestClient(main.app).post("/vcp/event", headers=headers, json=payload)
    assert response.status_code == 200
    store, signer, tree, _ = runtime
    signer.sign.assert_called_once()
    tree.add_leaf.assert_called_once()
    store.store.assert_awaited_once()
    event = store.store.await_args.args[0]
    assert not hasattr(event, "webhook_secret")
    assert SECRET not in event.to_canonical_json()
    assert SECRET not in response.text
    assert SECRET not in caplog.text


@pytest.mark.parametrize("method,path", [
    ("post", "/vcp/anchor/force"), ("get", "/vcp/events"),
    ("get", "/vcp/proof/synthetic-001"), ("get", "/vcp/verify/synthetic-001"),
    ("get", "/vcp/anchor/status"),
])
def test_other_vcp_endpoints_require_credentials_before_actions(runtime, method, path):
    response = getattr(TestClient(main.app), method)(path)
    assert response.status_code == 401
    assert_no_side_effects(runtime)


def test_lost_configuration_fails_closed(runtime, monkeypatch):
    monkeypatch.setitem(main.config["server"], "webhook_secret", "")
    response = TestClient(main.app).post("/vcp/event", json=PAYLOAD,
                                        headers={"X-VCP-Webhook-Secret": SECRET})
    assert response.status_code == 503
    assert_no_side_effects(runtime)


@pytest.mark.parametrize("origins", ["*", ["*"], ["https://*.example.com"],
                                    ["https://console.example.com/path"], ["null"]])
def test_cors_rejects_wildcards_or_non_origins(origins):
    with pytest.raises(ValueError):
        main.create_app({"server": {"allowed_origins": origins}})


def test_cors_only_advertises_configured_origins_without_credentials():
    app = main.create_app({"server": {"allowed_origins": ["https://console.example.com"]}})
    client = TestClient(app)
    headers = {"Origin": "https://console.example.com",
               "Access-Control-Request-Method": "POST",
               "Access-Control-Request-Headers": "X-VCP-Webhook-Secret"}
    allowed = client.options("/vcp/event", headers=headers)
    assert allowed.status_code == 200
    assert allowed.headers["access-control-allow-origin"] == headers["Origin"]
    assert "access-control-allow-credentials" not in allowed.headers
    headers["Origin"] = "https://untrusted.example.com"
    denied = client.options("/vcp/event", headers=headers)
    assert denied.status_code == 400
    assert "access-control-allow-origin" not in denied.headers
