import pytest
from datetime import datetime
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from interface.collect.email_threads.db import Base, get_db, EmailMessage
from interface.board.router import board_router

def _make_msg(case_id, from_addr, to_addr, sent_at, derivation="HEADER", mid=None):
    import json, uuid
    return EmailMessage(
        id=str(uuid.uuid4()),
        case_id=case_id,
        document_id="doc",
        message_id_raw=mid or f"<{uuid.uuid4()}@x>",
        thread_id=None,
        in_reply_to=None,
        references="[]",
        sent_at_raw=None,
        sent_at=sent_at,
        from_raw=json.dumps([["", from_addr]]),
        to_raw=json.dumps([["", to_addr]]),
        cc_raw="[]",
        subject="test",
        body_text="",
        derivation=derivation,
        content_hash=None,
        trust_headers="[]",
    )

@pytest.fixture
def client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)

    app = FastAPI()
    app.include_router(board_router)

    def override_get_db():
        db = SessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    return TestClient(app), SessionLocal

def test_actors_empty_case(client):
    test_client, _ = client
    r = test_client.get("/board/no-case/actors")
    assert r.status_code == 200
    data = r.json()
    assert data["total_messages"] == 0
    assert data["unique_actors"] == 0
    assert data["edges"] == []

def test_actors_single_message(client):
    test_client, Session = client
    db = Session()
    db.add(_make_msg("c1", "alice@x.com", "bob@x.com", datetime(2023, 1, 1, 10, 0)))
    db.commit(); db.close()

    r = test_client.get("/board/c1/actors")
    data = r.json()
    assert data["total_messages"] == 1
    assert data["unique_actors"] == 2
    assert len(data["edges"]) == 1
    e = data["edges"][0]
    assert e["from_address"] == "alice@x.com"
    assert e["to_address"] == "bob@x.com"
    assert e["count"] == 1
    assert e["first_contact"] is not None

def test_actors_multiple_messages_aggregate(client):
    test_client, Session = client
    db = Session()
    for i in range(3):
        db.add(_make_msg("c1", "alice@x.com", "bob@x.com", datetime(2023, 1, i + 1)))
    db.commit(); db.close()

    r = test_client.get("/board/c1/actors")
    data = r.json()
    assert len(data["edges"]) == 1
    assert data["edges"][0]["count"] == 3

def test_actors_direction_is_directional(client):
    test_client, Session = client
    db = Session()
    db.add(_make_msg("c1", "alice@x.com", "bob@x.com", datetime(2023, 1, 1, 10, 0)))
    db.add(_make_msg("c1", "bob@x.com", "alice@x.com", datetime(2023, 1, 1, 11, 0)))
    db.commit(); db.close()

    r = test_client.get("/board/c1/actors")
    data = r.json()
    assert len(data["edges"]) == 2
    pairs = {(e["from_address"], e["to_address"]) for e in data["edges"]}
    assert ("alice@x.com", "bob@x.com") in pairs
    assert ("bob@x.com", "alice@x.com") in pairs

def test_actors_quoted_rows_excluded(client):
    test_client, Session = client
    db = Session()
    db.add(_make_msg("c-quote", "alice@x.com", "bob@x.com",
                     datetime(2023, 1, 1), derivation="QUOTED"))
    db.commit(); db.close()

    r = test_client.get("/board/c-quote/actors")
    data = r.json()
    assert data["total_messages"] == 0
    assert data["edges"] == []

def test_actors_case_scoped(client):
    test_client, Session = client
    db = Session()
    db.add(_make_msg("case-a", "alice@x.com", "bob@x.com", datetime(2023, 1, 1)))
    db.commit(); db.close()

    r = test_client.get("/board/case-b/actors")
    data = r.json()
    assert data["total_messages"] == 0
    assert data["edges"] == []

def test_chronology_sorting_and_undated(client):
    test_client, Session = client
    db = Session()
    db.add(_make_msg("c-chron", "a@x.com", "b@x.com", datetime(2023, 1, 1, 10, 0)))
    db.add(_make_msg("c-chron", "b@x.com", "a@x.com", datetime(2023, 1, 5, 10, 0)))
    undated_msg = _make_msg("c-chron", "c@x.com", "d@x.com", None)
    undated_msg.sent_at_raw = "Unknown Date"
    db.add(undated_msg)
    db.commit(); db.close()

    r = test_client.get("/board/c-chron/chronology")
    data = r.json()
    assert data["total_dated"] == 2
    assert data["total_undated"] == 1
    assert data["truncated"] is False
    assert data["dated_entries"][0]["from_address"] == "a@x.com"
    assert data["undated_tray"][0]["from_address"] == "c@x.com"

def test_chronology_truncation_flag(client):
    test_client, Session = client
    db = Session()
    for i in range(2001):
        db.add(_make_msg("c-bulk", "a@x.com", "b@x.com", datetime(2023, 1, 1)))
    db.commit(); db.close()

    r = test_client.get("/board/c-bulk/chronology")
    data = r.json()
    assert data["truncated"] is True
    assert data["total_dated"] == 2000
