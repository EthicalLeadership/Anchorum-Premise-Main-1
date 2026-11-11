import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from interface.collect.email_threads.router import router, get_db
from interface.collect.email_threads.db import Base
from interface.collect.email_threads.ingest import EmailMessage

SIMPLE_EMAIL = b"""From: alice@example.com
To: bob@example.com
Subject: Test Upload
Date: Mon, 23 Oct 2023 10:00:00 +0000
Message-ID: <test-upload-1@example.com>
Content-Type: text/plain

Hello world.
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
        "/intake/case-123/email",
        files={"file": ("test.eml", SIMPLE_EMAIL, "message/rfc822")}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["messages_ingested"] >= 1
    assert "document_id" in data

def test_upload_invalid_extension():
    response = client.post(
        "/intake/case-123/email",
        files={"file": ("test.txt", b"not an email", "text/plain")}
    )
    assert response.status_code == 400
    assert "Only .eml or .msg" in response.json()["detail"]
