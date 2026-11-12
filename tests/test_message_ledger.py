"""Pins for the CR-1 ledger tables: Message, Finding, Decision.

- source_hash must be 64 chars (CheckConstraint + NOT NULL).
- both clocks recorded; timestamp_captured NOT NULL, timestamp_occurred nullable.
- FK chain Message -> Finding -> Decision is intact.
"""
import hashlib
from datetime import datetime, timezone

import pytest
from sqlalchemy import event
from sqlalchemy.exc import IntegrityError

from dossier_pipeline.schema import (
    Base, Case, Decision, Finding, Message, create_engine_and_session,
)


@pytest.fixture
def session():
    engine, session_factory = create_engine_and_session("sqlite:///:memory:")

    @event.listens_for(engine, "connect")
    def _fk_on(dbapi_conn, _):
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()

    Base.metadata.create_all(bind=engine)
    sess = session_factory()
    try:
        yield sess
    finally:
        sess.close()


def _make_case(sess, key="TEST-CASE-001"):
    case = Case(case_key=key, title="Test Case", jurisdiction="QC", matter_type="labour")
    sess.add(case); sess.commit()
    return case


def _hash(payload="test email body"):
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_message_without_source_hash_is_rejected(session):
    case = _make_case(session)
    session.add(Message(
        case_id=case.id, message_key="m-no-hash",
        timestamp_captured=datetime.now(timezone.utc),
        source_hash="", source_filename="x.eml",
        source_locator_json="{}", message_type="email",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_message_with_source_hash_is_accepted(session):
    case = _make_case(session, key="TEST-CASE-002")
    h = _hash()
    msg = Message(
        case_id=case.id, message_key="m-valid",
        timestamp_occurred=datetime(2026, 5, 1, 9, 0, tzinfo=timezone.utc),
        timestamp_captured=datetime.now(timezone.utc),
        source_hash=h, source_filename="x.eml",
        source_locator_json="{}", message_type="email", body_text="Hello",
    )
    session.add(msg); session.commit()
    assert msg.id is not None
    assert msg.source_hash == h
    assert msg.timestamp_occurred is not None
    assert msg.timestamp_captured is not None


def test_finding_requires_existing_message(session):
    session.add(Finding(
        message_id=99999, finding_key="f-orphan", category="reply",
        description="x", analyzed_at=datetime.now(timezone.utc),
        analysis_version="v1", status="candidate",
    ))
    with pytest.raises(IntegrityError):
        session.commit()
    session.rollback()


def test_finding_and_decision_chain(session):
    case = _make_case(session, key="TEST-CASE-003")
    msg = Message(
        case_id=case.id, message_key="m1",
        timestamp_captured=datetime.now(timezone.utc),
        source_hash=_hash(), source_filename="x.eml",
        source_locator_json="{}", message_type="email",
    )
    session.add(msg); session.commit()

    finding = Finding(
        message_id=msg.id, finding_key="f1", category="reply",
        description="unanswered", analyzed_at=datetime.now(timezone.utc),
        analysis_version="v1", status="candidate",
    )
    session.add(finding); session.commit()
    assert finding.id is not None

    decision = Decision(
        finding_id=finding.id, decision_key="d1", decided_by="reviewer",
        decided_at=datetime.now(timezone.utc), decision_version="v1",
        reasoning="confirmed", outcome="affirmed", status="affirmed",
    )
    session.add(decision); session.commit()
    assert decision.id is not None
