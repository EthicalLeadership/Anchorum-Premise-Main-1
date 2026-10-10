"""
Dossier DOSSIER-PIPELINE Evidence Governance Pipeline

Local, audit-grade evidence ingestion and classification system.
Connects to ProtonMail via Bridge IMAP.
"""

__version__ = "2.0.0"
__dossier_id__ = "DOSSIER-PIPELINE"

from .auth import (AuthToken, decode_token, fingerprint_credential, has_role,
                   issue_token, validate_bearer_token)
from .barreau_gate import BarreauGate, BarreauGateError, BarreauGateResult
from .enforcement_v2 import (ForbiddenWriteViolation, build_call_graph,
                             compute_reachability, resolve_imports,
                             scan_dynamic_dispatch,
                             scan_forbidden_control_writes,
                             scan_forbidden_mutator_calls,
                             scan_project_for_mutator_reachability)
from .projections_v2 import (FrozenDict, ProjectionSnapshot, SchemaField,
                             SchemaValidator, compare_evidence_projection,
                             compare_outbound_projection,
                             compare_seen_projection, deep_freeze,
                             detect_drift, projection_health_report,
                             rebuild_evidence_projection,
                             rebuild_outbound_projection,
                             rebuild_projection_snapshot,
                             rebuild_seen_projection)
from .schema import (AuditLog, Base, Case, Document, JurisdictionStamp, User,
                     create_engine_and_session, get_session, init_schema)
from .transaction import (BeginError, CommitError, JournalEntry,
                          JournalReplayError, PipelineTransaction,
                          RollbackError, StoreOpenError,
                          TransactionalWriteRouter, TransactionJournal)
