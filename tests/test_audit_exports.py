import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from interface.server import create_app


def _app(tmp_path):
    return create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )


def _new_case(client, key="A1"):
    return client.post(
        "/cases",
        json={
            "key": key, "title": "T", "jurisdiction": "QC",
            "matterType": "labour", "timezone": "UTC",
            "description": "", "memberIds": [],
        },
    )


def test_audit_returns_upload_and_analysis_events(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        _new_case(client, "AU1")
        up = client.post(
            "/cases/AU1/evidence",
            files={"file": ("a.txt", b"hello world", "text/plain")},
        )
        assert up.status_code == 201
        evidence_id = up.json()["id"]

        r = client.get("/cases/AU1/audit")
        assert r.status_code == 200, r.text
        rows = r.json()

        events = [row["event"] for row in rows]
        assert "evidence_uploaded" in events
        assert "evidence_analysed" in events

        uploaded = next(row for row in rows if row["event"] == "evidence_uploaded")
        assert uploaded["evidenceId"] == evidence_id
        assert uploaded["chain"] == "not_checked"
        assert uploaded["actor"] == "system"


def test_audit_is_ordered_ascending(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        _new_case(client, "AU2")
        for name in ["a.txt", "b.txt", "c.txt"]:
            client.post(
                "/cases/AU2/evidence",
                files={"file": (name, b"x", "text/plain")},
            )
        rows = client.get("/cases/AU2/audit").json()
        assert len(rows) >= 6
        ids = [int(row["id"].split("-")[1]) for row in rows]
        assert ids == sorted(ids)


def test_export_preview_blocked_when_no_evidence(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        _new_case(client, "EX1")
        r = client.post("/cases/EX1/exports/preview?type=evidence_index")
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["type"] == "evidence_index"
        assert body["blocked"] is True
        gate_ids = {g["id"]: g for g in body["gates"]}
        assert gate_ids["barreau"]["result"] == "fail"
        assert gate_ids["disclaimer"]["result"] == "pass"


def test_export_preview_passes_with_clean_evidence(tmp_path):
    app = _app(tmp_path)
    with TestClient(app) as client:
        _new_case(client, "EX2")
        client.post(
            "/cases/EX2/evidence",
            files={"file": ("clean.txt", b"hello", "text/plain")},
        )
        r = client.post("/cases/EX2/exports/preview?type=evidence_index")
        assert r.status_code == 200
        body = r.json()
        assert body["blocked"] is False
        assert all(g["result"] == "pass" for g in body["gates"])
