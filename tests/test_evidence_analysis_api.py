"""Pins for the routes that make a read artifact visible to a reader.

Three surfaces are covered here, each because it previously reported something
that was not true:

* the analysis route: before this, the artifact could be stored and read by
  nobody, and the only analysis surface was the whole pipeline's answer;
* the evidence item: ``received`` was the only status it could ever have, and
  a failed analysis was rendered as ``done`` by the UI mapping;
* custody: an ``uploaded`` entry with no statement about chain verification
  left a reader unable to tell whether the chain had been checked (it has not,
  and the entry now says so).

The routes are also pinned to stay in step with each other: the item's compact
analysis block and the analysis route serve the same record.
"""

import hashlib

from tests.test_interface_api import app_for, multipart_file, request

#: Deliberately non-legal prose: the assertion is about the routes, not about
#: what the lexicon happens to match.
NOTE = (
    b"Angel v. Murray file note. The delivery route was discussed with Murray "
    b"and the schedule was left unchanged by everyone present."
)

UNSUPPORTED = b"PK\x03\x04 this is not a Word document the connector can read"


def _case(app, key="CASE-ANALYSIS-001"):
    created = request(
        app,
        "POST",
        "/cases",
        {
            "key": key,
            "title": "Analysis test",
            "jurisdiction": "RI",
            "matterType": "contracts",
            "timezone": "America/Toronto",
            "description": "",
            "memberIds": [],
        },
    )
    assert created.status_code == 201
    return created.json()["id"]


def _without_timestamp(record):
    trimmed = dict(record)
    trimmed.pop("analysedAt", None)
    return trimmed


def _upload(app, case_id, content=NOTE, filename="note.txt", content_type="text/plain"):
    body, boundary = multipart_file(filename, content, content_type=content_type)
    response = request(
        app,
        "POST",
        f"/cases/{case_id}/evidence",
        raw_body=body,
        content_type=boundary,
    )
    assert response.status_code == 201, response.body
    return response.json()


def test_analysis_route_serves_the_record_for_the_stored_artifact(tmp_path):
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app)
    evidence = _upload(app, case_id)

    response = request(app, "GET", f"/evidence/{evidence['id']}/analysis")
    assert response.status_code == 200
    record = response.json()

    assert record["source"]["sha256"] == hashlib.sha256(NOTE).hexdigest()
    assert record["source"]["sha256"] == evidence["hash"]
    assert record["status"] == "processed"
    assert record["scopes"], "a processed artifact must report its scopes"
    assert record["projection"]["engineVersion"]
    assert record["projection"]["lexiconHash"]


def test_analysis_route_reports_what_it_could_not_read(tmp_path):
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-ANALYSIS-UNSUPPORTED")
    evidence = _upload(
        app,
        case_id,
        content=UNSUPPORTED,
        filename="manifest.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )

    record = request(app, "GET", f"/evidence/{evidence['id']}/analysis").json()
    assert record["status"] == "unsupported"
    assert record["reason"], "an unread artifact must carry the reason it was refused"
    assert record["scopes"] == []


def test_analysis_route_is_idempotent_and_reasks_on_demand(tmp_path):
    """Re-analysis must not require re-uploading evidence, which breaks custody."""
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-ANALYSIS-REPEAT")
    evidence = _upload(app, case_id)

    first = request(app, "POST", f"/evidence/{evidence['id']}/analyse")
    assert first.status_code == 200
    second = request(app, "POST", f"/evidence/{evidence['id']}/analyse")
    assert second.status_code == 200
    # The outcome must be identical. `analysedAt` records when the analysis last
    # ran, so it is expected to advance; everything else is the same answer.
    assert _without_timestamp(first.json()) == _without_timestamp(second.json())

    custody = request(app, "GET", f"/evidence/{evidence['id']}/custody").json()
    assert [entry["action"] for entry in custody].count("analysed") == 3
    assert request(app, "GET", f"/cases/{case_id}/evidence").json()[0][
        "duplicateCandidate"
    ] is False


def test_evidence_item_agrees_with_the_analysis_route(tmp_path):
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-ITEM-AGREEMENT")
    evidence = _upload(app, case_id)

    item = request(app, "GET", f"/evidence/{evidence['id']}").json()
    record = request(app, "GET", f"/evidence/{evidence['id']}/analysis").json()

    assert item["status"] == "processed"
    assert item["badges"] == ["received", "processed"]
    assert item["analysis"]["status"] == record["status"]
    assert item["analysis"]["scopesTotal"] == record["coverage"]["scopesTotal"]
    assert item["analysis"]["scopesMatched"] == record["coverage"]["scopesMatched"]
    assert item["analysis"]["analysedAt"] is not None


def test_custody_states_whether_the_chain_was_verified(tmp_path):
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-CUSTODY-DETAIL")
    evidence = _upload(app, case_id)

    custody = request(app, "GET", f"/evidence/{evidence['id']}/custody").json()
    assert [entry["action"] for entry in custody] == ["uploaded", "analysed"]
    for entry in custody:
        # This host has no control plane. `linked` would claim a check that
        # never happened, so the entry must say what was actually done.
        assert entry["chain"] == "not_checked"
        assert "no control chain" in entry["chainDetail"].lower()


def test_search_returns_excerpts_for_the_stored_text(tmp_path):
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-SEARCH-001")
    evidence = _upload(app, case_id)

    response = request(app, "GET", f"/cases/{case_id}/search?q=Murray")
    assert response.status_code == 200
    found = response.json()
    assert found, "the stored text must be searchable"
    # A bare array of hits is the existing contract; the method travels in a
    # header rather than being smuggled into the body.
    assert isinstance(found, list)
    assert {hit["id"] for hit in found} == {evidence["id"]}
    for hit in found:
        assert hit["excerpt"]


def test_search_reports_the_matching_method_in_a_header(tmp_path):
    """The body is a bare array, so the method has to travel in a header.

    Substring matching is not token matching, and a reader comparing hits with
    another implementation needs to know which one produced them.
    """
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-SEARCH-METHOD")
    _upload(app, case_id)

    response = request(app, "GET", f"/cases/{case_id}/search?q=Murray")
    assert response.status_code == 200
    assert response.headers["x-anchorum-search-method"] == "substring"

    empty = request(app, "GET", f"/cases/{case_id}/search?q=zzzznotpresent")
    assert empty.status_code == 200
    assert empty.json() == []
    assert empty.headers["x-anchorum-search-method"] == "substring"


def test_timeline_is_an_allowlist_of_events(tmp_path):
    app = app_for(tmp_path / "api.db", evidence_directory=tmp_path / "evidence")
    case_id = _case(app, key="CASE-TIMELINE-001")
    _upload(app, case_id)

    response = request(app, "GET", f"/cases/{case_id}/timeline")
    assert response.status_code == 200
    events = response.json()
    kinds = [event["event"] for event in events]

    assert "case_created" in kinds
    assert "evidence_uploaded" in kinds
    assert "evidence_analysed" in kinds
    for event in events:
        assert event["event"] in {
            "case_created",
            "evidence_uploaded",
            "evidence_verified",
            "evidence_analysed",
        }
        assert event["precision"] in {"exact", "range", "approximate", "unknown"}
        assert event["people"] == ["system"]
