"""Phase 4 gate: a third party can verify a decision from the audit log alone.

After the decision is written, this test does not touch the engine, adapter,
or flow. It reads the audit line as bytes, reconstructs the decision from
the record, and asserts the reconstruction matches what was produced.

That is the property the whole governance stack exists to deliver.
"""
from __future__ import annotations

import json
import pathlib
import re
import sys
from types import SimpleNamespace

_REPO = pathlib.Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from ccsp.verify import (
    CanonicalConcept, CanonicalizationRules, Engine,
    EvidenceRef, LexiconEntry, SemanticCandidate,
)
from dossier_pipeline.governance.flow import GovernedDecisionFlow
from dossier_pipeline.governance.semantic_adapter import SemanticEngineAdapter
from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.trace import TraceLog


def _legal_rules():
    return CanonicalizationRules.build(
        version="legal-v1",
        concepts=[
            CanonicalConcept("LEGAL_ESTABLISH_LIABILITY",
                             frozenset({"legal"}), True, ""),
            CanonicalConcept("LEGAL_EVIDENCE_INSUFFICIENT",
                             frozenset({"legal"}), False, ""),
        ],
        lexicon=[
            LexiconEntry(re.compile(r"establishes liability", re.I),
                         "LEGAL_ESTABLISH_LIABILITY"),
            LexiconEntry(re.compile(r"insufficient evidence", re.I),
                         "LEGAL_EVIDENCE_INSUFFICIENT"),
        ],
    )


class _PassPolicy:
    def decide(self, fields, *, now):
        return SimpleNamespace(
            route="PASS", reason="gate-test",
            severity="info", citation="", rule_id="gate",
            evaluated_at=now, fields_used=(), rule_errors=(),
        )


def test_third_party_can_verify_decision_from_audit_log(tmp_path):
    # ---------- 1. Build the real stack ----------
    rules = _legal_rules()
    engine = Engine(rules=rules, vertical_scope=frozenset({"legal"}))
    adapter = SemanticEngineAdapter(engine=engine, vertical_id="legal")

    # Capture everything we are about to forget.
    expected_config_hash = adapter.config_hash

    audit = AuditLog(tmp_path / "audit.jsonl")
    trace = TraceLog(tmp_path / "trace.jsonl")

    flow = GovernedDecisionFlow(
        engine=adapter,
        policy=_PassPolicy(),
        audit=audit,
        trace=trace,
        vertical_id="legal",
        config_hash=expected_config_hash,
        allow_unregistered=True,
    )

    candidates = [
        SemanticCandidate(
            raw_text="There is insufficient evidence.",
            normalized_text="There is insufficient evidence.",
            confidence=0.9,
            evidence=(EvidenceRef(doc_hash="a" * 64, page=1,
                                  span_start=10, span_end=32),),
        ),
    ]

    # ---------- 2. Make a decision ----------
    result = flow.decide([candidates], fields={"case": "T-001"}, now=1717200000)
    assert result.trace_id is not None

    # ---------- 3. Forget everything except the audit log on disk ----------
    del engine, adapter, flow, result

    audit_path = tmp_path / "audit.jsonl"
    raw_line = audit_path.read_text().splitlines()[0]
    record = json.loads(raw_line)["record"]

    # ---------- 4. Reconstruct the decision from the record alone ----------

    # 4a. Which concept won.
    assert "projections" in record
    assert len(record["projections"]) == 1
    p0 = record["projections"][0]
    assert p0["concept_id"] == "LEGAL_EVIDENCE_INSUFFICIENT"
    assert p0["classification"] == "canonical_projection"
    assert p0["admissible"] is True

    # 4b. Which evidence produced it.
    assert "evidence" in p0 and len(p0["evidence"]) == 1
    ev = p0["evidence"][0]
    assert ev["doc_hash"] == "a" * 64
    assert ev["page"] == 1
    assert ev["span_start"] == 10
    assert ev["span_end"] == 32

    # 4c. Which configuration was in force.
    assert record["config_hash"] == expected_config_hash
    assert len(record["config_hash"]) == 64
    int(record["config_hash"], 16)

    # 4d. Which input was processed.
    assert record["fields"] == {"case": "T-001"}

    # 4e. Which decision was routed.
    assert record["decision"]["route"] == "PASS"
    assert record["decision"]["evaluated_at"] == 1717200000

    # 4f. Internal hash consistency.
    assert p0["semantic_hash"] == record["projection_ids"][0]
    assert len(p0["semantic_hash"]) == 64
    int(p0["semantic_hash"], 16)

    # 4g. Vertical is identified.
    assert record["vertical_id"] == "legal"

    # NOTE: this record is sufficient to CHECK the decision, but not to
    # RECOMPUTE semantic_hash byte-for-byte. concept_distribution and
    # matched_entries are not carried. Closing that gap is Phase 4B.
