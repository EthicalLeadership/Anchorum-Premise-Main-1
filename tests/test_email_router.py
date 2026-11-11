import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from interface.collect.email_threads.router import router, get_db
from interface.collect.email_threads.db import Base, ExpectedSource
from interface.collect.email_threads.ingest import EmailMessage

SIMPLE_EMAIL = b"""From: alice@example.com
To: bob@example.com
Subject: Test Upload
Date: Mon, 23 Oct 2023 10:00:00 +0000
Message-ID: <test-upload-1@example.com>
Content-Type: text/plain

Hello world.
"""

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

app = FastAPI()
app.include_router(router)

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    try:
        db = TestingSessionLocal()
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_upload_email():
    response = client.post(
        "/intake/case-a/email",
        files={"file": ("test.eml", SIMPLE_EMAIL, "message/rfc822")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["messages_ingested"] >= 1
    assert "document_id" in data

def test_upload_invalid_extension():
    response = client.post(
        "/intake/case-b/email",
        files={"file": ("test.txt", b"not an email", "text/plain")}
    )
    assert response.status_code == 400
    assert "Only .eml or .msg" in response.json()["detail"]

def test_upload_creates_gap_for_quoted():
    response = client.post(
        "/intake/case-quoted/email",
        files={"file": ("test_quote.eml", QUOTED_EMAIL, "message/rfc822")}
    )
    assert response.status_code == 200

    db = TestingSessionLocal()
    gaps = db.query(ExpectedSource).filter(ExpectedSource.case_id == "case-quoted").all()
    assert len(gaps) == 1, f"Expected 1 gap for QUOTED row, found {len(gaps)}"
    assert gaps[0].status == "REFERENCED"
    assert "Missing original email" in gaps[0].description
    assert "Alice" in gaps[0].description or "alice" in gaps[0].description
    db.close()

def test_upload_plain_email_creates_no_gap():
    """Plain emails with no quotes should not create gaps."""
    response = client.post(
        "/intake/case-clean/email",
        files={"file": ("clean.eml", SIMPLE_EMAIL, "message/rfc822")}
    )
    assert response.status_code == 200

    db = TestingSessionLocal()
    gaps = db.query(ExpectedSource).filter(ExpectedSource.case_id == "case-clean").all()
    assert len(gaps) == 0, f"Plain email created {len(gaps)} unexpected gaps"
    db.close()
