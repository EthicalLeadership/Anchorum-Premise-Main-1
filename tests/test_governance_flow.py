"""Governed decision flow tests."""
from types import SimpleNamespace
import pytest

from dossier_pipeline.governance.flow import (
    GovernedDecision,
    GovernedDecisionError,
    GovernedDecisionFlow,
)
from dossier_pipeline.registry.audit import AuditLog
from dossier_pipeline.registry.trace import TraceLog


CH = "a" * 64


class StubEngine:
    def __init__(self, hashes):
        self._hashes = list(hashes)
        self._i = 0
    def project(self, candidates):
        h = self._hashes[self._i % len(self._hashes)]
        self._i += 1
        return SimpleNamespace(
            semantic_hash=h,
            classification="canonical_projection",
            admissible=True,
            concept_id="LEGAL_EVIDENCE_INSUFFICIENT",
        )


class StubPolicy:
    def __init__(self, route="PASS"):
        self._route = route
        self.calls = []
    def decide(self, fields, *, now):
        self.calls.append((fields, now))
        return SimpleNamespace(
            route=self._route,
            reason="stub",
            severity="info",
            citation="",
            rule_id="test_rule",
            evaluated_at=now,
            fields_used=(),
            rule_errors=(),
        )


@pytest.fixture
def logs(tmp_path):
    return (
        AuditLog(tmp_path / "audit.jsonl"),
        TraceLog(tmp_path / "trace.jsonl"),
    )


def _flow(logs, *, engine=None, policy=None, config_hash=CH,
          vertical="legal", registry=None):
    audit, trace = logs
    kwargs = dict(
        engine=engine or StubEngine(["h1"]),
        policy=policy or StubPolicy(),
        audit=audit,
        trace=trace,
        vertical_id=vertical,
        config_hash=config_hash,
        registry=registry,
    )
    if registry is None:
        kwargs["allow_unregistered"] = True
    return GovernedDecisionFlow(**kwargs)


def test_happy_path_writes_audit_and_trace(logs):
    flow = _flow(logs)
    result = flow.decide([[1, 2, 3]], fields={}, now=1234567890)
    assert isinstance(result, GovernedDecision)
    assert result.vertical_id == "legal"
    assert result.config_hash == CH
    assert result.audit_seq == 0
    assert result.trace_id is not None

    audit, trace = logs
    entries = list(audit)
    assert len(entries) == 1
    assert entries[0].record["vertical_id"] == "legal"
    assert entries[0].record["projection_ids"] == ["h1"]
    assert entries[0].record["decision"]["route"] == "PASS"

    traces = list(trace)
    assert len(traces) == 1
    assert traces[0].audit_seq == 0
    assert traces[0].projection_ids == ("h1",)
    assert traces[0].trace_id == result.trace_id


def test_audit_chain_verifies_after_decide(logs):
    flow = _flow(logs)
    flow.decide([[1]], fields={}, now=1)
    flow.decide([[2]], fields={}, now=2)
    audit, _ = logs
    assert audit.verify_chain() == []


def test_multiple_candidate_sets_produce_multiple_projections(logs):
    flow = _flow(logs, engine=StubEngine(["h1", "h2", "h3"]))
    result = flow.decide([[1], [2], [3]], fields={}, now=1)
    assert len(result.projections) == 3

    audit, _ = logs
    entry = list(audit)[0]
    assert entry.record["projection_ids"] == ["h1", "h2", "h3"]


def test_empty_candidate_sets_rejected(logs):
    flow = _flow(logs)
    with pytest.raises(GovernedDecisionError):
        flow.decide([], fields={}, now=1)


def test_invalid_config_hash_rejected(logs):
    audit, trace = logs
    with pytest.raises(GovernedDecisionError):
        GovernedDecisionFlow(
            engine=StubEngine(["h"]),
            policy=StubPolicy(),
            audit=audit,
            trace=trace,
            vertical_id="legal",
            config_hash="not-a-hash",
        )


def test_empty_vertical_rejected(logs):
    audit, trace = logs
    with pytest.raises(GovernedDecisionError):
        GovernedDecisionFlow(
            engine=StubEngine(["h"]),
            policy=StubPolicy(),
            audit=audit,
            trace=trace,
            vertical_id="",
            config_hash=CH,
        )


def test_audit_failure_is_fail_closed(logs, monkeypatch):
    flow = _flow(logs)
    audit, _ = logs
    def boom(record):
        raise RuntimeError("disk full")
    monkeypatch.setattr(audit, "append", boom)
    with pytest.raises(GovernedDecisionError):
        flow.decide([[1]], fields={}, now=1)


def test_trace_failure_is_fail_open(logs, monkeypatch, capsys):
    flow = _flow(logs)
    _, trace = logs
    def boom(rec):
        raise RuntimeError("disk full")
    monkeypatch.setattr(trace, "append", boom)
    result = flow.decide([[1]], fields={}, now=1)
    assert result.audit_seq == 0
    assert result.trace_id is None
    captured = capsys.readouterr()
    assert "trace write failed" in captured.err


def test_registry_lookup_enforced_when_registry_provided(logs):
    class StubRegistry:
        def __init__(self, hashes):
            self._h = set(hashes)
        def get(self, ch):
            if ch not in self._h:
                raise KeyError(ch)
            return "fake-entry"

    reg = StubRegistry(["b" * 64])
    with pytest.raises(GovernedDecisionError):
        _flow(logs, registry=reg)  # CH = "aaa..." not in registry

    # correct hash passes
    audit, trace = logs
    flow = GovernedDecisionFlow(
        engine=StubEngine(["h1"]), policy=StubPolicy(),
        audit=audit, trace=trace,
        vertical_id="legal", config_hash="b" * 64, registry=reg,
    )
    result = flow.decide([[1]], fields={}, now=1)
    assert result.config_hash == "b" * 64


def test_policy_receives_fields_and_now(logs):
    policy = StubPolicy()
    flow = _flow(logs, policy=policy)
    flow.decide([[1]], fields={"x": 42}, now=99)
    assert policy.calls == [({"x": 42}, 99)]


def test_audit_record_contains_fields(logs):
    """G1: the audit entry must let an auditor reconstruct the decision."""
    flow = _flow(logs)
    flow.decide([[1]], fields={"x": 42, "y": "abc"}, now=1)
    audit, _ = logs
    entry = list(audit)[0]
    assert "fields" in entry.record, "audit record must contain input fields"
    assert entry.record["fields"] == {"x": 42, "y": "abc"}


def test_audit_record_contains_projections(logs):
    """G2: audit record must contain the full projection, not only its hash.

    The current record carries projection_ids (hash strings). Two different
    inputs that both fall back to the same state produce identical hashes;
    an auditor cannot distinguish them from the record alone.
    """
    flow = _flow(logs)
    flow.decide([[1]], fields={}, now=1)
    audit, _ = logs
    entry = list(audit)[0]

    assert "projections" in entry.record, "audit record must contain projections"
    assert len(entry.record["projections"]) == 1

    p0 = entry.record["projections"][0]
    assert p0["semantic_hash"] == "h1"
    assert p0["classification"] == "canonical_projection"
    assert p0["admissible"] is True
    assert p0["concept_id"] == "LEGAL_EVIDENCE_INSUFFICIENT"


def test_registry_revocation_between_construction_and_decide_rejected(logs):
    """G3: if config_hash is revoked after __init__ but before decide,
    the decision must be refused."""
    class RevokingRegistry:
        def __init__(self):
            self.revoked = False
        def get(self, ch):
            if self.revoked:
                raise KeyError(ch)
            return "entry"

    reg = RevokingRegistry()
    audit, trace = logs
    flow = GovernedDecisionFlow(
        engine=StubEngine(["h1"]), policy=StubPolicy(),
        audit=audit, trace=trace,
        vertical_id="legal", config_hash=CH, registry=reg,
    )
    reg.revoked = True
    with pytest.raises(GovernedDecisionError):
        flow.decide([[1]], fields={}, now=1)


def test_ungoverned_default_rejected(logs):
    """G4: GovernedDecisionFlow without a registry must refuse to decide.

    The current default is registry=None, which silently produces a
    governed-looking decision with no registry check at all. That is
    the wrong default for a component named 'Governed'."""
    audit, trace = logs
    with pytest.raises(GovernedDecisionError):
        GovernedDecisionFlow(
            engine=StubEngine(["h1"]), policy=StubPolicy(),
            audit=audit, trace=trace,
            vertical_id="legal", config_hash=CH,
            # registry deliberately omitted
        )


def test_policy_receives_immutable_fields(logs):
    """G5: the fields object handed to the policy must be immutable.

    Otherwise a buggy or malicious policy can mutate the caller's dict and
    retroactively change what the audit record shows."""
    seen = {}

    class CapturingPolicy:
        def decide(self, fields, *, now):
            seen["type"] = type(fields).__name__
            seen["frozen"] = not hasattr(fields, "__setitem__")
            return SimpleNamespace(
                route="PASS", reason="ok", severity="info",
                citation="", rule_id="t", evaluated_at=now,
                fields_used=(), rule_errors=(),
            )

    audit, trace = logs
    flow = GovernedDecisionFlow(
        engine=StubEngine(["h1"]), policy=CapturingPolicy(),
        audit=audit, trace=trace,
        vertical_id="legal", config_hash=CH,
        allow_unregistered=True,
    )
    flow.decide([[1]], fields={"x": 1}, now=1)
    assert seen.get("frozen"), f"fields is mutable: {seen}"


def test_audit_record_contains_evidence(logs):
    """Gap 2: audit record must carry evidence refs so a third party can
    verify the projection without re-running the engine."""
    from types import SimpleNamespace

    class EvidenceEngine:
        def project(self, candidates):
            return SimpleNamespace(
                semantic_hash="h1",
                classification="canonical_projection",
                admissible=True,
                concept_id="LEGAL_EVIDENCE_INSUFFICIENT",
                canonical_text="insufficient evidence",
                evidence=(
                    SimpleNamespace(
                        doc_hash="a" * 64, page=1,
                        span_start=10, span_end=32,
                    ),
                ),
            )

    flow = _flow(logs, engine=EvidenceEngine())
    flow.decide([[1]], fields={}, now=1)
    audit, _ = logs
    entry = list(audit)[0]

    p0 = entry.record["projections"][0]
    assert "evidence" in p0, "audit record must carry evidence refs"
    assert len(p0["evidence"]) == 1
    assert p0["evidence"][0]["doc_hash"] == "a" * 64
    assert p0["evidence"][0]["span_start"] == 10
