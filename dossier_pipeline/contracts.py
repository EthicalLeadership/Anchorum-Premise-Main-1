"""
Dossier DOSSIER-PIPELINE Shared Contracts
Cross-cutting enums and dataclasses used across all pipeline layers.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

DECISION_TRACE_ALLOWED_MODES = {"ORCHESTRATED", "LEGACY_FALLBACK"}
DECISION_TRACE_REQUIRED_KEYS = ("arbitration_mode", "trust_boundary_version", "divergence_reason")


class ActorType(str, Enum):
    EMPLOYER = "employer"
    INSURER = "insurer"
    UNION = "union"
    MEDICAL = "medical"
    PSYCHOLOGIST = "psychologist"
    LEGAL = "legal"
    SELF = "self"
    UNKNOWN = "unknown"


class ClassificationLabel(str, Enum):
    URGENT = "urgent"
    LEGAL_SIGNIFICANT = "legal_significant"
    REQUIRES_RESPONSE = "requires_response"
    CONFLICT_MARKER = "conflict_marker"
    PRESSURE_TACTIC = "pressure_tactic"
    INFORMATIONAL = "informational"
    PRIVILEGED = "privileged"
    NOISE = "noise"


class RouteAction(str, Enum):
    HOLD_SILENT = "hold_silent"
    RESPOND_FORMAL = "respond_formal"
    ESCALATE_LEGAL = "escalate_legal"
    QUARANTINE_REVIEW = "quarantine_review"
    ARCHIVE = "archive"
    FORWARD_UNION = "forward_union"


class ResultStatus(str, Enum):
    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    QUARANTINED = "quarantined"
    REJECTED_POLICY = "rejected_policy"
    FAILED_RUNTIME = "failed_runtime"


@dataclass
class EmailEnvelope:
    message_id: str
    subject: str
    sender: str
    recipient: str
    date: str
    body_text: str
    attachments: List[Dict] = field(default_factory=list)

    # Transport proof signal extracted from SMTP/MTA transport headers when present.
    # Stored as audit-friendly deterministic metadata; raw header text is not retained.
    received_count: int = 0
    received_first_ts: str = ""
    received_last_ts: str = ""
    # Base64 fingerprint of normalized Received header list (MD-safe; avoids hex redaction).
    received_chain_fingerprint_b64: str = ""

    raw_sha256: str = ""
    message_key: str = ""
    original_message_id: str = ""
    ingest_timestamp: str = ""

    # Identity of the submitted artifact, kept distinct from `raw_sha256`.
    #
    # `raw_sha256` is the hash of the bytes actually ingested, which is the
    # transport envelope. For a real .eml that IS the artifact. For the document
    # bridge the ingested bytes are a wrapper this system synthesised, so these
    # fields carry what the submitter actually handed over. For an .eml the two
    # hashes are equal and `transport == "email"`.
    source_sha256: str = ""
    source_bytes: int = 0
    source_filename: str = ""
    source_media_type: str = ""
    transport: str = "email"
    #: Envelope fields that were invented rather than observed. Named explicitly
    #: so a reader of the signed record can tell them from observed values.
    synthesised_fields: Tuple[str, ...] = ()


@dataclass
class ClassificationResult:
    labels: List[ClassificationLabel]
    confidence: float
    actor: ActorType
    reasoning: List[str]
    rule_hits: List[str]
    #: Set when the actor classification is scoped rather than observed. A
    #: free-text `reasoning` line is not enough: `trace` is internal-only and is
    #: stripped from exports, so the reason has to be a field to travel.
    classification_scope_warning: str = ""


@dataclass
class ProvenanceResult:
    complete: bool
    missing_fields: List[str]
    human_review_required: bool
    thread_id: Optional[str] = None
    source_type: Optional[str] = None


@dataclass
class AdapterResult:
    classification: ClassificationResult
    provenance: ProvenanceResult
    trace: List[str]
    confidence: float
    raw_sha256: str
    payload_hash: str

    # Transport-proof fields for “confirmed received” evidence.
    received_count: int = 0
    received_first_ts: str = ""
    received_last_ts: str = ""
    received_chain_fingerprint_b64: str = ""

    message_id: str = ""
    message_key: str = ""
    original_message_id: str = ""

    # Artifact identity, carried off the envelope so it reaches the committed
    # record. Declared here, populated in `adapter.adapt`, committed in
    # `control._build_execution_context`: all three, or it is absent from the
    # signed record while still appearing in the pipeline's return value.
    source_sha256: str = ""
    source_bytes: int = 0
    source_filename: str = ""
    source_media_type: str = ""
    transport: str = "email"
    synthesised_fields: Tuple[str, ...] = ()
    classification_scope_warning: str = ""


@dataclass
class PolicyDecision:
    allowed: bool
    reason: str
    quarantine: bool = False


@dataclass
class ControlPlaneRecord:
    record_hash: str
    previous_hash: str
    timestamp: str
    payload: Dict[str, Any]
    decision: str
    route: str
    sequence_no: int = 0
    signature_algo: str = ""
    signature_key_id: str = ""
    signature: str = ""


@dataclass
class PipelineResult:
    status: ResultStatus
    message_key: str
    message_id: str = ""
    actor: str = ""
    route: str = ""
    reason: str = ""
    record_hash: str = ""
    previous_hash: str = ""
    raw_sha256: str = ""
    retryable: bool = False
    data: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ErrorEvent:
    stage: str
    message_id: str
    message_key: str
    error_type: str
    error_message: str
    traceback_hash: str
    retryable: bool
    occurred_at: str


@dataclass(frozen=True)
class TransformResult:
    route_candidate: RouteAction
    interpretation: List[str]


@dataclass(frozen=True)
class ValidationViolation:
    code: str
    message: str


@dataclass(frozen=True)
class ValidationResult:
    valid: bool
    violations: List[ValidationViolation] = field(default_factory=list)


@dataclass(frozen=True)
class ArbitrationDecision:
    route: RouteAction
    reasons: List[str]


@dataclass(frozen=True)
class DecisionTrace:
    arbitration_mode: str
    trust_boundary_version: str
    divergence_reason: Optional[str] = None


def validate_decision_trace(trace: Dict[str, Any]) -> List[str]:
    """Return invariant violations for DecisionTrace shape/content."""
    violations: List[str] = []
    if not isinstance(trace, dict):
        return ["decision_trace must be a dict"]

    missing = [k for k in DECISION_TRACE_REQUIRED_KEYS if k not in trace]
    if missing:
        violations.append(f"decision_trace missing required keys: {', '.join(missing)}")

    extra = [k for k in trace.keys() if k not in DECISION_TRACE_REQUIRED_KEYS]
    if extra:
        violations.append(f"decision_trace has unsupported keys: {', '.join(extra)}")

    mode = trace.get("arbitration_mode")
    if mode not in DECISION_TRACE_ALLOWED_MODES:
        violations.append("decision_trace arbitration_mode must be ORCHESTRATED or LEGACY_FALLBACK")

    version = trace.get("trust_boundary_version")
    if not isinstance(version, str) or not version.strip():
        violations.append("decision_trace trust_boundary_version must be a non-empty string")

    reason = trace.get("divergence_reason")
    if reason is not None and (not isinstance(reason, str) or not reason.strip()):
        violations.append("decision_trace divergence_reason must be null or non-empty string")

    return violations
