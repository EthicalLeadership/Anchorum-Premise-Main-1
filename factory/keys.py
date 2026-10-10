"""Key hierarchy.

    root_private   Held offline. Signs certificates.
    factory_private Held on the generation machine. Signs manifests.

Layout under `<factory_home>/`:
    root_private.key          hex, mode 0600. NEVER committed.
    root_public.hex           hex. Committable.
    factory_private.key       hex, mode 0600. NEVER committed.
    factory_certificate.json  Signed by root. Committable.
"""
from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    import nacl.signing
    _HAS_NACL = True
except ImportError:
    _HAS_NACL = False

from . import CERTIFICATE_VERSION


class KeyError_(Exception):
    pass


def _require_nacl() -> None:
    if not _HAS_NACL:
        raise KeyError_("PyNaCl is required; pip install pynacl")


def canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def generate_keypair() -> tuple[str, str]:
    """Return (private_hex, public_hex)."""
    _require_nacl()
    sk = nacl.signing.SigningKey.generate()
    return bytes(sk).hex(), bytes(sk.verify_key).hex()


def sign(private_hex: str, message: bytes) -> str:
    _require_nacl()
    sk = nacl.signing.SigningKey(bytes.fromhex(private_hex))
    return sk.sign(message).signature.hex()


def verify(public_hex: str, message: bytes, signature_hex: str) -> bool:
    _require_nacl()
    try:
        vk = nacl.signing.VerifyKey(bytes.fromhex(public_hex))
        vk.verify(message, bytes.fromhex(signature_hex))
        return True
    except Exception:
        return False


def fingerprint(public_hex: str) -> str:
    return hashlib.sha256(bytes.fromhex(public_hex)).hexdigest()[:16]


# ------------------------------------------------------------------ certs

@dataclass(frozen=True)
class Certificate:
    factory_public_key: str
    factory_name: str
    valid_from: str
    valid_until: str
    root_signature: str

    def body(self) -> dict:
        return {
            "type": "anchorum-factory-certificate",
            "version": CERTIFICATE_VERSION,
            "factory_public_key": self.factory_public_key,
            "factory_name": self.factory_name,
            "valid_from": self.valid_from,
            "valid_until": self.valid_until,
        }

    def to_json(self) -> dict:
        d = dict(self.body())
        d["root_signature"] = self.root_signature
        return d

    @classmethod
    def from_json(cls, data: dict) -> "Certificate":
        if not isinstance(data, dict):
            raise KeyError_("certificate: must be a mapping")
        if data.get("type") != "anchorum-factory-certificate":
            raise KeyError_(f"certificate: wrong type {data.get('type')!r}")
        if data.get("version") != CERTIFICATE_VERSION:
            raise KeyError_(f"certificate: unsupported version {data.get('version')!r}")
        for k in ("factory_public_key", "factory_name", "valid_from",
                  "valid_until", "root_signature"):
            if not isinstance(data.get(k), str) or not data[k]:
                raise KeyError_(f"certificate: {k!r} must be a non-empty string")
        return cls(
            factory_public_key=data["factory_public_key"],
            factory_name=data["factory_name"],
            valid_from=data["valid_from"],
            valid_until=data["valid_until"],
            root_signature=data["root_signature"],
        )


def issue_certificate(
    root_private_hex: str,
    factory_public_hex: str,
    factory_name: str,
    valid_days: int = 365,
) -> Certificate:
    now = datetime.now(timezone.utc)
    body = {
        "type": "anchorum-factory-certificate",
        "version": CERTIFICATE_VERSION,
        "factory_public_key": factory_public_hex,
        "factory_name": factory_name,
        "valid_from": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "valid_until": (now + timedelta(days=valid_days)).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    sig = sign(root_private_hex, canonical(body))
    return Certificate(
        factory_public_key=factory_public_hex,
        factory_name=factory_name,
        valid_from=body["valid_from"],
        valid_until=body["valid_until"],
        root_signature=sig,
    )


def verify_certificate(cert: Certificate, root_public_hex: str) -> tuple[bool, str]:
    """Return (ok, reason). reason is '' when ok."""
    if not verify(root_public_hex, canonical(cert.body()), cert.root_signature):
        return False, "certificate signature does not verify under root key"
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if cert.valid_from > now:
        return False, f"certificate not yet valid (from {cert.valid_from})"
    if cert.valid_until < now:
        return False, f"certificate expired at {cert.valid_until}"
    return True, ""


# -------------------------------------------------------------- on-disk

@dataclass(frozen=True)
class KeyMaterial:
    root_private_hex: str
    root_public_hex: str
    factory_private_hex: str
    factory_public_hex: str
    certificate: Certificate


def default_home() -> Path:
    env = os.environ.get("ANCHORUM_FACTORY_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return Path.cwd() / ".factory"


def _write_secret(path: Path, content: str) -> None:
    path.write_text(content, encoding="utf-8")
    os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)


def init_keys(home: Path, factory_name: str = "local-dev") -> KeyMaterial:
    home.mkdir(parents=True, exist_ok=True)
    root_priv, root_pub = generate_keypair()
    fac_priv, fac_pub = generate_keypair()
    cert = issue_certificate(root_priv, fac_pub, factory_name)
    _write_secret(home / "root_private.key", root_priv)
    (home / "root_public.hex").write_text(root_pub, encoding="utf-8")
    _write_secret(home / "factory_private.key", fac_priv)
    (home / "factory_certificate.json").write_text(
        json.dumps(cert.to_json(), indent=2), encoding="utf-8"
    )
    return KeyMaterial(
        root_private_hex=root_priv,
        root_public_hex=root_pub,
        factory_private_hex=fac_priv,
        factory_public_hex=fac_pub,
        certificate=cert,
    )


def load_keys(home: Path) -> KeyMaterial:
    try:
        root_priv = (home / "root_private.key").read_text(encoding="utf-8").strip()
        root_pub = (home / "root_public.hex").read_text(encoding="utf-8").strip()
        fac_priv = (home / "factory_private.key").read_text(encoding="utf-8").strip()
        cert_data = json.loads(
            (home / "factory_certificate.json").read_text(encoding="utf-8")
        )
    except FileNotFoundError as exc:
        raise KeyError_(
            f"key material missing under {home}: {exc}. Run `python -m factory.generate keys init` first."
        ) from exc
    cert = Certificate.from_json(cert_data)
    return KeyMaterial(
        root_private_hex=root_priv,
        root_public_hex=root_pub,
        factory_private_hex=fac_priv,
        factory_public_hex=cert.factory_public_key,
        certificate=cert,
    )
