"""Search hits must carry the character offset of the match.

Without position, an excerpt from a 40-page document tells a reader what
matched but not where. The offset is the same `match.start()` that builds
the excerpt — throwing it away costs the caller a second pass to recover.
"""
import pytest
from fastapi.testclient import TestClient

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
            "key": "SRCH-1", "title": "search offset test",
            "jurisdiction": "QC", "matterType": "labour",
            "timezone": "UTC", "description": "", "memberIds": [],
        })
        content = (
            b"The quick brown fox jumps over the lazy Murray dog.\n"
            b"Another line mentions Murray again."
        )
        c.post("/cases/SRCH-1/evidence",
               files={"file": ("note.txt", content, "text/plain")})
        yield c


def test_search_hit_carries_offset_pointing_at_the_match(client):
    r = client.get("/cases/SRCH-1/search?q=Murray")
    assert r.status_code == 200, r.text
    hits = r.json()
    assert len(hits) == 2, hits
    for hit in hits:
        assert "offset" in hit, hit
        assert isinstance(hit["offset"], int), hit
    for hit in hits:
        text_r = client.get(f"/evidence/{hit['id']}/text")
        assert text_r.status_code == 200, text_r.text
        text = text_r.json()["text"]
        start = hit["offset"]
        assert text[start:start + 6].lower() == "murray", (
            f"offset {start} does not point at 'Murray': "
            f"{text[start:start + 6]!r}"
        )
