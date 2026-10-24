"""Wire 6 — /export?format=pdf returns a real PDF report.

The PDF is a human-readable companion to the ZIP, not a replacement. The
tests pin the observable contract: magic bytes, MIME type, filename, and
that the report's content actually carries case data. Text extraction via
interface.pdf_text is used where byte-level assertions can't see content.
"""
import pytest
from fastapi.testclient import TestClient

from interface.pdf_text import extract_text
from interface.server import create_app


@pytest.fixture
def client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        c.post("/cases", json={
            "key": "PDF1", "title": "PDF report test",
            "jurisdiction": "QC", "matterType": "labour",
            "timezone": "UTC", "description": "", "memberIds": [],
        })
        c.post("/cases/PDF1/evidence",
               files={"file": ("exhibit-a.txt", b"exhibit content", "text/plain")})
        c.post("/cases/PDF1/stamp", json={"approved_by": "Me. Tremblay"})
        yield c


def test_default_export_is_zip(client):
    r = client.post("/cases/PDF1/export")
    assert r.status_code == 200
    assert r.content[:4] == b"PK\x03\x04"


def test_explicit_zip_is_zip(client):
    r = client.post("/cases/PDF1/export?format=zip")
    assert r.status_code == 200
    assert r.content[:4] == b"PK\x03\x04"


def test_pdf_format_returns_pdf_magic(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    assert r.status_code == 200
    assert r.content[:4] == b"%PDF"


def test_pdf_content_type(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    assert r.headers.get("content-type", "").startswith("application/pdf")


def test_pdf_filename(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    disp = r.headers.get("content-disposition", "")
    assert 'filename="case_PDF1_report.pdf"' in disp
    assert "attachment" in disp


def test_pdf_is_not_a_zip(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    assert r.content[:4] != b"PK\x03\x04"


def test_pdf_contains_case_key(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    text = extract_text(r.content)
    assert "PDF1" in text


def test_pdf_contains_evidence_filename(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    text = extract_text(r.content)
    assert "exhibit-a.txt" in text


def test_pdf_contains_preflight_section(client):
    r = client.post("/cases/PDF1/export?format=pdf")
    text = extract_text(r.content)
    assert "Pre-flight" in text


def test_invalid_format_returns_422(client):
    r = client.post("/cases/PDF1/export?format=docx")
    assert r.status_code == 422
    assert r.json().get("error") == "INVALID_FORMAT"
