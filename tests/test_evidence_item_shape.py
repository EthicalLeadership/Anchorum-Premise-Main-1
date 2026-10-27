"""What an evidence item tells a reader about the artifact itself.

The viewer prints the artifact's digest next to the HMAC of the custody row that
recorded it. The digest is the number a reader checks the file they were handed
against, so an item that omits it leaves the one field they can act on blank.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from interface.server import create_app

BODY = b"the grievor was suspended on 12 January 2024"


@pytest.fixture
def client(tmp_path):
    app = create_app(
        f"sqlite:///{tmp_path / 'api.db'}",
        local_api_mode=True,
        evidence_directory=tmp_path / "ev",
    )
    with TestClient(app) as c:
        created = c.post(
            "/cases",
            json={
                "key": "SHAPE-1",
                "title": "Shape",
                "jurisdiction": "QC",
                "matterType": "labour",
                "timezone": "UTC",
                "description": "",
                "memberIds": [],
            },
        )
        assert created.status_code == 201, created.text
        yield c


def test_item_carries_the_digest_of_the_stored_bytes(client):
    upload = client.post(
        "/cases/SHAPE-1/evidence",
        files={"file": ("exhibit.txt", BODY, "text/plain")},
    )
    assert upload.status_code == 201, upload.text
    uploaded = upload.json()

    item = client.get(f"/evidence/{uploaded['id']}").json()

    # The same value under every name it travels by: the upload reports it as
    # both `hash` and `sourceSha256`, the item reports it as `sha256`, and the
    # pipeline stores it as `source_sha256`. All of them must agree or a reader
    # comparing them is comparing nothing.
    assert item["sha256"] == uploaded["hash"] == uploaded["sourceSha256"]
    assert len(item["sha256"]) == 64


def test_every_item_in_the_register_carries_its_digest(client):
    client.post(
        "/cases/SHAPE-1/evidence",
        files={"file": ("first.txt", b"first", "text/plain")},
    )
    client.post(
        "/cases/SHAPE-1/evidence",
        files={"file": ("second.txt", b"second", "text/plain")},
    )

    items = client.get("/cases/SHAPE-1/evidence").json()

    assert len(items) == 2
    for item in items:
        assert len(item["sha256"]) == 64, item
    # Different bytes, different digests: a register that repeated one value
    # would let a reader believe two exhibits were the same file.
    assert items[0]["sha256"] != items[1]["sha256"]
