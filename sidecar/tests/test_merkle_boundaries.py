"""Pin historical tree behavior while rejecting unsupported consistency proofs."""

import hashlib
import pytest

from sidecar.merkle import MerkleTree, MerkleConsistencyProof


def test_historical_three_leaf_shape_is_not_rfc9162():
    values = [b"a", b"b", b"c"]
    leaves = [hashlib.sha256(b"\x00" + value).digest() for value in values]
    node = lambda a, b: hashlib.sha256(b"\x01" + a + b).digest()
    rfc_root = node(node(leaves[0], leaves[1]), leaves[2])
    historical_root = node(node(leaves[0], leaves[1]), node(leaves[2], leaves[2]))
    tree = MerkleTree()
    for value in values:
        tree.add_leaf(value)
    assert tree.get_root() == historical_root
    assert tree.get_root() != rfc_root
    tree.add_leaf(values[-1])
    assert tree.get_root() == historical_root  # Root alone cannot bind the count.


@pytest.mark.parametrize("old_size,new_size,proof", [(1, 2, []), (1, 2, [b"x" * 32]),
                                                     (2, 2, []), (0, 2, []), (3, 1, [])])
def test_unimplemented_consistency_verifier_never_reports_success(old_size, new_size, proof):
    assert MerkleConsistencyProof.verify(b"a" * 32, old_size, b"b" * 32, new_size, proof) is False


def test_unimplemented_consistency_generation_is_explicit():
    tree = MerkleTree()
    tree.add_leaf(b"a")
    tree.add_leaf(b"b")
    with pytest.raises(NotImplementedError, match="not implemented"):
        MerkleConsistencyProof.generate(1, tree)
