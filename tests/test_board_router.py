import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from interface.collect.email_threads.db import Base, get_db
from interface.collect.email_threads.ingest import ingest
from interface.board.router import board_router

QUOTED_EMAIL = b"""From: bob@example.com
To: alice@example.com
Subject: Re: Contract

Yes, I agree.

From: Alice <alice@example.com>
Sent: Monday, October 23, 2023 10:00 AM
To: Bob
Subject: Re: Contract

Are we still on for the meeting?
"""

PLAIN_EMAIL = b"""From: alice@example.com
To: bob@example.com
Subject: Hello
Date: Mon, 23 Oct 2023 10:00:00 +0000
Message-ID: <plain@example.com>
Content-Type: text/plain

Just a note.
"""

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

def test_gaps_empty_case(client):
    test_client, _ = client
    r = test_client.get("/board/no-such-case/gaps")
    assert r.status_code == 200
    data = r.json()
    assert data["case_id"] == "no-such-case"
    assert data["total"] == 0
    assert data["gaps"] == []

def test_gaps_after_quoted_ingest(client):
    test_client, Session = client
    db = Session()
    ingest("case-with-quote", "doc-1", QUOTED_EMAIL, db)
    db.close()

    r = test_client.get("/board/case-with-quote/gaps")
    assert r.status_code == 200
    data = r.json()
    assert data["total"] == 1
    gap = data["gaps"][0]
    assert gap["status"] == "REFERENCED"
    assert "Missing original email" in gap["description"]
    assert gap["referenced_in_message_id"] is not None
    assert gap["created_at"] is not None

def test_gaps_plain_ingest_creates_no_gap(client):
    test_client, Session = client
    db = Session()
    ingest("case-plain-only", "doc-2", PLAIN_EMAIL, db)
    db.close()

    r = test_client.get("/board/case-plain-only/gaps")
    assert r.status_code == 200
    assert r.json()["total"] == 0

def test_gaps_are_case_scoped(client):
    test_client, Session = client
    db = Session()
    ingest("case-iso-a", "doc-a", QUOTED_EMAIL, db)
    db.close()

    r = test_client.get("/board/case-iso-b/gaps")
    assert r.status_code == 200
    assert r.json()["total"] == 0
