import pytest
from interface.findings import evaluate_findings


def _parse_time(ts: str):
    """Helper to parse ISO timestamps."""
    if ts.endswith("Z"):
        ts = ts[:-1] + "+00:00"
    from datetime import datetime, timezone
    return datetime.fromisoformat(ts)


def test_empty_messages_returns_empty():
    """Rule 2: Empty messages list returns empty results."""
    assert evaluate_findings([]) == []


def test_late_reply_triggers():
    """Rule 1: Reply after deadline triggers finding."""
    m1 = {
        "id": "msg-1",
        "timestamp": "2026-01-01T10:00:00Z",
        "needs_reply": True,
        "from_actor": "alice@example.com",
        "to_actor": "bob@example.com",
    }
    m2 = {
        "id": "msg-2",
        "timestamp": "2026-01-10T10:00:00Z",  # 9 days later
        "from_actor": "bob@example.com",
        "to_actor": "alice@example.com",
    }
    messages = [m1, m2]
    findings = evaluate_findings(messages, reply_deadline_days=5)
    assert len(findings) == 1
    assert findings[0]["title"] == "Late reply"


def test_unanswered_triggers():
    """Rule 1: No reply by as_of triggers finding."""
    m1 = {
        "id": "msg-1",
        "timestamp": "2026-01-01T10:00:00Z",
        "needs_reply": True,
        "from_actor": "alice@example.com",
        "to_actor": "bob@example.com",
    }
    messages = [m1]
    findings = evaluate_findings(
        messages, reply_deadline_days=5, as_of="2026-01-15T00:00:00Z"
    )
    assert len(findings) == 1
    assert findings[0]["title"] == "Still unanswered"


def test_promise_no_followup_triggers():
    """Rule 2: Promise without follow-up triggers finding."""
    m1 = {
        "id": "msg-1",
        "timestamp": "2026-01-01T10:00:00Z",
        "from_actor": "alice@example.com",
        "to_actor": "bob@example.com",
        "body": "I will email you tomorrow",
    }
    messages = [m1]
    findings = evaluate_findings(
        messages, followup_deadline_days=3, as_of="2026-01-10T00:00:00Z"
    )
    assert len(findings) == 1
    assert findings[0]["rule"] == "Rule 2 (promised follow-up)"


def test_promise_with_followup_does_not_trigger():
    """Rule 2: Promise with timely follow-up does not trigger."""
    m1 = {
        "id": "msg-1",
        "timestamp": "2026-01-01T10:00:00Z",
        "from_actor": "alice@example.com",
        "to_actor": "bob@example.com",
        "body": "I will email you tomorrow",
    }
    m2 = {
        "id": "msg-2",
        "timestamp": "2026-01-02T10:00:00Z",  # Day 2, within 3-day deadline
        "from_actor": "alice@example.com",
        "to_actor": "bob@example.com",
        "channel": "email",
    }
    messages = [m1, m2]
    findings = evaluate_findings(
        messages, followup_deadline_days=3, as_of="2026-01-10T00:00:00Z"
    )
    assert findings == []
