"""
Dossier DOSSIER-PIPELINE Outbound Send Tracker

Tracks litigation hold notices, demand letters, and formal replies.
Integrates into the same hash-linked audit chain as inbound evidence.

Quebec Legal Context:
  • Bailiff (huissier) service = strongest proof of delivery [^9^]
  • Registered mail with AR (accusé de réception) = valid per C.C.P. art. 140 [^14^]
  • Service record (constat de service) = authentic act, presumed accurate [^9^]
"""

import datetime
import hashlib
import json
import sqlite3
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

from .contracts import (ActorType, AdapterResult, ClassificationLabel,
                        ClassificationResult, ControlPlaneRecord,
                        PolicyDecision, ProvenanceResult)
from .control import ControlPlane


class SendMethod(str, Enum):
    BAILIFF = "bailiff"                           # Huissier strongest proof
    REGISTERED_MAIL = "registered_mail"           # Lettre recommandée avec AR
    CERTIFIED_MAIL = "certified_mail"             # Lettre certifiée
    EMAIL_READ_RECEIPT = "email_read_receipt"     # Email with read receipt (weak)
    IN_PERSON = "in_person"                       # Remis en main propre
    COURIER = "courier"                           # Service de messagerie


class DocumentType(str, Enum):
    LITIGATION_HOLD = "litigation_hold"           # Avis de conservation
    DEMAND_LETTER = "demand_letter"               # Mise en demeure
    GRIEVANCE = "grievance"                       # Plainte/grief
    FORMAL_REPLY = "formal_reply"                 # Réponse formelle
    MEDICAL_REQUEST = "medical_request"           # Demande de dossier médical
    INSURER_NOTICE = "insurer_notice"             # Avis à l'assureur
    UNION_NOTICE = "union_notice"                 # Avis au syndicat


@dataclass
class OutboundSend:
    send_id: str                                    # Unique ID
    actor: str                                      # employer/insurer/union/medical/psychologist
    document_type: DocumentType
    document_path: str                              # Path to sent file
    document_hash: str                              # SHA-256 of file
    send_method: SendMethod
    send_date: str                                  # ISO timestamp
    sender_address: str                             # Your address
    recipient_address: str                        # Their address
    tracking_number: Optional[str] = None           # Tracking / bailiff file #
    delivery_proof_path: Optional[str] = None      # Path to AR receipt / constat
    delivery_date: Optional[str] = None             # When confirmed delivered
    response_deadline: Optional[str] = None         # e.g., 30 days from send
    response_received: bool = False
    response_date: Optional[str] = None
    notes: str = ""
    chain_record_hash: Optional[str] = None        # Linked to control plane


class OutboundRegistry:
    """
    SQLite-backed registry of all outbound sends.
    Every send is hashed and linked into the control plane chain.
    """

    def __init__(self, db_path: str, control_plane: ControlPlane):
        self.db_path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(db_path, check_same_thread=False, timeout=30)
        self.control = control_plane
        self._init_db()

    def _init_db(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS outbound_registry (
                send_id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                document_type TEXT NOT NULL,
                document_path TEXT,
                document_hash TEXT NOT NULL,
                send_method TEXT NOT NULL,
                send_date TEXT NOT NULL,
                sender_address TEXT NOT NULL,
                recipient_address TEXT NOT NULL,
                tracking_number TEXT,
                delivery_proof_path TEXT,
                delivery_date TEXT,
                response_deadline TEXT,
                response_received INTEGER DEFAULT 0,
                response_date TEXT,
                notes TEXT,
                chain_record_hash TEXT,
                outbox_status TEXT DEFAULT 'COMMITTED',
                last_error TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS outbound_outbox (
                send_id TEXT PRIMARY KEY,
                actor TEXT NOT NULL,
                document_type TEXT NOT NULL,
                document_hash TEXT NOT NULL,
                send_method TEXT NOT NULL,
                send_date TEXT NOT NULL,
                sender_address TEXT NOT NULL,
                recipient_address TEXT NOT NULL,
                tracking_number TEXT,
                response_deadline TEXT,
                notes TEXT,
                payload_json TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'PENDING',
                chain_record_hash TEXT,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        self.conn.commit()

    def register_send(
        self,
        actor: str,
        document_type: DocumentType,
        document_path: str,
        send_method: SendMethod,
        sender_address: str,
        recipient_address: str,
        tracking_number: Optional[str] = None,
        response_deadline_days: int = 30,
        notes: str = ""
    ) -> OutboundSend:
        """
        Register a new outbound send as a durable request and emit a canonical
        control-plane record for the request event.
        """
        path = Path(document_path)
        if not path.exists():
            raise FileNotFoundError(f"Document not found: {document_path}")

        doc_bytes = path.read_bytes()
        document_hash = hashlib.sha256(doc_bytes).hexdigest()

        send_id = hashlib.sha256(
            f"{actor}:{document_type.value}:{datetime.datetime.now().isoformat()}:{uuid.uuid4()}".encode()
        ).hexdigest()[:32]

        send_date = datetime.datetime.now().isoformat()
        deadline = (
            datetime.datetime.now() + datetime.timedelta(days=response_deadline_days)
        ).isoformat()

        normalized_actor = actor.strip().lower()
        chain_payload = {
            "direction": "outbound",
            "send_id": send_id,
            "actor": normalized_actor,
            "document_type": document_type.value,
            "document_hash": document_hash,
            "send_method": send_method.value,
            "send_date": send_date,
            "sender_address": sender_address,
            "recipient_address": recipient_address,
            "tracking_number": tracking_number,
            "response_deadline": deadline,
        }

        self.conn.execute("""
            INSERT INTO outbound_outbox
            (send_id, actor, document_type, document_hash, send_method, send_date,
             sender_address, recipient_address, tracking_number, response_deadline,
             notes, payload_json, status, chain_record_hash, attempts, last_error,
             created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING', NULL, 0, NULL, ?, ?)
        """, (
            send_id, normalized_actor, document_type.value, document_hash, send_method.value, send_date,
            sender_address, recipient_address, tracking_number, deadline,
            notes, json.dumps(chain_payload, sort_keys=True, ensure_ascii=False),
            send_date, send_date
        ))
        self.conn.execute("""
            INSERT INTO outbound_registry
            (send_id, actor, document_type, document_path, document_hash, send_method,
             send_date, sender_address, recipient_address, tracking_number,
             response_deadline, response_received, response_date, notes, chain_record_hash,
             outbox_status, last_error)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, NULL, ?, NULL, 'PENDING', NULL)
        """, (
            send_id, normalized_actor, document_type.value, str(path), document_hash, send_method.value,
            send_date, sender_address, recipient_address, tracking_number,
            deadline, notes
        ))
        self.conn.commit()

        synthetic_classification = ClassificationResult(
            labels=[ClassificationLabel.LEGAL_SIGNIFICANT],
            confidence=1.0,
            actor=ActorType.UNKNOWN if normalized_actor not in [a.value for a in ActorType] else ActorType(normalized_actor),
            reasoning=[f"Outbound request registered for {normalized_actor}"],
            rule_hits=[f"outbound_request:{normalized_actor}:{document_type.value}"]
        )
        synthetic_provenance = ProvenanceResult(
            complete=True,
            missing_fields=[],
            human_review_required=False,
            source_type=normalized_actor
        )
        synthetic_adapter = AdapterResult(
            classification=synthetic_classification,
            provenance=synthetic_provenance,
            trace=[f"Outbound request registered: {send_id}"],
            confidence=1.0,
            raw_sha256=document_hash,
            payload_hash=hashlib.sha256(
                json.dumps(chain_payload, sort_keys=True).encode()
            ).hexdigest(),
            message_id=send_id,
            message_key=send_id[:32],
            original_message_id=send_id,
        )
        synthetic_policy = PolicyDecision(
            allowed=True,
            reason=f"Outbound {document_type.value} request logged",
            quarantine=False
        )

        record = self.control.execute(synthetic_adapter, synthetic_policy)
        now = datetime.datetime.now().isoformat()
        self.conn.execute("""
            UPDATE outbound_outbox
            SET status = 'COMMITTED',
                chain_record_hash = ?,
                updated_at = ?,
                last_error = NULL
            WHERE send_id = ?
        """, (record.record_hash, now, send_id))
        self.conn.execute("""
            UPDATE outbound_registry
            SET chain_record_hash = ?,
                outbox_status = 'COMMITTED',
                last_error = NULL
            WHERE send_id = ?
        """, (record.record_hash, send_id))
        self.conn.commit()

        return self._load_send(send_id)

    def confirm_delivery(
        self,
        send_id: str,
        delivery_proof_path: str,
        delivery_date: Optional[str] = None
    ):
        """Update send with delivery confirmation (AR receipt, bailiff constat)."""
        cur = self.conn.execute(
            "SELECT 1 FROM outbound_registry WHERE send_id = ?", (send_id,)
        )
        if cur.fetchone() is None:
            raise ValueError(f"Unknown send_id: {send_id}")

        if delivery_date is None:
            delivery_date = datetime.datetime.now().isoformat()

        self.conn.execute("""
            UPDATE outbound_registry
            SET delivery_proof_path = ?, delivery_date = ?
            WHERE send_id = ?
        """, (delivery_proof_path, delivery_date, send_id))
        self.conn.commit()

    def confirm_response(self, send_id: str, response_date: Optional[str] = None):
        """Mark that a response was received."""
        cur = self.conn.execute(
            "SELECT 1 FROM outbound_registry WHERE send_id = ?", (send_id,)
        )
        if cur.fetchone() is None:
            raise ValueError(f"Unknown send_id: {send_id}")

        if response_date is None:
            response_date = datetime.datetime.now().isoformat()

        self.conn.execute("""
            UPDATE outbound_registry
            SET response_received = 1, response_date = ?
            WHERE send_id = ?
        """, (response_date, send_id))
        self.conn.commit()

    def reconcile_outbox(self) -> List[str]:
        fixed: List[str] = []
        cur = self.conn.execute("""
            SELECT send_id FROM outbound_outbox
            WHERE status = 'PENDING' OR status = 'FAILED_RETRYABLE'
            ORDER BY created_at ASC
        """)
        for (send_id,) in cur.fetchall():
            try:
                self._flush_outbox(send_id)
                fixed.append(send_id)
            except Exception:
                continue
        return fixed

    def get_pending(self) -> List[Dict]:
        """Get all sends awaiting delivery confirmation or response."""
        cur = self.conn.execute("""
            SELECT * FROM outbound_registry
            WHERE delivery_date IS NULL OR response_received = 0
            ORDER BY send_date ASC
        """)
        cols = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            d["response_received"] = bool(d["response_received"])
            rows.append(d)
        return rows

    def get_all(self) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM outbound_registry ORDER BY send_date ASC")
        cols = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            d["response_received"] = bool(d["response_received"])
            rows.append(d)
        return rows

    def export_manifest(self, path: str) -> str:
        """Export full outbound manifest as JSON."""
        data = {
            "registry": self.get_all(),
            "outbox": self.get_outbox(),
            "export_time": datetime.datetime.now().isoformat(),
            "tail_hash": self.control.get_tail_hash()
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)
        return path

    def get_outbox(self) -> List[Dict]:
        cur = self.conn.execute("SELECT * FROM outbound_outbox ORDER BY created_at ASC")
        cols = [desc[0] for desc in cur.description]
        rows = []
        for row in cur.fetchall():
            d = dict(zip(cols, row))
            rows.append(d)
        return rows

    def _load_send(self, send_id: str) -> OutboundSend:
        cur = self.conn.execute("SELECT * FROM outbound_registry WHERE send_id = ?", (send_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Unknown send_id: {send_id}")
        cols = [desc[0] for desc in cur.description]
        d = dict(zip(cols, row))
        return OutboundSend(
            send_id=d["send_id"],
            actor=d["actor"],
            document_type=DocumentType(d["document_type"]),
            document_path=d["document_path"],
            document_hash=d["document_hash"],
            send_method=SendMethod(d["send_method"]),
            send_date=d["send_date"],
            sender_address=d["sender_address"],
            recipient_address=d["recipient_address"],
            tracking_number=d["tracking_number"],
            delivery_proof_path=d["delivery_proof_path"],
            delivery_date=d["delivery_date"],
            response_deadline=d["response_deadline"],
            response_received=bool(d["response_received"]),
            response_date=d["response_date"],
            notes=d["notes"] or "",
            chain_record_hash=d["chain_record_hash"]
        )

    def _flush_outbox(self, send_id: str) -> str:
        cur = self.conn.execute("SELECT * FROM outbound_outbox WHERE send_id = ?", (send_id,))
        row = cur.fetchone()
        if row is None:
            raise ValueError(f"Unknown send_id: {send_id}")
        cols = [desc[0] for desc in cur.description]
        outbox = dict(zip(cols, row))
        if outbox["status"] == "COMMITTED" and outbox.get("chain_record_hash"):
            return outbox["chain_record_hash"]

        actor_normalized = outbox["actor"]
        actor_enum = (
            ActorType(actor_normalized)
            if actor_normalized in [a.value for a in ActorType]
            else ActorType.UNKNOWN
        )
        chain_payload = {
            "direction": "outbound",
            "send_id": outbox["send_id"],
            "actor": actor_normalized,
            "document_type": outbox["document_type"],
            "document_hash": outbox["document_hash"],
            "send_method": outbox["send_method"],
            "send_date": outbox["send_date"],
            "sender_address": outbox["sender_address"],
            "recipient_address": outbox["recipient_address"],
            "tracking_number": outbox["tracking_number"],
            "response_deadline": outbox["response_deadline"],
        }

        synthetic_classification = ClassificationResult(
            labels=[ClassificationLabel.LEGAL_SIGNIFICANT],
            confidence=1.0,
            actor=actor_enum,
            reasoning=[f"Outbound {outbox['document_type']} to {actor_normalized}"],
            rule_hits=[f"outbound:{actor_normalized}:{outbox['document_type']}"]
        )
        synthetic_provenance = ProvenanceResult(
            complete=True,
            missing_fields=[],
            human_review_required=False,
            source_type=actor_normalized
        )
        synthetic_adapter = AdapterResult(
            classification=synthetic_classification,
            provenance=synthetic_provenance,
            trace=[f"Outbound send registered: {outbox['send_id']}"],
            confidence=1.0,
            raw_sha256=outbox["document_hash"],
            payload_hash=hashlib.sha256(
                json.dumps(chain_payload, sort_keys=True).encode()
            ).hexdigest(),
            message_id=outbox["send_id"],
            message_key=outbox["send_id"][:32],
            original_message_id=outbox["send_id"],
        )
        synthetic_policy = PolicyDecision(
            allowed=True,
            reason=f"Outbound {outbox['document_type']} to {actor_normalized} logged for audit",
            quarantine=False
        )

        self.conn.execute("""
            UPDATE outbound_outbox
            SET attempts = attempts + 1,
                status = 'PENDING',
                last_error = NULL,
                updated_at = ?
            WHERE send_id = ?
        """, (datetime.datetime.now().isoformat(), send_id))
        self.conn.commit()

        try:
            record = self.control.execute(synthetic_adapter, synthetic_policy)
            now = datetime.datetime.now().isoformat()
            self.conn.execute("""
                UPDATE outbound_outbox
                SET status = 'COMMITTED',
                    chain_record_hash = ?,
                    updated_at = ?,
                    last_error = NULL
                WHERE send_id = ?
            """, (record.record_hash, now, send_id))
            self.conn.execute("""
                UPDATE outbound_registry
                SET chain_record_hash = ?,
                    outbox_status = 'COMMITTED',
                    last_error = NULL
                WHERE send_id = ?
            """, (record.record_hash, send_id))
            self.conn.commit()
            return record.record_hash
        except Exception as exc:
            now = datetime.datetime.now().isoformat()
            self.conn.execute("""
                UPDATE outbound_outbox
                SET status = 'FAILED_RETRYABLE',
                    last_error = ?,
                    updated_at = ?
                WHERE send_id = ?
            """, (str(exc), now, send_id))
            self.conn.execute("""
                UPDATE outbound_registry
                SET outbox_status = 'FAILED_RETRYABLE',
                    last_error = ?
                WHERE send_id = ?
            """, (str(exc), send_id))
            self.conn.commit()
            raise

    def close(self):
        """Release the underlying SQLite connection."""
        self.conn.close()
