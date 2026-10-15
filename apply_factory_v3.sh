#!/usr/bin/env bash
# apply_factory_v3.sh ANCHORUM gateway factory v0.3.0.
#
# Full rewrite. Trust hierarchy (root -> factory -> manifest), independent
# verifier, append-only generation log, transactional writes, strict schema
# validation, lifecycle state machine, two-step --force with acknowledgement.
#
# Idempotent: overwrites factory/ and verify/ cleanly on each run.

set -euo pipefail
REPO="${REPO:-/home/kark/anchorum-prem}"
[ -d "$REPO" ] || { echo "ERROR: $REPO not found"; exit 1; }
echo "==> Target: $REPO"; echo

rm -rf "$REPO/factory" "$REPO/verify"
mkdir -p "$REPO/factory/prompts" "$REPO/factory/examples" "$REPO/verify"

# ============================================================================
cat > "$REPO/factory/__init__.py" <<'EOF'
"""ANCHORUM gateway factory, v0.3.0.

Two-level trust hierarchy:

    root (offline)   authorizes   factory key   signs   manifest

Independent verifier in the `verify/` package re-checks the whole chain
without importing anything from `factory/`.

Lifecycle: DISCOVERED -> DRAFT -> VALIDATED -> EVALUATED ->
DOMAIN_APPROVED -> PROMOTED. The factory can only write at or below DRAFT.
"""
FACTORY_VERSION = "0.3.0"
MANIFEST_SCHEMA = 2
CERTIFICATE_VERSION = 1
EOF

# ============================================================================
cat > "$REPO/factory/schema.py" <<'EOF'
"""Strict validation of discovery documents.

Every value from the discovery source (LLM or file) is untrusted. This
module converts raw JSON into typed dataclasses. Anything that doesn't
conform is rejected before any file is written.

Identifiers are pattern-checked; lists have min/max; enums are enforced;
strings that will be emitted into YAML/JSON must not contain characters
that break those formats.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIELD_RE = _ID_RE
_CITATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")
_ROUTE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

MAX_LIST_ITEMS = 500
MAX_STRING_LEN = 500

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
VALID_CITATION_STATUSES = frozenset({"verified", "UNVERIFIED", "deprecated"})
VALID_EXTRACTORS = frozenset({"pdf_text", "pdf_form", "ocr", "csv", "json"})


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentSpec:
    id: str
    label: str
    filename_glob: str
    mime_types: tuple[str, ...]
    required_fields: tuple[str, ...]
    extractor: str
    retention_days: int
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class ActorSpec:
    id: str
    display: str
    patterns: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class RegulationSpec:
    id: str
    title: str
    status: str
    url: str | None
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class RiskSpec:
    id: str
    description: str
    severity: str
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class Source:
    type: str
    identifier: str
    prompt_version: str


@dataclass(frozen=True)
class Discovery:
    documents: tuple[DocumentSpec, ...]
    actors: tuple[ActorSpec, ...]
    regulations: tuple[RegulationSpec, ...]
    risk_patterns: tuple[RiskSpec, ...]
    routes: tuple[str, ...]
    source: Source

    def canonical_json(self) -> str:
        """Deterministic serialization for hashing; excludes source."""
        return json.dumps(
            {
                "documents": [asdict(d) for d in self.documents],
                "actors": [asdict(a) for a in self.actors],
                "regulations": [asdict(r) for r in self.regulations],
                "risk_patterns": [asdict(r) for r in self.risk_patterns],
                "routes": list(self.routes),
            },
            sort_keys=True, separators=(",", ":"),
        )


# ------------------------------------------------------------------ helpers

def _req_str(obj: dict, key: str, where: str, *, allow_empty: bool = False) -> str:
    v = obj.get(key)
    if not isinstance(v, str):
        raise SchemaError(f"{where}: {key!r} must be a string, got {type(v).__name__}")
    if not allow_empty and not v.strip():
        raise SchemaError(f"{where}: {key!r} must be non-empty")
    if len(v) > MAX_STRING_LEN:
        raise SchemaError(f"{where}: {key!r} exceeds {MAX_STRING_LEN} chars")
    return v


def _req_id(obj: dict, key: str, where: str, *, pattern: re.Pattern = _ID_RE) -> str:
    v = _req_str(obj, key, where)
    if not pattern.match(v):
        raise SchemaError(f"{where}: {key!r}={v!r} must match {pattern.pattern}")
    return v


def _req_list_str(
    obj: dict, key: str, where: str, *,
    min_items: int = 0, max_items: int = MAX_LIST_ITEMS,
    item_pattern: re.Pattern | None = None,
) -> tuple[str, ...]:
    v = obj.get(key, [])
    if not isinstance(v, list):
        raise SchemaError(f"{where}: {key!r} must be a list")
    if len(v) < min_items:
        raise SchemaError(f"{where}: {key!r} needs >= {min_items} items")
    if len(v) > max_items:
        raise SchemaError(f"{where}: {key!r} exceeds {max_items} items")
    out: list[str] = []
    for i, item in enumerate(v):
        if not isinstance(item, str):
            raise SchemaError(f"{where}.{key}[{i}]: must be a string")
        if not item.strip():
            raise SchemaError(f"{where}.{key}[{i}]: must be non-empty")
        if len(item) > MAX_STRING_LEN:
            raise SchemaError(f"{where}.{key}[{i}]: exceeds {MAX_STRING_LEN} chars")
        if item_pattern and not item_pattern.match(item):
            raise SchemaError(
                f"{where}.{key}[{i}]={item!r} must match {item_pattern.pattern}"
            )
        out.append(item)
    return tuple(out)


# ---------------------------------------------------------------- top level

def validate_discovery(raw: Any, source: Source) -> Discovery:
    if not isinstance(raw, dict):
        raise SchemaError("discovery: top level must be a mapping")
    for key in ("documents", "actors", "regulations", "risk_patterns"):
        if key not in raw:
            raise SchemaError(f"discovery: missing key {key!r}")
        if not isinstance(raw[key], list) or not raw[key]:
            raise SchemaError(f"discovery: {key!r} must be a non-empty list")

    documents = tuple(_validate_document(d, i) for i, d in enumerate(raw["documents"]))
    actors = tuple(_validate_actor(a, i) for i, a in enumerate(raw["actors"]))
    regulations = tuple(_validate_regulation(r, i) for i, r in enumerate(raw["regulations"]))
    risks = tuple(_validate_risk(r, i) for i, r in enumerate(raw["risk_patterns"]))

    routes_raw = raw.get("routes", ["QUARANTINE_REVIEW"])
    routes = _req_list_str(
        {"routes": routes_raw}, "routes", "discovery",
        min_items=1, max_items=50, item_pattern=_ROUTE_RE,
    )

    _check_unique("documents", [d.id for d in documents])
    _check_unique("actors", [a.id for a in actors])
    _check_unique("regulations", [r.id for r in regulations])
    _check_unique("risk_patterns", [r.id for r in risks])

    return Discovery(
        documents=documents, actors=actors, regulations=regulations,
        risk_patterns=risks, routes=routes, source=source,
    )


def _check_unique(what: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise SchemaError(f"discovery.{what}: duplicate id {i!r}")
        seen.add(i)


def _validate_document(d: Any, i: int) -> DocumentSpec:
    where = f"documents[{i}]"
    if not isinstance(d, dict):
        raise SchemaError(f"{where}: must be a mapping")
    doc_id = _req_id(d, "id", where)
    label = _req_str(d, "label", where)
    glob = _req_str(d, "filename_glob", where)
    if "/../" in glob or glob.startswith("/"):
        raise SchemaError(f"{where}.filename_glob: must not be absolute or traverse")
    mimes = _req_list_str(d, "mime_types", where, min_items=1)
    fields = _req_list_str(d, "required_fields", where, min_items=1, item_pattern=_FIELD_RE)
    extractor = _req_str(d, "extractor", where)
    if extractor not in VALID_EXTRACTORS:
        raise SchemaError(f"{where}.extractor={extractor!r} not in {sorted(VALID_EXTRACTORS)}")
    retention = d.get("retention_days")
    if not isinstance(retention, int) or isinstance(retention, bool):
        raise SchemaError(f"{where}.retention_days must be an int")
    if not 1 <= retention <= 36500:
        raise SchemaError(f"{where}.retention_days must be 1..36500")
    gaps = _req_list_str(d, "gaps", where, min_items=0)
    return DocumentSpec(
        id=doc_id, label=label, filename_glob=glob, mime_types=mimes,
        required_fields=fields, extractor=extractor,
        retention_days=retention, gaps=gaps,
    )


def _validate_actor(a: Any, i: int) -> ActorSpec:
    where = f"actors[{i}]"
    if not isinstance(a, dict):
        raise SchemaError(f"{where}: must be a mapping")
    return ActorSpec(
        id=_req_id(a, "id", where),
        display=_req_str(a, "display", where),
        patterns=_req_list_str(a, "patterns", where, min_items=1),
        gaps=_req_list_str(a, "gaps", where, min_items=0),
    )


def _validate_regulation(r: Any, i: int) -> RegulationSpec:
    where = f"regulations[{i}]"
    if not isinstance(r, dict):
        raise SchemaError(f"{where}: must be a mapping")
    rid = _req_id(r, "id", where, pattern=_CITATION_RE)
    status = _req_str(r, "status", where)
    if status not in VALID_CITATION_STATUSES:
        raise SchemaError(f"{where}.status={status!r} not in {sorted(VALID_CITATION_STATUSES)}")
    url = r.get("url")
    if url is not None and not isinstance(url, str):
        raise SchemaError(f"{where}.url must be a string or null")
    return RegulationSpec(
        id=rid, title=_req_str(r, "title", where), status=status, url=url,
        gaps=_req_list_str(r, "gaps", where, min_items=0),
    )


def _validate_risk(r: Any, i: int) -> RiskSpec:
    where = f"risk_patterns[{i}]"
    if not isinstance(r, dict):
        raise SchemaError(f"{where}: must be a mapping")
    sev = _req_str(r, "severity", where)
    if sev not in VALID_SEVERITIES:
        raise SchemaError(f"{where}.severity={sev!r} not in {sorted(VALID_SEVERITIES)}")
    return RiskSpec(
        id=_req_id(r, "id", where),
        description=_req_str(r, "description", where),
        severity=sev,
        gaps=_req_list_str(r, "gaps", where, min_items=0),
    )
EOF

# ============================================================================
cat > "$REPO/factory/lifecycle.py" <<'EOF'
"""Gateway lifecycle state machine.

States: DISCOVERED, DRAFT, VALIDATED, EVALUATED, DOMAIN_APPROVED, PROMOTED.

The factory can write at or below DRAFT only. A write to a gateway above
DRAFT requires --force and demotes it back to DRAFT (any prior validation
is invalidated by content change). No factory code path sets a state
above DRAFT.
"""
from __future__ import annotations

STATES = ("DISCOVERED", "DRAFT", "VALIDATED", "EVALUATED", "DOMAIN_APPROVED", "PROMOTED")
RANK = {s: i for i, s in enumerate(STATES)}
FACTORY_MAX_STATE = "DRAFT"


class LifecycleError(Exception):
    pass


def rank(state: str) -> int:
    if state not in RANK:
        raise LifecycleError(f"unknown lifecycle state {state!r}")
    return RANK[state]


def factory_may_write(current: str | None, *, force: bool) -> str:
    """Return the state the gateway will hold after this write.
    Raises LifecycleError if the transition is refused."""
    if current is None:
        return "DRAFT"
    if current not in RANK:
        raise LifecycleError(f"unknown current state {current!r}")
    if rank(current) <= rank(FACTORY_MAX_STATE):
        return "DRAFT"
    if not force:
        raise LifecycleError(
            f"gateway is at {current}; the factory writes at or below "
            f"{FACTORY_MAX_STATE} only. Rewriting a {current} gateway "
            f"invalidates its validation. Pass --force to demote to {FACTORY_MAX_STATE}."
        )
    return "DRAFT"
EOF

# ============================================================================
cat > "$REPO/factory/keys.py" <<'EOF'
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
EOF

# ============================================================================
cat > "$REPO/factory/provenance.py" <<'EOF'
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
EOF

# ============================================================================
cat > "$REPO/factory/generation_log.py" <<'EOF'
"""Append-only hash-chained generation log.

One JSON object per line at `<log_path>` (default: <factory_home>/generation_log.jsonl).

Each entry:

    {
      "seq": 42,
      "prev_hash": "hex64",         # entry_hash of previous, or "0"*64 for genesis
      "generation_id": "01J...",
      "gateway_name": "...",
      "factory_version": "0.3.0",
      "lifecycle": "DRAFT",
      "inputs_sha256": "hex64",
      "manifest_signature": "hex" | null,
      "recorded_at": "iso8601",
      "entry_hash": "hex64"         # sha256 of canonical JSON minus entry_hash
    }

Verification is a linear walk: recompute each entry_hash, confirm each
prev_hash matches the previous entry_hash. A tamper anywhere breaks the
chain at that point.
"""
from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

GENESIS_PREV = "0" * 64


class LogError(Exception):
    pass


def _canonical(obj: dict) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sha256_hex(b: bytes) -> str:
    import hashlib
    return hashlib.sha256(b).hexdigest()


def _entry_hash(entry_no_hash: dict) -> str:
    return _sha256_hex(_canonical(entry_no_hash))


@dataclass(frozen=True)
class LogEntry:
    seq: int
    prev_hash: str
    generation_id: str
    gateway_name: str
    factory_version: str
    lifecycle: str
    inputs_sha256: str
    manifest_signature: str | None
    recorded_at: str
    entry_hash: str

    def to_json(self) -> dict:
        return {
            "seq": self.seq,
            "prev_hash": self.prev_hash,
            "generation_id": self.generation_id,
            "gateway_name": self.gateway_name,
            "factory_version": self.factory_version,
            "lifecycle": self.lifecycle,
            "inputs_sha256": self.inputs_sha256,
            "manifest_signature": self.manifest_signature,
            "recorded_at": self.recorded_at,
            "entry_hash": self.entry_hash,
        }

    def body(self) -> dict:
        return {k: v for k, v in self.to_json().items() if k != "entry_hash"}


def _last_entry(path: Path) -> LogEntry | None:
    if not path.is_file():
        return None
    last_line = ""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                last_line = line
    if not last_line:
        return None
    return _parse_entry(json.loads(last_line), path)


def _parse_entry(data: dict, path: Path) -> LogEntry:
    required = {
        "seq": int, "prev_hash": str, "generation_id": str,
        "gateway_name": str, "factory_version": str, "lifecycle": str,
        "inputs_sha256": str, "recorded_at": str, "entry_hash": str,
    }
    for k, t in required.items():
        if not isinstance(data.get(k), t):
            raise LogError(f"{path}: entry missing or wrong-typed {k!r}")
    sig = data.get("manifest_signature")
    if sig is not None and not isinstance(sig, str):
        raise LogError(f"{path}: manifest_signature must be a string or null")
    return LogEntry(
        seq=data["seq"], prev_hash=data["prev_hash"],
        generation_id=data["generation_id"], gateway_name=data["gateway_name"],
        factory_version=data["factory_version"], lifecycle=data["lifecycle"],
        inputs_sha256=data["inputs_sha256"], manifest_signature=sig,
        recorded_at=data["recorded_at"], entry_hash=data["entry_hash"],
    )


def append(
    log_path: Path,
    *,
    generation_id: str,
    gateway_name: str,
    factory_version: str,
    lifecycle: str,
    inputs_sha256: str,
    manifest_signature: str | None,
) -> LogEntry:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    previous = _last_entry(log_path)
    seq = (previous.seq + 1) if previous else 1
    prev_hash = previous.entry_hash if previous else GENESIS_PREV
    body = {
        "seq": seq,
        "prev_hash": prev_hash,
        "generation_id": generation_id,
        "gateway_name": gateway_name,
        "factory_version": factory_version,
        "lifecycle": lifecycle,
        "inputs_sha256": inputs_sha256,
        "manifest_signature": manifest_signature,
        "recorded_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    eh = _entry_hash(body)
    entry = LogEntry(entry_hash=eh, **body)
    with log_path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry.to_json(), sort_keys=True) + "\n")
        fh.flush()
        os.fsync(fh.fileno())
    return entry


def verify_chain(log_path: Path) -> tuple[bool, str, int]:
    """Return (ok, reason, n_entries)."""
    if not log_path.is_file():
        return False, f"log not found: {log_path}", 0
    expected_prev = GENESIS_PREV
    expected_seq = 1
    n = 0
    with log_path.open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                data = json.loads(line)
            except json.JSONDecodeError as exc:
                return False, f"line {lineno}: invalid JSON: {exc}", n
            entry = _parse_entry(data, log_path)
            if entry.seq != expected_seq:
                return False, (
                    f"line {lineno}: seq {entry.seq} does not match "
                    f"expected {expected_seq}"
                ), n
            if entry.prev_hash != expected_prev:
                return False, (
                    f"line {lineno}: prev_hash {entry.prev_hash!r} does not "
                    f"match previous entry_hash {expected_prev!r}"
                ), n
            recomputed = _entry_hash(entry.body())
            if recomputed != entry.entry_hash:
                return False, (
                    f"line {lineno}: entry_hash {entry.entry_hash!r} does "
                    f"not match content hash {recomputed!r}"
                ), n
            expected_prev = entry.entry_hash
            expected_seq += 1
            n += 1
    return True, "", n


def find_generation(log_path: Path, generation_id: str) -> LogEntry | None:
    if not log_path.is_file():
        return None
    with log_path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            entry = _parse_entry(json.loads(line), log_path)
            if entry.generation_id == generation_id:
                return entry
    return None
EOF

# ============================================================================
cat > "$REPO/factory/writer.py" <<'EOF'
"""Transactional gateway writer.

    plan -> stage -> validate -> swap

Every write to a gateway passes through here. If any step fails the
destination is unchanged. A partial write never lands.
"""
from __future__ import annotations

import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import FACTORY_VERSION
from .generation_log import LogError, append as log_append
from .keys import Certificate, load_keys, KeyError_
from .lifecycle import LifecycleError, factory_may_write
from .provenance import (
    MANIFEST_NAME, Manifest, ManifestError,
    build_manifest, read_manifest, sha256_file, sha256_str,
    write_manifest_atomic,
)


IGNORED_NAMES = frozenset({
    ".DS_Store", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".git",
})


class WriteRefused(Exception):
    pass


@dataclass(frozen=True)
class WritePlan:
    gateway_dir: Path
    lifecycle_from: str | None
    lifecycle_to: str
    will_replace: tuple[str, ...]
    will_add: tuple[str, ...]
    will_delete: tuple[str, ...]
    human_edited: tuple[str, ...]
    untracked: tuple[str, ...]

    @property
    def is_destructive(self) -> bool:
        return bool(self.human_edited or self.will_delete or self.untracked)

    def summary(self) -> str:
        lines = [
            f"gateway:   {self.gateway_dir}",
            f"lifecycle: {self.lifecycle_from or '(none)'} -> {self.lifecycle_to}",
            f"replace:   {len(self.will_replace)} file(s)",
            f"add:       {len(self.will_add)} file(s)",
            f"delete:    {len(self.will_delete)} file(s)",
        ]
        if self.human_edited:
            lines.append("HUMAN-EDITED (would be overwritten):")
            lines += [f"  {p}" for p in self.human_edited]
        if self.untracked:
            lines.append("UNTRACKED (present, not in manifest):")
            lines += [f"  {p}" for p in self.untracked]
        return "\n".join(lines)

    def acknowledgement(self) -> str:
        return sha256_str(self.summary())


# -------------------------------------------------------------------- plan

def plan_write(gateway_dir: Path, new_files: dict[str, str], *, force: bool) -> WritePlan:
    lifecycle_to = factory_may_write(_peek_lifecycle(gateway_dir), force=force)
    existing = _read_manifest_or_none(gateway_dir)
    manifest_files = {f.path: f.sha256 for f in existing.files} if existing else {}

    will_replace, will_add = [], []
    for rel, content in new_files.items():
        p = gateway_dir / rel
        if not p.is_file():
            will_add.append(rel)
            continue
        if manifest_files.get(rel) == sha256_str(content):
            continue
        will_replace.append(rel)

    will_delete = [p for p in manifest_files if p not in new_files]
    human_edited = []
    for rel, expected in manifest_files.items():
        p = gateway_dir / rel
        if not p.is_file():
            continue
        if sha256_file(p) != expected:
            human_edited.append(rel)
    untracked = _list_untracked(gateway_dir, manifest_files)

    return WritePlan(
        gateway_dir=gateway_dir,
        lifecycle_from=_peek_lifecycle(gateway_dir),
        lifecycle_to=lifecycle_to,
        will_replace=tuple(sorted(will_replace)),
        will_add=tuple(sorted(will_add)),
        will_delete=tuple(sorted(will_delete)),
        human_edited=tuple(sorted(human_edited)),
        untracked=tuple(sorted(untracked)),
    )


# ------------------------------------------------------------------ commit

def commit_write(
    gateway_dir: Path,
    new_files: dict[str, str],
    *,
    inputs_sha256: str,
    source,                              # schema.Source
    force: bool,
    acknowledge: str | None,
    factory_home: Path,
    log_path: Path,
) -> Manifest:
    plan = plan_write(gateway_dir, new_files, force=force)

    if plan.is_destructive and not force:
        raise WriteRefused(
            "refused: writing would destroy or ignore existing content.\n"
            + plan.summary()
            + "\n\nPass --force to proceed."
        )
    if plan.is_destructive and force:
        if acknowledge is None:
            raise WriteRefused(
                "refused: --force requires --acknowledge=<sha256 of plan summary>.\n"
                + plan.summary()
                + f"\n\nExpected --acknowledge={plan.acknowledgement()}"
            )
        if acknowledge != plan.acknowledgement():
            raise WriteRefused(
                f"refused: acknowledgement mismatch.\n"
                f"Expected --acknowledge={plan.acknowledgement()}"
            )

    parent = gateway_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f"{gateway_dir.name}.staging.", dir=str(parent)))
    backup = parent / f"{gateway_dir.name}.backup.{uuid.uuid4().hex[:12]}"

    try:
        _stage(staging, new_files)
        _validate_staging(staging, parent)

        try:
            keys = load_keys(factory_home)
            cert = keys.certificate
            factory_priv = keys.factory_private_hex
        except KeyError_:
            cert = None
            factory_priv = None

        manifest = build_manifest(
            staging,
            files=sorted(new_files.keys()),
            inputs_sha256=inputs_sha256,
            source=source,
            lifecycle=plan.lifecycle_to,
            factory_version=FACTORY_VERSION,
            factory_private_hex=factory_priv,
            certificate=cert,
        )
        write_manifest_atomic(staging, manifest)
        _fsync_dir(staging)

        had_previous = gateway_dir.exists()
        if had_previous:
            os.replace(gateway_dir, backup)
        try:
            os.replace(staging, gateway_dir)
        except OSError:
            if had_previous and backup.exists():
                os.replace(backup, gateway_dir)
            raise
        _fsync_dir(parent)
        if backup.exists():
            shutil.rmtree(backup, ignore_errors=True)

        log_append(
            log_path,
            generation_id=manifest.generation_id,
            gateway_name=gateway_dir.name,
            factory_version=FACTORY_VERSION,
            lifecycle=manifest.lifecycle,
            inputs_sha256=inputs_sha256,
            manifest_signature=manifest.signature,
        )
        return manifest

    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not gateway_dir.exists():
            os.replace(backup, gateway_dir)
        raise


# ------------------------------------------------------------------ staging

def _stage(staging: Path, new_files: dict[str, str]) -> None:
    for rel, content in new_files.items():
        p = staging / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    (staging / "evals" / "golden").mkdir(parents=True, exist_ok=True)


def _validate_staging(staging: Path, parent: Path) -> None:
    """Load the staged gateway using the real loader. If it fails to load,
    the write is aborted and the destination is untouched."""
    try:
        from dossier_pipeline.gateway import GatewayError, load_gateway
    except ImportError:
        return
    try:
        load_gateway(staging.name, base_path=parent)
    except GatewayError as exc:
        raise WriteRefused(
            f"staged gateway failed to load: {exc}\n"
            f"the destination is unchanged"
        ) from exc


# ------------------------------------------------------------------ helpers

def _peek_lifecycle(gateway_dir: Path) -> str | None:
    m = _read_manifest_or_none(gateway_dir)
    return m.lifecycle if m else None


def _read_manifest_or_none(gateway_dir: Path) -> Manifest | None:
    if not gateway_dir.exists():
        return None
    try:
        return read_manifest(gateway_dir)
    except ManifestError as exc:
        raise WriteRefused(str(exc)) from exc


def _list_untracked(gateway_dir: Path, manifest_files: dict[str, str]) -> list[str]:
    if not gateway_dir.exists():
        return []
    tracked = set(manifest_files)
    tracked.add(MANIFEST_NAME)
    out: list[str] = []
    for root, dirs, files in os.walk(gateway_dir):
        dirs[:] = [d for d in dirs if d not in IGNORED_NAMES]
        for name in files:
            if name in IGNORED_NAMES:
                continue
            full = Path(root) / name
            rel = str(full.relative_to(gateway_dir))
            if rel in tracked:
                continue
            out.append(rel)
    return out


def _fsync_dir(p: Path) -> None:
    try:
        fd = os.open(str(p), os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
EOF

# ============================================================================
cat > "$REPO/factory/generate.py" <<'EOF'
"""Factory CLI.

    python -m factory.generate keys init [--factory-name NAME] [--home PATH]
    python -m factory.generate keys show
    python -m factory.generate write --vertical X --jurisdiction Y ...
    python -m factory.generate plan  --vertical X --jurisdiction Y ...
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import yaml

from . import FACTORY_VERSION
from . import keys as keys_mod
from . import schema as schema_mod
from .writer import WriteRefused, commit_write, plan_write
from .lifecycle import LifecycleError


PROMPT_VERSION = "01_discovery/0.1.0"
PROMPT_PATH = Path(__file__).parent / "prompts" / "01_discovery.md"


# --------------------------------------------------------------------- keys

def cmd_keys_init(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser().resolve()
    if (home / "root_private.key").exists() and not args.force:
        print(f"refused: keys already exist at {home}; use --force to regenerate",
              file=sys.stderr)
        return 2
    km = keys_mod.init_keys(home, factory_name=args.factory_name)
    print(f"root public key:    {km.root_public_hex}")
    print(f"  fingerprint:      {km.root_public_hex and keys_mod.fingerprint(km.root_public_hex)}")
    print(f"factory public key: {km.factory_public_hex}")
    print(f"  fingerprint:      {keys_mod.fingerprint(km.factory_public_hex)}")
    print()
    print(f"Wrote key material to {home}")
    print("IMPORTANT: move root_private.key to offline storage.")
    print("           root_public.hex and factory_certificate.json may be committed.")
    return 0


def cmd_keys_show(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser().resolve()
    km = keys_mod.load_keys(home)
    ok, reason = keys_mod.verify_certificate(km.certificate, km.root_public_hex)
    print(f"home:               {home}")
    print(f"root public key:    {km.root_public_hex}")
    print(f"  fingerprint:      {keys_mod.fingerprint(km.root_public_hex)}")
    print(f"factory public key: {km.factory_public_hex}")
    print(f"  fingerprint:      {keys_mod.fingerprint(km.factory_public_hex)}")
    print(f"factory name:       {km.certificate.factory_name}")
    print(f"valid:              {km.certificate.valid_from} -> {km.certificate.valid_until}")
    print(f"certificate:        {'OK' if ok else 'INVALID: ' + reason}")
    return 0 if ok else 1


# ----------------------------------------------------------------- discovery

def load_discovery(args: argparse.Namespace) -> schema_mod.Discovery:
    if args.from_json:
        p = Path(args.from_json)
        raw = json.loads(p.read_text(encoding="utf-8"))
        source = schema_mod.Source(
            type="file", identifier=str(p.resolve()),
            prompt_version=PROMPT_VERSION,
        )
        return schema_mod.validate_discovery(raw, source)

    target = os.environ.get("ANCHORUM_FACTORY_LLM")
    if not target:
        raise SystemExit(
            "no discovery source: pass --from-json <file> or set "
            "ANCHORUM_FACTORY_LLM=module:callable"
        )
    module_name, _, func_name = target.partition(":")
    if not module_name or not func_name:
        raise SystemExit(f"ANCHORUM_FACTORY_LLM={target!r} must be 'module:callable'")
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name)
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    raw = fn(args.vertical, args.jurisdiction, prompt_text)
    source = schema_mod.Source(
        type="llm", identifier=target, prompt_version=PROMPT_VERSION,
    )
    return schema_mod.validate_discovery(raw, source)


# ---------------------------------------------------------------- renderers

def render_gateway_yaml(args, discovery: schema_mod.Discovery, source) -> str:
    docs = []
    for d in discovery.documents:
        docs.append({
            "id": d.id,
            "label": d.label,
            "match": {"filename_glob": d.filename_glob, "mime_types": list(d.mime_types)},
            "required_fields": list(d.required_fields),
            "extractor": d.extractor,
            "retention_days": d.retention_days,
        })
    spec = {
        "schema_version": "1.1",
        "identity": {
            "name": args.vertical,
            "version": "0.0.1-draft",
            "jurisdiction": args.jurisdiction,
            "tier": args.tier,
            "description": f"Draft gateway for {args.vertical} ({args.jurisdiction}).",
        },
        "routes": list(discovery.routes),
        "documents": docs,
        "actors": {
            "path": "actors.json",
            "required_roles": [a.id for a in discovery.actors],
        },
        "policy": {"path": "policy.cel", "citations_path": "regulations.json",
                   "decision_log": True},
        "risk": {"path": "risk_patterns.json"},
        "evals": {
            "golden_dir": "evals/golden/",
            "thresholds": {
                "_global": {
                    "precision": 0.90, "recall": 0.85,
                    "field_completeness": 0.95, "field_precision": 0.95,
                }
            },
        },
        "legal": {
            "privacy_jurisdictions": [args.jurisdiction],
            "retention_days_default": args.retention_days,
            "consent_required": False,
            "phi_handling": args.phi == "true",
        },
    }
    header = (
        f"# ANCHORUM-FACTORY-GENERATED\n"
        f"# generator: factory/{FACTORY_VERSION}\n"
        f"# prompt:    {PROMPT_VERSION}\n"
        f"# source:    {source.type}:{source.identifier}\n"
    )
    return header + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)


def render_policy_cel(discovery: schema_mod.Discovery, source) -> str:
    lines = [
        f"// ANCHORUM-FACTORY-GENERATED",
        f"// generator: factory/{FACTORY_VERSION}",
        f"// prompt:    {PROMPT_VERSION}",
        f"// source:    {source.type}:{source.identifier}",
        "",
        "// Rules below are commented-out skeletons. Uncomment, replace",
        "// `false` with the real condition, add the rule to the golden set,",
        "// and run evals. Do not ship a draft.",
        "",
    ]
    for r in discovery.risk_patterns:
        lines += [
            f"// === rule: {r.id} ===",
            f"// {r.description}",
            "//",
            "// false",
            "//   ? {",
            f"//       \"route\": \"QUARANTINE_REVIEW\",",
            f"//       \"reason\": {json.dumps(r.description)},",
            f"//       \"severity\": {json.dumps(r.severity)},",
            f"//       \"citation\": \"UNVERIFIED\",",
            f"//       \"fields_used\": []",
            "//     }",
            "//   : null",
            "// === end ===",
            "",
        ]
    lines += [
        "// === rule: default ===",
        "// MANDATORY. Do not delete.",
        "true",
        "  ? {",
        "      \"route\": \"QUARANTINE_REVIEW\",",
        "      \"reason\": \"Draft gateway: no rule matched\",",
        "      \"severity\": \"info\",",
        "      \"citation\": \"\",",
        "      \"fields_used\": []",
        "    }",
        "  : null",
        "// === end ===",
        "",
    ]
    return "\n".join(lines)


def render_actors_json(discovery: schema_mod.Discovery) -> str:
    out = {
        a.id: {"display": a.display, "patterns": list(a.patterns)}
        for a in discovery.actors
    }
    return json.dumps(out, indent=2) + "\n"


def render_regulations_json(discovery: schema_mod.Discovery) -> str:
    out = {
        r.id: {"title": r.title, "status": r.status, "url": r.url}
        for r in discovery.regulations
    }
    return json.dumps(out, indent=2) + "\n"


def render_risk_patterns_json(discovery: schema_mod.Discovery) -> str:
    out = {
        r.id: {"description": r.description, "severity": r.severity}
        for r in discovery.risk_patterns
    }
    return json.dumps(out, indent=2) + "\n"


def render_review_queue_md(args, discovery, source) -> str:
    lines = [
        f"# {args.vertical} review queue",
        "",
        f"Generated by factory/{FACTORY_VERSION}.",
        f"Source:  {source.type}:{source.identifier}",
        f"Tier:    {args.tier}",
        f"PHI:     {args.phi}",
        "",
        "## Before this gateway can be promoted to tier A",
        "",
        "- [ ] Implement every rule in `policy.cel` (they are commented out).",
        "- [ ] Verify every citation in `regulations.json`; change `status` to `verified`.",
        "- [ ] Add golden cases under `evals/golden/` one per declared type minimum.",
        "- [ ] Run `python -m evals.run " + args.vertical + "` and reach `pass: true`.",
        "- [ ] Domain expert sign-off on schema, actors, policy, risk patterns.",
        f"- [ ] Confirm PHI handling: currently `{args.phi}`.",
        "",
        "## Gaps reported by the discovery source",
        "",
    ]
    for d in discovery.documents:
        for g in d.gaps:
            lines.append(f"- document `{d.id}`: {g}")
    for a in discovery.actors:
        for g in a.gaps:
            lines.append(f"- actor `{a.id}`: {g}")
    for r in discovery.regulations:
        if r.status == "UNVERIFIED":
            lines.append(f"- regulation `{r.id}`: needs verification")
        for g in r.gaps:
            lines.append(f"- regulation `{r.id}`: {g}")
    for r in discovery.risk_patterns:
        for g in r.gaps:
            lines.append(f"- risk `{r.id}`: {g}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- cli

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--vertical", required=True)
    p.add_argument("--jurisdiction", required=True)
    p.add_argument("--tier", default="C", choices=["B", "C"])
    p.add_argument("--phi", required=True, choices=["true", "false"])
    p.add_argument("--retention-days", type=int, required=True)
    p.add_argument("--from-json", type=Path, default=None)
    p.add_argument("--gateways-dir", type=Path, default=None)
    p.add_argument("--factory-home", type=Path, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--acknowledge", default=None)


def _base_gateways_dir(args) -> Path:
    if args.gateways_dir:
        return args.gateways_dir.resolve()
    env = os.environ.get("ANCHORUM_GATEWAYS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd() / "gateways"
    if cwd.is_dir():
        return cwd.resolve()
    return (Path(__file__).resolve().parent.parent / "gateways").resolve()


def _base_factory_home(args) -> Path:
    if args.factory_home:
        return args.factory_home.expanduser().resolve()
    return keys_mod.default_home()


def _base_log_path(home: Path) -> Path:
    env = os.environ.get("ANCHORUM_FACTORY_LOG")
    if env:
        return Path(env).expanduser().resolve()
    return home / "generation_log.jsonl"


def build_files(args, discovery, source) -> dict[str, str]:
    return {
        "gateway.yaml": render_gateway_yaml(args, discovery, source),
        "policy.cel": render_policy_cel(discovery, source),
        "actors.json": render_actors_json(discovery),
        "regulations.json": render_regulations_json(discovery),
        "risk_patterns.json": render_risk_patterns_json(discovery),
        "REVIEW_QUEUE.md": render_review_queue_md(args, discovery, source),
    }


def cmd_write(args: argparse.Namespace) -> int:
    gateways_dir = _base_gateways_dir(args)
    factory_home = _base_factory_home(args)
    log_path = _base_log_path(factory_home)
    gateway_dir = gateways_dir / args.vertical

    discovery = load_discovery(args)
    files = build_files(args, discovery, discovery.source)
    inputs_sha256 = schema_mod.SchemaError  # placeholder for clarity
    import hashlib
    inputs_sha256 = hashlib.sha256(discovery.canonical_json().encode()).hexdigest()

    try:
        manifest = commit_write(
            gateway_dir,
            files,
            inputs_sha256=inputs_sha256,
            source=discovery.source,
            force=args.force,
            acknowledge=args.acknowledge,
            factory_home=factory_home,
            log_path=log_path,
        )
    except (WriteRefused, LifecycleError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"wrote draft gateway: {gateway_dir}")
    print(f"  generation_id: {manifest.generation_id}")
    print(f"  lifecycle:     {manifest.lifecycle}")
    print(f"  files:         {len(manifest.files)}")
    print(f"  signed:        {'yes' if manifest.signature else 'no (no keys found)'}")
    print(f"  log entry:     {log_path}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    gateways_dir = _base_gateways_dir(args)
    gateway_dir = gateways_dir / args.vertical
    discovery = load_discovery(args)
    files = build_files(args, discovery, discovery.source)
    plan = plan_write(gateway_dir, files, force=args.force)
    print(plan.summary())
    if plan.is_destructive:
        print()
        print(f"To proceed: --force --acknowledge={plan.acknowledgement()}")
    return 0


# -------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="factory.generate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_keys = sub.add_parser("keys", help="key management")
    keys_sub = p_keys.add_subparsers(dest="keys_cmd", required=True)
    ki = keys_sub.add_parser("init")
    ki.add_argument("--factory-name", default="local-dev")
    ki.add_argument("--home", type=Path, default=str(keys_mod.default_home()))
    ki.add_argument("--force", action="store_true")
    ki.set_defaults(func=cmd_keys_init)
    ks = keys_sub.add_parser("show")
    ks.add_argument("--home", type=Path, default=str(keys_mod.default_home()))
    ks.set_defaults(func=cmd_keys_show)

    pw = sub.add_parser("write", help="write a gateway")
    _add_common(pw)
    pw.set_defaults(func=cmd_write)

    pp = sub.add_parser("plan", help="show what a write would do")
    _add_common(pp)
    pp.set_defaults(func=cmd_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
EOF

# ============================================================================
cat > "$REPO/factory/prompts/01_discovery.md" <<'EOF'
# Discovery prompt v0.1.0

Produce a single JSON document describing a gateway for the ANCHORUM
platform. Return JSON only. No prose, no markdown fences.

## Inputs

- vertical: {{vertical}}
- jurisdiction: {{jurisdiction}}

## Output schema

```json
{
  "documents": [
    {
      "id": "snake_case_id",
      "label": "Human Label",
      "filename_glob": "*substring*",
      "mime_types": ["application/pdf"],
      "required_fields": ["field_one", "field_two"],
      "extractor": "pdf_text",
      "retention_days": 2555,
      "gaps": ["what a domain expert must verify"]
    }
  ],
  "actors": [
    {"id": "snake_case_role", "display": "Human Role",
     "patterns": ["keyword", "name@domain.example"], "gaps": []}
  ],
  "regulations": [
    {"id": "CITATION-ID", "title": "Full title", "status": "verified",
     "url": "https://... or null", "gaps": []}
  ],
  "risk_patterns": [
    {"id": "snake_case_id", "description": "What this detects",
     "severity": "high", "gaps": []}
  ],
  "routes": ["QUARANTINE_REVIEW", "HOLD_FOR_REVIEW"]
}

EOF

echo
echo "==> apply_factory_v3.sh complete"
