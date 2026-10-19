import asyncio
import hashlib
import json
from dataclasses import dataclass
from urllib.parse import urlsplit

from sqlalchemy import create_engine, inspect, select

from dossier_pipeline.schema import AuditLog, Case, Document, init_schema
from interface.server import create_app


@dataclass
class Response:
    status_code: int
    body: bytes
    #: Lower-cased response headers. Some contracts travel in a header rather
    #: than the body (the search route reports its matching method this way,
    #: because its body is a bare array of hits).
    headers: dict | None = None

    def json(self):
        return json.loads(self.body)


def request(
    app,
    method,
    url,
    body=None,
    *,
    raw_body=None,
    content_type=None,
):
    parsed = urlsplit(url)
    body_bytes = (
        raw_body
        if raw_body is not None
        else b"" if body is None else json.dumps(body).encode()
    )
    headers = [(b"host", b"testserver")]
    request_content_type = content_type or (
        "application/json" if body is not None else None
    )
    if request_content_type is not None:
        headers.append((b"content-type", request_content_type.encode()))

    async def send_request():
        sent_request = False
        messages = []

        async def receive():
            nonlocal sent_request
            if sent_request:
                return {"type": "http.disconnect"}
            sent_request = True
            return {"type": "http.request", "body": body_bytes, "more_body": False}

        async def send(message):
            messages.append(message)

        scope = {
            "type": "http",
            "asgi": {"version": "3.0", "spec_version": "2.3"},
            "http_version": "1.1",
            "method": method,
            "scheme": "http",
            "path": parsed.path,
            "raw_path": parsed.path.encode(),
            "query_string": parsed.query.encode(),
            "root_path": "",
            "headers": headers,
            "client": ("testclient", 50000),
            "server": ("testserver", 80),
        }
        async with app.router.lifespan_context(app):
            await app(scope, receive, send)
        start = next(message for message in messages if message["type"] == "http.response.start")
        response_body = b"".join(
            message.get("body", b"")
            for message in messages
            if message["type"] == "http.response.body"
        )
        response_headers = {
            key.decode().lower(): value.decode(errors="replace")
            for key, value in start.get("headers", [])
        }
        return Response(start["status"], response_body, response_headers)

    return asyncio.run(send_request())


def app_for(path, *, local_api_mode=True, evidence_directory=None):
    return create_app(
        f"sqlite:///{path}",
        local_api_mode=local_api_mode,
        evidence_directory=evidence_directory,
    )


def multipart_file(filename, content, *, content_type="text/plain", extra_fields=None):
    """A one-file multipart body, optionally with additional text parts.

    `extra_fields` exists for the optional form fields on the evidence upload
    (`category`, `source`). Their values are sent as plain text parts, which is
    what `Form(None)` on the route reads.
    """
    boundary = "anchorum-test-boundary"
    parts = [
        (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: {content_type}\r\n\r\n"
        ).encode()
        + content
        + b"\r\n"
    ]
    for name, value in (extra_fields or {}).items():
        parts.append(
            (
                f"--{boundary}\r\n"
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'
                f"{value}\r\n"
            ).encode()
        )
    parts.append(f"--{boundary}--\r\n".encode())
    return b"".join(parts), f"multipart/form-data; boundary={boundary}"


def test_health_and_local_session(tmp_path):
    app = app_for(tmp_path / "api.db")
    assert request(app, "GET", "/health").json() == {"status": "ok"}
    response = request(app, "GET", "/session")
    assert response.status_code == 200
    assert response.json() == {"name": "Local developer", "role": "case_admin"}


def test_existing_sqlite_documents_get_local_storage_metadata_columns(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY,
                case_key VARCHAR(128) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL,
                jurisdiction VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                case_id INTEGER NOT NULL,
                document_key VARCHAR(128) NOT NULL UNIQUE,
                filename VARCHAR(255) NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )

    init_schema(engine)
    columns = {
        column["name"]
        for column in inspect(engine).get_columns("documents")
    }
    assert {"storage_key", "media_type", "byte_size"} <= columns
    engine.dispose()


def test_case_list_create_get_and_key_lookup(tmp_path):
    app = app_for(tmp_path / "api.db")
    created = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CASE-LOCAL-001",
            "title": "Local test case",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "America/Montreal",
            "description": "Local-only test data",
            "memberIds": [],
        },
    )
    assert created.status_code == 201
    case_ref = created.json()
    assert case_ref["key"] == "CASE-LOCAL-001"

    by_id = request(app, "GET", f"/cases/{case_ref['id']}")
    assert by_id.status_code == 200
    assert by_id.json() == {
        "id": case_ref["id"],
        "key": "CASE-LOCAL-001",
        "title": "Local test case",
        "jurisdiction": "QC",
        "timezone": "America/Montreal",
        "status": "open",
        "holdCount": 0,
        "integrityStatus": "unknown",
    }
    assert request(app, "GET", "/cases/CASE-LOCAL-001").json() == by_id.json()

    rows = request(app, "GET", "/cases").json()
    assert rows == [
        {
            "id": case_ref["id"],
            "key": "CASE-LOCAL-001",
            "title": "Local test case",
            "status": "open",
            "ownerId": "local-operator",
            "evidenceCount": 0,
            "holdCount": 0,
            "lastActivity": rows[0]["lastActivity"],
            "timezone": "America/Montreal",
        }
    ]


def test_duplicate_case_key_returns_named_conflict(tmp_path):
    app = app_for(tmp_path / "api.db")
    payload = {
        "key": "CASE-DUP",
        "title": "Duplicate",
        "jurisdiction": "QC",
        "matterType": "labour",
        "timezone": "America/Montreal",
        "description": "",
        "memberIds": [],
    }
    assert request(app, "POST", "/cases", payload).status_code == 201
    response = request(app, "POST", "/cases", payload)
    assert response.status_code == 409
    assert response.json()["error"] == "CASE_KEY_TAKEN"


def test_local_evidence_upload_list_custody_and_hash_verification(tmp_path):
    evidence_directory = tmp_path / "evidence"
    app = app_for(
        tmp_path / "api.db",
        evidence_directory=evidence_directory,
    )
    case = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CASE-EVIDENCE-001",
            "title": "Evidence test",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "America/Montreal",
            "description": "",
            "memberIds": [],
        },
    ).json()
    content = b"local evidence bytes"
    body, content_type = multipart_file("original.txt", content)

    uploaded = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert uploaded.status_code == 201
    evidence = uploaded.json()
    assert evidence["hash"] == hashlib.sha256(content).hexdigest()
    assert evidence["duplicate"] is False
    # The upload response reports what actually happened to the artifact rather
    # than a constant. `stored` only means the bytes landed; the analysis pass
    # then runs, so the value here is the extraction outcome, and an artifact
    # whose extraction did not succeed reports that instead of looking fine.
    assert evidence["processingStatus"] == "extracted"

    listed = request(app, "GET", f"/cases/{case['id']}/evidence")
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    item = items[0]
    assert item["id"] == evidence["id"]
    assert item["name"] == "original.txt"
    # `received` is the entry status; it advances once the analysis pass has run,
    # and both are reported so a reader never sees only a stale status.
    assert item["status"] == "processed"
    assert item["badges"] == ["received", "processed"]
    assert item["quarantinedReason"] is None
    assert item["holdReason"] is None
    assert item["duplicateCandidate"] is False
    # The item carries the same compact analysis view the analysis route serves.
    assert item["analysis"]["status"] == "processed"
    assert item["analysis"]["scopesTotal"] == 1
    assert item["analysis"]["scopesMatched"] == 0
    assert item["analysis"]["analysedAt"] is not None
    assert request(app, "GET", f"/evidence/{evidence['id']}").json() == item
    downloaded = request(app, "GET", f"/evidence/{evidence['id']}/download")
    assert downloaded.status_code == 200
    assert downloaded.body == content
    custody = request(app, "GET", f"/evidence/{evidence['id']}/custody").json()
    # Two entries: the bytes were accepted, and the analysis pass then ran on
    # them. The analysis is a custody event in its own right, otherwise the
    # record would show an artifact that was never read.
    assert [entry["action"] for entry in custody] == ["uploaded", "analysed"]
    assert all(entry["chain"] == "not_checked" for entry in custody)

    verification = request(app, "POST", f"/evidence/{evidence['id']}/verify")
    assert verification.status_code == 200
    assert verification.json()["result"] == "pass"
    assert verification.json()["steps"] == [{"id": "hash", "result": "pass"}]
    assert request(app, "GET", "/cases").json()[0]["evidenceCount"] == 1

    with app.state.db_sessions() as db:
        document = db.scalar(
            select(Document).where(Document.document_key == evidence["id"])
        )
        assert document is not None
        stored_file = evidence_directory / f"{document.storage_key}.bin"
    assert stored_file.read_bytes() == content

    stored_file.write_bytes(b"altered evidence bytes")
    failed = request(app, "POST", f"/evidence/{evidence['id']}/verify")
    assert failed.status_code == 200
    assert failed.json()["result"] == "fail"
    assert failed.json()["failingStep"] == "hash_mismatch_at_readback"


def test_local_evidence_duplicate_is_reported_without_mislabeling_pipeline(tmp_path):
    app = app_for(
        tmp_path / "api.db",
        evidence_directory=tmp_path / "evidence",
    )
    case = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CASE-DUP-EVIDENCE",
            "title": "Evidence duplicate test",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "America/Montreal",
            "description": "",
            "memberIds": [],
        },
    ).json()
    body, content_type = multipart_file("copy.txt", b"same original")

    first = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    second = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True
    # A duplicate is still analysed (it is its own row), so the status reflects
    # the extraction outcome. The `duplicate` flag above carries the dedup
    # signal; the status field is not asked to mean two things at once.
    assert second.json()["processingStatus"] == "extracted"
    rows = request(app, "GET", f"/cases/{case['id']}/evidence").json()
    assert all(row["duplicateCandidate"] for row in rows)


def test_api_requires_explicit_local_test_mode(tmp_path):
    app = app_for(tmp_path / "api.db", local_api_mode=False)
    response = request(app, "GET", "/cases")
    assert response.status_code == 503
    assert response.json()["error"] == "LOCAL_API_MODE_DISABLED"


def test_unimplemented_product_routes_fail_explicitly(tmp_path):
    app = app_for(tmp_path / "api.db")
    case = request(
        app,
        "POST",
        "/cases",
        {
            "key": "CASE-UNAVAILABLE",
            "title": "Local test case",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "America/Montreal",
            "description": "",
            "memberIds": [],
        },
    ).json()
    case_id = case["id"]
    body, ct = multipart_file("a.txt", b"hello")
    upload = request(
        app, "POST", f"/cases/{case_id}/evidence", raw_body=body, content_type=ct,
    ).json()
    evidence_id = upload["id"]

    # The only intentional stub left is Saul: it should fail closed with 501.
    response = request(app, "POST", f"/evidence/{evidence_id}/consult")
    assert response.status_code == 501
    assert response.json()["error"] == "FEATURE_UNAVAILABLE"

def test_upload_appends_to_existing_case(tmp_path):
    app = app_for(tmp_path / "api.db")
    request(app, "GET", "/health")

    with app.state.db_sessions() as session:
        session.add(
            Case(case_key="TEST-001", title="Test case", jurisdiction="QC")
        )
        session.commit()

    body, content_type = multipart_file("note.txt", b"hello\n")
    upload = request(
        app,
        "POST",
        "/cases/TEST-001/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert upload.status_code == 201, upload.body
    created = upload.json()
    assert created["id"].startswith("E-")

    listed = request(app, "GET", "/cases/TEST-001/evidence")
    assert listed.status_code == 200
    rows = listed.json()
    assert len(rows) == 1
    assert rows[0]["id"] == created["id"]


def test_delete_removes_evidence_and_bytes(tmp_path):
    evidence_root = tmp_path / "evidence"
    app = app_for(tmp_path / "api.db", evidence_directory=evidence_root)
    request(app, "GET", "/health")

    with app.state.db_sessions() as session:
        session.add(
            Case(case_key="TEST-002", title="Delete case", jurisdiction="QC")
        )
        session.commit()

    body, content_type = multipart_file("gone.txt", b"goodbye\n")
    upload = request(
        app,
        "POST",
        "/cases/TEST-002/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert upload.status_code == 201, upload.body
    evidence_id = upload.json()["id"]

    assert len(list(evidence_root.glob("*.bin"))) == 1

    deleted = request(app, "DELETE", f"/evidence/{evidence_id}")
    assert deleted.status_code == 200, deleted.body

    listed = request(app, "GET", "/cases/TEST-002/evidence")
    assert listed.status_code == 200
    assert listed.json() == []

    with app.state.db_sessions() as session:
        from dossier_pipeline.schema import Document as _Doc
        assert session.query(_Doc).count() == 0

    assert list(evidence_root.glob("*.bin")) == []
    assert list(evidence_root.glob("*.txt")) == []
def test_init_schema_adds_category_and_source_to_a_legacy_documents_table(tmp_path):
    """The migration is the `document_additions` loop, so prove it runs.

    A legacy table is built by hand without either column, a row is inserted,
    and `init_schema` is then expected to add both while leaving the row intact
    with NULL values.
    """
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-intake.db'}")
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE cases (
                id INTEGER PRIMARY KEY,
                case_key VARCHAR(128) NOT NULL UNIQUE,
                title VARCHAR(255) NOT NULL,
                jurisdiction VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                case_id INTEGER NOT NULL,
                document_key VARCHAR(128) NOT NULL UNIQUE,
                filename VARCHAR(255) NOT NULL,
                content_hash VARCHAR(64) NOT NULL,
                created_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            "INSERT INTO documents "
            "(id, case_id, document_key, filename, content_hash, created_at) "
            "VALUES (1, 1, 'E-legacy', 'old.txt', 'deadbeef', '2026-01-01 00:00:00')"
        )

    init_schema(engine)
    columns = {column["name"] for column in inspect(engine).get_columns("documents")}
    assert {"category", "source"} <= columns

    with engine.connect() as connection:
        row = connection.exec_driver_sql(
            "SELECT category, source FROM documents WHERE id = 1"
        ).fetchone()
    # The migration adds columns; it does not invent values for existing rows.
    assert row == (None, None)

    # Running it again must be a no-op rather than a second ALTER TABLE.
    init_schema(engine)
    assert {column["name"] for column in inspect(engine).get_columns("documents")} == columns
    engine.dispose()


def _case_with_evidence_directory(tmp_path, key="CASE-INTAKE"):
    evidence_directory = tmp_path / "evidence"
    app = app_for(tmp_path / "api.db", evidence_directory=evidence_directory)
    case = request(
        app,
        "POST",
        "/cases",
        {
            "key": key,
            "title": "Intake metadata",
            "jurisdiction": "QC",
            "matterType": "labour",
            "timezone": "America/Montreal",
            "description": "",
            "memberIds": [],
        },
    ).json()
    return app, case, evidence_directory


def test_upload_stores_category_and_source(tmp_path):
    app, case, _ = _case_with_evidence_directory(tmp_path, "CASE-CATEGORY")
    body, content_type = multipart_file(
        "clinic-note.pdf",
        b"clinic note body",
        extra_fields={"category": "medical", "source": "clinic"},
    )
    uploaded = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert uploaded.status_code == 201, uploaded.body
    payload = uploaded.json()
    assert payload["category"] == "medical"
    assert payload["source"] == "clinic"

    # `_evidence_item` backs both routes, so both must report the same values.
    for path in (
        f"/cases/{case['id']}/evidence",
        f"/evidence/{payload['id']}",
    ):
        response = request(app, "GET", path)
        assert response.status_code == 200
        item = response.json()
        if isinstance(item, list):
            item = item[0]
        assert item["category"] == "medical"
        assert item["source"] == "clinic"


def test_upload_without_category_or_source_store_null(tmp_path):
    app, case, _ = _case_with_evidence_directory(tmp_path, "CASE-NO-METADATA")
    body, content_type = multipart_file("plain.txt", b"plain body")
    uploaded = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert uploaded.status_code == 201, uploaded.body
    payload = uploaded.json()
    assert payload["category"] is None
    assert payload["source"] is None

    item = request(app, "GET", f"/cases/{case['id']}/evidence").json()[0]
    assert item["category"] is None
    assert item["source"] is None


def test_upload_treats_empty_and_whitespace_values_as_unset(tmp_path):
    app, case, _ = _case_with_evidence_directory(tmp_path, "CASE-BLANK-METADATA")
    body, content_type = multipart_file(
        "blank.txt",
        b"blank metadata",
        extra_fields={"category": "   ", "source": ""},
    )
    uploaded = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert uploaded.status_code == 201, uploaded.body
    # A blank part means "no answer", which is NULL rather than an empty string.
    assert uploaded.json()["category"] is None
    assert uploaded.json()["source"] is None


def test_upload_trims_surrounding_whitespace(tmp_path):
    app, case, _ = _case_with_evidence_directory(tmp_path, "CASE-TRIM-METADATA")
    body, content_type = multipart_file(
        "trim.txt",
        b"trim metadata",
        extra_fields={"category": "  payroll  ", "source": " employer "},
    )
    uploaded = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert uploaded.status_code == 201, uploaded.body
    assert uploaded.json()["category"] == "payroll"
    assert uploaded.json()["source"] == "employer"


def test_upload_rejects_a_category_outside_the_allowlist(tmp_path):
    app, case, evidence_directory = _case_with_evidence_directory(tmp_path, "CASE-BAD-CATEGORY")
    body, content_type = multipart_file(
        "bad.txt",
        b"bad category body",
        extra_fields={"category": "taxes"},
    )
    rejected = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"] == "INVALID_CATEGORY"

    # Rejected before any bytes reached their final path, and before a row existed.
    assert list(evidence_directory.glob("*.bin")) == []
    assert list(evidence_directory.glob(".upload-*")) == []
    with app.state.db_sessions() as session:
        assert session.query(Document).count() == 0
        assert [row.action for row in session.query(AuditLog).all()] == [
            "evidence_upload_rejected"
        ]


def test_upload_rejects_a_source_outside_the_allowlist(tmp_path):
    app, case, evidence_directory = _case_with_evidence_directory(tmp_path, "CASE-BAD-SOURCE")
    body, content_type = multipart_file(
        "bad.txt",
        b"bad source body",
        extra_fields={"source": "neighbour"},
    )
    rejected = request(
        app,
        "POST",
        f"/cases/{case['id']}/evidence",
        raw_body=body,
        content_type=content_type,
    )
    assert rejected.status_code == 422
    assert rejected.json()["error"] == "INVALID_SOURCE"
    assert list(evidence_directory.glob("*.bin")) == []
