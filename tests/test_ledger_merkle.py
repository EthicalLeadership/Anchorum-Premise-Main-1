import hashlib
import random
import pytest
from interface.ledger.merkle import merkle_root


def _leaf(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()


def test_empty_list():
    assert merkle_root([]) == hashlib.sha256(b"").hexdigest()


def test_single_leaf():
    leaf = _leaf("hello")
    assert merkle_root([leaf]) == leaf


def test_two_leaves_order_independent():
    a, b = _leaf("a"), _leaf("b")
    lo, hi = sorted([a, b])
    expected = hashlib.sha256(bytes.fromhex(lo) + bytes.fromhex(hi)).hexdigest()
    assert merkle_root([a, b]) == expected
    assert merkle_root([b, a]) == expected


def test_three_leaves_duplicates_last():
    a, b, c = _leaf("a"), _leaf("b"), _leaf("c")
    s = sorted([a, b, c])
    dups = s + [s[-1]]
    h1 = hashlib.sha256(bytes.fromhex(dups[0]) + bytes.fromhex(dups[1])).digest()
    h2 = hashlib.sha256(bytes.fromhex(dups[2]) + bytes.fromhex(dups[3])).digest()
    expected = hashlib.sha256(h1 + h2).hexdigest()
    assert merkle_root([a, b, c]) == expected


def test_deterministic():
    leaves = [_leaf(f"msg{i}") for i in range(10)]
    assert merkle_root(leaves) == merkle_root(leaves)


def test_order_independent():
    leaves = [_leaf(f"msg{i}") for i in range(10)]
    shuffled = leaves[:]
    random.Random(42).shuffle(shuffled)
    assert merkle_root(leaves) == merkle_root(shuffled)


def test_tamper_detected():
    leaves = [_leaf(f"msg{i}") for i in range(10)]
    root1 = merkle_root(leaves)
    leaves[5] = _leaf("msg5-tampered")
    root2 = merkle_root(leaves)
    assert root1 != root2


def test_invalid_leaf_length():
    with pytest.raises(ValueError):
        merkle_root(["tooshort"])


def test_invalid_leaf_hex():
    with pytest.raises(ValueError):
        merkle_root(["z" * 64])
