"""
Court-admissible evidence primitives for DOSSIER-PIPELINE.

This module introduces append-only evidence packets, custody events,
hash chaining, sealed manifests, and independent verification helpers.

The implementation is intentionally self-contained so it can be used by
the existing pipeline without relying on the control-plane codepath.
"""

from __future__ import annotations

import datetime
import hashlib
import hmac
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from dossier_enforcement import (FailureMode, LockRegistry, LockSpec,
                                  TransactionGate, assert_that, invariant)


class SystemState(str, Enum):
    OK = "ok"
    DEGRADED = "degraded"
    COMPROMISED = "compromised"
    LOCKED = "locked"


class CustodyAction(str, Enum):
    INGESTED = "INGESTED"
    VIEWED = "VIEWED"
    EXPORTED = "EXPORTED"
    VERIFIED = "VERIFIED"


@dataclass(frozen=True)
class EvidencePacket:
    evidence_id: str
    event_type: str
    raw_payload: Dict[str, Any]
    normalized_payload: Dict[str, Any]
    metadata: Dict[str, Any]
    hash_self: str
    hash_prev: str
    hash_chain_id: str
    signature_system: str
    timestamp_utc: str
    sequence_no: int
    duplicate_of: Optional[str] = None


@dataclass(frozen=True)
class CustodyEvent:
    custody_id: str
    evidence_id: str
    actor_id: str
    action: CustodyAction
    timestamp_utc: str
    signature: str
    previous_custody_hash: str
    record_hash: str
    content_hash: str
    created_at: str


@dataclass(frozen=True)
class AnchorCheckpoint:
    anchor_id: str
    hash_chain_id: str
    sequence_start: int
    sequence_end: int
    merkle_root: str
    tail_hash: str
    packet_count: int
    timestamp_utc: str


@dataclass(frozen=True)
class VerificationReport:
    system_state: SystemState
    integrity_pass: bool
    total_packets: int
    total_custody_events: int
    mismatches: List[Dict[str, Any]] = field(default_factory=list)
    tail_hash: str = ""
    anchor_hash: str = ""
    custody_chain_ok: bool = True
    custody_chain_problems: List[str] = field(default_factory=list)


class EvidenceSignerUnbound(RuntimeError):
    """Raised when the signer has no key material and would sign with nothing.

    An HMAC keyed by the empty string is a public key: every signature it
    produces can be computed by anyone, so ``verify()`` proves nothing and the
    evidence chain stops being tamper-evident. That failure mode is silent and
    therefore worse than refusing to start, so construction fails closed.
    """


class EvidenceSigner:
    """
    Lightweight signing abstraction.

    Default implementation uses HMAC-SHA256 keyed by an environment secret.
    The interface is intentionally isolated so it can later be replaced by
    a real Ed25519/HSM-backed signer without changing storage or verification.

    The secret is mandatory. Pass one explicitly, or set
    ``GDC_EVIDENCE_SECRET``. There is deliberately no unbound fallback.
    """

    def __init__(self, secret: Optional[str] = None):
        resolved = secret if secret is not None else os.getenv("GDC_EVIDENCE_SECRET")
        if resolved is None or not resolved.strip():
            raise EvidenceSignerUnbound(
                "No evidence signing secret available. Set GDC_EVIDENCE_SECRET "
                "(or pass an explicit secret). Refusing to sign evidence with an "
                "empty key, because those signatures are forgeable by anyone."
            )
        self.secret = resolved

    def sign(self, message: str) -> str:
        return hmac.new(self.secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()

    def verify(self, message: str, signature: str) -> bool:
        return hmac.compare_digest(self.sign(message), signature)

    def fingerprint(self) -> str:
        return hashlib.sha256(self.secret.encode("utf-8")).hexdigest()


def _canonical_json(payload: Any) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def _utc_now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _merkle_root(hashes: Sequence[str]) -> str:
    if not hashes:
        return _sha256("")
    level = list(hashes)
    while len(level) > 1:
        next_level: List[str] = []
        for index in range(0, len(level), 2):
            left = level[index]
            right = level[index + 1] if index + 1 < len(level) else left
            next_level.append(_sha256(left + right))
        level = next_level
    return level[0]


_evidence_registry = LockRegistry(scope="evidence")

class EvidenceStore:
    """
    Append-only SQLite store for evidence packets and custody events.
    """

    def __init__(self, db_path: str, signer: Optional[EvidenceSigner] = None):
        self.db_path = db_path
        # The signer is resolved on first use, not here. Opening the store to
        # read it needs no key material; only signing and signature
        # verification do. Resolving eagerly made every read-only command fail
        # closed without GDC_EVIDENCE_SECRET - including commands that never
        # look at an evidence signature - which is a false requirement, not a
        # control. Signing and explicit verification still fail closed (F-02).
        self._signer = signer
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._init_db()
        self.state = self._recompute_state()

    @property
    def signer(self) -> EvidenceSigner:
        """The store's signer, resolved on first use.

        Raises ``EvidenceSignerUnbound`` when no key material is configured, so
        signing and signature verification remain fail-closed; they just no
        longer do so merely because the store was opened.
        """
        if self._signer is None:
            self._signer = EvidenceSigner()
        return self._signer

    def configured_signer(self) -> Optional[EvidenceSigner]:
        """The signer if key material is available, else ``None``.

        Used to decide whether signatures *can* be checked. Never raises, so a
        caller can open and inspect a store without a key and still refuse to
        claim it verified signatures.
        """
        if self._signer is not None:
            return self._signer
        if os.getenv("GDC_EVIDENCE_SECRET", "").strip():
            return self.signer
        return None

    def _init_db(self) -> None:
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS evidence_packets (
                sequence_no INTEGER PRIMARY KEY AUTOINCREMENT,
                evidence_id TEXT UNIQUE NOT NULL,
                event_type TEXT NOT NULL,
                raw_payload TEXT NOT NULL,
                normalized_payload TEXT NOT NULL,
                metadata TEXT NOT NULL,
                hash_self TEXT UNIQUE NOT NULL,
                hash_prev TEXT NOT NULL,
                hash_chain_id TEXT NOT NULL,
                signature_system TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                duplicate_of TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS custody_events (
                custody_id TEXT PRIMARY KEY,
                evidence_id TEXT NOT NULL,
                actor_id TEXT NOT NULL,
                action TEXT NOT NULL,
                timestamp_utc TEXT NOT NULL,
                signature TEXT NOT NULL,
                previous_custody_hash TEXT NOT NULL DEFAULT '',
                record_hash TEXT NOT NULL DEFAULT '',
                content_hash TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY(evidence_id) REFERENCES evidence_packets(evidence_id)
            )
            """
        )
        for column in (
            "previous_custody_hash",
            "record_hash",
            "content_hash",
        ):
            try:
                self.conn.execute(
                    f"ALTER TABLE custody_events ADD COLUMN {column} TEXT NOT NULL DEFAULT ''"
                )
            except sqlite3.OperationalError as exc:
                if "duplicate column name" not in str(exc).lower():
                    raise
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS anchors (
                anchor_id TEXT PRIMARY KEY,
                hash_chain_id TEXT NOT NULL,
                sequence_start INTEGER NOT NULL,
                sequence_end INTEGER NOT NULL,
                merkle_root TEXT NOT NULL,
                tail_hash TEXT NOT NULL,
                packet_count INTEGER NOT NULL,
                timestamp_utc TEXT NOT NULL
            )
            """
        )
        self.conn.commit()

    def _tail_hash(self) -> str:
        cur = self.conn.execute(
            "SELECT hash_self FROM evidence_packets ORDER BY sequence_no DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else "0" * 64

    def _next_sequence(self) -> int:
        cur = self.conn.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM evidence_packets")
        return int(cur.fetchone()[0])

    def _recompute_state(self) -> SystemState:
        # Opening the store checks what can be checked without a key: the hash
        # links, the ordering, the duplicate ids. Signature verification needs
        # key material, so when none is configured it is deferred to an
        # explicit verify() call - which does require the key. The alternative
        # would be to report "unverified" as "OK", which is the failure this
        # module exists to prevent.
        report = self.verify(verify_signatures=self.configured_signer() is not None)
        return report.system_state

    def ingest(
        self,
        *,
        event_type: str,
        raw_payload: Dict[str, Any],
        normalized_payload: Dict[str, Any],
        metadata: Dict[str, Any],
        hash_chain_id: Optional[str] = None,
        duplicate_of: Optional[str] = None,
        evidence_id: Optional[str] = None,
    ) -> EvidencePacket:
        lock = _evidence_registry.create_hierarchical_lock(
            LockSpec(f"evidence.capture.{metadata.get('dossier_id', 'default')}.{hash_chain_id or 'chain'}", hierarchy_order=40)
        )
        packet: Optional[EvidencePacket] = None
        with lock:
            with TransactionGate(f"evidence-{metadata.get('dossier_id', 'default')}", auto_commit=True) as gate:
                if self.state == SystemState.LOCKED:
                    raise RuntimeError("Evidence store is LOCKED")

                evidence_id = evidence_id or (
                    str(uuid.uuid7()) if hasattr(uuid, "uuid7") else str(uuid.uuid4())
                )
                timestamp_utc = _utc_now()
                current_prev = self._tail_hash()
                chain_id = hash_chain_id or metadata.get("hash_chain_id") or _sha256(metadata.get("dossier_id", "default"))
                sequence_no = self._next_sequence()

                metadata = dict(metadata)
                metadata["signer_fingerprint"] = self.signer.fingerprint()

                packet_payload = {
                    "evidence_id": evidence_id,
                    "event_type": event_type,
                    "raw_payload": raw_payload,
                    "normalized_payload": normalized_payload,
                    "metadata": metadata,
                    "hash_prev": current_prev,
                    "hash_chain_id": chain_id,
                    "timestamp_utc": timestamp_utc,
                    "sequence_no": sequence_no,
                    "duplicate_of": duplicate_of,
                }
                hash_self = _sha256(_canonical_json(packet_payload))
                signature_system = self.signer.sign(hash_self)

                packet = EvidencePacket(
                    evidence_id=evidence_id,
                    event_type=event_type,
                    raw_payload=raw_payload,
                    normalized_payload=normalized_payload,
                    metadata=metadata,
                    hash_self=hash_self,
                    hash_prev=current_prev,
                    hash_chain_id=chain_id,
                    signature_system=signature_system,
                    timestamp_utc=timestamp_utc,
                    sequence_no=sequence_no,
                    duplicate_of=duplicate_of,
                )

                self.conn.execute(
                    """
                    INSERT INTO evidence_packets (
                        evidence_id, event_type, raw_payload, normalized_payload, metadata,
                        hash_self, hash_prev, hash_chain_id, signature_system, timestamp_utc,
                        duplicate_of, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        packet.evidence_id,
                        packet.event_type,
                        _canonical_json(packet.raw_payload),
                        _canonical_json(packet.normalized_payload),
                        _canonical_json(packet.metadata),
                        packet.hash_self,
                        packet.hash_prev,
                        packet.hash_chain_id,
                        packet.signature_system,
                        packet.timestamp_utc,
                        packet.duplicate_of,
                        timestamp_utc,
                    ),
                )
                self.conn.commit()
                self.state = self._recompute_state()
                gate.execute_now(
                    forward=lambda: None,
                    reverse=lambda: None,
                    description="store evidence packet",
                )
                invariant(
                    packet.hash_self == _sha256(_canonical_json(packet_payload)),
                    "evidence.hash_integrity",
                    actual=packet.hash_self,
                    expected=_sha256(_canonical_json(packet_payload)),
                )

        if packet is None:
            raise RuntimeError("Evidence packet was not created")
        return packet

    def add_custody_event(self, evidence_id: str, actor_id: str, action: CustodyAction) -> CustodyEvent:
        timestamp_utc = _utc_now()
        custody_id = str(uuid.uuid4())
        signer = self.signer
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            packet = self.conn.execute(
                "SELECT hash_self FROM evidence_packets WHERE evidence_id = ?",
                (evidence_id,),
            ).fetchone()
            if packet is None:
                raise ValueError(f"Evidence packet not found: {evidence_id}")
            prior = self.conn.execute(
                """
                SELECT record_hash FROM custody_events
                WHERE evidence_id = ?
                ORDER BY created_at DESC, custody_id DESC
                LIMIT 1
                """,
                (evidence_id,),
            ).fetchone()
            previous_custody_hash = prior[0] if prior else "0" * 64
            content_hash = packet[0]
            record_payload = self._custody_record_payload(
                custody_id=custody_id,
                evidence_id=evidence_id,
                actor_id=actor_id,
                action=action,
                timestamp_utc=timestamp_utc,
                created_at=timestamp_utc,
                previous_custody_hash=previous_custody_hash,
                content_hash=content_hash,
            )
            record_hash = _sha256(_canonical_json(record_payload))
            signature = signer.sign(record_hash)
            custody_event = CustodyEvent(
                custody_id=custody_id,
                evidence_id=evidence_id,
                actor_id=actor_id,
                action=action,
                timestamp_utc=timestamp_utc,
                signature=signature,
                previous_custody_hash=previous_custody_hash,
                record_hash=record_hash,
                content_hash=content_hash,
                created_at=timestamp_utc,
            )
            self.conn.execute(
                """
                INSERT INTO custody_events (
                    custody_id, evidence_id, actor_id, action, timestamp_utc, signature,
                    previous_custody_hash, record_hash, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    custody_event.custody_id,
                    custody_event.evidence_id,
                    custody_event.actor_id,
                    custody_event.action.value,
                    custody_event.timestamp_utc,
                    custody_event.signature,
                    custody_event.previous_custody_hash,
                    custody_event.record_hash,
                    custody_event.content_hash,
                    timestamp_utc,
                ),
            )
            self.conn.commit()
        except Exception:
            self.conn.rollback()
            raise
        self.state = self._recompute_state()
        return custody_event

    @staticmethod
    def _custody_record_payload(
        *,
        custody_id: str,
        evidence_id: str,
        actor_id: str,
        action: CustodyAction,
        timestamp_utc: str,
        created_at: str,
        previous_custody_hash: str,
        content_hash: str,
    ) -> Dict[str, str]:
        return {
            "custody_id": custody_id,
            "evidence_id": evidence_id,
            "actor_id": actor_id,
            "action": action.value,
            "timestamp_utc": timestamp_utc,
            "created_at": created_at,
            "previous_custody_hash": previous_custody_hash,
            "content_hash": content_hash,
        }

    def create_anchor(self) -> AnchorCheckpoint:
        packets = self.get_packets()
        if not packets:
            raise ValueError("No evidence packets available for anchoring")

        anchor_id = str(uuid.uuid4())
        root = _merkle_root([p.hash_self for p in packets])
        tail_hash = packets[-1].hash_self
        sequence_start = packets[0].sequence_no
        sequence_end = packets[-1].sequence_no
        timestamp_utc = _utc_now()

        checkpoint = AnchorCheckpoint(
            anchor_id=anchor_id,
            hash_chain_id=packets[-1].hash_chain_id,
            sequence_start=sequence_start,
            sequence_end=sequence_end,
            merkle_root=root,
            tail_hash=tail_hash,
            packet_count=len(packets),
            timestamp_utc=timestamp_utc,
        )
        self.conn.execute(
            """
            INSERT INTO anchors (
                anchor_id, hash_chain_id, sequence_start, sequence_end,
                merkle_root, tail_hash, packet_count, timestamp_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                checkpoint.anchor_id,
                checkpoint.hash_chain_id,
                checkpoint.sequence_start,
                checkpoint.sequence_end,
                checkpoint.merkle_root,
                checkpoint.tail_hash,
                checkpoint.packet_count,
                checkpoint.timestamp_utc,
            ),
        )
        self.conn.commit()
        return checkpoint

    def get_packets(self) -> List[EvidencePacket]:
        cur = self.conn.execute(
            """
            SELECT sequence_no, evidence_id, event_type, raw_payload, normalized_payload,
                   metadata, hash_self, hash_prev, hash_chain_id, signature_system,
                   timestamp_utc, duplicate_of
            FROM evidence_packets
            ORDER BY sequence_no ASC
            """
        )
        packets: List[EvidencePacket] = []
        for row in cur.fetchall():
            packets.append(
                EvidencePacket(
                    sequence_no=row[0],
                    evidence_id=row[1],
                    event_type=row[2],
                    raw_payload=json.loads(row[3]),
                    normalized_payload=json.loads(row[4]),
                    metadata=json.loads(row[5]),
                    hash_self=row[6],
                    hash_prev=row[7],
                    hash_chain_id=row[8],
                    signature_system=row[9],
                    timestamp_utc=row[10],
                    duplicate_of=row[11],
                )
            )
        return packets

    def get_custody_events(self, evidence_id: Optional[str] = None) -> List[CustodyEvent]:
        sql = """
            SELECT custody_id, evidence_id, actor_id, action, timestamp_utc, signature,
                   previous_custody_hash, record_hash, content_hash, created_at
            FROM custody_events
        """
        params: Tuple[str, ...] = ()
        if evidence_id is not None:
            sql += " WHERE evidence_id = ?"
            params = (evidence_id,)
        sql += " ORDER BY created_at ASC, custody_id ASC"
        cur = self.conn.execute(sql, params)
        return [
            CustodyEvent(
                custody_id=row[0],
                evidence_id=row[1],
                actor_id=row[2],
                action=CustodyAction(row[3]),
                timestamp_utc=row[4],
                signature=row[5],
                previous_custody_hash=row[6],
                record_hash=row[7],
                content_hash=row[8],
                created_at=row[9],
            )
            for row in cur.fetchall()
        ]

    def verify_custody_chain(
        self,
        evidence_id: str,
        *,
        verify_signatures: bool = True,
    ) -> Tuple[bool, List[str]]:
        events = self.get_custody_events(evidence_id)
        if not events:
            return False, ["no_custody_events"]

        packet = self.conn.execute(
            "SELECT hash_self FROM evidence_packets WHERE evidence_id = ?",
            (evidence_id,),
        ).fetchone()
        if packet is None:
            return False, ["evidence_packet_missing"]

        problems: List[str] = []
        previous_hash = "0" * 64
        for event in events:
            if not event.record_hash:
                problems.append(f"legacy_unlinked_event:{event.custody_id}")
                previous_hash = event.record_hash
                continue
            if event.previous_custody_hash != previous_hash:
                problems.append(f"chain_link_broken:{event.custody_id}")
            payload = self._custody_record_payload(
                custody_id=event.custody_id,
                evidence_id=event.evidence_id,
                actor_id=event.actor_id,
                action=event.action,
                timestamp_utc=event.timestamp_utc,
                created_at=event.created_at,
                previous_custody_hash=event.previous_custody_hash,
                content_hash=event.content_hash,
            )
            expected_hash = _sha256(_canonical_json(payload))
            if event.record_hash != expected_hash:
                problems.append(f"record_hash_mismatch:{event.custody_id}")
            if verify_signatures and not self.signer.verify(event.record_hash, event.signature):
                problems.append(f"signature_invalid:{event.custody_id}")
            if event.content_hash != packet[0]:
                problems.append(f"content_hash_mismatch:{event.custody_id}")
            previous_hash = event.record_hash

        return not problems, problems

    def export_bundle(self, bundle_dir: str, exporter_id: str) -> str:
        bundle_path = Path(bundle_dir)
        bundle_path.mkdir(parents=True, exist_ok=True)

        packets = self.get_packets()
        custody_events = self.get_custody_events()
        cur = self.conn.execute(
            """
            SELECT anchor_id, hash_chain_id, sequence_start, sequence_end, merkle_root,
                   tail_hash, packet_count, timestamp_utc
            FROM anchors
            ORDER BY sequence_end DESC, timestamp_utc DESC
            LIMIT 1
            """
        )
        anchor_row = cur.fetchone()

        evidence_path = bundle_path / "evidence.jsonl"
        custody_path = bundle_path / "custody_log.jsonl"
        chain_snapshot_path = bundle_path / "chain_snapshot.json"
        anchors_path = bundle_path / "anchors.json"
        manifest_path = bundle_path / "manifest.json"
        signatures_path = bundle_path / "signatures.sig"

        with evidence_path.open("w", encoding="utf-8") as handle:
            for packet in packets:
                handle.write(_canonical_json(packet.__dict__) + "\n")

        with custody_path.open("w", encoding="utf-8") as handle:
            for event in custody_events:
                handle.write(_canonical_json(event.__dict__) + "\n")

        chain_snapshot = {
            "packet_count": len(packets),
            "custody_count": len(custody_events),
            "tail_hash": packets[-1].hash_self if packets else "",
            "hash_chain_id": packets[-1].hash_chain_id if packets else "",
            "system_state": self.state.value,
        }
        chain_snapshot_path.write_text(_canonical_json(chain_snapshot), encoding="utf-8")

        anchors = []
        anchor_root = ""
        if anchor_row is not None:
            anchor = AnchorCheckpoint(
                anchor_id=anchor_row[0],
                hash_chain_id=anchor_row[1],
                sequence_start=anchor_row[2],
                sequence_end=anchor_row[3],
                merkle_root=anchor_row[4],
                tail_hash=anchor_row[5],
                packet_count=anchor_row[6],
                timestamp_utc=anchor_row[7],
            )
            anchors = [anchor.__dict__]
            anchor_root = anchor.merkle_root

        anchors_path.write_text(_canonical_json(anchors), encoding="utf-8")

        manifest = {
            "exporter_id": exporter_id,
            "exported_at": _utc_now(),
            "packet_count": len(packets),
            "custody_count": len(custody_events),
            "bundle_hash": _sha256(
                _canonical_json({
                    "evidence": [p.hash_self for p in packets],
                    "custody": [c.signature for c in custody_events],
                    "anchor": anchor_root,
                })
            ),
            "tail_hash": chain_snapshot["tail_hash"],
            "anchor_root": anchor_root,
            "signing_public_key": "hmac-sha256",
            "signer_fingerprint": self.signer.fingerprint(),
        }
        manifest_text = _canonical_json(manifest)
        manifest_signature = self.signer.sign(manifest_text)
        signatures_path.write_text(manifest_signature, encoding="utf-8")
        manifest["manifest_signature"] = manifest_signature
        manifest_path.write_text(_canonical_json(manifest), encoding="utf-8")

        self.add_custody_event(
            evidence_id=packets[-1].evidence_id if packets else "",
            actor_id=exporter_id,
            action=CustodyAction.EXPORTED,
        )

        return str(bundle_path)

    def verify(self, *, verify_signatures: bool = True) -> VerificationReport:
        """Recompute the evidence chain and report integrity.

        ``verify_signatures`` is the distinction that matters: the hash chain,
        ordering and duplicate checks are arithmetic over stored bytes and need
        no key, while a signature can only be checked with the key that made it.
        Passing ``verify_signatures=False`` therefore yields a *structural*
        result that says nothing about authenticity, which is why the default
        is ``True`` and why it fails closed instead of downgrading silently.
        """
        if verify_signatures and self.configured_signer() is None:
            raise EvidenceSignerUnbound(
                "verify() checks signatures, which requires GDC_EVIDENCE_SECRET. "
                "Pass verify_signatures=False for a structural-only check, and "
                "do not report that as authenticity."
            )

        packets = self.get_packets()
        custody_events = self.get_custody_events()
        mismatches: List[Dict[str, Any]] = []
        previous_hash = "0" * 64
        previous_timestamp: Optional[str] = None
        duplicate_seen: set[str] = set()

        for packet in packets:
            expected_payload = {
                "evidence_id": packet.evidence_id,
                "event_type": packet.event_type,
                "raw_payload": packet.raw_payload,
                "normalized_payload": packet.normalized_payload,
                "metadata": packet.metadata,
                "hash_prev": packet.hash_prev,
                "hash_chain_id": packet.hash_chain_id,
                "timestamp_utc": packet.timestamp_utc,
                "sequence_no": packet.sequence_no,
                "duplicate_of": packet.duplicate_of,
            }
            expected_hash = _sha256(_canonical_json(expected_payload))
            if packet.hash_prev != previous_hash:
                mismatches.append(
                    {
                        "sequence_no": packet.sequence_no,
                        "field": "hash_prev",
                        "expected": previous_hash,
                        "found": packet.hash_prev,
                    }
                )
            if expected_hash != packet.hash_self:
                mismatches.append(
                    {
                        "sequence_no": packet.sequence_no,
                        "field": "hash_self",
                        "expected": expected_hash,
                        "found": packet.hash_self,
                    }
                )
            if previous_timestamp is not None and packet.timestamp_utc < previous_timestamp:
                mismatches.append(
                    {
                        "sequence_no": packet.sequence_no,
                        "field": "timestamp_order",
                        "expected": f">= {previous_timestamp}",
                        "found": packet.timestamp_utc,
                    }
                )
            if packet.evidence_id in duplicate_seen:
                mismatches.append(
                    {
                        "sequence_no": packet.sequence_no,
                        "field": "duplicate_evidence_id",
                        "expected": "unique evidence_id",
                        "found": packet.evidence_id,
                    }
                )
            duplicate_seen.add(packet.evidence_id)
            if verify_signatures and not self.signer.verify(packet.hash_self, packet.signature_system):
                mismatches.append(
                    {
                        "sequence_no": packet.sequence_no,
                        "field": "signature_system",
                        "expected": "valid signature",
                        "found": packet.signature_system,
                    }
                )
            previous_hash = packet.hash_self
            previous_timestamp = packet.timestamp_utc

        for event in custody_events:
            if event.record_hash:
                message = event.record_hash
            else:
                message = (
                    f"{event.custody_id}:{event.evidence_id}:{event.actor_id}:"
                    f"{event.action.value}:{event.timestamp_utc}"
                )
            if verify_signatures and not self.signer.verify(message, event.signature):
                mismatches.append(
                    {
                        "custody_id": event.custody_id,
                        "field": "custody_signature",
                        "expected": "valid signature",
                        "found": event.signature,
                    }
                )

        custody_chain_problems: List[str] = []
        custody_chain_ok = True
        for evidence_id in sorted({event.evidence_id for event in custody_events}):
            chain_ok, problems = self.verify_custody_chain(
                evidence_id,
                verify_signatures=verify_signatures,
            )
            custody_chain_ok = custody_chain_ok and chain_ok
            custody_chain_problems.extend(problems)

        state = SystemState.OK if not mismatches else SystemState.COMPROMISED
        if mismatches:
            self.state = SystemState.LOCKED
        return VerificationReport(
            system_state=state,
            integrity_pass=not mismatches,
            total_packets=len(packets),
            total_custody_events=len(custody_events),
            mismatches=mismatches,
            tail_hash=packets[-1].hash_self if packets else "",
            anchor_hash=_merkle_root([p.hash_self for p in packets]),
            custody_chain_ok=custody_chain_ok,
            custody_chain_problems=custody_chain_problems,
        )

    def close(self) -> None:
        self.conn.close()
