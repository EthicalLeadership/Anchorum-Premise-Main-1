"""Tests for the canonicalize function and canonical_hash helper."""

import pytest
from anchorum_ledger.canonical import canonicalize, canonical_hash


def test_determinism():
    """Two runs of canonicalize on the same input must produce identical bytes."""
    obj = {"a": 1, "b": [2, 3], "c": True}
    b1 = canonicalize(obj)
    b2 = canonicalize(obj)
    assert b1 == b2


def test_sorted_keys():
    """Dictionary keys are sorted in the output."""
    obj = {"z": 1, "a": 2}
    result = canonicalize(obj).decode("utf-8")
    assert result.startswith('{"a":2,"z":1}')


def test_no_whitespace():
    """Output contains no spaces or newlines."""
    obj = {"x": 1}
    result = canonicalize(obj)
    assert " " not in result.decode()
    assert "\n" not in result.decode()


def test_int_float_distinction():
    """int and float are distinct (42 != 42.0)."""
    obj1 = {"x": 42}
    obj2 = {"x": 42.0}
    assert canonicalize(obj1) != canonicalize(obj2)


def test_bool_int_distinction():
    """bool and int are distinct (true != 1)."""
    obj1 = {"x": True}
    obj2 = {"x": 1}
    assert canonicalize(obj1) != canonicalize(obj2)


def test_canonical_hash_consistency():
    """Same object always produces the same hash."""
    obj = {"message_id": "m-1", "text": "hello"}
    h1 = canonical_hash(obj)
    h2 = canonical_hash(obj)
    assert h1 == h2


def test_different_objects_different_hashes():
    """Different objects produce different hashes."""
    obj1 = {"id": 1}
    obj2 = {"id": 2}
    assert canonical_hash(obj1) != canonical_hash(obj2)
