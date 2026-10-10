"""Append-only signed registry store. One JSONL file.

The store requires a v3 trust anchor at construction. Every append is
verified against the anchor's authorized signer set. There is no legacy
mode; anchors are mandatory per Design D.

Revocation is a property of the anchor, not a separate file. To revoke
a signer, produce a new anchor with the signer's revoked_at set (see
trust.revoke), then construct a new store with that anchor and the
predecessor argument set to the previous anchor.

Option A of the K4 design: the store holds exactly one anchor (the
current one). It does not manage a chain. If a caller rotates or
revokes, they construct a new store with the new anchor and pass the
old anchor as `predecessor` so the transition is verified.
"""
from __future__ import annotations
import json
import sys
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Iterator, Optional

if sys.platform == "win32":
    import msvcrt

    @contextmanager
    def _locked(f):
        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            f.seek(0)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    @contextmanager
    def _locked(f):
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)

from .entry import RegistryEntry, sign_entry, verify_entry, snapshot_hash
from .trust import TrustAnchor, TrustError, verify_anchor


DEFAULT_STORE_PATH = Path(".anchorum/registry.jsonl")


class RegistryError(Exception): pass
class DuplicateConfigHash(RegistryError): pass
class UnknownConfigHash(RegistryError): pass
class SignatureInvalid(RegistryError): pass
class SnapshotHashMismatch(RegistryError): pass
class RevokedSigner(RegistryError): pass
class UnauthorizedSigner(RegistryError): pass


class RegistryStore:
    def __init__(
        self,
        path: Path = DEFAULT_STORE_PATH,
        *,
        trust_anchor: TrustAnchor = None,
        root_pubkeys: dict = None,
        predecessor: Optional[TrustAnchor] = None):
        if trust_anchor is None:
            raise RegistryError("trust_anchor is required")
        if root_pubkeys is None:
            raise RegistryError("root_pubkeys is required")
        if trust_anchor is None:
            raise RegistryError("trust_anchor is required (Design D: anchor mandatory)")
        if not root_pubkeys:
            raise RegistryError("root_pubkeys is required and must be non-empty")
        try:
            verify_anchor(trust_anchor, root_pubkeys, predecessor=predecessor)
        except TrustError as e:
            raise RegistryError(f"trust_anchor invalid: {e}") from e
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._anchor = trust_anchor
        self._root_pubkeys = dict(root_pubkeys)

    @property
    def path(self) -> Path:
        return self._path

    @property
    def anchor(self) -> TrustAnchor:
        return self._anchor

    def _iter_raw(self) -> Iterator[dict]:
        if not self._path.exists():
            return
        with self._path.open() as f:
            for lineno, line in enumerate(f, 1):
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    raise RegistryError(f"line {lineno}: invalid JSON: {e}") from e

    def __iter__(self) -> Iterator[RegistryEntry]:
        for d in self._iter_raw():
            yield RegistryEntry(**d)

    def all_config_hashes(self) -> list[str]:
        return [e.config_hash for e in self]

    def contains(self, config_hash: str) -> bool:
        return any(e.config_hash == config_hash for e in self)

    def _authorized_pubkey_or_raise(self, signer_id: str):
        if not self._anchor.contains(signer_id):
            raise UnauthorizedSigner(
                f"signer {signer_id!r} not in trust anchor"
            )
        revoked_at = self._anchor.revoked_at(signer_id)
        if revoked_at is not None:
            raise RevokedSigner(
                f"signer {signer_id!r} revoked at {revoked_at}"
            )
        pub = self._anchor.authorized_pubkey(signer_id)
        if pub is None:
            raise UnauthorizedSigner(
                f"signer {signer_id!r} pubkey could not be parsed"
            )
        return pub

    def append(self, entry: RegistryEntry) -> None:
        # Anchor-based authorization is mandatory.
        pub = self._authorized_pubkey_or_raise(entry.signer_id)
        if not verify_entry(entry, pub):
            raise SignatureInvalid(
                f"signature invalid against trust anchor for {entry.config_hash}"
            )
        if snapshot_hash(entry.config_snapshot) != entry.config_hash:
            raise SnapshotHashMismatch(
                f"snapshot does not hash to config_hash: "
                f"expected {entry.config_hash}, "
                f"got {snapshot_hash(entry.config_snapshot)}"
            )
        # S1: lock contains() + write() together. Opened 'a+' so we can
        # read the current contents for the duplicate check and then
        # append, all under one exclusive lock.
        with self._path.open("a+", encoding="utf-8") as f:
            with _locked(f):
                f.seek(0)
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        row = json.loads(line)
                    except json.JSONDecodeError as e:
                        raise RegistryError(
                            f"corrupt registry line: {e}"
                        ) from e
                    if row.get("config_hash") == entry.config_hash:
                        raise DuplicateConfigHash(
                            f"already registered: {entry.config_hash}"
                        )
                f.seek(0, 2)
                f.write(json.dumps(asdict(entry), sort_keys=True,
                                   separators=(",", ":")))
                f.write("\n")
                f.flush()

    def get(self, config_hash: str) -> RegistryEntry:
        for e in self:
            if e.config_hash == config_hash:
                return e
        raise UnknownConfigHash(config_hash)

    def verify_all(self) -> list[tuple[str, str]]:
        """Verify every entry against the anchor's authorized signer set.

        Reports:
          * signer not in anchor
          * signer revoked
          * signature invalid against anchor
          * snapshot hash mismatch
        """
        errors: list[tuple[str, str]] = []
        for e in self:
            if not self._anchor.contains(e.signer_id):
                errors.append((
                    e.config_hash,
                    f"signer {e.signer_id!r} not in trust anchor",
                ))
                continue
            revoked_at = self._anchor.revoked_at(e.signer_id)
            if revoked_at is not None:
                errors.append((
                    e.config_hash,
                    f"signer {e.signer_id!r} revoked at {revoked_at}",
                ))
                continue
            pub = self._anchor.authorized_pubkey(e.signer_id)
            if pub is None:
                errors.append((
                    e.config_hash,
                    f"signer {e.signer_id!r} pubkey could not be parsed",
                ))
                continue
            if not verify_entry(e, pub):
                errors.append((
                    e.config_hash,
                    "signature invalid against trust anchor",
                ))
                continue
            if snapshot_hash(e.config_snapshot) != e.config_hash:
                errors.append((e.config_hash, "snapshot hash mismatch"))
        return errors
