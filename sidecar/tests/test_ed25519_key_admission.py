"""Reject weak configured keys without changing historical evidence bytes."""

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from sidecar.vcp_core import VCPSigner


P = 2**255 - 19
SMALL_ORDER_KEYS = (
    "0100000000000000000000000000000000000000000000000000000000000000",
    "ecffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff7f",
    "0000000000000000000000000000000000000000000000000000000000000000",
    "0000000000000000000000000000000000000000000000000000000000000080",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc05",
    "26e8958fc2b227b045c3f489f2ef98f0d5dfac05d3c63339b13802886d53fc85",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac037a",
    "c7176a703d4dd84fba3c0b760d10670f2a2053fa2c39ccc64ec7fd7792ac03fa",
)


def noncanonical_keys():
    for y in range(P, 2**255):
        for sign in (0, 1):
            yield (y | (sign << 255)).to_bytes(32, "little")
    for y in (1, P - 1):
        yield (y | (1 << 255)).to_bytes(32, "little")


@pytest.mark.parametrize("key_hex", SMALL_ORDER_KEYS)
def test_small_order_key_cannot_be_configured(key_hex):
    public_key = Ed25519PublicKey.from_public_bytes(bytes.fromhex(key_hex))
    with pytest.raises(ValueError, match="small-order"):
        VCPSigner(public_key=public_key)


@pytest.mark.parametrize("raw", list(noncanonical_keys()))
def test_noncanonical_key_cannot_be_configured(raw):
    public_key = Ed25519PublicKey.from_public_bytes(raw)
    with pytest.raises(ValueError, match="noncanonical"):
        VCPSigner(public_key=public_key)


def test_identity_key_cannot_enter_through_pem_loading(tmp_path):
    signer = VCPSigner.generate()
    private_path, public_path = tmp_path / "private.pem", tmp_path / "public.pem"
    signer.save_to_files(str(private_path), str(public_path))
    identity = Ed25519PublicKey.from_public_bytes(b"\x01" + bytes(31))
    public_path.write_bytes(identity.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ))
    with pytest.raises(ValueError, match="small-order"):
        VCPSigner.load_from_files(str(private_path), str(public_path))


def test_generated_and_reloaded_keys_keep_valid_signature_behavior(tmp_path):
    signer = VCPSigner.generate()
    private_path, public_path = tmp_path / "private.pem", tmp_path / "public.pem"
    signer.save_to_files(str(private_path), str(public_path))
    reloaded = VCPSigner.load_from_files(str(private_path), str(public_path))
    public_only = VCPSigner(public_key=Ed25519PublicKey.from_public_bytes(
        bytes.fromhex(signer.get_public_key_hex())
    ))
    signature = signer.sign(b"original message")
    for verifier in (signer, reloaded, public_only):
        assert verifier.verify(b"original message", signature) is True
        assert verifier.verify(b"changed message", signature) is False
        assert verifier.verify(b"original message", b"\x01" + bytes(63)) is False
