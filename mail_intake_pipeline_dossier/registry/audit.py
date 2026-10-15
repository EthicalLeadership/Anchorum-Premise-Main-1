"""Hash-chained, signed audit log. Append-only. Tamper-evident.

Each entry carries:

  * ``prev_hash``   - the previous entry's ``entry_hash`` (``""`` at genesis)
  * ``record_hash`` - sha256 of the record
  * ``entry_hash``  - sha256 over ``(seq, prev_hash, record_hash)``
  * ``signature``   - HMAC-SHA256 over the entry identity, keyed by
                      ``GDC_AUDIT_SIGNING_KEY``
  * ``key_id``      - which key produced the signature

Why the signature is not optional
---------------------------------
A hash chain alone is tamper-*evident* only against accidental corruption.
Anyone able to write the file can rewrite the whole log and recompute every
hash, and ``verify_chain()`` then reports no errors at all - audit finding
F-03, confirmed by probe (``audit.chain.full_rewrite_undetected``). The
signature is what makes a rewrite detectable without the key, so the key is
mandatory: constructing an :class:`AuditLog` without key material fails closed
rather than quietly producing an unsigned chain.

Residual limitation, stated plainly: HMAC is symmetric. An attacker who has
the signing key can forge entries. This raises the bar from "anyone who can
write the file" to "anyone who can read the key", which is the same standard
the rest of this codebase's chains use. Independent verification requires an
asymmetric signer with an externally witnessed key, which is out of scope here
and is tracked as its own follow-up.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Iterator, Optional

try:  # POSIX only; the deployment target is Linux.
    import fcntl
except ImportError:  # pragma: no cover - exercised only on non-POSIX hosts
    fcntl = None  # type: ignore[assignment]

import hashlib
import hmac

from ._canonical import canonical_json, sha256_hex

DEFAULT_AUDIT_PATH = Path(".anchorum/audit.jsonl")

AUDIT_SIGNING_KEY_ENV = "GDC_AUDIT_SIGNING_KEY"
AUDIT_SIGNING_KEY_ID_ENV = "GDC_AUDIT_SIGNING_KEY_ID"
AUDIT_PATH_ENV = "GDC_AUDIT_PATH"

LEGACY_UNSIGNED = "unsigned entry (legacy: predates audit signing)"


class AuditError(Exception):
    pass


class ChainBroken(AuditError):
    pass


class AuditSigningKeyMissing(AuditError):
    """Raised when the audit log has no key and would be unsigned."""


@dataclass(frozen=True)
class AuditEntry:
    seq: int
    prev_hash: str
    record: dict
    record_hash: str
    entry_hash: str
    signature: str = ""
    key_id: str = ""


def _entry_hash(seq: int, prev_hash: str, record_hash: str) -> str:
    payload = {"seq": seq, "prev_hash": prev_hash, "record_hash": record_hash}
    return sha256_hex(canonical_json(payload).encode("utf-8"))


def _record_hash(record: dict) -> str:
    return sha256_hex(canonical_json(record).encode("utf-8"))


class AuditSigner:
    """HMAC signer for audit entries. Key material is mandatory."""

    def __init__(self, key: Optional[str] = None, key_id: Optional[str] = None):
        resolved = key if key is not None else os.getenv(AUDIT_SIGNING_KEY_ENV)
        if resolved is None or not resolved.strip():
            raise AuditSigningKeyMissing(
                f"No audit signing key available. Set {AUDIT_SIGNING_KEY_ENV} "
                "(or pass an explicit key). Refusing to write an unsigned "
                "audit chain, because a hash-only chain can be rewritten "
                "wholesale without detection."
            )
        self._key = resolved.encode("utf-8")
        self.key_id = key_id or os.getenv(AUDIT_SIGNING_KEY_ID_ENV) or "audit-default"

    def sign(self, seq: int, entry_hash: str) -> str:
        payload = canonical_json({"seq": seq, "entry_hash": entry_hash}).encode("utf-8")
        return hmac.new(self._key, payload, hashlib.sha256).hexdigest()

    def verify(self, seq: int, entry_hash: str, signature: str) -> bool:
        if not signature:
            return False
        return hmac.compare_digest(self.sign(seq, entry_hash), signature)


def _default_path() -> Path:
    configured = os.getenv(AUDIT_PATH_ENV)
    return Path(configured) if configured else DEFAULT_AUDIT_PATH


class AuditLog:
    def __init__(self, path: Optional[Path] = None, signer: Optional[AuditSigner] = None):
        self._path = Path(path) if path is not None else _default_path()
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock_path = self._path.with_name(self._path.name + ".lock")
        self._signer = signer or AuditSigner()

    @property
    def path(self) -> Path:
        return self._path

    @property
    def signer_key_id(self) -> str:
        return self._signer.key_id

    @contextmanager
    def _exclusive(self) -> Iterator[None]:
        """Serialise appends across processes and threads.

        Without this, two writers can read the same tail and both append an
        entry claiming the same ``seq``, which produces a chain that cannot be
        verified afterwards.
        """
        handle = self._lock_path.open("a")
        try:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
            handle.close()

    def _load_entry(self, raw: dict) -> AuditEntry:
        known = {field.name for field in AuditEntry.__dataclass_fields__.values()}
        unknown = set(raw) - known
        if unknown:
            raise AuditError(f"unrecognised audit entry field(s): {sorted(unknown)}")
        return AuditEntry(**raw)

    def _entries(self) -> Iterator[AuditEntry]:
        if not self._path.exists():
            return
        with self._path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if line:
                    yield self._load_entry(json.loads(line))

    def _last_entry(self) -> Optional[AuditEntry]:
        last: Optional[AuditEntry] = None
        for entry in self._entries():
            last = entry
        return last

    def append(self, record: dict) -> AuditEntry:
        with self._exclusive():
            last = self._last_entry()
            if last is None:
                seq, prev = 0, ""
            else:
                seq, prev = last.seq + 1, last.entry_hash
            record_hash = _record_hash(record)
            entry_hash = _entry_hash(seq, prev, record_hash)
            entry = AuditEntry(
                seq=seq,
                prev_hash=prev,
                record=record,
                record_hash=record_hash,
                entry_hash=entry_hash,
                signature=self._signer.sign(seq, entry_hash),
                key_id=self._signer.key_id,
            )
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(
                    json.dumps(asdict(entry), sort_keys=True, separators=(",", ":"))
                )
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            return entry

    def __iter__(self) -> Iterator[AuditEntry]:
        yield from self._entries()

    def verify_chain(self) -> list[tuple[int, str]]:
        """Return ``[(seq, problem), ...]``; empty means the chain is intact.

        An entry with no signature at all is reported, never accepted: an
        unsigned entry is indistinguishable from one an attacker inserted.
        """
        errors: list[tuple[int, str]] = []
        expected_seq = 0
        expected_prev = ""
        for entry in self._entries():
            if entry.seq != expected_seq:
                errors.append((entry.seq, f"expected seq {expected_seq}"))
            if entry.prev_hash != expected_prev:
                errors.append((entry.seq, "prev_hash mismatch"))
            if entry.record_hash != _record_hash(entry.record):
                errors.append((entry.seq, "record_hash mismatch"))
            if entry.entry_hash != _entry_hash(entry.seq, entry.prev_hash, entry.record_hash):
                errors.append((entry.seq, "entry_hash mismatch"))
            if not entry.signature:
                errors.append((entry.seq, LEGACY_UNSIGNED))
            elif not self._signer.verify(entry.seq, entry.entry_hash, entry.signature):
                errors.append((entry.seq, "signature mismatch"))
            expected_seq, expected_prev = entry.seq + 1, entry.entry_hash
        return errors

    def get(self, seq: int) -> AuditEntry:
        for entry in self._entries():
            if entry.seq == seq:
                return entry
        raise AuditError(f"no entry at seq={seq}")
