"""Search hits must say *where* the match is, not only what it says.

An excerpt alone is not actionable: a phrase found somewhere in a forty-page
exhibit leaves the reader scrolling, and "open the document" then means
"search for it again by eye". `offset` and `line` are what let the viewer land
on the match, so they are part of the contract and are pinned here.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interface.anchorum_api import create_app

LETTER = (
    "Medical Note\n"
    "Patient: A. Tremblay\n"
    "Lumbar disc herniation at L4-L5 confirmed by MRI.\n"
    "Recommended rest period: six weeks.\n"
)


@pytest.fixture()
def client(tmp_path):
    app = create_app(
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "evidence",
    )
    with TestClient(app) as test_client:
        test_client.post(
            "/cases",
            json={
                "key": "C-1",
                "title": "Matter",
                "jurisdiction": "qc",
                "matterType": "labour",
                "timezone": "America/Toronto",
            },
        )
        test_client.post(
            "/cases/C-1/evidence",
            files={"file": ("letter.txt", LETTER.encode(), "text/plain")},
        )
        yield test_client


def search(client: TestClient, query: str) -> list[dict]:
    response = client.get("/cases/C-1/search", params={"q": query})
    assert response.status_code == 200, response.text
    return response.json()


def test_hit_reports_the_line_the_match_is_on(client: TestClient):
    hits = search(client, "L4-L5")
    assert len(hits) == 1
    # Third line of the letter, 1-based.
    assert hits[0]["line"] == 3


def test_hit_offset_points_at_the_match(client: TestClient):
    hits = search(client, "six weeks")
    assert len(hits) == 1
    offset = hits[0]["offset"]
    assert LETTER[offset : offset + len("six weeks")] == "six weeks"


def test_line_and_offset_agree(client: TestClient):
    """The two must describe the same position; a disagreement would send the
    viewer to the right line of the wrong document."""
    hits = search(client, "herniation")
    hit = hits[0]
    assert hit["offset"] == LETTER.index("herniation")
    assert hit["line"] == LETTER[: hit["offset"]].count("\n") + 1


def test_a_first_line_match_is_line_one(client: TestClient):
    hits = search(client, "Medical")
    assert hits[0]["line"] == 1
    assert hits[0]["offset"] == 0


def test_multiple_matches_each_carry_their_own_line(client: TestClient):
    # "e" appears on every line; the cap is 50 and the lines must differ
    # across the first few hits rather than all reporting line 1.
    hits = search(client, "e")
    lines = {hit["line"] for hit in hits if hit["id"]}
    assert len(lines) > 1
    assert min(lines) == 1
