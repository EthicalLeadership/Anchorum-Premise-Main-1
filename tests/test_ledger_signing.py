import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)
from interface.ledger.signing import (
    SigningError,
    load_private_key_raw,
    load_private_key_pem,
    load_public_key_pem,
    public_key_pem,
    sign,
    verify,
)


def test_sign_verify_roundtrip():
    key = Ed25519PrivateKey.generate()
    sig = sign(key, b"the case ledger")
    assert verify(key.public_key(), sig, b"the case ledger") is True


def test_verify_wrong_data():
    key = Ed25519PrivateKey.generate()
    sig = sign(key, b"original")
    assert verify(key.public_key(), sig, b"tampered") is False


def test_verify_wrong_key():
    k1 = Ed25519PrivateKey.generate()
    k2 = Ed25519PrivateKey.generate()
    sig = sign(k1, b"data")
    assert verify(k2.public_key(), sig, b"data") is False


def test_verify_malformed_signature():
    key = Ed25519PrivateKey.generate()
    assert verify(key.public_key(), "not-base64!!!", b"data") is False
    assert verify(key.public_key(), "", b"data") is False


def test_load_raw_key_wrong_length():
    with pytest.raises(SigningError):
        load_private_key_raw(b"tooshort")
    with pytest.raises(SigningError):
        load_private_key_raw(b"x" * 33)


def test_load_raw_key_correct():
    raw = b"a" * 32
    k1 = load_private_key_raw(raw)
    k2 = load_private_key_raw(raw)
    assert public_key_pem(k1) == public_key_pem(k2)


def test_public_key_pem_roundtrip():
    key = Ed25519PrivateKey.generate()
    pem = public_key_pem(key)
    parsed = load_public_key_pem(pem)
    sig = sign(key, b"test")
    assert verify(parsed, sig, b"test")


def test_error_message_does_not_leak_key():
    """ALP-1.5: exception messages must not contain key material."""
    raw = b"SECRET" * 5 + b"AB"  # 32 bytes but distinctive
    try:
        load_private_key_raw(raw[:31])  # wrong length
    except SigningError as e:
        msg = str(e)
        assert "SECRET" not in msg
        assert "31" in msg  # length is safe to reveal


def test_sign_refuses_if_internal_verify_fails(monkeypatch):
    """ALP-1.3: sign() must raise if internal verification fails.

    Patches signing.verify (Python function) rather than
    Ed25519PublicKey.verify, because the latter is a Rust extension
    method in modern cryptography and cannot be monkeypatched.
    """
    from interface.ledger import signing as signing_module

    key = Ed25519PrivateKey.generate()

    def always_returns_false(public_key, sig, data):
        return False

    monkeypatch.setattr(signing_module, "verify", always_returns_false)

    with pytest.raises(SigningError, match="did not verify"):
        sign(key, b"data")
