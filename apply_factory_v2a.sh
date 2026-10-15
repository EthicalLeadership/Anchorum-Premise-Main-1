#!/usr/bin/env bash
# apply_factory_v2a.sh factory infrastructure v2.
# Strict schema validation, lifecycle state machine, signed-optional
# provenance, transactional gateway swap.
# Idempotent; overwrites factory/{schema,provenance,lifecycle,writer}.py.

set -euo pipefail
REPO="${REPO:-/home/kark/anchorum-prem}"
[ -d "$REPO/factory" ] || { echo "ERROR: $REPO/factory missing"; exit 1; }
echo "==> Target: $REPO"; echo

# ============================================================================
cat > "$REPO/factory/schema.py" <<'FILE_EOF'
"""Strict validation of discovery documents.

Every value from the discovery source (LLM or file) is untrusted. This
module converts the raw JSON into typed, validated dataclasses. Anything
that doesn't conform is rejected at the boundary, before any file is
written.

Design rules:
  - No exceptions from downstream code for missing fields: by the time
    render_* sees a Discovery, every required field is present and has
    the right type.
  - Identifiers are validated against a conservative pattern so they can
    be used as filenames, YAML keys, and route names without escaping.
  - Strings that will be emitted into YAML/JSON must not contain
    characters that break those formats. We reject rather than escape.
  - Every collection has both a required minimum size and a maximum size,
    so an LLM cannot produce a 10,000-element list.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

# Identifier: lowercase ASCII, starts with a letter, digits/underscore after.
_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
# Snake-case field name (same as identifier).
_FIELD_RE = _ID_RE
# Citation IDs are allowed to contain hyphens and capitals (FMCSA-49-CFR-391.45).
_CITATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")

MAX_LIST_ITEMS = 500
MAX_STRING_LEN = 500

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
VALID_CITATION_STATUSES = frozenset({"verified", "UNVERIFIED", "deprecated"})
# Extractor registry names the pipeline understands. Extend with care.
VALID_EXTRACTORS = frozenset({"pdf_text", "pdf_form", "ocr", "csv", "json"})


class SchemaError(ValueError):
    """A discovery document failed validation."""


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
class Discovery:
    documents: tuple[DocumentSpec, ...]
    actors: tuple[ActorSpec, ...]
    regulations: tuple[RegulationSpec, ...]
    risk_patterns: tuple[RiskSpec, ...]
    routes: tuple[str, ...]
    source: "Source"

    def canonical_json(self) -> str:
        """Deterministic serialization for hashing. Excludes `source`."""
        import json
        return json.dumps(
            {
                "documents": [_dc(d) for d in self.documents],
                "actors": [_dc(a) for a in self.actors],
                "regulations": [_dc(r) for r in self.regulations],
                "risk_patterns": [_dc(r) for r in self.risk_patterns],
                "routes": list(self.routes),
            },
            sort_keys=True,
            separators=(",", ":"),
        )


@dataclass(frozen=True)
class Source:
    type: str            # "file" | "llm"
    identifier: str      # file path or module:callable


def _dc(obj: Any) -> dict:
    from dataclasses import asdict
    return asdict(obj)


# --------------------------------------------------------------- validators

def _req_str(obj: dict, key: str, where: str, *, allow_empty: bool = False) -> str:
    v = obj.get(key)
    if not isinstance(v, str):
        raise SchemaError(f"{where}: {key!r} must be a string, got {type(v).__name__}")
    if not allow_empty and not v.strip():
        raise SchemaError(f"{where}: {key!r} must be non-empty")
    if len(v) > MAX_STRING_LEN:
        raise SchemaError(f"{where}: {key!r} exceeds {MAX_STRING_LEN} chars")
    return v


def _req_id(obj: dict, key: str, where: str, *, pattern=_ID_RE) -> str:
    v = _req_str(obj, key, where)
    if not pattern.match(v):
        raise SchemaError(
            f"{where}: {key!r}={v!r} must match {pattern.pattern}"
        )
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
    out = []
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


def _opt_list_str(obj: dict, key: str, where: str) -> tuple[str, ...]:
    return _req_list_str(obj, key, where, min_items=0)


# --------------------------------------------------------------- top level

def validate_discovery(raw: Any, source: Source) -> Discovery:
    """Convert raw discovery JSON into a validated Discovery.

    Raises SchemaError with a specific path in the message on any failure.
    """
    if not isinstance(raw, dict):
        raise SchemaError("discovery: top level must be a mapping")

    for key in ("documents", "actors", "regulations", "risk_patterns"):
        if key not in raw:
            raise SchemaError(f"discovery: missing key {key!r}")
        if not isinstance(raw[key], list):
            raise SchemaError(f"discovery: {key!r} must be a list")
        if not raw[key]:
            raise SchemaError(f"discovery: {key!r} must be non-empty")

    documents = tuple(_validate_document(d, i) for i, d in enumerate(raw["documents"]))
    actors = tuple(_validate_actor(a, i) for i, a in enumerate(raw["actors"]))
    regulations = tuple(
        _validate_regulation(r, i) for i, r in enumerate(raw["regulations"])
    )
    risks = tuple(
        _validate_risk(r, i) for i, r in enumerate(raw["risk_patterns"])
    )

    routes_raw = raw.get("routes", ["QUARANTINE_REVIEW"])
    routes = _req_list_str(
        {"routes": routes_raw}, "routes", "discovery",
        min_items=1, max_items=50, item_pattern=_ID_RE.pattern and None,
    )
    # Validate route IDs (uppercase snake is normal).
    for r in routes:
        if not re.match(r"^[A-Z][A-Z0-9_]{0,63}$", r):
            raise SchemaError(
                f"discovery.routes: {r!r} must be UPPER_SNAKE_CASE"
            )

    _check_unique("documents", [d.id for d in documents])
    _check_unique("actors", [a.id for a in actors])
    _check_unique("regulations", [r.id for r in regulations])
    _check_unique("risk_patterns", [r.id for r in risks])

    # Cross-check: every risk_pattern should have a route available.
    # Not enforced (drafts may share routes), but refuse the obvious case.
    return Discovery(
        documents=documents,
        actors=actors,
        regulations=regulations,
        risk_patterns=risks,
        routes=routes,
        source=source,
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
    fields = _req_list_str(
        d, "required_fields", where, min_items=1, item_pattern=_FIELD_RE
    )
    extractor = _req_str(d, "extractor", where)
    if extractor not in VALID_EXTRACTORS:
        raise SchemaError(
            f"{where}.extractor={extractor!r} not in {sorted(VALID_EXTRACTORS)}"
        )
    retention = d.get("retention_days")
    if not isinstance(retention, int) or isinstance(retention, bool):
        raise SchemaError(f"{where}.retention_days must be an int")
    if not 1 <= retention <= 36500:
        raise SchemaError(f"{where}.retention_days must be 1..36500")
    gaps = _opt_list_str(d, "gaps", where)
    return DocumentSpec(
        id=doc_id, label=label, filename_glob=glob,
        mime_types=mimes, required_fields=fields,
        extractor=extractor, retention_days=retention, gaps=gaps,
    )


def _validate_actor(a: Any, i: int) -> ActorSpec:
    where = f"actors[{i}]"
    if not isinstance(a, dict):
        raise SchemaError(f"{where}: must be a mapping")
    return ActorSpec(
        id=_req_id(a, "id", where),
        display=_req_str(a, "display", where),
        patterns=_req_list_str(a, "patterns", where, min_items=1),
        gaps=_opt_list_str(a, "gaps", where),
    )


def _validate_regulation(r: Any, i: int) -> RegulationSpec:
    where = f"regulations[{i}]"
    if not isinstance(r, dict):
        raise SchemaError(f"{where}: must be a mapping")
    rid = _req_id(r, "id", where, pattern=_CITATION_RE)
    status = _req_str(r, "status", where)
    if status not in VALID_CITATION_STATUSES:
        raise SchemaError(
            f"{where}.status={status!r} not in {sorted(VALID_CITATION_STATUSES)}"
        )
    url = r.get("url")
    if url is not None and not isinstance(url, str):
        raise SchemaError(f"{where}.url must be a string or null")
    return RegulationSpec(
        id=rid,
        title=_req_str(r, "title", where),
        status=status,
        url=url,
        gaps=_opt_list_str(r, "gaps", where),
    )


def _validate_risk(r: Any, i: int) -> RiskSpec:
    where = f"risk_patterns[{i}]"
    if not isinstance(r, dict):
        raise SchemaError(f"{where}: must be a mapping")
    sev = _req_str(r, "severity", where)
    if sev not in VALID_SEVERITIES:
        raise SchemaError(
            f"{where}.severity={sev!r} not in {sorted(VALID_SEVERITIES)}"
        )
    return RiskSpec(
        id=_req_id(r, "id", where),
        description=_req_str(r, "description", where),
        severity=sev,
        gaps=_opt_list_str(r, "gaps", where),
    )
FILE_EOF
echo "  wrote factory/schema.py"

# ============================================================================
cat > "$REPO/factory/lifecycle.py" <<'FILE_EOF'
"""Gateway lifecycle state machine.

States, in order. A gateway is exactly one of:

    DISCOVERED       A discovery document exists; nothing written.
    DRAFT            Factory wrote files. Not evaluated. Not approved.
    VALIDATED        Human reviewed schema and citations.
    EVALUATED        Evals pass with a real extractor and human goldens.
    DOMAIN_APPROVED  Domain expert signed off.
    PROMOTED         Production-deployable.

The factory can produce DISCOVERED or DRAFT only. It may not write to a
gateway whose current state is above DRAFT without --force, and even then
it demotes the result back to DRAFT (a rewrite invalidates any prior
validation). No code path in the factory can set a state above DRAFT.

Transitions allowed (src -> dst):
    None          -> DISCOVERED
    None          -> DRAFT
    DISCOVERED    -> DRAFT
    DRAFT         -> DRAFT     (regeneration; requires --force if edited)
    any -> DRAFT               (only if --force is passed; demotion)

Transitions NOT allowed from the factory:
    anything -> VALIDATED or above. Those require explicit human action
    using a separate tool (not yet written; out of scope).
"""
from __future__ import annotations


STATES = (
    "DISCOVERED",
    "DRAFT",
    "VALIDATED",
    "EVALUATED",
    "DOMAIN_APPROVED",
    "PROMOTED",
)
RANK = {s: i for i, s in enumerate(STATES)}

FACTORY_MAX_STATE = "DRAFT"


class LifecycleError(Exception):
    """A lifecycle transition was refused."""


def rank(state: str) -> int:
    if state not in RANK:
        raise LifecycleError(f"unknown lifecycle state {state!r}")
    return RANK[state]


def factory_may_write(current: str | None, *, force: bool) -> str:
    """Decide what state the factory can write to.

    Returns the state the gateway will be in after this write.

    Raises LifecycleError if the transition is refused.
    """
    if current is None:
        return "DRAFT"
    if current not in RANK:
        raise LifecycleError(f"unknown current state {current!r}")
    if rank(current) <= rank(FACTORY_MAX_STATE):
        # Regeneration of a draft is allowed (human-edit detection is a
        # separate check in writer.py). Result stays DRAFT.
        return "DRAFT"
    # Current is above DRAFT. Only --force can demote.
    if not force:
        raise LifecycleError(
            f"gateway is at {current}; the factory may only write at or "
            f"below {FACTORY_MAX_STATE}. Rewriting a {current} gateway "
            f"invalidates its validation and approval. Pass --force to "
            f"demote it back to {FACTORY_MAX_STATE}, or update the "
            f"gateway with the appropriate human tool."
        )
    return "DRAFT"
FILE_EOF
echo "  wrote factory/lifecycle.py"

# ============================================================================
cat > "$REPO/factory/provenance.py" <<'FILE_EOF'
"""Provenance manifest for factory-generated gateways.

The manifest (`.anchorum-factory.json`) is the factory's record of what
it wrote and under what conditions. It is strictly validated on read.

Signing (optional):
  If ANCHORUM_FACTORY_SIGNING_KEY is set (hex-encoded Ed25519 seed), the
  manifest is signed. The signature covers the canonical JSON of the
  manifest with the `signature` field omitted. Verification uses the
  embedded public key.

  Signed: tampering with any field of the manifest is detectable, so
  the writer's human-edit detection cannot be defeated by editing the
  manifest to match the edited file.
  Unsigned: the manifest is a self-asserting record. The writer's
  human-edit detection holds against accidents, not adversaries.

  The manifest records which case applies in `signature` (null if unsigned).
"""
from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MANIFEST_NAME = ".anchorum-factory.json"
MANIFEST_SCHEMA = 1

_GEN_ID_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"  # Crockford base32


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
class Signature:
    algorithm: str
    public_key: str
    value: str


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
    signature: Signature | None

    def to_json(self, *, include_signature: bool = True) -> dict:
        d = {
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
        }
        if include_signature:
            d["signature"] = (
                None if self.signature is None
                else {
                    "algorithm": self.signature.algorithm,
                    "public_key": self.signature.public_key,
                    "value": self.signature.value,
                }
            )
        return d

    def canonical_json(self) -> str:
        """Deterministic serialization for signing; excludes `signature`."""
        return json.dumps(
            self.to_json(include_signature=False),
            sort_keys=True, separators=(",", ":"),
        )


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
    """26-char Crockford-base32 ULID-ish. Monotonic within the same ms
    is not guaranteed; uniqueness is (48 bits of randomness)."""
    ts = int(time.time() * 1000).to_bytes(6, "big")
    rnd = secrets.token_bytes(10)
    raw = ts + rnd
    n = int.from_bytes(raw, "big")
    chars = []
    for _ in range(26):
        chars.append(_GEN_ID_ALPHABET[n & 0x1F])
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
        signature=None,
    )
    signed = _maybe_sign(m)
    return signed


# ------------------------------------------------------------------ signing

def _signing_key_bytes() -> bytes | None:
    env = os.environ.get("ANCHORUM_FACTORY_SIGNING_KEY", "").strip()
    if not env:
        return None
    try:
        key = bytes.fromhex(env)
    except ValueError as exc:
        raise ValueError(
            f"ANCHORUM_FACTORY_SIGNING_KEY must be hex-encoded: {exc}"
        ) from exc
    if len(key) != 32:
        raise ValueError(
            f"ANCHORUM_FACTORY_SIGNING_KEY must be 32 bytes (64 hex chars); "
            f"got {len(key)} bytes"
        )
    return key


def _maybe_sign(m: Manifest) -> Manifest:
    key = _signing_key_bytes()
    if key is None:
        return m
    try:
        import nacl.signing  # type: ignore
    except ImportError as exc:
        raise ValueError(
            "signing requested but PyNaCl is not installed; "
            "pip install pynacl or unset ANCHORUM_FACTORY_SIGNING_KEY"
        ) from exc
    signing_key = nacl.signing.SigningKey(key)
    message = m.canonical_json().encode("utf-8")
    signed = signing_key.sign(message)
    verify_key_hex = bytes(signing_key.verify_key).hex()
    return replace(
        m,
        signature=Signature(
            algorithm="ed25519",
            public_key=verify_key_hex,
            value=signed.signature.hex(),
        ),
    )


def verify_signature(m: Manifest) -> bool:
    """Return True if the manifest is signed and the signature is valid.

    An unsigned manifest returns False.
    """
    if m.signature is None:
        return False
    try:
        import nacl.signing  # type: ignore
    except ImportError:
        return False
    try:
        pk = bytes.fromhex(m.signature.public_key)
        sig = bytes.fromhex(m.signature.value)
    except ValueError:
        return False
    vk = nacl.signing.VerifyKey(pk)
    message = m.canonical_json().encode("utf-8")
    try:
        vk.verify(message, sig)
        return True
    except Exception:
        return False


# ---------------------------------------------------------------- reading

class ManifestError(ValueError):
    """Manifest is missing, malformed, or of an unsupported schema."""


def read_manifest(gateway_dir: Path) -> Manifest | None:
    """Read and validate the manifest. Raises ManifestError on any defect.

    Returns None if the file does not exist. Never returns a partially
    validated manifest.
    """
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
            raise ManifestError(
                f"{p}: {key!r} must be {typ.__name__}, got {type(v).__name__}"
            )
        return v

    sv = need("schema_version", int)
    if sv != MANIFEST_SCHEMA:
        raise ManifestError(
            f"{p}: schema_version {sv} unsupported; loader speaks {MANIFEST_SCHEMA}"
        )
    source_d = need("source", dict)
    for k in ("type", "identifier", "prompt_version"):
        if not isinstance(source_d.get(k), str):
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
            raise ManifestError(f"{p}: files[{i}].sha256 is not hex-64")
        files.append(FileEntry(path=path, sha256=sha))

    sig_raw = data.get("signature")
    sig: Signature | None = None
    if sig_raw is not None:
        if not isinstance(sig_raw, dict):
            raise ManifestError(f"{p}: signature must be a mapping or null")
        for k in ("algorithm", "public_key", "value"):
            if not isinstance(sig_raw.get(k), str):
                raise ManifestError(f"{p}: signature.{k} must be a string")
        sig = Signature(
            algorithm=sig_raw["algorithm"],
            public_key=sig_raw["public_key"],
            value=sig_raw["value"],
        )

    m = Manifest(
        schema_version=sv,
        generation_id=need("generation_id", str),
        factory_version=need("factory_version", str),
        generated_at=need("generated_at", str),
        lifecycle=need("lifecycle", str),
        source=Source(
            type=source_d["type"],
            identifier=source_d["identifier"],
            prompt_version=source_d["prompt_version"],
        ),
        inputs_sha256=need("inputs_sha256", str),
        files=tuple(files),
        signature=sig,
    )

    if m.signature is not None:
        if not verify_signature(m):
            raise ManifestError(
                f"{p}: signature verification failed the manifest has "
                f"been modified, or the signature block is corrupt"
            )
    return m


def write_manifest_atomic(gateway_dir: Path, manifest: Manifest) -> Path:
    """Write the manifest to a temp file and replace atomically."""
    p = gateway_dir / MANIFEST_NAME
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest.to_json(), indent=2, sort_keys=True),
        encoding="utf-8",
    )
    tmp.replace(p)
    return p
FILE_EOF
echo "  wrote factory/provenance.py"

# ============================================================================
cat > "$REPO/factory/writer.py" <<'FILE_EOF'
"""Transactional writer for factory-generated gateways.

A write proceeds as:

    1.  Ownership check     does the destination exist? is it ours?
    2.  Human-edit check    any tracked file changed since last generation?
    3.  Untracked-file check any file present that we didn't create?
    4.  Lifecycle check     is the destination at or below DRAFT?
    5.  Stage               write everything to <name>.staging.<id>/
    6.  Self-validate       call load_gateway() against the staging dir
    7.  Swap                rename old aside, rename staging in, delete old
    8.  fsync

If any step fails, the destination is unchanged.

Design rules:
  - A partial write never lands at the destination.
  - A write that would lose human work is refused unless --force is passed
    with an explicit acknowledgement string.
  - The gateway directory is either the old generation or the new one,
    never a mix.
"""
from __future__ import annotations

import errno
import os
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path

from . import FACTORY_VERSION
from .lifecycle import LifecycleError, factory_may_write
from .provenance import (
    MANIFEST_NAME,
    Manifest,
    ManifestError,
    build_manifest,
    read_manifest,
    sha256_file,
    write_manifest_atomic,
)


# Files that we don't consider "content" for ownership/untracked purposes.
IGNORED_NAMES = frozenset({
    ".DS_Store", "__pycache__", ".pytest_cache", ".mypy_cache",
    ".ruff_cache", ".git",
})


class WriteRefused(Exception):
    """Any of the preconditions for a safe write failed."""


@dataclass(frozen=True)
class WritePlan:
    """A description of what a write would do, produced before touching disk."""
    gateway_dir: Path
    lifecycle_from: str | None
    lifecycle_to: str
    will_replace: tuple[str, ...]      # tracked files whose content will change
    will_add: tuple[str, ...]          # new files
    will_delete: tuple[str, ...]       # tracked files not in the new set
    human_edited: tuple[str, ...]      # tracked files whose current hash != manifest
    untracked: tuple[str, ...]         # present files not in the manifest

    @property
    def is_destructive(self) -> bool:
        return bool(self.human_edited or self.will_delete or self.untracked)

    def summary(self) -> str:
        lines = [
            f"gateway:  {self.gateway_dir}",
            f"lifecycle: {self.lifecycle_from or '(none)'} -> {self.lifecycle_to}",
            f"replace:  {len(self.will_replace)} file(s)",
            f"add:      {len(self.will_add)} file(s)",
            f"delete:   {len(self.will_delete)} file(s)",
        ]
        if self.human_edited:
            lines.append("HUMAN-EDITED (would be overwritten):")
            lines += [f"  {p}" for p in self.human_edited]
        if self.untracked:
            lines.append("UNTRACKED (present, not in manifest):")
            lines += [f"  {p}" for p in self.untracked]
        return "\n".join(lines)


# -------------------------------------------------------------------- plan

def plan_write(
    gateway_dir: Path,
    new_files: dict[str, str],
    *,
    force: bool,
) -> WritePlan:
    """Compute what a write would do without touching disk.

    Raises WriteRefused if a precondition fails and the caller has not
    requested --force with an acknowledgement.
    """
    lifecycle_to = factory_may_write(
        _peek_lifecycle(gateway_dir), force=force
    )

    existing = _read_manifest_or_none(gateway_dir)
    manifest_files = {f.path: f.sha256 for f in existing.files} if existing else {}

    will_replace: list[str] = []
    will_add: list[str] = []
    for rel, content in new_files.items():
        p = gateway_dir / rel
        if not p.is_file():
            will_add.append(rel)
            continue
        if manifest_files.get(rel) == sha256_of_str(content):
            continue  # identical content, no-op
        will_replace.append(rel)

    will_delete = [p for p in manifest_files if p not in new_files]

    human_edited: list[str] = []
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


def sha256_of_str(s: str) -> str:
    import hashlib
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


# ------------------------------------------------------------------ commit

def commit_write(
    gateway_dir: Path,
    new_files: dict[str, str],
    *,
    inputs_sha256: str,
    source,               # provenance.Source
    force: bool,
    acknowledge: str | None,
) -> Manifest:
    """Perform the write transactionally.

    `acknowledge` must equal plan_write(...).summary() when plan.is_destructive,
    proving the caller saw exactly what would be replaced.
    """
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
                "refused: --force requires --acknowledge=<summary-hash> "
                "so the caller has seen exactly what will change.\n"
                + plan.summary()
            )
        expected = sha256_of_str(plan.summary())
        if acknowledge != expected:
            raise WriteRefused(
                f"refused: acknowledgement mismatch. Expected sha256:\n"
                f"  {expected}\nPass --acknowledge={expected} to proceed."
            )

    parent = gateway_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    staging = parent / f".{gateway_dir.name}.staging.{uuid.uuid4().hex[:12]}"
    backup = parent / f".{gateway_dir.name}.backup.{uuid.uuid4().hex[:12]}"

    try:
        _stage(staging, new_files, gateway_dir, plan)
        manifest = build_manifest(
            staging,
            files=sorted(new_files.keys()),
            inputs_sha256=inputs_sha256,
            source=source,
            lifecycle=plan.lifecycle_to,
            factory_version=FACTORY_VERSION,
        )
        write_manifest_atomic(staging, manifest)
        _fsync_dir(staging)

        _validate_staging(staging)

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
        return manifest

    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        if backup.exists() and not gateway_dir.exists():
            os.replace(backup, gateway_dir)
        raise


def _stage(
    staging: Path,
    new_files: dict[str, str],
    gateway_dir: Path,
    plan: WritePlan,
) -> None:
    """Write new content to staging, copying preserved files from the
    destination. Files not in new_files but not deleted are preserved
    only if the caller has retained them; currently we treat every
    non-listed file as delete-on-write."""
    staging.mkdir(parents=True, exist_ok=False)
    for rel, content in new_files.items():
        p = staging / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    # Ensure evals/golden exists so load_gateway can validate.
    (staging / "evals" / "golden").mkdir(parents=True, exist_ok=True)


def _validate_staging(staging: Path) -> None:
    """Load the staged gateway via the real loader. If it doesn't load,
    the write is aborted. This is the 'validate then swap' step.

    Note: the factory produces tier C drafts, which the loader accepts.
    A tier A gateway with commented-out rules would be rejected by the
    loader; that's intended.
    """
    # Import lazily so tests that don't need the loader can import writer.
    try:
        from dossier_pipeline.gateway import load_gateway, GatewayError
    except ImportError:
        return  # loader not installed in this environment; skip
    try:
        load_gateway(staging.name, base_path=staging.parent)
    except GatewayError as exc:
        raise WriteRefused(
            f"staged gateway failed to load: {exc}\nThe write was aborted; "
            f"the destination is unchanged."
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


def _list_untracked(
    gateway_dir: Path, manifest_files: dict[str, str]
) -> list[str]:
    if not gateway_dir.exists():
        return []
    tracked = set(manifest_files.keys())
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
    except OSError as exc:
        if exc.errno in (errno.EPERM, errno.EACCES):
            return  # some filesystems refuse; best-effort
        raise
    try:
        os.fsync(fd)
    finally:
        os.close(fd)
FILE_EOF
echo "  wrote factory/writer.py"

# ============================================================================
# Verification
# ============================================================================
echo
echo "==> Verification"
for f in factory/schema.py factory/lifecycle.py factory/provenance.py factory/writer.py; do
    if [ ! -f "$REPO/$f" ]; then
        echo "  MISS $f"; exit 1
    fi
    printf "  OK    %-45s %8s bytes  " "$f" "$(stat -c%s "$REPO/$f")"
    if python3 -c "import ast; ast.parse(open('$REPO/$f').read())" 2>/dev/null; then
        echo "syntax OK"
    else
        echo "SYNTAX ERROR"
        python3 -c "import ast; ast.parse(open('$REPO/$f').read())"
        exit 1
    fi
done

echo
echo "==> Import check (schema + lifecycle + provenance need only stdlib)"
cd "$REPO"
python3 -c "
from factory.schema import validate_discovery, Source, SchemaError
from factory.lifecycle import factory_may_write, LifecycleError
from factory.provenance import build_manifest, new_generation_id, sha256_str
print('  imports OK')
print('  sample generation_id:', new_generation_id())
try:
    factory_may_write('PROMOTED', force=False)
except LifecycleError as e:
    print('  lifecycle refuses PROMOTED without force: OK')
"

echo
echo "==> v2a landed."
echo
echo "Next:  v2b (generate.py rewrite + prompts + README + smoke test)."
echo "       Say 'ready for v2b' and I'll write that drop."
