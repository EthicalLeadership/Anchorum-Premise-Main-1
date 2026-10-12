"""
Dossier DOSSIER-PIPELINE — Control Plane
Hash-linked audit chain. Immutable records. Tribunal-ready integrity.
"""

import datetime
import hashlib
import hmac
import json
import os
import sqlite3
from pathlib import Path
from typing import Any, Dict, List, Optional

from .anchor_core import build_anchor_payload, merkle_root
from .contracts import (AdapterResult, ControlPlaneRecord, DecisionTrace,
                        PolicyDecision, RouteAction, validate_decision_trace)
from .decision import DecisionEngine
from .trust_boundary import BOUNDARY_CONTRACT_VERSION

GENESIS_HASH = "0" * 64

# Every timestamp this module writes is UTC with an explicit offset and is
# tagged with the clock that produced it. The previous implementation used
# ``datetime.datetime.now()``: naive local time, no timezone, no source, so a
# reader could not tell whether ordering was meaningful or which clock a value
# came from (audit finding F-13). No NTP or timestamp authority is used here -
# recording the source is what makes that limit explicit instead of implied.
TIME_SOURCE_SYSTEM_CLOCK_UTC = "system_clock_utc"


def _utc_now_iso() -> str:
    """Current time as an offset-aware UTC ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


class ChainIntegrityError(RuntimeError):
    """Raised when control chain verification fails in strict mode."""


class ControlPlane:
    """
    Orchestrates governed execution and emits immutable, hash-linked
    decision records. The chain is append-only and verifiable.

    This module is the single source of truth for governed history.
    All other stores are projections that must be traceable back to a
    control record hash when they represent committed pipeline outcomes.
    """

    def __init__(self, db_path: str):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self._init_db()
        self.engine = DecisionEngine()
        self.last_hash = self._get_last_hash()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS control_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sequence_no INTEGER,
                record_hash TEXT UNIQUE NOT NULL,
                previous_hash TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                payload TEXT NOT NULL,
                decision TEXT NOT NULL,
                route TEXT NOT NULL,
                signature_algo TEXT,
                signature_key_id TEXT,
                signature TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS control_events (
                event_id TEXT PRIMARY KEY,
                event_seq INTEGER,
                timestamp TEXT NOT NULL,
                message_id TEXT,
                message_key TEXT,
                stage TEXT NOT NULL,
                payload_hash TEXT NOT NULL,
                decision TEXT NOT NULL,
                state_before TEXT,
                state_after TEXT,
                reason_codes TEXT NOT NULL,
                record_hash TEXT NOT NULL,
                payload TEXT NOT NULL
            )
        """)
        self._migrate_schema()
        self.conn.commit()

    def _table_columns(self, table_name: str) -> set[str]:
        cur = self.conn.execute(f"PRAGMA table_info({table_name})")
        return {row[1] for row in cur.fetchall()}

    def _migrate_schema(self) -> None:
        control_columns = self._table_columns("control_records")
        if "sequence_no" not in control_columns:
            self.conn.execute("ALTER TABLE control_records ADD COLUMN sequence_no INTEGER")
        if "signature_algo" not in control_columns:
            self.conn.execute("ALTER TABLE control_records ADD COLUMN signature_algo TEXT")
        if "signature_key_id" not in control_columns:
            self.conn.execute("ALTER TABLE control_records ADD COLUMN signature_key_id TEXT")
        if "signature" not in control_columns:
            self.conn.execute("ALTER TABLE control_records ADD COLUMN signature TEXT")

        event_columns = self._table_columns("control_events")
        if "event_seq" not in event_columns:
            self.conn.execute("ALTER TABLE control_events ADD COLUMN event_seq INTEGER")

        self._backfill_sequence_and_signatures()

    def _signing_key(self) -> bytes:
        key = os.getenv("GDC_CONTROL_SIGNING_KEY")
        if not key:
            raise RuntimeError(
                "GDC_CONTROL_SIGNING_KEY is not set. Refusing to sign control "
                "records with a hard-coded fallback. Set the variable for the "
                "environment (dev/test/prod)."
            )
        return key.encode("utf-8")

    def _signing_key_id(self) -> str:
        return os.getenv("GDC_CONTROL_SIGNING_KEY_ID", "local-dev")

    def _signature_algo(self) -> str:
        return "hmac-sha256"

    def _compute_record_hash(self, previous_hash: str, timestamp: str, payload_json: str) -> str:
        record_content = f"{previous_hash}:{timestamp}:{payload_json}"
        return hashlib.sha256(record_content.encode("utf-8")).hexdigest()

    def _compute_record_signature(
        self,
        sequence_no: int,
        record_hash: str,
        previous_hash: str,
        timestamp: str,
        payload_json: str,
    ) -> str:
        sign_input = (
            f"{sequence_no}:{record_hash}:{previous_hash}:{timestamp}:{payload_json}".encode("utf-8")
        )
        return hmac.new(self._signing_key(), sign_input, hashlib.sha256).hexdigest()

    def _next_sequence(self) -> int:
        cur = self.conn.execute("SELECT COALESCE(MAX(sequence_no), 0) + 1 FROM control_records")
        row = cur.fetchone()
        return int(row[0]) if row and row[0] is not None else 1

    def _deterministic_event_id(self, event_seq: int, message_id: str, payload_hash: str) -> str:
        base = f"control.recorded:{event_seq}:{message_id}:{payload_hash}"
        return hashlib.sha256(base.encode("utf-8")).hexdigest()

    def _backfill_sequence_and_signatures(self) -> None:
        rows = self.conn.execute(
            """
            SELECT id, sequence_no, record_hash, previous_hash, timestamp, payload, signature
            FROM control_records
            ORDER BY id ASC
            """
        ).fetchall()

        expected_seq = 1
        for row in rows:
            rec_id, sequence_no, record_hash, previous_hash, timestamp, payload_json, signature = row
            if sequence_no != expected_seq:
                self.conn.execute(
                    "UPDATE control_records SET sequence_no = ? WHERE id = ?",
                    (expected_seq, rec_id),
                )

            if not signature:
                signature = self._compute_record_signature(
                    expected_seq,
                    record_hash,
                    previous_hash,
                    timestamp,
                    payload_json,
                )
                self.conn.execute(
                    """
                    UPDATE control_records
                    SET signature_algo = ?, signature_key_id = ?, signature = ?
                    WHERE id = ?
                    """,
                    (self._signature_algo(), self._signing_key_id(), signature, rec_id),
                )
            expected_seq += 1

        self.conn.execute(
            """
            UPDATE control_events
            SET event_seq = (
                SELECT sequence_no
                FROM control_records
                WHERE control_records.record_hash = control_events.record_hash
            )
            WHERE event_seq IS NULL
            """
        )

    def _get_last_hash(self) -> str:
        cur = self.conn.execute(
            "SELECT record_hash FROM control_records ORDER BY id DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row[0] if row else GENESIS_HASH

    def get_tail_hash(self) -> str:
        self.last_hash = self._get_last_hash()
        return self.last_hash

    def has_record_hash(self, record_hash: str) -> bool:
        cur = self.conn.execute(
            "SELECT 1 FROM control_records WHERE record_hash = ?",
            (record_hash,),
        )
        return cur.fetchone() is not None

    def get_record_by_hash(self, record_hash: str) -> Optional[Dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT record_hash, previous_hash, timestamp, payload, decision, route
            FROM control_records
            WHERE record_hash = ?
            """,
            (record_hash,),
        )
        row = cur.fetchone()
        if row is None:
            return None
        return {
            "record_hash": row[0],
            "previous_hash": row[1],
            "timestamp": row[2],
            "payload": json.loads(row[3]),
            "decision": row[4],
            "route": row[5],
        }

    def _build_execution_context(
        self,
        adapter: AdapterResult,
        policy: PolicyDecision
    ) -> Dict:
        return {
            "message_id": adapter.message_id,
            "original_message_id": adapter.original_message_id,
            "message_key": adapter.message_key,
            "raw_sha256": adapter.raw_sha256,
            "payload_hash": adapter.payload_hash,
            "actor": adapter.classification.actor.value,
            "labels": [l.value for l in adapter.classification.labels],
            "confidence": adapter.confidence,
            "policy_allowed": policy.allowed,
            "policy_reason": policy.reason,
            "policy_quarantine": policy.quarantine,
            "trace": adapter.trace,

            # Which clock produced this record's timestamp. No NTP or timestamp
            # authority is used; naming the source keeps that limit explicit.
            "time_source": TIME_SOURCE_SYSTEM_CLOCK_UTC,

            # Transport-proof fields (counts/timestamps + MD-safe base64 fingerprint)
            "received_count": adapter.received_count,
            "received_first_ts": adapter.received_first_ts,
            "received_last_ts": adapter.received_last_ts,
            "received_chain_fingerprint_b64": adapter.received_chain_fingerprint_b64,
        }

    def _build_reason_codes(self, policy: PolicyDecision, reasoning: List[str]) -> List[str]:
        codes = [code for code in policy.reason.split("; ") if code]
        codes.extend(reasoning)
        return codes

    def execute(
        self,
        adapter: AdapterResult,
        policy: PolicyDecision,
        route: Optional[RouteAction | str] = None,
        reasoning: Optional[List[str]] = None,
        divergence_reason: Optional[str] = None,
    ) -> ControlPlaneRecord:
        arbitration_mode = "ORCHESTRATED"
        if route is None or reasoning is None:
            route, reasoning = self.engine.decide(adapter, policy)
            arbitration_mode = "LEGACY_FALLBACK"

        route_value = route.value if isinstance(route, RouteAction) else route
        decision_trace = DecisionTrace(
            arbitration_mode=arbitration_mode,
            trust_boundary_version=BOUNDARY_CONTRACT_VERSION,
            divergence_reason=divergence_reason,
        )
        decision_trace_payload = {
            "arbitration_mode": decision_trace.arbitration_mode,
            "trust_boundary_version": decision_trace.trust_boundary_version,
            "divergence_reason": decision_trace.divergence_reason,
        }
        violations = validate_decision_trace(decision_trace_payload)
        if violations:
            raise ValueError("; ".join(violations))

        payload: Dict = self._build_execution_context(adapter, policy)
        payload.update({
            "route": route_value,
            "decision_reasoning": reasoning,
            "decision_trace": decision_trace_payload,
        })

        payload_json = json.dumps(payload, sort_keys=True)
        reason_codes = self._build_reason_codes(policy, reasoning)

        try:
            # Serialize chain appends across processes so each writer reads the
            # true tail before hashing and inserting its record.
            self.conn.execute("BEGIN IMMEDIATE")
            current_last_hash = self._get_last_hash()
            sequence_no = self._next_sequence()
            timestamp = _utc_now_iso()

            # Hash chain: SHA256(previous_hash + ":" + timestamp + ":" + payload_json)
            record_hash = self._compute_record_hash(current_last_hash, timestamp, payload_json)
            record_signature = self._compute_record_signature(
                sequence_no,
                record_hash,
                current_last_hash,
                timestamp,
                payload_json,
            )

            record = ControlPlaneRecord(
                record_hash=record_hash,
                previous_hash=current_last_hash,
                timestamp=timestamp,
                payload=payload,
                decision=policy.reason,
                route=route_value,
                sequence_no=sequence_no,
                signature_algo=self._signature_algo(),
                signature_key_id=self._signing_key_id(),
                signature=record_signature,
            )

            self.conn.execute(
                """
                INSERT INTO control_records
                (sequence_no, record_hash, previous_hash, timestamp, payload, decision, route,
                 signature_algo, signature_key_id, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence_no,
                    record_hash,
                    current_last_hash,
                    timestamp,
                    payload_json,
                    policy.reason,
                    route_value,
                    self._signature_algo(),
                    self._signing_key_id(),
                    record_signature,
                )
            )

            event_id = self._deterministic_event_id(sequence_no, adapter.message_id, adapter.payload_hash)
            event_payload = {
                "event_id": event_id,
                "event_seq": sequence_no,
                "timestamp": timestamp,
                "message_id": adapter.message_id,
                "message_key": adapter.message_key,
                "stage": "control.recorded",
                "payload_hash": adapter.payload_hash,
                "decision": policy.reason,
                "state_before": "POLICY_EVALUATED",
                "state_after": "CONTROL_RECORDED",
                "reason_codes": reason_codes,
                "record_hash": record_hash,
                "payload": payload,
            }
            self.conn.execute(
                """
                INSERT INTO control_events
                (event_id, event_seq, timestamp, message_id, message_key, stage, payload_hash,
                 decision, state_before, state_after, reason_codes, record_hash, payload)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event_id,
                    sequence_no,
                    timestamp,
                    adapter.message_id,
                    adapter.message_key,
                    "control.recorded",
                    adapter.payload_hash,
                    policy.reason,
                    "POLICY_EVALUATED",
                    "CONTROL_RECORDED",
                    json.dumps(reason_codes, ensure_ascii=False),
                    record_hash,
                    payload_json,
                )
            )
            self.conn.commit()
            self.last_hash = record_hash
            return record
        except Exception:
            self.conn.rollback()
            raise

    def verify_chain(self, raise_on_failure: bool = False) -> Dict:
        """
        Recomputes every hash in the chain and reports integrity.
        Returns dict with pass/fail and mismatch details.
        """
        cur = self.conn.execute(
            "SELECT id, sequence_no, record_hash, previous_hash, timestamp, payload, signature "
            "FROM control_records ORDER BY id ASC"
        )
        rows = cur.fetchall()

        mismatches = []
        previous_hash = GENESIS_HASH
        previous_timestamp: Optional[str] = None
        expected_sequence = 1
        total = len(rows)

        for row in rows:
            _id, sequence_no, stored_hash, stored_prev, ts, payload_json, stored_signature = row
            try:
                payload = json.loads(payload_json)
            except Exception:
                payload = None

            if not isinstance(payload, dict):
                mismatches.append({
                    "id": _id,
                    "field": "payload_json",
                    "expected": "valid json object",
                    "found": "invalid",
                })
            else:
                trace_violations = validate_decision_trace(payload.get("decision_trace", {}))
                for trace_violation in trace_violations:
                    mismatches.append({
                        "id": _id,
                        "field": "decision_trace",
                        "expected": "valid decision trace",
                        "found": trace_violation,
                    })

            if sequence_no != expected_sequence:
                mismatches.append({
                    "id": _id,
                    "field": "sequence_no",
                    "expected": expected_sequence,
                    "found": sequence_no,
                })

            if stored_prev != previous_hash:
                mismatches.append({
                    "id": _id,
                    "field": "previous_hash",
                    "expected": previous_hash,
                    "found": stored_prev
                })

            # CF-01: Monotonic timestamp check — records must not be backdated.
            if previous_timestamp is not None and ts < previous_timestamp:
                mismatches.append({
                    "id": _id,
                    "field": "timestamp_order",
                    "expected": f">= {previous_timestamp}",
                    "found": ts
                })

            recompute = self._compute_record_hash(previous_hash, ts, payload_json)

            if recompute != stored_hash:
                mismatches.append({
                    "id": _id,
                    "field": "record_hash",
                    "expected": recompute,
                    "found": stored_hash
                })

            expected_signature = self._compute_record_signature(
                expected_sequence,
                stored_hash,
                stored_prev,
                ts,
                payload_json,
            )
            if stored_signature != expected_signature:
                mismatches.append({
                    "id": _id,
                    "field": "signature",
                    "expected": expected_signature,
                    "found": stored_signature,
                })

            previous_hash = stored_hash
            previous_timestamp = ts
            expected_sequence += 1

        if raise_on_failure and mismatches:
            raise ChainIntegrityError(
                f"Control-chain verification failed with {len(mismatches)} mismatch(es)."
            )

        return {
            "total_records": total,
            "mismatches": mismatches,
            "integrity_pass": len(mismatches) == 0,
            "tail_hash": self.get_tail_hash(),
            "determinism_guarantee": {
                "sort_key": "sequence_no ASC",
                "canonical_json": True,
            },
        }

    def get_all_records(self) -> List[Dict]:
        """Return every committed record, in sequence order.

        This is the integrity accessor, so it deliberately does not filter.
        ``export_anchor`` and ``verify_anchor`` compute the Merkle root and
        record count from this result: if it dropped any record, the anchor
        would not cover the chain and the dropped record could be altered or
        deleted without detection.

        An earlier revision silently excluded records whose payload had
        ``policy_allowed is False`` in order to keep rejected outcomes out of a
        presentation view. That filter is gone (audit finding F-04). It is no
        longer reachable anyway - ``REJECTED_POLICY`` short-circuits control
        execution per STATE_MACHINE_SPEC.md and writes no control record - but
        leaving it here invited the next reader to re-derive the old behaviour.
        Filtering for display belongs to the caller, never to the function that
        defines what the chain contains.
        """
        cur = self.conn.execute(
            "SELECT sequence_no, record_hash, previous_hash, timestamp, payload, decision, route, signature "
            "FROM control_records ORDER BY id ASC"
        )
        return [
            {
                "sequence_no": row[0],
                "record_hash": row[1],
                "previous_hash": row[2],
                "timestamp": row[3],
                "payload": json.loads(row[4]),
                "decision": row[5],
                "route": row[6],
                "signature": row[7],
            }
            for row in cur.fetchall()
        ]

    def get_event_stream(self) -> List[Dict[str, Any]]:
        cur = self.conn.execute(
            """
            SELECT event_id, event_seq, timestamp, message_id, message_key, stage, payload_hash,
                   decision, state_before, state_after, reason_codes, record_hash, payload
            FROM control_events
            ORDER BY event_seq ASC, timestamp ASC
            """
        )
        rows = cur.fetchall()
        return [
            {
                "event_id": row[0],
                "event_seq": row[1],
                "timestamp": row[2],
                "message_id": row[3],
                "message_key": row[4],
                "stage": row[5],
                "payload_hash": row[6],
                "decision": row[7],
                "state_before": row[8],
                "state_after": row[9],
                "reason_codes": json.loads(row[10]),
                "record_hash": row[11],
                "payload": json.loads(row[12]),
            }
            for row in rows
        ]

    def execute_anchor(self, anchor_payload: Dict) -> ControlPlaneRecord:
        payload_json = json.dumps(anchor_payload, sort_keys=True, ensure_ascii=False)
        try:
            self.conn.execute("BEGIN IMMEDIATE")
            current_last_hash = self._get_last_hash()
            sequence_no = self._next_sequence()
            timestamp = _utc_now_iso()
            record_hash = self._compute_record_hash(current_last_hash, timestamp, payload_json)
            record_signature = self._compute_record_signature(
                sequence_no,
                record_hash,
                current_last_hash,
                timestamp,
                payload_json,
            )
            record = ControlPlaneRecord(
                record_hash=record_hash,
                previous_hash=current_last_hash,
                timestamp=timestamp,
                payload=anchor_payload,
                decision="anchor",
                route="anchor",
                sequence_no=sequence_no,
                signature_algo=self._signature_algo(),
                signature_key_id=self._signing_key_id(),
                signature=record_signature,
            )
            self.conn.execute(
                """
                INSERT INTO control_records
                (sequence_no, record_hash, previous_hash, timestamp, payload, decision, route,
                 signature_algo, signature_key_id, signature)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sequence_no,
                    record_hash,
                    current_last_hash,
                    timestamp,
                    payload_json,
                    "anchor",
                    "anchor",
                    self._signature_algo(),
                    self._signing_key_id(),
                    record_signature,
                )
            )
            self.conn.commit()
            self.last_hash = record_hash
            return record
        except Exception:
            self.conn.rollback()
            raise

    def export_anchor(self, anchor_path: str) -> str:
        records = self.get_all_records()
        anchor_payload = build_anchor_payload(
            dossier_id=self.db_path,
            tail_hash=self.get_tail_hash(),
            record_count=len(records),
            merkle_root_hash=merkle_root([record["record_hash"] for record in records]),
        )
        anchor = {
            **anchor_payload,
            "exported_at": _utc_now_iso(),
        }
        anchor_json = json.dumps(anchor, sort_keys=True, ensure_ascii=False)
        anchor["anchor_hash"] = hashlib.sha256(anchor_json.encode()).hexdigest()
        secret = os.getenv("GDC_ANCHOR_SECRET", "")
        if secret:
            anchor["anchor_signature"] = hashlib.sha256((anchor["anchor_hash"] + ":" + secret).encode()).hexdigest()
        with open(anchor_path, "w", encoding="utf-8") as f:
            json.dump(anchor, f, indent=2, ensure_ascii=False)
        return anchor_path

    def verify_anchor(self, anchor_path: str) -> Dict:
        with open(anchor_path, "r", encoding="utf-8") as f:
            anchor = json.load(f)

        expected_tail = self.get_tail_hash()
        records = self.get_all_records()
        current_payload = {
            "namespace": anchor.get("namespace", "dossier_pipeline.anchor"),
            "dossier_id": anchor.get("dossier_id", self.db_path),
            "tail_hash": expected_tail,
            "record_count": len(records),
            "merkle_root": merkle_root([record["record_hash"] for record in records]),
            "exported_at": anchor.get("exported_at"),
        }
        current_json = json.dumps(current_payload, sort_keys=True, ensure_ascii=False)
        current_hash = hashlib.sha256(current_json.encode()).hexdigest()

        signature_valid = True
        secret = os.getenv("GDC_ANCHOR_SECRET", "")
        if secret and anchor.get("anchor_signature"):
            signature_valid = anchor["anchor_signature"] == hashlib.sha256((anchor["anchor_hash"] + ":" + secret).encode()).hexdigest()

        return {
            "anchor_tail_hash": anchor.get("tail_hash"),
            "current_tail_hash": expected_tail,
            "anchor_hash": anchor.get("anchor_hash"),
            "current_hash": current_hash,
            "tail_match": anchor.get("tail_hash") == expected_tail,
            "hash_match": anchor.get("anchor_hash") == current_hash,
            "signature_valid": signature_valid,
            "integrity_pass": anchor.get("tail_hash") == expected_tail and signature_valid,
        }

    def close(self):
        """Release the underlying SQLite connection."""
        self.conn.close()
