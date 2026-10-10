"""End-to-end: real CCSP engine -> adapter -> GovernedDecisionFlow.

Uses the actual `ccsp.verify.Engine`, not a stub. If any layer of the
stack has an interface mismatch (wrong attribute name, wrong type,
missing field), it will surface here rather than in production.
"""
import pathlib
import re
import sys
from types import SimpleNamespace

import pytest

# Repo root on path so `ccsp.verify` is importable regardless of pytest's
# rootdir behavior.
_REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ccsp.verify import (
    CanonicalConcept,
    CanonicalizationRules,
    Engine as CCSPEngine,
    EvidenceRef,
    LexiconEntry,
    SemanticCandidate,
)

from dossier_pipeline.governance import (
    GovernedDecisionFlow,
    SemanticEngineAdapter,
)
from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.trace import TraceLog


CH = "a" * 64


def _legal_rules() -> CanonicalizationRules:
    return CanonicalizationRules.build(
        version="legal-v1",
        concepts=[
            CanonicalConcept(
                "LEGAL_EVIDENCE_INSUFFICIENT",
                frozenset({"legal"}), False, "",
            ),
        ],
        lexicon=[
            LexiconEntry(
                re.compile(r"insufficient evidence", re.I),
                "LEGAL_EVIDENCE_INSUFFICIENT",
            ),
        ],
    )


class _StubPolicy:
    def decide(self, fields, *, now):
        return SimpleNamespace(
            route="PASS", reason="ok", severity="info",
            citation="", rule_id="t", evaluated_at=now,
            fields_used=(), rule_errors=(),
        )


def test_ccsp_engine_through_governed_flow(tmp_path):
    # 1. Real CCSP engine
    rules = _legal_rules()
    ccsp_engine = CCSPEngine(
        rules=rules,
        vertical_scope=frozenset({"legal"}),
    )

    # 2. Real adapter wrapping the real engine
    adapter = SemanticEngineAdapter(
        engine=ccsp_engine,
        vertical_id="legal",
        lexicon_hash=getattr(rules, "hash", ""),
    )

    # 3. Real audit and trace logs
    audit = AuditLog(tmp_path / "audit.jsonl")
    trace = TraceLog(tmp_path / "trace.jsonl")

    # 4. Real flow
    flow = GovernedDecisionFlow(
        engine=adapter,
        policy=_StubPolicy(),
        audit=audit,
        trace=trace,
        vertical_id="legal",
        config_hash=CH,
        allow_unregistered=True,
    )

    # 5. Real candidates (two surface forms of the same concept)
    ev_a = (EvidenceRef(doc_hash="a" * 64),)
    ev_b = (EvidenceRef(doc_hash="b" * 64),)
    candidates = [
        SemanticCandidate(
            "There is insufficient evidence.",
            "There is insufficient evidence.", 0.9, ev_a,
        ),
        SemanticCandidate(
            "insufficient evidence on review",
            "insufficient evidence on review", 0.85, ev_b,
        ),
    ]

    result = flow.decide([candidates], fields={"x": 1}, now=1234567890)

    # --- decision returned ---
    assert result.decision.route == "PASS"
    assert result.audit_seq == 0
    assert result.trace_id is not None
    assert result.vertical_id == "legal"
    assert result.config_hash == CH

    # --- real CCSP projection with real semantics ---
    assert len(result.projections) == 1
    projection = result.projections[0]
    assert projection.concept_id == "LEGAL_EVIDENCE_INSUFFICIENT"
    assert projection.admissible is True
    assert isinstance(projection.semantic_hash, str)
    assert len(projection.semantic_hash) == 64

    # --- audit record matches the live projection ---
    entries = list(audit)
    assert len(entries) == 1
    record = entries[0].record
    assert record["vertical_id"] == "legal"
    assert record["config_hash"] == CH
    assert record["fields"] == {"x": 1}
    assert record["projection_ids"] == [projection.semantic_hash]
    assert record["projections"][0]["semantic_hash"] == projection.semantic_hash
    assert record["projections"][0]["concept_id"] == "LEGAL_EVIDENCE_INSUFFICIENT"

    # --- trace links back ---
    traces = list(trace)
    assert len(traces) == 1
    assert traces[0].projection_ids == (projection.semantic_hash,)
    assert traces[0].audit_seq == entries[0].seq
    assert traces[0].trace_id == result.trace_id
    assert traces[0].config_hash == CH

    # --- re-derivation: same engine, same candidates -> same hash ---
    direct = ccsp_engine.project(candidates)
    assert direct.semantic_hash == projection.semantic_hash

    # --- chain integrity holds after the write ---
    assert audit.verify_chain() == []
