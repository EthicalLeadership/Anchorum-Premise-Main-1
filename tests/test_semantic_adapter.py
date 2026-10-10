"""Adapter tests: thin wrapper plus integration with GovernedDecisionFlow."""
from types import SimpleNamespace
import pytest

from dossier_pipeline.governance import (
    GovernedDecisionFlow,
    SemanticEngineAdapter,
)
from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.trace import TraceLog


class _StubEngine:
    def __init__(self, hashes):
        self._hashes = list(hashes)
        self._i = 0
        self.calls = 0

    def project(self, candidates):
        self.calls += 1
        h = self._hashes[self._i % len(self._hashes)]
        self._i += 1
        return SimpleNamespace(
            semantic_hash=h,
            classification="canonical_projection",
            admissible=True,
            concept_id="LEGAL_EVIDENCE_INSUFFICIENT",
            canonical_text="insufficient evidence",
            confidence_int=90,
            confidence_calibration="calibrated",
        )


class _StubPolicy:
    def decide(self, fields, *, now):
        return SimpleNamespace(
            route="PASS", reason="ok", severity="info",
            citation="", rule_id="t", evaluated_at=now,
            fields_used=(), rule_errors=(),
        )


CH = "a" * 64


@pytest.fixture
def logs(tmp_path):
    return (
        AuditLog(tmp_path / "audit.jsonl"),
        TraceLog(tmp_path / "trace.jsonl"),
    )


def test_adapter_requires_vertical_id():
    with pytest.raises(ValueError):
        SemanticEngineAdapter(engine=_StubEngine(["h"]), vertical_id="")


def test_adapter_rejects_non_string_vertical():
    with pytest.raises(ValueError):
        SemanticEngineAdapter(engine=_StubEngine(["h"]), vertical_id=123)


def test_adapter_rejects_engine_without_project():
    with pytest.raises(TypeError):
        SemanticEngineAdapter(engine=object(), vertical_id="legal")


def test_adapter_rejects_non_callable_project():
    class _Bad:
        project = "not callable"
    with pytest.raises(TypeError):
        SemanticEngineAdapter(engine=_Bad(), vertical_id="legal")


def test_adapter_exposes_metadata():
    a = SemanticEngineAdapter(
        engine=_StubEngine(["h"]), vertical_id="legal", lexicon_hash="abc",
    )
    assert a.vertical_id == "legal"
    assert a.lexicon_hash == "abc"
    assert a.engine is not None


def test_adapter_forwards_project_unchanged():
    engine = _StubEngine(["h1", "h2"])
    a = SemanticEngineAdapter(engine=engine, vertical_id="legal")
    assert a.project([1]).semantic_hash == "h1"
    assert a.project([2]).semantic_hash == "h2"
    assert engine.calls == 2


def test_adapter_works_with_flow_end_to_end(logs):
    audit, trace = logs
    adapter = SemanticEngineAdapter(
        engine=_StubEngine(["h1", "h2"]),
        vertical_id="legal", lexicon_hash="lex123",
    )
    flow = GovernedDecisionFlow(
        engine=adapter, policy=_StubPolicy(),
        audit=audit, trace=trace,
        vertical_id="legal", config_hash=CH,
        allow_unregistered=True,
    )
    result = flow.decide([[1], [2]], fields={"x": 1}, now=1)

    assert result.audit_seq == 0
    assert len(result.projections) == 2
    assert result.projections[0].semantic_hash == "h1"
    assert result.projections[1].semantic_hash == "h2"

    entry = list(audit)[0]
    assert entry.record["projection_ids"] == ["h1", "h2"]

    traces = list(trace)
    assert traces[0].projection_ids == ("h1", "h2")


def test_lexicon_hash_does_not_leak_into_audit(logs):
    audit, _ = logs
    adapter = SemanticEngineAdapter(
        engine=_StubEngine(["h1"]),
        vertical_id="legal", lexicon_hash="LEAK_CANARY",
    )
    flow = GovernedDecisionFlow(
        engine=adapter, policy=_StubPolicy(),
        audit=audit, trace=logs[1],
        vertical_id="legal", config_hash=CH,
        allow_unregistered=True,
    )
    flow.decide([[1]], fields={}, now=1)
    assert "LEAK_CANARY" not in str(list(audit)[0].record)


def test_build_for_vertical_with_real_lexicon():
    """The convenience factory must construct a working adapter from a
    real YAML lexicon and the real ccsp.verify.Engine."""
    import pathlib as _pl
    import sys as _sys

    _root = _pl.Path(__file__).resolve().parent.parent
    if str(_root) not in _sys.path:
        _sys.path.insert(0, str(_root))

    from dossier_pipeline.governance import build_for_vertical

    lexicon_path = _root / "lexicons" / "legal-v1.yaml"
    if not lexicon_path.exists():
        pytest.skip(f"lexicon file not present: {lexicon_path}")

    adapter = build_for_vertical(
        lexicon_path=lexicon_path,
        vertical_id="legal",
    )
    assert adapter.vertical_id == "legal"
    assert adapter.lexicon_hash
    assert hasattr(adapter, "project")

    from ccsp.verify import EvidenceRef, SemanticCandidate
    candidates = [
        SemanticCandidate(
            "There is insufficient evidence.",
            "There is insufficient evidence.", 0.9,
            (EvidenceRef(doc_hash="c" * 64),),
        ),
    ]
    projection = adapter.project(candidates)
    assert projection.semantic_hash
    assert projection.admissible is True


def test_adapter_exposes_config_hash():
    """Gap 1: adapter.config_hash must be derived from the engine, not supplied."""
    from dossier_pipeline.governance.semantic_adapter import SemanticEngineAdapter

    class FakeEngine:
        def __init__(self):
            self._ch = "a" * 64
        def project(self, candidates):
            return None

    a = SemanticEngineAdapter(engine=FakeEngine(), vertical_id="legal")
    assert a.config_hash == "a" * 64


def test_adapter_config_hash_raises_without_engine_hash():
    """Gap 1: if the engine exposes no config hash, the property must raise
    rather than silently returning a caller-supplied value."""
    from dossier_pipeline.governance.semantic_adapter import SemanticEngineAdapter

    class BareEngine:
        def project(self, candidates):
            return None

    a = SemanticEngineAdapter(engine=BareEngine(), vertical_id="legal")
    with pytest.raises(ValueError, match="config_hash"):
        _ = a.config_hash
