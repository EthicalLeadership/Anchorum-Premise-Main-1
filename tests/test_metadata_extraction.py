import pytest
from interface.classifier import extract_metadata
from interface.analysis import analyse
from interface.server import create_app
from fastapi.testclient import TestClient
import tempfile
from pathlib import Path

def test_extract_iso_date():
    assert extract_metadata("Date: 2023-11-05")["date"] == "2023-11-05"

def test_extract_numeric_date():
    # DD/MM/YYYY
    assert extract_metadata("Date: 05/11/2023")["date"] == "2023-11-05"
    # DD-MM-YY (should expand to 20YY)
    assert extract_metadata("Date: 05-11-23")["date"] == "2023-11-05"

def test_extract_text_date_french():
    assert extract_metadata("Le 12 janvier 2024")["date"] == "2024-01-12"
    assert extract_metadata("le 1er fevrier 2024")["date"] == "2024-02-01"

def test_extract_text_date_english():
    assert extract_metadata("January 15, 2024")["date"] is None # Current regex expects day month year
    assert extract_metadata("15 January 2024")["date"] == "2024-01-15"

def test_extract_author():
    assert extract_metadata("Dr. Jean Dupont")["author"] == "Jean Dupont"
    assert extract_metadata("Docteur Marie Curie")["author"] == "Marie Curie"
    assert extract_metadata("Me. Pierre Trudeau")["author"] == "Pierre Trudeau"

def test_extract_issuer():
    # These three previously asserted the fragment rather than the
    # organisation: "Montreal", "General", "Superieure". That was the defect,
    # not the contract — an issuer of "Montreal" names a city and loses which
    # institution issued the document, and the value is rendered in the
    # timeline and used by author search.
    assert extract_metadata("Clinique Montreal")["issuer"] == "Clinique Montreal"
    assert extract_metadata("Hopital General de Montreal")["issuer"] == "Hopital General de Montreal"
    assert extract_metadata("Cour Superieure")["issuer"] == "Cour Superieure"

def test_extract_metadata_empty():
    assert extract_metadata("") == {"date": None, "author": None, "issuer": None}
    assert extract_metadata("No dates or names here.") == {"date": None, "author": None, "issuer": None}

def test_analyse_integration():
    text = "Le 12 janvier 2024, Dr. Jean Dupont de la Clinique Montreal."
    record = analyse(text.encode("utf-8"), "note.txt")
    assert record["metadata"]["date"] == "2024-01-12"
    assert record["metadata"]["author"] == "Jean Dupont"
    assert record["metadata"]["issuer"] == "Clinique Montreal"

def test_api_exposes_metadata():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "api.db"
    ev_path = Path(tmp) / "evidence"
    ev_path.mkdir()
    app = create_app(f"sqlite:///{db_path}", local_api_mode=True, evidence_directory=ev_path)
    
    with TestClient(app) as client:
        client.post("/cases", json={"key": "M1", "title": "Meta", "jurisdiction": "QC", "matterType": "labour", "timezone": "UTC", "description": "", "memberIds": []})
        
        text = "Payroll 2023-11-05. Dr. Jean Dupont. Clinique Montreal."
        resp = client.post("/cases/M1/evidence", files={"file": ("meta.txt", text.encode(), "text/plain")})
        assert resp.status_code == 201, resp.text
        body = resp.json()
        assert body["analysis"]["metadata"]["date"] == "2023-11-05"
        assert body["analysis"]["metadata"]["author"] == "Jean Dupont"
        assert body["analysis"]["metadata"]["issuer"] == "Clinique Montreal"
        
        # Check list endpoint
        list_resp = client.get("/cases/M1/evidence")
        items = list_resp.json()
        assert items[0]["analysis"]["metadata"]["date"] == "2023-11-05"
