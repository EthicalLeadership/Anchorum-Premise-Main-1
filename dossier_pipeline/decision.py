"""
Dossier DOSSIER-PIPELINE — Decision Engine (Silence Matrix)
Label-to-route derivation with reasoning traces.
"""

from typing import List, Tuple

from dossier_enforcement import (FailureMode, LockRegistry, LockSpec,
                                  TransactionGate, assert_that, invariant)

from .contracts import (ActorType, AdapterResult, ArbitrationDecision,
                        ClassificationLabel, PolicyDecision, RouteAction,
                        TransformResult, ValidationResult, ValidationViolation)

_decision_registry = LockRegistry(scope="decision")

class DecisionEngine:
    """
    Implements the Silence Matrix for Dossier DOSSIER-PIPELINE.
    Every route decision is explainable and auditable.

    The engine is strictly operational: it routes work, it does not
    produce legal conclusions.
    """

    def transform(
        self,
        adapter: AdapterResult,
        policy: PolicyDecision
    ) -> TransformResult:
        lock = _decision_registry.create_hierarchical_lock(
            LockSpec(f"decision.route.{adapter.message_key or adapter.message_id}", hierarchy_order=30)
        )
        with lock:
            with TransactionGate(f"decision-{adapter.message_key or adapter.message_id}", auto_commit=True) as gate:
                labels = adapter.classification.labels
                actor = adapter.classification.actor
                interpretation: List[str] = []
                interpretation.append("Decision scope: administrative routing only")
                assert_that(
                    policy.reason is not None,
                    "Policy decision must include reason",
                    assertion_id="DEC-PRE-001",
                    mode=FailureMode.HARD,
                    context={"message_id": adapter.message_id},
                    actual=policy.reason,
                    expected="non-empty reason",
                )

                # ---- EMPLOYER ----
                if actor == ActorType.EMPLOYER:
                    if ClassificationLabel.PRESSURE_TACTIC in labels:
                        route_candidate = RouteAction.HOLD_SILENT
                        interpretation.append(
                            "SILENCE MATRIX [EMPLOYER+PRESSURE]: Hold silent. "
                            "Do not respond. Document only. Any reply risks waiving rights."
                        )
                    elif ClassificationLabel.REQUIRES_RESPONSE in labels:
                        route_candidate = RouteAction.QUARANTINE_REVIEW
                        interpretation.append(
                            "SILENCE MATRIX [EMPLOYER+REQUIRES_RESPONSE]: Employer demands "
                            "response — legal review mandatory before any reply."
                        )
                    else:
                        route_candidate = RouteAction.ARCHIVE
                        interpretation.append(
                            "SILENCE MATRIX [EMPLOYER]: Informational — archive and monitor."
                        )

                # ---- INSURER ----
                elif actor == ActorType.INSURER:
                    if ClassificationLabel.LEGAL_SIGNIFICANT in labels:
                        route_candidate = RouteAction.QUARANTINE_REVIEW
                        interpretation.append(
                            "SILENCE MATRIX [INSURER+LEGAL]: Review with counsel before "
                            "any disclosure or response."
                        )
                    else:
                        route_candidate = RouteAction.ARCHIVE
                        interpretation.append(
                            "SILENCE MATRIX [INSURER]: Routine — archive."
                        )

                # ---- UNION ----
                elif actor == ActorType.UNION:
                    route_candidate = RouteAction.FORWARD_UNION
                    interpretation.append(
                        "SILENCE MATRIX [UNION]: Forward to delegate and archive."
                    )

                # ---- MEDICAL ----
                elif actor == ActorType.MEDICAL:
                    if (
                        ClassificationLabel.PRIVILEGED in labels
                        or ClassificationLabel.LEGAL_SIGNIFICANT in labels
                    ):
                        route_candidate = RouteAction.QUARANTINE_REVIEW
                        interpretation.append(
                            "SILENCE MATRIX [MEDICAL+PRIVILEGED]: Protect confidentiality. "
                            "Review before any disclosure to employer/insurer."
                        )
                    else:
                        route_candidate = RouteAction.ARCHIVE
                        interpretation.append(
                            "SILENCE MATRIX [MEDICAL]: Routine — archive."
                        )

                # ---- PSYCHOLOGIST ----
                elif actor == ActorType.PSYCHOLOGIST:
                    route_candidate = RouteAction.QUARANTINE_REVIEW
                    interpretation.append(
                        "SILENCE MATRIX [PSYCHOLOGIST]: High sensitivity. "
                        "Review before any action."
                    )

                # ---- LEGAL ----
                elif actor == ActorType.LEGAL:
                    route_candidate = RouteAction.ESCALATE_LEGAL
                    interpretation.append(
                        "SILENCE MATRIX [LEGAL]: Escalate to counsel immediately."
                    )

                # ---- SELF ----
                elif actor == ActorType.SELF:
                    route_candidate = RouteAction.QUARANTINE_REVIEW
                    interpretation.append(
                        "SILENCE MATRIX [SELF]: Outgoing — manual review required."
                    )

                # ---- UNKNOWN ----
                else:
                    route_candidate = RouteAction.QUARANTINE_REVIEW
                    interpretation.append(
                        "SILENCE MATRIX [UNKNOWN]: Actor unrecognised — manual review required."
                    )

                invariant(
                    route_candidate in list(RouteAction),
                    "decision.route_valid",
                    actual=route_candidate.value,
                    expected="RouteAction member",
                )
                gate.execute_now(
                    forward=lambda: None,
                    reverse=lambda: None,
                    description="store decision routing",
                )
                return TransformResult(route_candidate=route_candidate, interpretation=interpretation)

    def validate_transform(self, transformed: TransformResult) -> ValidationResult:
        violations: List[ValidationViolation] = []
        if transformed.route_candidate not in list(RouteAction):
            violations.append(
                ValidationViolation(
                    code="DEC-VAL-001",
                    message="Route candidate must map to a known RouteAction",
                )
            )
        return ValidationResult(valid=not violations, violations=violations)

    def arbitrate(self, transformed: TransformResult, policy: PolicyDecision) -> ArbitrationDecision:
        route = transformed.route_candidate
        reasons: List[str] = []
        if policy.quarantine:
            if route == RouteAction.HOLD_SILENT:
                reasons.append(
                    "Arbitration note: policy quarantine flag present; HOLD_SILENT preserved and human review flagged."
                )
            elif route != RouteAction.QUARANTINE_REVIEW:
                reasons.append(
                    "Arbitration override: policy quarantine flag forced QUARANTINE_REVIEW route."
                )
                route = RouteAction.QUARANTINE_REVIEW
        return ArbitrationDecision(route=route, reasons=reasons)

    def decide(
        self,
        adapter: AdapterResult,
        policy: PolicyDecision
    ) -> Tuple[RouteAction, List[str]]:
        transformed = self.transform(adapter, policy)
        validation = self.validate_transform(transformed)
        if not validation.valid:
            raise ValueError("Decision transform validation failed")
        arbitration = self.arbitrate(transformed, policy)
        reasoning = transformed.interpretation + arbitration.reasons + [f"Final route: {arbitration.route.value}"]
        return arbitration.route, reasoning
