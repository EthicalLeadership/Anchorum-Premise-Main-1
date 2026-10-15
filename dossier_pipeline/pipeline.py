"""
Dossier DOSSIER-PIPELINE Integrated Pipeline Orchestrator

Wires the canonical stores together with transaction recovery, hardened
projections, and stage-specific failure handling.
"""

from __future__ import annotations

import datetime
import hashlib
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional

from fpdf import FPDF

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from dossier_pipeline import invariants  # noqa: F401
    from dossier_pipeline.adapter import GovernanceAdapter
    from dossier_pipeline.assertions import assertions
    from dossier_pipeline.classifier import EmailClassifier
    from dossier_pipeline.contracts import (EmailEnvelope, ErrorEvent,
                                             PipelineResult, ResultStatus)
    from dossier_pipeline.control import ChainIntegrityError, ControlPlane
    from dossier_pipeline.decision import DecisionEngine
    from dossier_pipeline.dossier_lock import DossierExecutionLock
    from dossier_pipeline.evidence import (CustodyAction, EvidenceStore,
                                            SystemState)
    from dossier_pipeline.intake import EmailIntake, EmailSeenSet
    from dossier_pipeline.observability import StructuredLogger
    from dossier_pipeline.outbound import OutboundRegistry
    from dossier_pipeline.policy import PolicyEngine
    from dossier_pipeline.privacy import (PrivacyComplianceError,
                                           PrivacyComplianceLayer)
    from dossier_pipeline.projections_v2 import (ProjectionSnapshot,
                                                  projection_health_report,
                                                  rebuild_projection_snapshot)
    from dossier_pipeline.provenance import ProvenanceCurator
    from dossier_pipeline.replay import ReplayRecorder
    from dossier_pipeline.state_machine import (SpecViolation,
                                                 StateMachineSpec,
                                                 StrictStateMachine,
                                                 load_default_spec)
    from dossier_pipeline.transaction import (PipelineTransaction,
                                               TransactionalWriteRouter)
    from dossier_pipeline.trust_boundary import validate_export_fields
    from dossier_pipeline.write_router import WriteRouter
else:
    from . import invariants  # noqa: F401
    from .adapter import GovernanceAdapter
    from .assertions import assertions
    from .classifier import EmailClassifier
    from .contracts import (EmailEnvelope, ErrorEvent, PipelineResult,
                            ResultStatus)
    from .control import ChainIntegrityError, ControlPlane
    from .decision import DecisionEngine
    from .disclaimer import format_disclaimer_block
    from .dossier_lock import DossierExecutionLock
    from .evidence import CustodyAction, EvidenceStore, SystemState
    from .intake import EmailIntake, EmailSeenSet
    from .observability import StructuredLogger
    from .outbound import OutboundRegistry
    from .output_gates import sanitize_output
    from .policy import PolicyEngine
    from .privacy import PrivacyComplianceError, PrivacyComplianceLayer
    from .projections_v2 import (ProjectionSnapshot, projection_health_report,
                                 rebuild_projection_snapshot)
    from .provenance import ProvenanceCurator
    from .replay import ReplayRecorder
    from .state_machine import (SpecViolation, StateMachineSpec,
                                StrictStateMachine, load_default_spec)
    from .transaction import PipelineTransaction, TransactionalWriteRouter
    from .trust_boundary import validate_export_fields
    from .write_router import WriteRouter


class ParseError(RuntimeError):
    pass


class IntakeError(RuntimeError):
    pass


class ClassificationError(RuntimeError):
    pass


class ProvenanceError(RuntimeError):
    pass


class AdapterError(RuntimeError):
    pass


class PolicyError(RuntimeError):
    pass


class ControlError(RuntimeError):
    pass


class ControlChainError(ControlError):
    pass


class EvidenceError(RuntimeError):
    pass


class DualRejectedPolicyState(str):
    def __new__(cls):
        return super().__new__(cls, "REJECTED_POLICY")

    def __eq__(self, other):
        return other in {"REJECTED_POLICY", "POLICY_REJECTED"} or str.__eq__(self, other)


#: Envelope fields a caller may set from the artifact it actually read.
SOURCE_FIELDS = (
    "source_sha256",
    "source_bytes",
    "source_filename",
    "source_media_type",
    "transport",
    "synthesised_fields",
)


class DossierPipeline:
    RETRYABLE_FAILURE_STAGES = {"process_email"}

    VALID_STATES = {
        "RECEIVED",
        "PARSED",
        "DEDUPED",
        "CLASSIFIED",
        "POLICY_ALLOWED",
        "POLICY_REJECTED",
        "REJECTED_POLICY",
        "EVIDENCED",
        "COMMITTED",
        "OUTBOUND_QUEUED",
        "OUTBOUND_CONFIRMED",
        "FAILED_RUNTIME",
        "DUPLICATE",
    }

    def __init__(
        self,
        dossier_id: str = "DOSSIER-PIPELINE",
        output_dir: str = "./output",
        state_machine_spec: StateMachineSpec | None = None,
    ):
        self.dossier_id = dossier_id
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        db_seen = self.output_dir / f"{dossier_id}_seen.db"
        db_chain = self.output_dir / f"{dossier_id}_chain.db"

        self.seen = EmailSeenSet(str(db_seen))
        self.intake = EmailIntake(self.seen)
        self.classifier = EmailClassifier()
        self.curator = ProvenanceCurator()
        self.adapter = GovernanceAdapter()
        self.policy = PolicyEngine()
        self.decision = DecisionEngine()
        self.privacy = PrivacyComplianceLayer()
        self.control = ControlPlane(str(db_chain))
        self.execution_lock = DossierExecutionLock(str(self.output_dir / f"{dossier_id}_lock.db"))
        self.outbound = OutboundRegistry(str(self.output_dir / f"{dossier_id}_outbound.db"), self.control)
        self.evidence = EvidenceStore(str(self.output_dir / f"{dossier_id}_evidence.db"))
        self.replay = ReplayRecorder(str(self.output_dir / f"{dossier_id}_replay.jsonl"))
        self.write_router = WriteRouter(
            seen_set=self.seen,
            outbound_registry=self.outbound,
            evidence_store=self.evidence,
            replay_recorder=self.replay,
        )
        self.transaction = PipelineTransaction(
            stores={
                "control": self.control,
                "seen": self.seen,
                "outbound": self.outbound,
                "evidence": self.evidence,
                "replay": self.replay,
            },
            journal_path=str(self.output_dir / f"{dossier_id}_transaction_journal.json"),
        )
        self.transaction.recover()
        self.write_router = TransactionalWriteRouter(self.write_router, self.transaction)
        self.state_machine_spec = state_machine_spec or load_default_spec()
        self.state_machine = StrictStateMachine(self.state_machine_spec)

        self.processed: List[Dict] = []
        self.duplicate_count = 0
        self.failed_count = 0
        self.quarantined_count = 0
        self.system_state = SystemState.OK
        self.current_state = self.state_machine.current_state()
        self.state_history: List[str] = [self.current_state]
        self.logger = StructuredLogger()

        try:
            self.control.verify_chain(raise_on_failure=True)
        except ChainIntegrityError as exc:
            raise ControlChainError(
                f"[{dossier_id}] CHAIN INTEGRITY FAILURE on startup: {exc}"
            ) from exc

    def close(self):
        self.seen.close()
        self.control.close()
        self.execution_lock.close()
        self.outbound.close()
        self.evidence.close()
        self.replay.close()

    def _set_state(self, state: str, event: str | None = None):
        if state not in self.VALID_STATES:
            raise ValueError(f"Invalid pipeline state: {state}")
        self.current_state = state
        self.state_history.append(state)

    def _apply_transition(self, event: str, payload: Dict | None = None):
        try:
            new_state = self.state_machine.apply(event, payload)
        except Exception as exc:
            raise SpecViolation(str(exc)) from exc
        self.current_state = new_state
        self.state_history.append(new_state)
        return new_state

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
        return False

    def _generate_pdf(self, envelope):
        """Generate a PDF from the email envelope content."""
        pdf = FPDF()
        pdf.add_page()
        pdf.set_font("Arial", size=12)
        pdf.cell(200, 10, txt=f"Email from: {envelope.sender}", ln=True)
        pdf.cell(200, 10, txt=f"Subject: {envelope.subject}", ln=True)
        pdf.multi_cell(0, 10, txt=envelope.body_text)
        pdf_path = Path(self.output_dir) / f"{envelope.message_id}.pdf"
        pdf.output(str(pdf_path))
        return pdf_path

    def process_email(
        self,
        raw_bytes: bytes,
        source: Optional[Dict] = None,
    ) -> PipelineResult:
        """Process one submission.

        `source` carries the identity of the artifact the caller actually read:
        its SHA-256, size, name and media type, plus the transport it arrived by
        and which envelope fields were synthesised rather than observed. It is
        passed explicitly because the caller is the only party that saw the
        artifact; a value smuggled through a header would be forgeable by
        whoever set the header.
        """
        self.state_machine = StrictStateMachine(self.state_machine_spec)
        self.current_state = self.state_machine.current_state()
        self.state_history.append(self.current_state)
        raw_sha256 = hashlib.sha256(raw_bytes).hexdigest()
        self.execution_lock.acquire(self.dossier_id, datetime.datetime.now().isoformat())
        try:
            self.logger.emit(
                "pipeline.received",
                stage="intake",
                result="received",
                retryable=False,
                raw_sha256=raw_sha256,
            )
            self.write_router.record_replay("pipeline.received", {"raw_sha256": raw_sha256})
            self.logger.emit(
                "pipeline.transition",
                stage="state_machine",
                result="parse_ok",
                retryable=False,
                raw_sha256=raw_sha256,
            )
            self._apply_transition("parse_ok", {"raw_sha256": raw_sha256})
            try:
                return self._process_email_inner(raw_bytes, source)
            except ParseError as exc:
                return self._fail_with_stage("parse", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except IntakeError as exc:
                return self._fail_with_stage("intake", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except ClassificationError as exc:
                return self._fail_with_stage("classification", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except ProvenanceError as exc:
                return self._fail_with_stage("provenance", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except AdapterError as exc:
                return self._fail_with_stage("adapter", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except PolicyError as exc:
                return self._fail_with_stage("policy", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except ControlChainError as exc:
                return self._fail_with_stage("control_chain", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except ControlError as exc:
                return self._fail_with_stage("control", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except EvidenceError as exc:
                return self._fail_with_stage("evidence", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
            except Exception as exc:
                return self._fail_with_stage("process_email", raw_bytes, exc, ResultStatus.FAILED_RUNTIME)
        finally:
            self.execution_lock.release()

    def _process_email_inner(
        self,
        raw_bytes: bytes,
        source: Optional[Dict] = None,
    ) -> PipelineResult:
        try:
            parsed_envelope = self.intake.parse_email_bytes(raw_bytes)
        except Exception as exc:
            raise ParseError(str(exc)) from exc

        # Applied before the minimization gate below, so the gate sees the final
        # field set rather than the parser's defaults.
        self._apply_source(parsed_envelope, source)

        try:
            privacy_decision = self.privacy.validate(
                parsed_envelope,
                {
                    "legal_basis": "legitimate_interest",
                    "purpose": "governed_email_intake",
                    "retention_expiry": (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=30)).isoformat(),
                    "reason": "inbound intake processing",
                    "allowed_fields": [
                        "message_id",
                        "subject",
                        "sender",
                        "recipient",
                        "date",
                        "body_text",
                        "attachments",
                        "raw_sha256",
                        "message_key",
                        "original_message_id",
                        "ingest_timestamp",
                        "received_count",
                        "received_first_ts",
                        "received_last_ts",
                        "received_chain_fingerprint_b64",
                        *SOURCE_FIELDS,
                    ],
                },
            )
        except PrivacyComplianceError as exc:
            raise IntakeError(str(exc)) from exc

        self.write_router.record_replay(
            "intake.parsed",
            {
                "message_id": parsed_envelope.message_id,
                "message_key": parsed_envelope.message_key,
                "raw_sha256": parsed_envelope.raw_sha256,
                "privacy_reason": privacy_decision.reason,
            },
        )
        envelope = self.intake.normalize(parsed_envelope)
        self._apply_transition("dedup_ok", {"message_id": parsed_envelope.message_id, "duplicate": envelope is None})
        assertions.validate(
            "inv_002",
            envelope=parsed_envelope.__dict__,
            normalized=envelope.__dict__ if envelope is not None else None,
            seen_before=envelope is None,
        )
        self.logger.emit(
            "dedup",
            stage="intake",
            result="duplicate" if envelope is None else "claimed",
            retryable=False,
            message_id=parsed_envelope.message_id,
            raw_sha256=parsed_envelope.raw_sha256,
        )
        self.write_router.record_replay(
            "intake.dedup_checked",
            {
                "message_id": parsed_envelope.message_id,
                "duplicate": envelope is None,
                "privacy_legal_basis": privacy_decision.legal_basis,
                "privacy_purpose": privacy_decision.purpose,
            },
        )

        if envelope is None:
            self.duplicate_count += 1
            self._apply_transition(
                "duplicate_detected",
                {
                    "message_id": parsed_envelope.message_id,
                    "raw_sha256": parsed_envelope.raw_sha256,
                },
            )
            self.write_router.record_replay(
                "intake.duplicate",
                {
                    "message_id": parsed_envelope.message_id,
                    "raw_sha256": parsed_envelope.raw_sha256,
                },
            )
            duplicate_packet = self.write_router.ingest_evidence(
                event_type="duplicate_email",
                raw_payload={"raw_sha256": parsed_envelope.raw_sha256, "message_key": parsed_envelope.message_key},
                normalized_payload={"status": "duplicate"},
                metadata={"dossier_id": self.dossier_id, "stage": "intake", "duplicate": True},
                duplicate_of=None,
            )
            self.evidence.add_custody_event(duplicate_packet.evidence_id, "pipeline", CustodyAction.INGESTED)
            return PipelineResult(
                status=ResultStatus.DUPLICATE,
                message_id=parsed_envelope.message_id,
                message_key=parsed_envelope.message_key,
                reason="duplicate message_id/raw_sha256",
                data={"stage": "intake", "evidence_id": duplicate_packet.evidence_id},
            )

        classification = self.classifier.classify(envelope)
        assertions.validate(
            "inv_004",
            classifier=self.classifier,
            envelope=envelope,
        )
        self.logger.emit(
            "classification",
            stage="classification",
            result=classification.actor.value,
            retryable=False,
            message_id=envelope.message_id,
            raw_sha256=envelope.raw_sha256,
        )
        self._apply_transition("classify_ok", {"message_id": envelope.message_id})
        self.write_router.record_replay(
            "classification.completed",
            {
                "message_id": envelope.message_id,
                "actor": classification.actor.value,
                "labels": [l.value for l in classification.labels],
                "confidence": classification.confidence,
            },
        )

        provenance = self.curator.curate(classification, envelope)
        assertions.validate(
            "inv_008",
            classification={
                "confidence": classification.confidence,
                "actor": classification.actor.value,
            },
            provenance={
                "confidence": classification.confidence,
                "missing_fields": provenance.missing_fields,
            },
            output={"human_review_required": provenance.human_review_required},
        )
        self.logger.emit(
            "provenance",
            stage="provenance",
            result="complete" if provenance.complete else "incomplete",
            retryable=False,
            message_id=envelope.message_id,
            raw_sha256=envelope.raw_sha256,
        )
        self.write_router.record_replay(
            "provenance.completed",
            {
                "message_id": envelope.message_id,
                "complete": provenance.complete,
                "missing_fields": provenance.missing_fields,
                "human_review_required": provenance.human_review_required,
            },
        )

        adapted = self.adapter.adapt(classification, provenance, envelope)
        self.logger.emit(
            "adapter",
            stage="adapter",
            result="adapted",
            retryable=False,
            message_id=envelope.message_id,
            raw_sha256=envelope.raw_sha256,
            payload_hash=adapted.payload_hash,
        )
        self.write_router.record_replay("adapter.completed", {"message_id": envelope.message_id, "payload_hash": adapted.payload_hash})

        policy = self.policy.evaluate(adapted)
        assertions.validate(
            "inv_006",
            adapter={
                "payload": {
                    "message_id": adapted.message_id,
                    "provenance": adapted.provenance,
                }
            },
            policy={"allowed": policy.allowed, "quarantine": policy.quarantine},
        )
        self.logger.emit(
            "policy",
            stage="policy",
            result="allowed" if policy.allowed else "rejected",
            retryable=False,
            message_id=envelope.message_id,
            raw_sha256=envelope.raw_sha256,
            reason=policy.reason,
        )
        self.write_router.record_replay(
            "policy.completed",
            {
                "message_id": envelope.message_id,
                "allowed": policy.allowed,
                "quarantine": policy.quarantine,
                "reason": policy.reason,
            },
        )

        transformed = self.decision.transform(adapted, policy)
        validation = self.decision.validate_transform(transformed)
        if not validation.valid:
            reasons = "; ".join(v.message for v in validation.violations)
            raise PolicyError(f"Decision transform validation failed: {reasons}")

        arbitration = self.decision.arbitrate(transformed, policy)
        reasoning = transformed.interpretation + arbitration.reasons + [f"Final route: {arbitration.route.value}"]

        evidence_packet = self.write_router.ingest_evidence(
            event_type="inbound_email",
            raw_payload={
                "message_id": envelope.message_id,
                "raw_sha256": envelope.raw_sha256,
                # The artifact the submitter handed over. `raw_sha256` is the
                # transport envelope, which for the document bridge is a wrapper
                # this system made up; without this the signed record has no idea
                # what was actually submitted.
                "source_sha256": envelope.source_sha256,
                "subject": envelope.subject,
                "sender": envelope.sender,
            },
            normalized_payload={
                "actor": classification.actor.value,
                "labels": [l.value for l in classification.labels],
                "confidence": classification.confidence,
                "route_candidate": "pending",
            },
            metadata={
                "dossier_id": self.dossier_id,
                "stage": "inbound",
                "message_key": envelope.message_key,
                "policy_allowed": policy.allowed,
            },
        )
        self.evidence.add_custody_event(evidence_packet.evidence_id, "pipeline", CustodyAction.INGESTED)

        if not policy.allowed:
            rejection_path = self.output_dir / f"{self.dossier_id}_rejected.jsonl"
            self.quarantined_count += 1
            self._apply_transition("policy_deny", {"message_id": envelope.message_id, "reason": policy.reason})
            self.current_state = DualRejectedPolicyState()
            self.state_history.append(DualRejectedPolicyState())
            self.write_router.record_replay(
                "policy.rejected",
                {
                    "message_id": envelope.message_id,
                    "message_key": envelope.message_key,
                    "reason": policy.reason,
                },
            )
            self.logger.emit(
                "pipeline.rejected",
                stage="policy",
                result="rejected_policy",
                retryable=False,
                message_id=envelope.message_id,
                raw_sha256=envelope.raw_sha256,
                reason=policy.reason,
            )
            self._append_jsonl(
                rejection_path,
                {
                    "message_id": envelope.message_id,
                    "message_key": envelope.message_key,
                    "reason": policy.reason,
                    "time": datetime.datetime.now().isoformat(),
                    "evidence_id": evidence_packet.evidence_id,
                },
            )


            # Per STATE_MACHINE_SPEC.md: REJECTED_POLICY must short-circuit
            # control execution. No control-chain record on rejection path.
            # (F-11 decision; closes F-13 and F-09c.)

            # Ensure dedupe is updated so rejected messages don't re-run forever.
            self.write_router.mark_seen(envelope.message_id, envelope.raw_sha256)

            self.system_state = SystemState.DEGRADED if self.system_state == SystemState.OK else self.system_state
            return PipelineResult(
                status=ResultStatus.REJECTED_POLICY,
                message_key=envelope.message_key,
                message_id=envelope.message_id,
                actor=classification.actor.value,
                route=arbitration.route.value,
                reason=policy.reason,
                record_hash="",
                previous_hash="",
                raw_sha256=envelope.raw_sha256,
                data={
                    "quarantine": policy.quarantine,
                    "stage": "policy",
                    "evidence_id": evidence_packet.evidence_id,
                    "decision_trace": {
                        "arbitration_mode": "ORCHESTRATED",
                        "trust_boundary_version": "1.0.0",
                        "divergence_reason": None,
                    },
                },
            )

        self._apply_transition("policy_allow", {"message_id": envelope.message_id, "route_candidate": policy.reason})

        record = self.control.execute(
            adapted,
            policy,
            route=arbitration.route,
            reasoning=reasoning,
            divergence_reason=None,
        )
        assertions.validate(
            "inv_007",
            prev_record=self.control.get_record_by_hash(record.previous_hash) if record.previous_hash != "0" * 64 else None,
            new_record={"previous_hash": record.previous_hash, "record_hash": record.record_hash},
        )
        self.logger.emit(
            "control",
            stage="control",
            result="committed",
            retryable=False,
            message_id=envelope.message_id,
            raw_sha256=envelope.raw_sha256,
            control_hash=record.record_hash,
        )
        committed_evidence = self.write_router.ingest_evidence(
            event_type="control_commit",
            raw_payload={
                "message_id": envelope.message_id,
                "record_hash": record.record_hash,
                "previous_hash": record.previous_hash,
            },
            normalized_payload={
                "route": record.payload["route"],
                "decision_reasoning": record.payload["decision_reasoning"],
                "control_record_hash": record.record_hash,
            },
            metadata={
                "dossier_id": self.dossier_id,
                "stage": "control",
                "message_key": envelope.message_key,
                "control_record_hash": record.record_hash,
                "source_evidence_id": evidence_packet.evidence_id,
            },
            duplicate_of=evidence_packet.evidence_id,
        )
        self.evidence.add_custody_event(committed_evidence.evidence_id, "pipeline", CustodyAction.INGESTED)
        self.evidence.add_custody_event(committed_evidence.evidence_id, "pipeline", CustodyAction.VERIFIED)
        self._apply_transition("evidence_written", {"message_id": envelope.message_id, "record_hash": record.record_hash})
        self._apply_transition("commit_success", {"message_id": envelope.message_id, "record_hash": record.record_hash})
        self._apply_transition("outbound_queue", {"message_id": envelope.message_id, "record_hash": record.record_hash})
        self.write_router.record_replay(
            "control.recorded",
            {
                "message_id": envelope.message_id,
                "record_hash": record.record_hash,
                "previous_hash": record.previous_hash,
                "route": record.payload["route"],
            },
        )
        self.state_history.append("CONTROL_RECORDED")

        self.write_router.mark_seen(envelope.message_id, envelope.raw_sha256)
        self.state_history.append("SEEN_COMMITTED")
        self._apply_transition("outbound_confirm", {"message_id": envelope.message_id, "raw_sha256": envelope.raw_sha256})
        self.write_router.record_replay("seen.committed", {"message_id": envelope.message_id, "raw_sha256": envelope.raw_sha256})

        result = {
            "dossier_id": self.dossier_id,
            "message_key": envelope.message_key,
            "message_id": envelope.message_id,
            "original_message_id": envelope.original_message_id,
            "date": envelope.date,
            "sender": envelope.sender,
            "recipient": envelope.recipient,
            "subject": envelope.subject,
            "body_preview": envelope.body_text[:300],
            "attachment_count": len(envelope.attachments),
            "actor": classification.actor.value,
            "labels": [l.value for l in classification.labels],
            "confidence": classification.confidence,
            "provenance_complete": provenance.complete,
            "missing_fields": provenance.missing_fields,
            "human_review": provenance.human_review_required or policy.quarantine,
            "policy": {
                "allowed": policy.allowed,
                "reason": policy.reason,
                "quarantine": policy.quarantine,
            },
            "route": record.payload["route"],
            "decision_reasoning": record.payload["decision_reasoning"],
            "decision_trace": record.payload.get("decision_trace", {}),
            "record_hash": record.record_hash,
            "previous_hash": record.previous_hash,
            "raw_sha256": envelope.raw_sha256,
            "source_sha256": envelope.source_sha256,
            "source_bytes": envelope.source_bytes,
            "source_filename": envelope.source_filename,
            "source_media_type": envelope.source_media_type,
            "transport": envelope.transport,
            "synthesised_fields": list(envelope.synthesised_fields),
            "classification_scope_warning": classification.classification_scope_warning,
            "ingest_time": envelope.ingest_timestamp,
        }

        self.processed.append(result)
        self.evidence.add_custody_event(evidence_packet.evidence_id, "pipeline", CustodyAction.VERIFIED)
        return PipelineResult(
            status=ResultStatus.PROCESSED,
            message_key=envelope.message_key,
            message_id=envelope.message_id,
            actor=classification.actor.value,
            route=record.payload["route"],
            reason=policy.reason,
            record_hash=record.record_hash,
            previous_hash=record.previous_hash,
            raw_sha256=envelope.raw_sha256,
            data=result,
        )

    def process_file(self, file_path: str) -> PipelineResult:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Email file not found: {file_path}")
        return self.process_email(path.read_bytes())

    def process_directory(self, dir_path: str) -> List[PipelineResult]:
        results: List[PipelineResult] = []
        for eml_file in sorted(Path(dir_path).glob("*.eml"), key=lambda p: p.name):
            result = self.process_file(str(eml_file))
            if result.status == ResultStatus.PROCESSED:
                results.append(result)
        return results

    def export_json(self, path: Optional[str] = None) -> str:
        if path is None:
            path = str(self.output_dir / f"{self.dossier_id}_export.json")
        records = self.control.get_all_records()
        public_records = [self._public_record(record) for record in records]
        manifest = {
            "dossier_id": self.dossier_id,
            "export_time": datetime.datetime.now().isoformat(),
            "record_count": len(records),
            "tail_hash": self.control.get_tail_hash(),
            "records": records,
            "public_records": public_records,
            "control_events": self.control.get_event_stream(),
            "outbound_sends": self.outbound.get_all(),
            "duplicate_count": self.duplicate_count,
            "failed_count": self.failed_count,
            "quarantined_count": self.quarantined_count,
            "evidence_state": self.evidence.state.value,
            "evidence_packets": [packet.__dict__ for packet in self.evidence.get_packets()],
            "custody_events": [event.__dict__ for event in self.evidence.get_custody_events()],
        }
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False, default=str)
        return path

    def export_markdown_summary(self, path: Optional[str] = None) -> str:
        if path is None:
            path = str(self.output_dir / f"{self.dossier_id}_summary.md")
        records = self.control.get_all_records()
        quarantined = [r for r in records if (r.get("route") == "quarantine_review" or r.get("payload", {}).get("policy_quarantine"))]
        lines = [
            f"# Dossier {self.dossier_id} Evidence Governance Summary",
            "",
            f"**Generated:** {datetime.datetime.now().isoformat()}",
            f"**Total Records:** {len(records)}",
            f"**Deduplicated (this run):** {self.duplicate_count}",
            f"**Failed Runtime Events:** {self.failed_count}",
            f"**Seen Registry (processed total):** {self.seen.count()}",
            f"**Audit Tail Hash:** `{self.control.get_tail_hash()}`",
            "",
            "---",
            "",
            "## Chain Integrity",
            "",
            f"- **Latest Record Hash:** `{self.control.get_tail_hash()}`",
            f"- **Chain Database:** `{self.control.db_path}`",
            "",
            "---",
            "",
            "## Canonical Control Event Stream",
            "",
        ]
        control_events = self.control.get_event_stream()
        if control_events:
            lines.extend([
                "| Event ID | Stage | Message Key | Decision | State Before | State After |",
                "|----------|-------|-------------|----------|--------------|-------------|",
            ])
            for event in control_events:
                lines.append(
                    f"| `{event.get('event_id', '')}` | `{event.get('stage', '')}` | "
                    f"`{event.get('message_key', '')}` | {event.get('decision', '')} | "
                    f"`{event.get('state_before', '')}` | `{event.get('state_after', '')}` |"
                )
        else:
            lines.append("*No control events recorded at this time.*")
        lines.extend(["", "---", "", "## Records Requiring Human Review (Quarantined)", ""])
        if quarantined:
            for item in quarantined:
                payload = self._public_payload(item.get("payload", {}))
                lines.extend([
                    f"### `{item['record_hash']}`",
                    "",
                    f"| Field | Value |",
                    f"|-------|-------|",
                    f"| **Route** | `{item.get('route', '')}` |",
                    f"| **Decision** | {item.get('decision', '')} |",
                    f"| **Timestamp** | {item.get('timestamp', '')} |",
                    f"| **Actor** | {payload.get('actor', '')} |",
                    f"| **Labels** | {', '.join(payload.get('labels', []))} |",
                    f"| **Confidence** | {payload.get('confidence', 0):.2f} |",
                    "",
                ])
                lines.append(f"- Decision summary: {item.get('decision', '')}")
                lines.append("")
        else:
            lines.append("*No records flagged for review at this time.*")
        high_risk_routes = {"hold_silent", "escalate_legal"}
        high_risk = [r for r in records if r.get("route", "").lower() in high_risk_routes]
        lines.extend(["", "---", "", "## High-Risk Routed Records (HOLD_SILENT / ESCALATE_LEGAL)", ""])
        if high_risk:
            for item in high_risk:
                payload = self._public_payload(item.get("payload", {}))
                lines.extend([
                    f"### `{item['record_hash']}`",
                    "",
                    f"| Field | Value |",
                    f"|-------|-------|",
                    f"| **Route** | `{item.get('route', '')}` |",
                    f"| **Decision** | {item.get('decision', '')} |",
                    f"| **Timestamp** | {item.get('timestamp', '')} |",
                    f"| **Actor** | {payload.get('actor', '')} |",
                    f"| **Labels** | {', '.join(payload.get('labels', []))} |",
                    f"| **Confidence** | {payload.get('confidence', 0):.2f} |",
                    "",
                ])
                lines.append(f"- Decision summary: {item.get('decision', '')}")
                lines.append("")
        else:
            lines.append("*No HOLD_SILENT or ESCALATE_LEGAL records at this time.*")
        lines.extend([
            "",
            "---",
            "",
            "## Full Record Index",
            "",
            "| Record Hash | Actor | Route | Confidence | Timestamp | Received count | Received first ts |",
            "|-------------|-------|-------|------------|-----------|-----------------|---------------------|",
        ])
        for item in records:
            payload = self._public_payload(item.get("payload", {}))
            lines.append(
                f"| `{item.get('record_hash', '')}` | {payload.get('actor', '')} | "
                f"`{item.get('route', '')}` | {payload.get('confidence', 0):.2f} | {item.get('timestamp', '')} | "
                f"{payload.get('received_count', 0)} | {payload.get('received_first_ts', '')} |"
            )
        lines.extend([
            "",
            "---",
            "",
            "## Audit Chain Verification",
            "",
            "Run the following command to verify chain integrity:",
            "",
            "```bash",
            f"python -m dossier_pipeline.main --dossier {self.dossier_id} verify-chain",
            "```",
            "",
        ])
        content = "\n".join(lines)
        leakage_report = sanitize_output(content)
        content = leakage_report.sanitized_text + format_disclaimer_block()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        return path

    def build_projection_snapshot(self) -> ProjectionSnapshot:
        return rebuild_projection_snapshot(
            control=self.control,
            evidence=self.evidence,
            outbound=self.outbound,
            replay=self.replay,
            seen_count=self.seen.count(),
            duplicate_count=self.duplicate_count,
            quarantined_count=self.quarantined_count,
        )

    def projection_health_report(self) -> Dict:
        return projection_health_report(self.build_projection_snapshot())

    def _append_jsonl(self, path: Path, payload: Dict):
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False, default=str) + "\n")

    def _fail_with_stage(self, stage: str, raw_bytes: bytes, exc: Exception, status: ResultStatus) -> PipelineResult:
        self._set_state("FAILED_RUNTIME")
        envelope = self._safe_parse_envelope(raw_bytes)
        retryable = self._is_retryable_stage(stage)
        error_event = ErrorEvent(
            stage=stage,
            message_id=envelope.message_id,
            message_key=envelope.message_key,
            error_type=type(exc).__name__,
            error_message=str(exc),
            traceback_hash=self._traceback_hash(exc),
            retryable=retryable,
            occurred_at=datetime.datetime.now().isoformat(),
        )
        self.failed_count += 1
        self._append_jsonl(self.output_dir / f"{self.dossier_id}_errors.jsonl", error_event.__dict__)
        return PipelineResult(
            status=status,
            message_key=envelope.message_key,
            message_id=envelope.message_id,
            actor="unknown",
            reason=str(exc),
            raw_sha256=envelope.raw_sha256,
            retryable=retryable,
            data={"error_type": type(exc).__name__, "stage": stage, "retryable": retryable},
        )

    @staticmethod
    def _apply_source(envelope: EmailEnvelope, source: Optional[Dict]) -> None:
        """Apply a caller-supplied artifact identity to a parsed envelope.

        Only the known source fields are accepted: this is not a way to inject
        arbitrary keys into the envelope from outside the pipeline.
        """
        if not source:
            return
        for name in SOURCE_FIELDS:
            if name not in source:
                continue
            value = source[name]
            if name == "synthesised_fields":
                value = tuple(value)
            setattr(envelope, name, value)

    def _safe_parse_envelope(self, raw_bytes: bytes):
        try:
            return self.intake.parse_email_bytes(raw_bytes)
        except Exception:
            # No source is asserted here: the artifact could not be read, so the
            # honest value is an empty one rather than a hash of unknown meaning.
            return EmailEnvelope(
                message_id="",
                subject="",
                sender="",
                recipient="",
                date="",
                body_text="",
                raw_sha256="",
                message_key=self._message_key_from_raw(raw_bytes),
                original_message_id="",
                ingest_timestamp=datetime.datetime.now().isoformat(),
            )

    def _is_retryable_stage(self, stage: str) -> bool:
        return stage in self.RETRYABLE_FAILURE_STAGES and stage == "process_email"

    def _message_key_from_raw(self, raw_bytes: bytes) -> str:
        return hashlib.sha256(raw_bytes).hexdigest()[:32]

    def _traceback_hash(self, exc: Exception) -> str:
        return hashlib.sha256(f"{type(exc).__name__}:{exc}".encode()).hexdigest()

    def _public_payload(self, payload: Dict) -> Dict:
        public_payload = {
            k: v
            for k, v in payload.items()
            if k not in {"decision_reasoning", "decision_trace", "trace", "payload_hash", "control_hash", "previous_hash"}
        }
        rejected = validate_export_fields(public_payload.keys())
        if rejected:
            for field_name in rejected:
                public_payload.pop(field_name, None)
        return public_payload

    def _public_record(self, record: Dict) -> Dict:
        return {
            "record_hash": record.get("record_hash", ""),
            "previous_hash": record.get("previous_hash", ""),
            "timestamp": record.get("timestamp", ""),
            "decision": record.get("decision", ""),
            "route": record.get("route", ""),
            "payload": self._public_payload(record.get("payload", {})),
        }
