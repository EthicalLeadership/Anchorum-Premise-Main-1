"""Tests for the signing module."""

import pytest
from cryptography.hazmat.primitives import serialization
from anchorum_ledger.signing import (
    SigningError,
    load_private_key_raw,
    sign,
    verify,
    public_key_pem,
)


def test_load_private_key_raw():
    """Loading a 32-byte seed creates a valid private key."""
    seed = b"0" * 32
    key = load_private_key_raw(seed)
    assert key is not None


def test_load_private_key_wrong_size():
    """Private key must be exactly 32 bytes."""
    with pytest.raises(SigningError):
        load_private_key_raw(b"0" * 16)


def test_sign_produces_signature():
    """Signing produces a valid base64 signature."""
    seed = b"0" * 32
    data = b"Hello, World!"
    key = load_private_key_raw(seed)
    sig_b64 = sign(key, data)
    assert isinstance(sig_b64, str)


def test_sign_signature_verifies():
    """The signature verifies against the public key."""
    seed = b"0" * 32
    data = b"Hello, World!"
    key = load_private_key_raw(seed)
    sig_b64 = sign(key, data)
    assert verify(key.public_key(), sig_b64, data) is True


def test_verify_wrong_signature():
    """Wrong signature fails verification."""
    seed1 = b"0" * 32
    seed2 = b"1" * 32
    data = b"Hello, World!"
    key1 = load_private_key_raw(seed1)
    sig_b64 = sign(key1, data)
    # Now use a different key's public key (won't verify)
    key2 = load_private_key_raw(seed2)
    assert verify(key2.public_key(), sig_b64, data) is False


def test_verify_invalid_data():
    """Verification fails when data doesn't match."""
    seed = b"0" * 32
    data1 = b"Hello"
    data2 = b"World"
    key = load_private_key_raw(seed)
    sig_b64 = sign(key, data1)
    assert verify(key.public_key(), sig_b64, data2) is False


def test_public_key_pem():
    """Converting private to public key PEM works."""
    seed = b"0" * 32
    key = load_private_key_raw(seed)
    pem = public_key_pem(key)
    assert isinstance(pem, str)
    assert "-----BEGIN PUBLIC KEY-----" in pem


def test_public_key_pem_loads():
    """The PEM string can be loaded back as a public key."""
    seed = b"0" * 32
    key = load_private_key_raw(seed)
    pem = public_key_pem(key)
    pub_key = serialization.load_pem_public_key(pem.encode("ascii"))
    assert isinstance(pub_key, type(key.public_key()))
