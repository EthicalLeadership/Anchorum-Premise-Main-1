import pytest
from interface.ledger.canonical import canonicalize, canonical_hash


def test_empty_object():
    assert canonicalize({}) == b"{}"


def test_sorted_keys():
    assert canonicalize({"b": 1, "a": 2}) == b'{"a":2,"b":1}'
    assert canonicalize({"a": 2, "b": 1}) == b'{"a":2,"b":1}'


def test_no_whitespace():
    result = canonicalize({"a": 1, "b": [1, 2, 3]})
    assert b" " not in result
    assert result == b'{"a":1,"b":[1,2,3]}'


def test_nested_sorted():
    assert canonicalize({"z": {"b": 1, "a": 2}, "a": 3}) == b'{"a":3,"z":{"a":2,"b":1}}'


def test_list_order_preserved():
    assert canonicalize([3, 1, 2]) == b"[3,1,2]"


def test_unicode_preserved():
    result = canonicalize({"name": "caf\u00e9"})
    assert b"\\u" not in result
    assert "caf\u00e9".encode("utf-8") in result


def test_control_chars_escaped():
    result = canonicalize({"x": "a\nb"})
    assert b"\\n" in result


def test_int_vs_float():
    assert canonical_hash({"n": 42}) != canonical_hash({"n": 42.0})


def test_bool_vs_int():
    assert canonical_hash({"n": True}) != canonical_hash({"n": 1})


def test_null():
    assert canonicalize({"n": None}) == b'{"n":null}'


def test_determinism_two_runs():
    obj = {"z": 1, "a": [3, {"y": 2, "x": 1}]}
    assert canonicalize(obj) == canonicalize(obj)


def test_determinism_insertion_order():
    obj1 = {"a": 1, "b": 2, "c": 3}
    obj2 = {"c": 3, "a": 1, "b": 2}
    assert canonical_hash(obj1) == canonical_hash(obj2)


def test_nan_rejected():
    with pytest.raises(ValueError):
        canonicalize({"n": float("nan")})


def test_inf_rejected():
    with pytest.raises(ValueError):
        canonicalize({"n": float("inf")})
