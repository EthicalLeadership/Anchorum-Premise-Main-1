import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from unittest.mock import patch

from interface.cases.router import router, get_db, Base, Case
from interface.cases.keys import generate_case_key, Jurisdiction, MatterType

app = FastAPI()
app.include_router(router)

engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
TestingSessionLocal = sessionmaker(bind=engine)
Base.metadata.create_all(bind=engine)

def override_get_db():
    db = TestingSessionLocal()
    try: yield db
    finally: db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

def test_generate_key_format():
    key = generate_case_key(Jurisdiction.QC, MatterType.LAB)
    parts = key.split("-")
    assert len(parts) == 4
    assert parts[0] == "QC"
    assert parts[1] == "LAB"
    assert len(parts[2]) == 4 # Year
    assert len(parts[3]) == 8 # Secure suffix
    # Ensure no confusing characters (0, 1, O, I, L)
    assert not any(c in "01OIL" for c in parts[3])

def test_create_case_endpoint():
    response = client.post("/cases", json={
        "title": "Test Case",
        "jurisdiction": "QC",
        "matter_type": "LAB"
    })
    assert response.status_code == 200
    data = response.json()
    assert data["case_key"].startswith("QC-LAB-")
    assert data["title"] == "Test Case"

def test_collision_retry():
    # Force generate_case_key to return the SAME key twice, triggering IntegrityError
    # then let it succeed.
    keys = ["QC-LAB-2026-AAAAAAAA", "QC-LAB-2026-AAAAAAAA", "QC-LAB-2026-BBBBBBBB"]
    
    with patch("interface.cases.router.generate_case_key", side_effect=keys):
        # 1st request: succeeds
        r1 = client.post("/cases", json={"title": "First", "jurisdiction": "QC", "matter_type": "LAB"})
        assert r1.status_code == 200
        assert r1.json()["case_key"] == "QC-LAB-2026-AAAAAAAA"
        
        # 2nd request: hits collision, retries, succeeds
        r2 = client.post("/cases", json={"title": "Second", "jurisdiction": "QC", "matter_type": "LAB"})
        assert r2.status_code == 200
        assert r2.json()["case_key"] == "QC-LAB-2026-BBBBBBBB"

def test_collision_max_retries_exceeded():
    with patch("interface.cases.router.generate_case_key", return_value="QC-LAB-2026-CCCCCCCC"):
        client.post("/cases", json={"title": "First", "jurisdiction": "QC", "matter_type": "LAB"})
        
        # This one will collide 5 times and throw 500
        response = client.post("/cases", json={"title": "Second", "jurisdiction": "QC", "matter_type": "LAB"})
        assert response.status_code == 500
        assert "Failed to generate unique key" in response.json()["detail"]
