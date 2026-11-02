"""
Merkle Tree Implementation for VCP
Historical PoC Merkle tree with odd-node duplication (not RFC 6962/9162)

Implements:
- Leaf hashing with domain separation (0x00 prefix)
- Internal node hashing with domain separation (0x01 prefix)
- Merkle inclusion proofs
- Batch construction

References:
- RFC 9162 §2.1.1: the reference split construction differs from this PoC
- VCP v1.1 Specification Section 6 (Three-Layer Architecture)

Copyright (c) 2025 VeritasChain Standards Organization
License: MIT
"""

import hashlib
from dataclasses import dataclass
from typing import List, Tuple, Optional
from enum import Enum


class ProofDirection(Enum):
    """Direction indicator for Merkle proof nodes."""
    LEFT = "left"
    RIGHT = "right"


@dataclass
class MerkleProofNode:
    """Single node in a Merkle inclusion proof."""
    direction: ProofDirection
    hash: bytes
    
    def to_dict(self) -> dict:
        """Convert to dictionary representation."""
        return {
            "direction": self.direction.value,
            "hash": self.hash.hex()
        }


class MerkleTree:
    """
    Historical PoC tree using RFC-style domain prefixes and odd-node duplication.

    This is not the RFC 6962/9162 split construction. Historical roots and
    proofs keep this algorithm; verification does not establish RFC conformance.
    
    Features:
    - Domain separation for leaf (0x00) and internal (0x01) nodes
    - Efficient incremental construction
    - Merkle inclusion proofs
    - Supports verification without full tree
    
    Usage:
        tree = MerkleTree()
        idx = tree.add_leaf(data_hash)
        root = tree.get_root()
        proof = tree.get_proof(idx)
        valid = MerkleTree.verify_proof(data_hash, proof, root)
    """
    
    # Domain separation prefixes per RFC 6962
    LEAF_PREFIX = b'\x00'
    INTERNAL_PREFIX = b'\x01'
    
    def __init__(self, hash_algo: str = 'sha256'):
        """
        Initialize empty Merkle tree.
        
        Args:
            hash_algo: Hash algorithm to use (default: sha256)
        """
        self.hash_algo = hash_algo
        self._leaves: List[bytes] = []
        self._layers: List[List[bytes]] = [[]]  # Bottom layer first
        self._root: Optional[bytes] = None
        self._dirty = True  # Indicates if tree needs recalculation
    
    @property
    def size(self) -> int:
        """Number of leaves in the tree."""
        return len(self._leaves)
    
    def _hash(self, data: bytes) -> bytes:
        """Compute hash of data."""
        return hashlib.new(self.hash_algo, data).digest()
    
    def _leaf_hash(self, data: bytes) -> bytes:
        """
        Compute leaf hash with domain separation.
        
        RFC 6962: MTH({d(0)}) = SHA-256(0x00 || d(0))
        """
        return self._hash(self.LEAF_PREFIX + data)
    
    def _internal_hash(self, left: bytes, right: bytes) -> bytes:
        """
        Compute internal node hash with domain separation.
        
        Uses the RFC-style 0x01 prefix, but subtree construction differs.
        """
        return self._hash(self.INTERNAL_PREFIX + left + right)
    
    def add_leaf(self, data_hash: bytes) -> int:
        """
        Add a leaf to the tree.
        
        Args:
            data_hash: The hash of the data (not the raw data)
        
        Returns:
            Index of the added leaf
        """
        leaf_hash = self._leaf_hash(data_hash)
        self._leaves.append(leaf_hash)
        self._dirty = True
        return len(self._leaves) - 1
    
    def _rebuild(self):
        """Rebuild the tree from leaves."""
        if not self._dirty:
            return
        
        if len(self._leaves) == 0:
            self._layers = [[]]
            self._root = None
            self._dirty = False
            return
        
        # Start with leaf layer
        self._layers = [self._leaves.copy()]
        
        # Build up the tree
        current_layer = self._leaves.copy()
        
        while len(current_layer) > 1:
            next_layer = []
            
            for i in range(0, len(current_layer), 2):
                left = current_layer[i]
                
                # Historical odd-node duplication; not RFC 6962/9162 splitting.
                if i + 1 < len(current_layer):
                    right = current_layer[i + 1]
                else:
                    right = left  # Duplicate for odd count
                
                parent = self._internal_hash(left, right)
                next_layer.append(parent)
            
            self._layers.append(next_layer)
            current_layer = next_layer
        
        self._root = current_layer[0] if current_layer else None
        self._dirty = False
    
    def get_root(self) -> bytes:
        """
        Get the Merkle root.
        
        Returns:
            Merkle root hash
        
        Raises:
            ValueError: If tree is empty
        """
        if len(self._leaves) == 0:
            raise ValueError("Cannot get root of empty tree")
        
        self._rebuild()
        return self._root
    
    def get_proof(self, leaf_index: int) -> List[Tuple[str, bytes]]:
        """
        Get Merkle inclusion proof for a leaf.
        
        Args:
            leaf_index: Index of the leaf
        
        Returns:
            List of (position, hash) tuples forming the proof path
            position is 'left' or 'right' indicating sibling position
        
        Raises:
            IndexError: If leaf_index is out of bounds
        """
        if leaf_index < 0 or leaf_index >= len(self._leaves):
            raise IndexError(f"Leaf index {leaf_index} out of bounds")
        
        self._rebuild()
        
        proof = []
        index = leaf_index
        
        for layer_idx in range(len(self._layers) - 1):
            layer = self._layers[layer_idx]
            
            # Determine sibling position
            if index % 2 == 0:
                # Current node is left child, sibling is right
                sibling_index = index + 1
                position = 'right'
            else:
                # Current node is right child, sibling is left
                sibling_index = index - 1
                position = 'left'
            
            # Get sibling hash (duplicate if at edge)
            if sibling_index < len(layer):
                sibling_hash = layer[sibling_index]
            else:
                sibling_hash = layer[index]  # Duplicate for odd count
            
            proof.append((position, sibling_hash))
            
            # Move to parent index
            index = index // 2
        
        return proof
    
    def verify_inclusion(self, leaf_index: int, data_hash: bytes) -> bool:
        """
        Verify that a data hash is included at the specified index.
        
        Args:
            leaf_index: Expected index of the leaf
            data_hash: Original data hash (before leaf hashing)
        
        Returns:
            True if the data is included at the index
        """
        if leaf_index < 0 or leaf_index >= len(self._leaves):
            return False
        
        expected_leaf_hash = self._leaf_hash(data_hash)
        return self._leaves[leaf_index] == expected_leaf_hash
    
    @classmethod
    def verify_proof(cls, data_hash: bytes, proof: List[Tuple[str, bytes]], 
                     expected_root: bytes, hash_algo: str = 'sha256') -> bool:
        """
        Verify a Merkle inclusion proof.
        
        Args:
            data_hash: Original data hash
            proof: List of (position, hash) tuples
            expected_root: Expected Merkle root
            hash_algo: Hash algorithm used
        
        Returns:
            True if proof is valid
        """
        def _hash(data: bytes) -> bytes:
            return hashlib.new(hash_algo, data).digest()
        
        # Start with leaf hash
        current = _hash(cls.LEAF_PREFIX + data_hash)
        
        # Walk up the tree
        for position, sibling_hash in proof:
            if position == 'left':
                current = _hash(cls.INTERNAL_PREFIX + sibling_hash + current)
            else:
                current = _hash(cls.INTERNAL_PREFIX + current + sibling_hash)
        
        return current == expected_root
    
    def reset(self):
        """Clear all leaves and reset the tree."""
        self._leaves = []
        self._layers = [[]]
        self._root = None
        self._dirty = True
    
    def get_leaf_hashes(self) -> List[bytes]:
        """Get all leaf hashes."""
        return self._leaves.copy()
    
    def to_dict(self) -> dict:
        """Serialize tree to dictionary."""
        self._rebuild()
        return {
            "size": self.size,
            "root": self._root.hex() if self._root else None,
            "leaves": [leaf.hex() for leaf in self._leaves],
            "hash_algo": self.hash_algo
        }
    
    @classmethod
    def from_leaves(cls, leaf_data_hashes: List[bytes], hash_algo: str = 'sha256') -> 'MerkleTree':
        """
        Construct tree from a list of data hashes.
        
        Args:
            leaf_data_hashes: List of data hashes (not leaf hashes)
            hash_algo: Hash algorithm to use
        
        Returns:
            Constructed MerkleTree
        """
        tree = cls(hash_algo=hash_algo)
        for data_hash in leaf_data_hashes:
            tree.add_leaf(data_hash)
        return tree


# ============================================================================
# Merkle Audit Path Utilities
# ============================================================================

def compute_merkle_root(leaf_hashes: List[bytes], hash_algo: str = 'sha256') -> bytes:
    """
    Compute Merkle root from a list of leaf hashes.
    
    This is a convenience function for one-shot computation.
    
    Args:
        leaf_hashes: List of data hashes
        hash_algo: Hash algorithm
    
    Returns:
        Merkle root
    """
    tree = MerkleTree.from_leaves(leaf_hashes, hash_algo)
    return tree.get_root()


def format_proof_for_json(proof: List[Tuple[str, bytes]]) -> List[dict]:
    """
    Format Merkle proof for JSON serialization.
    
    Args:
        proof: Proof from MerkleTree.get_proof()
    
    Returns:
        JSON-serializable list
    """
    return [{"position": pos, "hash": h.hex()} for pos, h in proof]


def parse_proof_from_json(proof_json: List[dict]) -> List[Tuple[str, bytes]]:
    """
    Parse Merkle proof from JSON.
    
    Args:
        proof_json: JSON proof structure
    
    Returns:
        Proof as list of tuples
    """
    return [(item["position"], bytes.fromhex(item["hash"])) for item in proof_json]


# ============================================================================
# Consistency Proof (for append-only log verification)
# ============================================================================

class MerkleConsistencyProof:
    """
    Unimplemented consistency-proof interface; it provides no verified result.

    Generation fails explicitly and verification always returns False. The
    historical PoC tree is not an RFC 6962/9162 consistency-proof implementation.
    """
    
    @staticmethod
    def generate(old_tree_size: int, new_tree: MerkleTree) -> List[bytes]:
        """
        Refuse generation because consistency proofs are not implemented.
        
        Args:
            old_tree_size: Size of the older tree
            new_tree: The current (larger) tree
        
        Returns:
            List of hashes forming the consistency proof
        """
        raise NotImplementedError("Consistency proof generation is not implemented")
    
    @staticmethod
    def verify(old_root: bytes, old_size: int, 
               new_root: bytes, new_size: int,
               proof: List[bytes]) -> bool:
        """
        Return False: consistency verification is not implemented.
        
        Args:
            old_root: Root of the older tree
            old_size: Size of the older tree
            new_root: Root of the newer tree
            new_size: Size of the newer tree
            proof: Consistency proof hashes
        
        Returns:
            False (not verified); this interface cannot establish consistency
        """
        return False


# ============================================================================
# Testing Utilities
# ============================================================================

if __name__ == "__main__":
    # Basic test
    print("Testing MerkleTree implementation...")
    
    # Create tree
    tree = MerkleTree()
    
    # Add some leaves
    test_data = [
        hashlib.sha256(b"event1").digest(),
        hashlib.sha256(b"event2").digest(),
        hashlib.sha256(b"event3").digest(),
        hashlib.sha256(b"event4").digest(),
    ]
    
    for data in test_data:
        idx = tree.add_leaf(data)
        print(f"Added leaf {idx}: {data.hex()[:16]}...")
    
    # Get root
    root = tree.get_root()
    print(f"\nMerkle root: {root.hex()}")
    
    # Get and verify proof for each leaf
    for i, data in enumerate(test_data):
        proof = tree.get_proof(i)
        print(f"\nProof for leaf {i}:")
        for pos, h in proof:
            print(f"  {pos}: {h.hex()[:16]}...")
        
        # Verify
        valid = MerkleTree.verify_proof(data, proof, root)
        print(f"  Verification: {'PASS' if valid else 'FAIL'}")
    
    print("\nAll tests completed!")
