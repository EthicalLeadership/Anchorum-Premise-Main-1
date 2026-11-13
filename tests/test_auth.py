"""CR-10.6 — Unconditional authentication baseline."""
import pytest
from fastapi.testclient import TestClient
from interface.anchorum_api import create_app

@pytest.fixture
def app(tmp_path):
    return create_app(
        database_url=f"sqlite:///{tmp_path}/test.db",
        evidence_directory=str(tmp_path / "evidence"),
        local_api_mode=True,
    )

def test_rejects_invalid_host(app, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = TestClient(app)
    r = client.get("/board/1/actors", headers={"Host": "evil.com"})
    assert r.status_code == 400
    assert r.json()["error"] == "INVALID_HOST"

def test_rejects_invalid_origin_on_post(app, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = TestClient(app)
    r = client.post("/cases", headers={"Origin": "http://evil.com"})
    assert r.status_code == 403
    assert r.json()["error"] == "INVALID_ORIGIN"

def test_requires_api_key_on_api_routes(app, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = TestClient(app)
    r = client.get("/board/1/actors")
    assert r.status_code == 401
    assert r.json()["error"] == "UNAUTHORIZED"

def test_accepts_valid_api_key(app, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = TestClient(app)
    api_key = app.state.api_key
    r = client.get("/board/1/actors", headers={"x-anchorum-key": api_key})
    # Should pass auth (404/200/422 depending on case existence)
    assert r.status_code in (200, 404, 422)

def test_allows_browser_origin_on_post(app, monkeypatch):
    monkeypatch.delenv("PYTEST_CURRENT_TEST", raising=False)
    client = TestClient(app)
    # Allowed origin bypasses API key for CSRF-safety
    r = client.post("/cases", headers={"Origin": "http://localhost:5173"})
    assert r.status_code not in (401, 403)
