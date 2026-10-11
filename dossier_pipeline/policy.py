"""
Dossier DOSSIER-PIPELINE — Policy Engine
Hard enforcement boundaries for governed execution.
"""

from typing import List

from dossier_enforcement import (FailureMode, LockRegistry, LockSpec,
                                  TransactionGate, assert_that, invariant)

from .contracts import (ActorType, AdapterResult, ClassificationLabel,
                        PolicyDecision)

_policy_registry = LockRegistry(scope="policy")

class PolicyEngine:
    """
    Evaluates whether an adapted payload may proceed through the pipeline.
    Rules are ordered and mandatory. No exceptions.

    Rule 1 (missing payload_hash) is a blocking hard error — the record
    cannot be processed without a cryptographic fingerprint.

    Rules 2–5 are non-short-circuiting: ALL matching rules are evaluated
    so that the audit record captures every policy concern, not only the
    first one encountered.

    The engine remains operational only: it may quarantine or route for
    human review, but it does not generate legal conclusions.
    """

    def evaluate(self, adapter: AdapterResult) -> PolicyDecision:
        lock = _policy_registry.create_hierarchical_lock(
            LockSpec(f"policy.doc.{adapter.message_key or adapter.message_id}", hierarchy_order=20)
        )
        with lock:
            with TransactionGate(f"policy-{adapter.message_key or adapter.message_id}", auto_commit=True) as gate:
                # Rule 1: Cryptographic fingerprints are mandatory — hard block
                assert_that(
                    bool(adapter.payload_hash and adapter.raw_sha256),
                    "Missing raw_sha256 or payload_hash — cryptographic fingerprint required",
                    assertion_id="POL-PRE-001",
                    mode=FailureMode.HARD,
                    context={"message_id": adapter.message_id},
                    actual={"payload_hash": adapter.payload_hash, "raw_sha256": adapter.raw_sha256},
                    expected="both present",
                )

                quarantine_reasons: List[str] = []
                operational_notes: List[str] = []

                # Rule 2: Employer pressure during protected leave → quarantine
                if (
                    adapter.classification.actor == ActorType.EMPLOYER
                    and ClassificationLabel.PRESSURE_TACTIC in adapter.classification.labels
                ):
                    quarantine_reasons.append(
                        "Employer pressure detected during disability leave — "
                        "requires human review before any response"
                    )
                    operational_notes.append("pressure_tactic:employer")

                # Rule 3: Conflict markers always quarantine
                if ClassificationLabel.CONFLICT_MARKER in adapter.classification.labels:
                    quarantine_reasons.append(
                        "Conflict marker detected — verify facts before action"
                    )
                    operational_notes.append("conflict_marker")

                # Rule 4 (low-confidence legal) was removed per F-16.
                # It could not fire: the classifier's confidence is
                # 0.3 + rule_hits*0.15, and any LEGAL_SIGNIFICANT match adds
                # at least two hits (language + legal), so confidence >= 0.6
                # whenever the label is present.  The threshold was exactly
                # the floor.  If a low-confidence signal is wanted, it needs
                # a classifier confidence model that can express uncertainty;
                # see F-16.

                # Rule 5: Privileged content → quarantine for confidentiality protection
                if ClassificationLabel.PRIVILEGED in adapter.classification.labels:
                    quarantine_reasons.append(
                        "Privileged content detected — protect confidentiality"
                    )
                    operational_notes.append("privileged")

                if quarantine_reasons:
                    reason = "; ".join(quarantine_reasons)
                    if operational_notes:
                        reason = f"{reason} | notes: {', '.join(operational_notes)}"
                    decision = PolicyDecision(
                        allowed=False,
                        reason=reason,
                        quarantine=True
                    )
                else:
                    decision = PolicyDecision(
                        allowed=True,
                        reason="Clear path — no policy constraints triggered",
                        quarantine=False
                    )

                invariant(
                    isinstance(decision.quarantine, bool),
                    "policy.quarantine_flag",
                    actual=decision.quarantine,
                    expected=True if not decision.allowed else False,
                )
                gate.execute_now(
                    forward=lambda: None,
                    reverse=lambda: None,
                    description="store policy decision",
                )
                return decision
