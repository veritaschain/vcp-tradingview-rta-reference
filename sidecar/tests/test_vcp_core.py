"""
VCP Core Unit Tests
VeritasChain Protocol v1.1

Tests:
- VCPEvent canonical JSON serialization
- Ed25519 signing and verification
- Merkle tree construction and proofs
- Event hash computation

Copyright (c) 2025 VeritasChain Standards Organization
License: MIT
"""

import hashlib
import json
import pytest
from datetime import datetime, timezone

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from sidecar.vcp_core import VCPEvent, VCPSigner, generate_event_id, compute_event_hash
from sidecar.merkle import MerkleTree


# ============================================================================
# VCPEvent Tests
# ============================================================================

class TestVCPEvent:
    """Test VCPEvent data model."""
    
    def create_sample_event(self) -> VCPEvent:
        """Create a sample VCP event for testing."""
        return VCPEvent(
            event_id="test-event-001",
            timestamp="2025-01-15T10:30:00.000Z",
            event_type="ORDER_NEW",
            tier="SILVER",
            policy_id="urn:vso:policy:tv-retail:v1",
            clock_sync="BEST_EFFORT",
            system_id="TV-STRATEGY-001",
            account_id="DEMO-ACCOUNT",
            payload={
                "order_id": "ORD-001",
                "symbol": "BTCUSD",
                "side": "BUY",
                "quantity": 1.0,
                "price": 50000.0
            }
        )
    
    def test_event_creation(self):
        """Test basic event creation."""
        event = self.create_sample_event()
        
        assert event.event_id == "test-event-001"
        assert event.event_type == "ORDER_NEW"
        assert event.tier == "SILVER"
        assert event.vcp_version == "1.1"
    
    def test_canonical_json_format(self):
        """Test canonical JSON serialization (RFC 8785)."""
        event = self.create_sample_event()
        canonical = event.to_canonical_json()
        
        # Should be valid JSON
        parsed = json.loads(canonical)
        
        # Keys should be sorted
        keys = list(parsed.keys())
        assert keys == sorted(keys), "Keys should be lexicographically sorted"
        
        # No whitespace (except in strings)
        assert "  " not in canonical, "Should have no extra whitespace"
        assert "\n" not in canonical, "Should have no newlines"
    
    def test_canonical_json_deterministic(self):
        """Test that canonical JSON is deterministic."""
        event1 = self.create_sample_event()
        event2 = self.create_sample_event()
        
        canonical1 = event1.to_canonical_json()
        canonical2 = event2.to_canonical_json()
        
        assert canonical1 == canonical2, "Same events should produce identical canonical JSON"
    
    def test_canonical_json_different_events(self):
        """Test that different events produce different canonical JSON."""
        event1 = self.create_sample_event()
        event2 = self.create_sample_event()
        event2.event_id = "test-event-002"
        
        canonical1 = event1.to_canonical_json()
        canonical2 = event2.to_canonical_json()
        
        assert canonical1 != canonical2, "Different events should produce different canonical JSON"
    
    def test_nested_payload_sorting(self):
        """Test that nested payload dictionaries are sorted."""
        event = self.create_sample_event()
        event.payload = {
            "zebra": 1,
            "apple": 2,
            "nested": {
                "z_key": "z",
                "a_key": "a"
            }
        }
        
        canonical = event.to_canonical_json()
        parsed = json.loads(canonical)
        
        # Check nested sorting
        payload_keys = list(parsed["payload"].keys())
        nested_keys = list(parsed["payload"]["nested"].keys())
        
        assert payload_keys == sorted(payload_keys)
        assert nested_keys == sorted(nested_keys)
    
    def test_to_dict_roundtrip(self):
        """Test dictionary serialization roundtrip."""
        event = self.create_sample_event()
        event_dict = event.to_dict()
        
        restored = VCPEvent.from_dict(event_dict)
        
        assert restored.event_id == event.event_id
        assert restored.event_type == event.event_type
        assert restored.payload == event.payload


# ============================================================================
# VCPSigner Tests
# ============================================================================

class TestVCPSigner:
    """Test Ed25519 signing functionality."""
    
    def test_key_generation(self):
        """Test key pair generation."""
        signer = VCPSigner.generate()
        
        assert signer is not None
        assert signer.get_public_key_hex() is not None
        assert len(signer.get_public_key_hex()) == 64  # 32 bytes = 64 hex chars
    
    def test_sign_and_verify(self):
        """Test signing and verification."""
        signer = VCPSigner.generate()
        
        message = b"Test message for VCP"
        signature = signer.sign(message)
        
        assert signature is not None
        assert len(signature) == 64  # Ed25519 signature is 64 bytes
        
        # Verify should pass
        assert signer.verify(message, signature) is True
    
    def test_verify_wrong_message(self):
        """Test verification fails for wrong message."""
        signer = VCPSigner.generate()
        
        message = b"Test message"
        signature = signer.sign(message)
        
        wrong_message = b"Wrong message"
        assert signer.verify(wrong_message, signature) is False
    
    def test_verify_wrong_signature(self):
        """Test verification fails for wrong signature."""
        signer = VCPSigner.generate()
        
        message = b"Test message"
        wrong_signature = b'\x00' * 64
        
        assert signer.verify(message, wrong_signature) is False
    
    def test_different_signers_different_keys(self):
        """Test that different signers have different keys."""
        signer1 = VCPSigner.generate()
        signer2 = VCPSigner.generate()
        
        assert signer1.get_public_key_hex() != signer2.get_public_key_hex()


# ============================================================================
# Merkle Tree Tests
# ============================================================================

class TestMerkleTree:
    """Test the historical odd-duplication PoC Merkle implementation."""
    
    def test_empty_tree(self):
        """Test empty tree behavior."""
        tree = MerkleTree()
        
        assert tree.size == 0
        
        with pytest.raises(ValueError):
            tree.get_root()
    
    def test_single_leaf(self):
        """Test tree with single leaf."""
        tree = MerkleTree()
        
        data = hashlib.sha256(b"leaf1").digest()
        idx = tree.add_leaf(data)
        
        assert idx == 0
        assert tree.size == 1
        
        root = tree.get_root()
        assert len(root) == 32  # SHA256 hash
    
    def test_two_leaves(self):
        """Test tree with two leaves."""
        tree = MerkleTree()
        
        data1 = hashlib.sha256(b"leaf1").digest()
        data2 = hashlib.sha256(b"leaf2").digest()
        
        tree.add_leaf(data1)
        tree.add_leaf(data2)
        
        assert tree.size == 2
        
        root = tree.get_root()
        assert len(root) == 32
    
    def test_proof_generation(self):
        """Test Merkle proof generation."""
        tree = MerkleTree()
        
        # Add 4 leaves
        leaves = [hashlib.sha256(f"leaf{i}".encode()).digest() for i in range(4)]
        for leaf in leaves:
            tree.add_leaf(leaf)
        
        # Get proof for each leaf
        for i in range(4):
            proof = tree.get_proof(i)
            assert len(proof) == 2  # log2(4) = 2 levels
    
    def test_proof_verification(self):
        """Test Merkle proof verification."""
        tree = MerkleTree()
        
        leaves = [hashlib.sha256(f"leaf{i}".encode()).digest() for i in range(4)]
        for leaf in leaves:
            tree.add_leaf(leaf)
        
        root = tree.get_root()
        
        # Verify each leaf
        for i, leaf in enumerate(leaves):
            proof = tree.get_proof(i)
            assert MerkleTree.verify_proof(leaf, proof, root) is True
    
    def test_proof_fails_for_wrong_leaf(self):
        """Test that proof fails for wrong leaf data."""
        tree = MerkleTree()
        
        leaves = [hashlib.sha256(f"leaf{i}".encode()).digest() for i in range(4)]
        for leaf in leaves:
            tree.add_leaf(leaf)
        
        root = tree.get_root()
        proof = tree.get_proof(0)
        
        # Wrong leaf should fail
        wrong_leaf = hashlib.sha256(b"wrong").digest()
        assert MerkleTree.verify_proof(wrong_leaf, proof, root) is False
    
    def test_odd_number_of_leaves(self):
        """Test tree with odd number of leaves (requires duplication)."""
        tree = MerkleTree()
        
        # Add 5 leaves
        leaves = [hashlib.sha256(f"leaf{i}".encode()).digest() for i in range(5)]
        for leaf in leaves:
            tree.add_leaf(leaf)
        
        assert tree.size == 5
        
        root = tree.get_root()
        assert len(root) == 32
        
        # All proofs should still verify
        for i, leaf in enumerate(leaves):
            proof = tree.get_proof(i)
            assert MerkleTree.verify_proof(leaf, proof, root) is True
    
    def test_domain_separation(self):
        """Test RFC 6962 domain separation prefixes."""
        tree = MerkleTree()
        
        leaf_data = hashlib.sha256(b"test").digest()
        tree.add_leaf(leaf_data)
        
        # Manual calculation with domain separation
        expected_leaf_hash = hashlib.sha256(b'\x00' + leaf_data).digest()
        
        assert tree._leaves[0] == expected_leaf_hash
    
    def test_reset(self):
        """Test tree reset functionality."""
        tree = MerkleTree()
        
        leaves = [hashlib.sha256(f"leaf{i}".encode()).digest() for i in range(4)]
        for leaf in leaves:
            tree.add_leaf(leaf)
        
        assert tree.size == 4
        
        tree.reset()
        
        assert tree.size == 0


# ============================================================================
# Integration Tests
# ============================================================================

class TestIntegration:
    """Integration tests for complete VCP flow."""
    
    def test_full_event_flow(self):
        """Test complete event processing flow."""
        # 1. Create event
        event = VCPEvent(
            event_id="INT-TEST-001",
            timestamp="2025-01-15T10:30:00.000Z",
            event_type="ORDER_NEW",
            tier="SILVER",
            policy_id="urn:vso:policy:tv-retail:v1",
            clock_sync="BEST_EFFORT",
            system_id="TEST-SYSTEM",
            account_id="TEST-ACCOUNT",
            payload={"order_id": "ORD-001", "symbol": "BTCUSD"}
        )
        
        # 2. Generate canonical JSON and hash
        canonical = event.to_canonical_json()
        event_hash = hashlib.sha256(canonical.encode('utf-8')).digest()
        
        # 3. Sign
        signer = VCPSigner.generate()
        signature = signer.sign(event_hash)
        
        # 4. Add to Merkle tree
        tree = MerkleTree()
        idx = tree.add_leaf(event_hash)
        
        # 5. Verify
        assert signer.verify(event_hash, signature) is True
        
        proof = tree.get_proof(idx)
        root = tree.get_root()
        assert MerkleTree.verify_proof(event_hash, proof, root) is True
    
    def test_batch_processing(self):
        """Test batch event processing."""
        signer = VCPSigner.generate()
        tree = MerkleTree()
        
        events = []
        
        # Process 10 events
        for i in range(10):
            event = VCPEvent(
                event_id=f"BATCH-{i:03d}",
                timestamp=f"2025-01-15T10:{i:02d}:00.000Z",
                event_type="ORDER_NEW",
                tier="SILVER",
                policy_id="urn:vso:policy:tv-retail:v1",
                clock_sync="BEST_EFFORT",
                system_id="TEST-SYSTEM",
                account_id="TEST-ACCOUNT",
                payload={"order_id": f"ORD-{i:03d}"}
            )
            
            canonical = event.to_canonical_json()
            event_hash = hashlib.sha256(canonical.encode('utf-8')).digest()
            signature = signer.sign(event_hash)
            idx = tree.add_leaf(event_hash)
            
            events.append({
                "event": event,
                "hash": event_hash,
                "signature": signature,
                "index": idx
            })
        
        # Verify all events
        root = tree.get_root()
        
        for e in events:
            assert signer.verify(e["hash"], e["signature"]) is True
            proof = tree.get_proof(e["index"])
            assert MerkleTree.verify_proof(e["hash"], proof, root) is True


# ============================================================================
# Run Tests
# ============================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
