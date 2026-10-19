import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from interface.server import create_app
from interface.anchorum_api import _record_filed_date, EVENT_EVIDENCE_FILED_WITH_DATE
from dossier_pipeline.schema import Document, Case, AuditLog
from sqlalchemy import select

@pytest.fixture
def app_and_db(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as client:
        yield app, client

def test_record_filed_date_helper(app_and_db):
    app, _ = app_and_db
    with app.state.db_sessions() as session:
        case = Case(case_key="T1", title="T", jurisdiction="QC", created_at=datetime.now(timezone.utc))
        session.add(case)
        session.commit()
        
        doc = Document(
            case_id=case.id, document_key="E-1", filename="a.txt",
            content_hash="abc", created_at=datetime.now(timezone.utc),
            analysis_json=json.dumps({"metadata": {"date": "2024-01-12", "author": "Dr. X"}})
        )
        session.add(doc)
        session.commit()

        # 1. First call writes the row
        _record_filed_date(session, case.id, doc)
        session.commit()
        
        logs = session.scalars(select(AuditLog).where(AuditLog.action == EVENT_EVIDENCE_FILED_WITH_DATE)).all()
        assert len(logs) == 1
        details = json.loads(logs[0].details)
        assert details["date"] == "2024-01-12"
        assert details["author"] == "Dr. X"

        # 2. Second call deduplicates
        _record_filed_date(session, case.id, doc)
        session.commit()
        logs = session.scalars(select(AuditLog).where(AuditLog.action == EVENT_EVIDENCE_FILED_WITH_DATE)).all()
        assert len(logs) == 1, "Should deduplicate"

def test_timeline_surfaces_document_date(app_and_db):
    app, client = app_and_db
    client.post("/cases", json={
        "key": "T1", "title": "T", "jurisdiction": "QC",
        "matterType": "labour", "timezone": "UTC",
        "description": "", "memberIds": [],
    })
    
    # Bypass upload to isolate timeline logic
    with app.state.db_sessions() as session:
        case = session.scalar(select(Case).where(Case.case_key == "T1"))
        doc = Document(
            case_id=case.id, document_key="E-1", filename="a.txt",
            content_hash="abc", created_at=datetime.now(timezone.utc),
            analysis_json=json.dumps({"metadata": {"date": "2024-01-12"}})
        )
        session.add(doc)
        session.commit()
        _record_filed_date(session, case.id, doc)
        session.commit()

    r = client.get("/cases/T1/timeline")
    assert r.status_code == 200
    events = r.json()
    matching = [e for e in events if e["event"] == EVENT_EVIDENCE_FILED_WITH_DATE]
    assert len(matching) == 1
    ev = matching[0]
    assert ev["date"] == "2024-01-12"
    assert ev["precision"] == "day"
    assert ev["evidenceId"] == "E-1"

def test_timeline_skips_when_no_date(app_and_db):
    app, client = app_and_db
    client.post("/cases", json={
        "key": "T2", "title": "T", "jurisdiction": "QC",
        "matterType": "labour", "timezone": "UTC",
        "description": "", "memberIds": [],
    })
    
    with app.state.db_sessions() as session:
        case = session.scalar(select(Case).where(Case.case_key == "T2"))
        doc = Document(
            case_id=case.id, document_key="E-2", filename="a.txt",
            content_hash="abc", created_at=datetime.now(timezone.utc),
            analysis_json=json.dumps({"metadata": {}})
        )
        session.add(doc)
        session.commit()
        _record_filed_date(session, case.id, doc)
        session.commit()

    r = client.get("/cases/T2/timeline")
    events = r.json()
    matching = [e for e in events if e["event"] == EVENT_EVIDENCE_FILED_WITH_DATE]
    assert matching == []
