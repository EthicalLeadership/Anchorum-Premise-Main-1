"""Cryptographically anchored signer authorization v3 (Design D).

The trust anchor is a monotonic, versioned, signed state machine. It is
the sole authority for which signers may produce registry entries and
which have been revoked. Revocation is a state transition on the anchor;
there is no separate revocation file.

Prior art: this is the TUF (The Update Framework) metadata model applied
to signer authorization. Anchors are versioned, threshold-signed, and
expire; root rotation is a threshold-signed transition; freshness is
`expires_at`; rollback protection is monotonic `anchor_seq`.

Transition classes and their authorization:

  * Root-set change      requires predecessor.threshold signatures from
                         predecessor.root_ids
  * Signer addition      requires anchor.threshold signatures from
                         anchor.root_ids
  * Signer revocation    requires 1 signature from anchor.root_ids
  * No-op (metadata)     requires 1 signature from anchor.root_ids

Disallowed transitions (rejected outright):

  * Signer removal           mark revoked instead
  * Signer pubkey change     create a new signer id instead
  * Un-revoking a signer     revoked_at is monotonic
  * Changing revoked_at      value is immutable once set
  * Adding an already-revoked signer
  * Non-None rotation_of on a genesis anchor

Freshness contract: a verifier must obtain a fresh anchor within
`expires_at` of the last one. Rotation anchors default to 90 days;
revocation anchors default to 7 days.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from ._canonical import canonical_json, sha256_hex


ANCHOR_VERSION = "3"
DEFAULT_ANCHOR_PATH = Path(".anchorum/trust-anchor.json")
ENV_ROOT_PUBKEYS = "ANCHORUM_ROOT_PUBKEYS"
DEFAULT_ROTATION_TTL = timedelta(days=90)
DEFAULT_REVOCATION_TTL = timedelta(days=7)


class TrustError(Exception):
    """Raised on any anchor integrity failure."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _now_iso() -> str:
    return _now().strftime("%Y-%m-%dT%H:%M:%SZ")


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


@dataclass(frozen=True)
class Signer:
    pubkey: str                     # hex raw Ed25519 public key
    authorized_at: str              # iso timestamp
    revoked_at: Optional[str] = None


def _normalize_signers(signers: dict, default_authorized_at: str) -> dict:
    """Accept {sid: Signer} or {sid: hex_str}; return {sid: Signer}."""
    out = {}
    for sid, v in signers.items():
        if isinstance(v, Signer):
            out[sid] = v
        elif isinstance(v, str):
            out[sid] = Signer(
                pubkey=v,
                authorized_at=default_authorized_at,
                revoked_at=None,
            )
        else:
            raise TrustError(
                f"signer {sid!r} must be Signer or hex pubkey str, "
                f"got {type(v).__name__}"
            )
    return out


@dataclass(frozen=True)
class TrustAnchor:
    anchor_version: str
    anchor_seq: int
    root_ids: tuple
    threshold: int
    signers: dict                   # signer_id -> Signer
    issued_at: str
    expires_at: str
    signatures: dict                # root_id -> hex
    rotation_of: Optional[str] = None

    def payload(self) -> dict:
        return {
            "anchor_version": self.anchor_version,
            "anchor_seq": self.anchor_seq,
            "root_ids": list(self.root_ids),
            "threshold": self.threshold,
            "signers": {
                sid: {
                    "pubkey": s.pubkey,
                    "authorized_at": s.authorized_at,
                    "revoked_at": s.revoked_at,
                }
                for sid, s in self.signers.items()
            },
            "issued_at": self.issued_at,
            "expires_at": self.expires_at,
            "rotation_of": self.rotation_of,
        }

    def canonical_payload(self) -> bytes:
        return canonical_json(self.payload()).encode("utf-8")

    def canonical_hash(self) -> str:
        return sha256_hex(self.canonical_payload())

    def valid_signers(self, root_pubkeys: dict) -> list:
        valid = []
        payload = self.canonical_payload()
        for root_id in self.root_ids:
            sig_hex = self.signatures.get(root_id)
            if not sig_hex:
                continue
            pub = root_pubkeys.get(root_id)
            if pub is None:
                continue
            try:
                pub.verify(bytes.fromhex(sig_hex), payload)
                valid.append(root_id)
            except (InvalidSignature, ValueError):
                pass
        return valid

    def is_expired(self, now: Optional[datetime] = None) -> bool:
        now = now or _now()
        return _parse_iso(self.expires_at) <= now

    def contains(self, signer_id: str) -> bool:
        return signer_id in self.signers

    def signer_pubkey(self, signer_id: str) -> Optional[Ed25519PublicKey]:
        entry = self.signers.get(signer_id)
        if entry is None:
            return None
        try:
            return Ed25519PublicKey.from_public_bytes(bytes.fromhex(entry.pubkey))
        except (ValueError, TypeError):
            return None

    def authorized_pubkey(self, signer_id: str) -> Optional[Ed25519PublicKey]:
        entry = self.signers.get(signer_id)
        if entry is None or entry.revoked_at is not None:
            return None
        try:
            return Ed25519PublicKey.from_public_bytes(bytes.fromhex(entry.pubkey))
        except (ValueError, TypeError):
            return None

    def revoked_at(self, signer_id: str) -> Optional[str]:
        entry = self.signers.get(signer_id)
        return entry.revoked_at if entry is not None else None


# --- signer-state transition legality -----------------------------------

def _classify_signer_changes(old: dict, new: dict) -> dict:
    """Validate signer-state transition. Raise on any illegal change.

    Legal changes:
      * revoked_at goes None -> timestamp on an existing signer
      * revoked_at value stays identical
      * new signers are added with revoked_at=None

    Illegal changes (raise):
      * signer removed
      * signer pubkey changed
      * signer un-revoked (timestamp -> None)
      * signer revoked_at value changed (timestamp -> different timestamp)
      * new signer added already-revoked
    """
    old_ids = set(old.keys())
    new_ids = set(new.keys())

    removed = old_ids - new_ids
    if removed:
        raise TrustError(
            f"signer(s) removed: {sorted(removed)}; mark revoked instead"
        )

    added = new_ids - old_ids
    for sid in sorted(added):
        if new[sid].revoked_at is not None:
            raise TrustError(f"new signer {sid!r} added already-revoked")

    pubkey_changed = []
    un_revoked = []
    revoked_value_changed = []
    revocations = 0

    for sid in old_ids & new_ids:
        o = old[sid]
        n = new[sid]
        if o.pubkey != n.pubkey:
            pubkey_changed.append(sid)
        if o.revoked_at is None and n.revoked_at is not None:
            revocations += 1
        elif o.revoked_at is not None and n.revoked_at is None:
            un_revoked.append(sid)
        elif o.revoked_at != n.revoked_at:
            revoked_value_changed.append(sid)

    if pubkey_changed:
        raise TrustError(
            f"signer pubkey changed for {sorted(pubkey_changed)}; "
            "create a new signer id instead"
        )
    if un_revoked:
        raise TrustError(
            f"signer un-revoked for {sorted(un_revoked)}; "
            "revoked_at is monotonic"
        )
    if revoked_value_changed:
        raise TrustError(
            f"revoked_at value changed for {sorted(revoked_value_changed)}; "
            "value is immutable once set"
        )

    return {"added": added, "revocations": revocations}


# --- construction -------------------------------------------------------

def build_anchor(
    *,
    root_ids: tuple,
    threshold: int,
    signers: dict,
    root_private_keys: dict,
    anchor_seq: int = 0,
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
    rotation_of: Optional[str] = None,
) -> TrustAnchor:
    if not isinstance(threshold, int) or threshold < 1:
        raise TrustError("threshold must be a positive integer")
    if threshold > len(root_ids):
        raise TrustError(
            f"threshold {threshold} exceeds root count {len(root_ids)}"
        )
    if len(set(root_ids)) != len(root_ids):
        raise TrustError("root_ids contains duplicates")

    issued_at = issued_at or _now_iso()
    if expires_at is None:
        expires_at = _iso(_parse_iso(issued_at) + DEFAULT_ROTATION_TTL)
    if expires_at <= issued_at:
        raise TrustError("expires_at must be strictly after issued_at")

    norm_signers = _normalize_signers(signers, issued_at)

    unsigned = TrustAnchor(
        anchor_version=ANCHOR_VERSION,
        anchor_seq=anchor_seq,
        root_ids=tuple(root_ids),
        threshold=threshold,
        signers=norm_signers,
        issued_at=issued_at,
        expires_at=expires_at,
        signatures={},
        rotation_of=rotation_of,
    )
    payload = unsigned.canonical_payload()
    signatures = {}
    for root_id in root_ids:
        key = root_private_keys.get(root_id)
        if key is None:
            continue
        signatures[root_id] = key.sign(payload).hex()
    return replace(unsigned, signatures=signatures)


# --- verification -------------------------------------------------------

def verify_anchor(
    anchor: TrustAnchor,
    root_pubkeys: dict,
    predecessor: Optional[TrustAnchor] = None,
    now: Optional[datetime] = None,
) -> None:
    """Raise TrustError if the anchor is not structurally or
    cryptographically valid.

    Freshness (expires_at) is checked unconditionally.
    If predecessor is None, treat as genesis.
    If predecessor is provided, enforce transition rules and the
    authorization for the transition class.
    """
    if anchor.anchor_version != ANCHOR_VERSION:
        raise TrustError(f"unsupported anchor_version {anchor.anchor_version!r}")
    if not isinstance(anchor.threshold, int) or anchor.threshold < 1:
        raise TrustError("threshold must be a positive integer")
    if anchor.threshold > len(anchor.root_ids):
        raise TrustError("threshold exceeds root count")

    now = now or _now()
    if anchor.is_expired(now):
        raise TrustError(f"anchor expired at {anchor.expires_at}")

    if predecessor is None:
        if anchor.rotation_of is not None:
            raise TrustError("genesis anchor must have rotation_of=None")
        valid = anchor.valid_signers(root_pubkeys)
        if len(valid) < anchor.threshold:
            raise TrustError(
                f"genesis anchor: {len(valid)}/{anchor.threshold} valid "
                f"signatures from {sorted(anchor.root_ids)}"
            )
        return

    if anchor.rotation_of != predecessor.canonical_hash():
        raise TrustError(
            "anchor.rotation_of does not match predecessor.canonical_hash()"
        )
    if anchor.anchor_seq != predecessor.anchor_seq + 1:
        raise TrustError(
            f"anchor_seq not monotonic: "
            f"{predecessor.anchor_seq} -> {anchor.anchor_seq}"
        )
    if _parse_iso(anchor.issued_at) < _parse_iso(predecessor.issued_at):
        raise TrustError(
            f"issued_at went backwards: "
            f"{predecessor.issued_at} -> {anchor.issued_at}"
        )

    changes = _classify_signer_changes(predecessor.signers, anchor.signers)

    root_set_changed = (
        anchor.root_ids != predecessor.root_ids
        or anchor.threshold != predecessor.threshold
    )

    if root_set_changed:
        required = predecessor.threshold
        root_ids_to_check = predecessor.root_ids
    elif changes["added"]:
        required = anchor.threshold
        root_ids_to_check = anchor.root_ids
    else:
        required = 1
        root_ids_to_check = anchor.root_ids

    payload = anchor.canonical_payload()
    valid = []
    for root_id in root_ids_to_check:
        sig_hex = anchor.signatures.get(root_id)
        if not sig_hex:
            continue
        pub = root_pubkeys.get(root_id)
        if pub is None:
            continue
        try:
            pub.verify(bytes.fromhex(sig_hex), payload)
            valid.append(root_id)
        except (InvalidSignature, ValueError):
            pass
    if len(valid) < required:
        kind = (
            "root-set change" if root_set_changed
            else "signer addition" if changes["added"]
            else "revocation" if changes["revocations"]
            else "metadata-only"
        )
        raise TrustError(
            f"anchor transition ({kind}): "
            f"{len(valid)}/{required} valid signatures"
        )


def require_valid_anchor(
    anchor: TrustAnchor,
    root_pubkeys: dict,
    predecessor: Optional[TrustAnchor] = None,
    now: Optional[datetime] = None,
) -> None:
    """Verify signatures and freshness. `root_pubkeys` is required."""
    verify_anchor(anchor, root_pubkeys, predecessor=predecessor, now=now)


# --- transitions --------------------------------------------------------

def rotate(
    *,
    old_anchor: TrustAnchor,
    new_root_ids: tuple,
    new_threshold: int,
    root_private_keys: dict,
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> TrustAnchor:
    """Produce a new anchor with a changed root set and/or threshold.

    Requires at least `old_anchor.threshold` of the *old* root private
    keys. Signers are preserved.
    """
    supplied = {
        rid: k for rid, k in root_private_keys.items()
        if rid in old_anchor.root_ids
    }
    if len(supplied) < old_anchor.threshold:
        raise TrustError(
            f"rotation requires {old_anchor.threshold} old root keys; "
            f"got {len(supplied)}"
        )

    issued_at = issued_at or _now_iso()
    if _parse_iso(issued_at) < _parse_iso(old_anchor.issued_at):
        raise TrustError("issued_at must be >= predecessor.issued_at")
    if expires_at is None:
        expires_at = _iso(_parse_iso(issued_at) + DEFAULT_ROTATION_TTL)

    return build_anchor(
        root_ids=tuple(new_root_ids),
        threshold=new_threshold,
        signers=old_anchor.signers,
        root_private_keys=supplied,
        anchor_seq=old_anchor.anchor_seq + 1,
        issued_at=issued_at,
        expires_at=expires_at,
        rotation_of=old_anchor.canonical_hash(),
    )


def revoke(
    *,
    old_anchor: TrustAnchor,
    signer_id: str,
    root_id: str,
    root_private_key: Ed25519PrivateKey,
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> TrustAnchor:
    """Produce a new anchor with a single signer revoked.

    Requires exactly one root private key. Revocation is 1-of-N.
    """
    if root_id not in old_anchor.root_ids:
        raise TrustError(f"root {root_id!r} is not in the current root set")
    if signer_id not in old_anchor.signers:
        raise TrustError(f"signer {signer_id!r} not in anchor")
    existing = old_anchor.signers[signer_id]
    if existing.revoked_at is not None:
        raise TrustError(
            f"signer {signer_id!r} already revoked at {existing.revoked_at}"
        )

    issued_at = issued_at or _now_iso()
    if _parse_iso(issued_at) < _parse_iso(old_anchor.issued_at):
        raise TrustError("issued_at must be >= predecessor.issued_at")
    if expires_at is None:
        expires_at = _iso(_parse_iso(issued_at) + DEFAULT_REVOCATION_TTL)

    new_signers = dict(old_anchor.signers)
    new_signers[signer_id] = replace(existing, revoked_at=issued_at)

    return build_anchor(
        root_ids=old_anchor.root_ids,
        threshold=old_anchor.threshold,
        signers=new_signers,
        root_private_keys={root_id: root_private_key},
        anchor_seq=old_anchor.anchor_seq + 1,
        issued_at=issued_at,
        expires_at=expires_at,
        rotation_of=old_anchor.canonical_hash(),
    )


# --- v2 migration (Decision 2a: fresh genesis) --------------------------

def migrate_v2_to_v3(
    *,
    v2_anchor: dict,
    root_private_keys: dict,
    issued_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> TrustAnchor:
    """Convert a raw v2 anchor dict into a fresh v3 genesis anchor.

    Per Decision 2a, the migrated anchor is a *new genesis*: rotation_of
    is None and anchor_seq is 0. Trust in the v2 chain does not transfer
    automatically; the caller must re-sign with v2 threshold roots.
    """
    v2_root_ids = tuple(v2_anchor["root_ids"])
    v2_threshold = int(v2_anchor["threshold"])
    v2_signers_hex = dict(v2_anchor["signers"])
    v2_issued_at = v2_anchor.get("issued_at") or _now_iso()

    supplied = {
        rid: k for rid, k in root_private_keys.items() if rid in v2_root_ids
    }
    if len(supplied) < v2_threshold:
        raise TrustError(
            f"migration requires {v2_threshold} v2 root keys; got {len(supplied)}"
        )

    issued_at = issued_at or _now_iso()
    if expires_at is None:
        expires_at = _iso(_parse_iso(issued_at) + DEFAULT_ROTATION_TTL)

    signers = {
        sid: Signer(
            pubkey=hex_val,
            authorized_at=v2_issued_at,
            revoked_at=None,
        )
        for sid, hex_val in v2_signers_hex.items()
    }

    return build_anchor(
        root_ids=v2_root_ids,
        threshold=v2_threshold,
        signers=signers,
        root_private_keys=supplied,
        anchor_seq=0,
        issued_at=issued_at,
        expires_at=expires_at,
        rotation_of=None,
    )


# --- save / load --------------------------------------------------------

def save_anchor(anchor: TrustAnchor, path: Path = DEFAULT_ANCHOR_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    d = anchor.payload()
    d["signatures"] = dict(anchor.signatures)
    path.write_text(
        json.dumps(d, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def load_anchor(path: Path = DEFAULT_ANCHOR_PATH) -> TrustAnchor:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    required = {
        "anchor_version", "anchor_seq", "root_ids", "threshold",
        "signers", "issued_at", "expires_at", "signatures",
    }
    missing = required - set(data.keys())
    if missing:
        raise TrustError(f"anchor missing fields: {sorted(missing)}")
    if data["anchor_version"] != ANCHOR_VERSION:
        raise TrustError(
            f"unsupported anchor_version {data['anchor_version']!r}; "
            f"this build supports {ANCHOR_VERSION!r}"
        )
    signers = {}
    for sid, entry in data["signers"].items():
        if not isinstance(entry, dict):
            raise TrustError(
                f"signer {sid!r} has v2 shape; run migrate_v2_to_v3"
            )
        signers[sid] = Signer(
            pubkey=entry["pubkey"],
            authorized_at=entry["authorized_at"],
            revoked_at=entry.get("revoked_at"),
        )
    return TrustAnchor(
        anchor_version=data["anchor_version"],
        anchor_seq=int(data["anchor_seq"]),
        root_ids=tuple(data["root_ids"]),
        threshold=int(data["threshold"]),
        signers=signers,
        issued_at=data["issued_at"],
        expires_at=data["expires_at"],
        signatures=dict(data["signatures"]),
        rotation_of=data.get("rotation_of"),
    )


# --- root pubkey input --------------------------------------------------

def parse_root_pubkeys_env(var: str = ENV_ROOT_PUBKEYS) -> dict:
    raw = os.environ.get(var, "").strip()
    if not raw:
        return {}
    out = {}
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise TrustError(
                f"invalid root pubkey entry {chunk!r}; expected name:hex"
            )
        name, hex_key = chunk.split(":", 1)
        name = name.strip()
        hex_key = hex_key.strip()
        if not name or not hex_key:
            raise TrustError(f"invalid root pubkey entry {chunk!r}")
        try:
            out[name] = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(hex_key)
            )
        except (ValueError, TypeError) as e:
            raise TrustError(f"invalid pubkey for {name!r}: {e}") from e
    return out


def root_pubkeys_from_file(path: Path) -> dict:
    out = {}
    for lineno, line in enumerate(
        Path(path).read_text(encoding="utf-8").splitlines(), 1
    ):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise TrustError(f"line {lineno}: expected name:hex")
        name, hex_key = line.split(":", 1)
        name = name.strip()
        hex_key = hex_key.strip()
        if not name or not hex_key:
            raise TrustError(f"line {lineno}: empty name or hex")
        try:
            out[name] = Ed25519PublicKey.from_public_bytes(
                bytes.fromhex(hex_key)
            )
        except (ValueError, TypeError) as e:
            raise TrustError(f"line {lineno}: {e}") from e
    return out
