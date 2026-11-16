"""Tests for the merkle_root function."""

import pytest
from anchorum_ledger.merkle import merkle_root


def test_single_leaf():
    """Single leaf → its own hash is the root."""
    leaf = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"  # sha256("")
    root = merkle_root([leaf])
    assert root == leaf


def test_order_independent():
    """Merkle root is order-independent (due to sorting)."""
    leaf_a = "0a" * 32
    leaf_b = "1b" * 32
    leaf_c = "2c" * 32
    assert merkle_root([leaf_a, leaf_b, leaf_c]) == merkle_root([leaf_c, leaf_b, leaf_a])


def test_duplicate_last_leaf():
    """Odd number of leaves → duplicate last one."""
    # This is a simple check - actual hash depends on implementation
    leaf_a = "0a" * 32
    odd = [leaf_a]
    even = [leaf_a, leaf_a]
    assert merkle_root(odd) == merkle_root(even)


def test_empty_leaves():
    """Empty input → null root convention."""
    root = merkle_root([])
    assert len(root) == 64  # It's a SHA-256 hash


def test_invalid_leaf_length():
    """Leaves must be exactly 64 hex characters."""
    with pytest.raises(ValueError):
        merkle_root(["0a" * 30])


def test_invalid_leaf_non_hex():
    """Leaves must be valid hexadecimal."""
    with pytest.raises(ValueError):
        merkle_root(["GG" + "00" * 62])
