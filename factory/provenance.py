"""Manifest structure, hashing, signing, and I/O.

Manifest schema v2:

    {
      "schema_version": 2,
      "generation_id": "01J...",
      "factory_version": "0.3.0",
      "generated_at": "2026-...",
      "lifecycle": "DRAFT",
      "source": {"type": "file", "identifier": "...", "prompt_version": "..."},
      "inputs_sha256": "hex",
      "files": [{"path": "...", "sha256": "..."}],
      "certificate": { ... } | null,
      "signature": "hex" | null
    }

If a factory key is available, `certificate` and `signature` are set and
the manifest is authenticated end-to-end:

    root --authorizes--> factory --signs--> manifest --hashes--> files

If no key is available, both are null and the manifest is unsigned
(accident protection only).
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from . import MANIFEST_SCHEMA
from .keys import Certificate, canonical, sign, verify


MANIFEST_NAME = ".anchorum-factory.json"

_B32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


@dataclass(frozen=True)
class FileEntry:
    path: str
    sha256: str


@dataclass(frozen=True)
class Source:
    type: str
    identifier: str
    prompt_version: str


@dataclass(frozen=True)
class Manifest:
    schema_version: int
    generation_id: str
    factory_version: str
    generated_at: str
    lifecycle: str
    source: Source
    inputs_sha256: str
    files: tuple[FileEntry, ...]
    certificate: Certificate | None
    signature: str | None

    def body(self) -> dict:
        return {
            "schema_version": self.schema_version,
            "generation_id": self.generation_id,
            "factory_version": self.factory_version,
            "generated_at": self.generated_at,
            "lifecycle": self.lifecycle,
            "source": {
                "type": self.source.type,
                "identifier": self.source.identifier,
                "prompt_version": self.source.prompt_version,
            },
            "inputs_sha256": self.inputs_sha256,
            "files": [{"path": f.path, "sha256": f.sha256} for f in self.files],
            "certificate": None if self.certificate is None else self.certificate.to_json(),
        }

    def to_json(self) -> dict:
        d = self.body()
        d["signature"] = self.signature
        return d

    def canonical_for_signing(self) -> bytes:
        return canonical(self.body())


# ------------------------------------------------------------------ helpers

def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def new_generation_id() -> str:
    ts = int(time.time() * 1000).to_bytes(6, "big")
    raw = ts + secrets.token_bytes(10)
    n = int.from_bytes(raw, "big")
    chars = []
    for _ in range(26):
        chars.append(_B32[n & 0x1F])
        n >>= 5
    return "".join(reversed(chars))


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- building

def build_manifest(
    gateway_dir: Path,
    *,
    files: list[str],
    inputs_sha256: str,
    source: Source,
    lifecycle: str,
    factory_version: str,
    factory_private_hex: str | None,
    certificate: Certificate | None,
) -> Manifest:
    entries = []
    for rel in files:
        p = gateway_dir / rel
        if not p.is_file():
            raise ValueError(f"manifest: file missing at build time: {rel}")
        entries.append(FileEntry(path=rel, sha256=sha256_file(p)))
    m = Manifest(
        schema_version=MANIFEST_SCHEMA,
        generation_id=new_generation_id(),
        factory_version=factory_version,
        generated_at=now_iso(),
        lifecycle=lifecycle,
        source=source,
        inputs_sha256=inputs_sha256,
        files=tuple(entries),
        certificate=certificate,
        signature=None,
    )
    if factory_private_hex and certificate is not None:
        sig = sign(factory_private_hex, m.canonical_for_signing())
        m = replace(m, signature=sig)
    return m


# ----------------------------------------------------------------- reading

class ManifestError(ValueError):
    pass


def read_manifest(gateway_dir: Path) -> Manifest | None:
    p = gateway_dir / MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ManifestError(f"{p}: invalid JSON: {exc}") from exc
    return _parse_manifest(data, p)


def _parse_manifest(data: Any, p: Path) -> Manifest:
    def need(key: str, typ: type) -> Any:
        v = data.get(key)
        if not isinstance(v, typ):
            raise ManifestError(f"{p}: {key!r} must be {typ.__name__}")
        return v

    sv = need("schema_version", int)
    if sv != MANIFEST_SCHEMA:
        raise ManifestError(f"{p}: schema_version {sv} unsupported; expected {MANIFEST_SCHEMA}")

    src = need("source", dict)
    for k in ("type", "identifier", "prompt_version"):
        if not isinstance(src.get(k), str):
            raise ManifestError(f"{p}: source.{k} must be a string")

    files_raw = need("files", list)
    files: list[FileEntry] = []
    for i, f in enumerate(files_raw):
        if not isinstance(f, dict):
            raise ManifestError(f"{p}: files[{i}] must be a mapping")
        path = f.get("path")
        sha = f.get("sha256")
        if not isinstance(path, str) or not isinstance(sha, str):
            raise ManifestError(f"{p}: files[{i}] path/sha256 must be strings")
        if "/../" in path or path.startswith("/"):
            raise ManifestError(f"{p}: files[{i}].path escapes gateway dir")
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ManifestError(f"{p}: files[{i}].sha256 not hex-64")
        files.append(FileEntry(path=path, sha256=sha))

    cert_raw = data.get("certificate")
    cert: Certificate | None = None
    if cert_raw is not None:
        try:
            cert = Certificate.from_json(cert_raw)
        except Exception as exc:
            raise ManifestError(f"{p}: certificate: {exc}") from exc

    sig_raw = data.get("signature")
    sig: str | None = None
    if sig_raw is not None:
        if not isinstance(sig_raw, str) or not sig_raw:
            raise ManifestError(f"{p}: signature must be a non-empty string or null")
        sig = sig_raw

    return Manifest(
        schema_version=sv,
        generation_id=need("generation_id", str),
        factory_version=need("factory_version", str),
        generated_at=need("generated_at", str),
        lifecycle=need("lifecycle", str),
        source=Source(
            type=src["type"], identifier=src["identifier"],
            prompt_version=src["prompt_version"],
        ),
        inputs_sha256=need("inputs_sha256", str),
        files=tuple(files),
        certificate=cert,
        signature=sig,
    )


def write_manifest_atomic(gateway_dir: Path, manifest: Manifest) -> Path:
    p = gateway_dir / MANIFEST_NAME
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest.to_json(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(p)
    return p
