"""Local/test HTTP API for the Anchorum Prem Main shell."""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from fastapi import Depends, FastAPI, File, HTTPException, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import make_url

from dossier_pipeline.schema import AuditLog, Case, Document, init_schema
from interface import analysis as analysis_service

ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = Path(__file__).resolve().parent
DIST_ROOT = INTERFACE_ROOT / "dist"

#: The one guard for everything the API writes beside a stored artifact. The
#: storage key is a uuid4 hex digest; a name that does not match it never
#: reaches the filesystem.
STORAGE_KEY_PATTERN = re.compile(r"[0-9a-f]{32}")

#: Search bounds. Hits are capped and each excerpt is a fixed window, so a
#: query cannot pull a whole document back through the API.
SEARCH_HIT_LIMIT = 50
SEARCH_CONTEXT_CHARS = 80
#: Substring matching: case-insensitive `in` over the extracted text. Reported
#: in a response header because it is not the same as token matching.
SEARCH_METHOD_SUBSTRING = "substring"

#: `documents.extract_status` (what analysis did) mapped to the evidence status
#: the interface shows. `stored` is the pre-analysis state and keeps the
#: existing `received` label, so nothing that reads the old value breaks.
EVIDENCE_STATUS = {
    "stored": "received",
    "extracted": "processed",
    "unsupported": "unsupported",
    "empty": "empty",
    "skipped_oversize": "skipped_oversize",
    "failed": "failed",
}

#: `documents.extract_status` mapped to the analysis-status vocabulary the
#: analysis route reports. An item that has not been analysed is `pending`
#: rather than a fabricated result.
ANALYSIS_STATUS = {
    "stored": "pending",
    "extracted": "processed",
    "unsupported": "unsupported",
    "empty": "empty",
    "skipped_oversize": "skipped_oversize",
    "failed": "failed",
}

#: The audit actions the timeline surfaces and the event name each becomes. An
#: allowlist rather than a passthrough, so a new audit action does not show up
#: in the timeline until someone decides what it means to a reader.
TIMELINE_EVENTS = {
    "evidence_verified": "evidence_verified",
    "evidence_analysed": "evidence_analysed",
}

#: This API slice has no control plane, so no chain is ever walked here. The
#: value stays `not_checked` and the detail says why; `linked` would claim a
#: check that did not happen.
CUSTODY_CHAIN = "not_checked"
CUSTODY_CHAIN_DETAIL = (
    "No control chain exists on this host: this entry is the local audit row. "
    "The tamper-evident chain lives in the dossier pipeline's own store."
)

#: Audit actions that appear in an evidence item's custody list, and the word
#: the interface shows for each.
CUSTODY_ACTIONS = {
    "evidence_uploaded": "uploaded",
    "evidence_verified": "verified",
    "evidence_analysed": "analysed",
}


class CaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    key: str = Field(min_length=1, max_length=128)
    title: str = Field(min_length=1, max_length=255)
    jurisdiction: str = Field(min_length=1, max_length=64)
    matter_type: str = Field(alias="matterType", min_length=1, max_length=64)
    timezone: str = Field(min_length=1, max_length=128)
    description: str = ""
    member_ids: list[str] = Field(default_factory=list, alias="memberIds")

    @field_validator("key", "title", "jurisdiction", "matter_type", "timezone")
    @classmethod
    def require_non_blank(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("Field must not be blank")
        return normalized


class CaseCreated(BaseModel):
    id: str
    key: str


class SessionResponse(BaseModel):
    name: str
    role: Literal["case_admin", "reviewer", "auditor"]


def _local_mode_enabled() -> bool:
    return os.getenv("ANCHORUM_LOCAL_API_MODE", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }


def _local_database_url() -> str:
    configured = os.getenv("ANCHORUM_DATABASE_URL")
    if configured:
        return configured
    default_path = ROOT / "output" / "anchorum-local.db"
    return f"sqlite:///{default_path}"


def _local_evidence_directory() -> Path:
    configured = os.getenv("ANCHORUM_EVIDENCE_DIRECTORY")
    if configured:
        return Path(configured).expanduser().resolve()
    return ROOT / "output" / "evidence"


def _local_api_guard(enabled: bool) -> None:
    if not enabled:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "error": "LOCAL_API_MODE_DISABLED",
                "message": (
                    "Set ANCHORUM_LOCAL_API_MODE=1 to enable the single-user "
                    "local/test API. This API is not production-ready."
                ),
            },
        )


def _not_implemented(feature: str, detail: str) -> None:
    raise HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail={"error": "FEATURE_UNAVAILABLE", "feature": feature, "message": detail},
    )


def _case_id(case: Case) -> str:
    return str(case.id)


def _datetime_text(value) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.isoformat()


def _case_row(db: Session, case: Case) -> dict:
    evidence_count = db.scalar(
        select(func.count(Document.id)).where(Document.case_id == case.id)
    )
    return {
        "id": _case_id(case),
        "key": case.case_key,
        "title": case.title,
        "status": case.status,
        "ownerId": case.owner_user_id,
        "evidenceCount": int(evidence_count or 0),
        "holdCount": 0,
        "lastActivity": _datetime_text(case.created_at),
        "timezone": case.timezone,
    }


def _case_summary(case: Case) -> dict:
    return {
        "id": _case_id(case),
        "key": case.case_key,
        "title": case.title,
        "jurisdiction": case.jurisdiction,
        "timezone": case.timezone,
        "status": case.status,
        "holdCount": 0,
        "integrityStatus": "unknown",
    }


def _decoded_analysis(document: Document) -> dict | None:
    """The stored analysis record, or None when the item has not been analysed.

    A record that cannot be decoded is treated as absent rather than raising: a
    corrupt row must not take the whole evidence list down with it.
    """
    if not document.analysis_json:
        return None
    try:
        record = json.loads(document.analysis_json)
    except (TypeError, ValueError):
        return None
    return record if isinstance(record, dict) else None


def _analysis_summary(document: Document) -> dict | None:
    """The compact analysis view carried on every evidence item."""
    record = _decoded_analysis(document)
    if record is None:
        return None
    coverage = record.get("coverage") or {}
    return {
        "status": record.get("status", ""),
        "scopesTotal": coverage.get("scopesTotal", 0),
        "scopesMatched": coverage.get("scopesMatched", 0),
        "warning": coverage.get("warning"),
        "analysedAt": (
            _datetime_text(document.analysed_at) if document.analysed_at else None
        ),
    }


def _evidence_item(db: Session, document: Document) -> dict:
    duplicate_count = db.scalar(
        select(func.count(Document.id)).where(
            Document.case_id == document.case_id,
            Document.content_hash == document.content_hash,
        )
    )
    status = EVIDENCE_STATUS.get(document.extract_status or "stored", "received")
    badges = ["received"] if status == "received" else ["received", status]
    return {
        "id": document.document_key,
        "name": document.filename,
        "status": status,
        "badges": badges,
        "analysis": _analysis_summary(document),
        "quarantinedReason": None,
        "holdReason": None,
        "duplicateCandidate": int(duplicate_count or 0) > 1,
    }


def _custody_log(
    db: Session,
    *,
    case_id: int,
    evidence_id: str,
    action: str,
) -> None:
    db.add(
        AuditLog(
            case_id=case_id,
            actor_username="system",
            action=action,
            details=json.dumps({"evidenceId": evidence_id}, separators=(",", ":")),
        )
    )


def create_app(
    database_url: str | None = None,
    *,
    local_api_mode: bool | None = None,
    evidence_directory: str | Path | None = None,
) -> FastAPI:
    """Build the local/test app; API operations are disabled unless opted in."""
    enabled = _local_mode_enabled() if local_api_mode is None else local_api_mode
    url = database_url or _local_database_url()
    storage_root = (
        Path(evidence_directory).expanduser().resolve()
        if evidence_directory
        else _local_evidence_directory()
    )
    if not url.startswith("sqlite:"):
        raise ValueError("The initial Anchorum API slice supports SQLite only")

    engine = create_engine(
        url,
        connect_args={"check_same_thread": False},
        future=True,
    )
    db_sessions = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        database_name = make_url(url).database
        if database_name and database_name != ":memory:":
            Path(database_name).expanduser().resolve().parent.mkdir(
                parents=True,
                exist_ok=True,
            )
        init_schema(engine)
        yield
        engine.dispose()

    app = FastAPI(
        title="Anchorum Prem Main API",
        version="0.1.0",
        description=(
            "Local/test API slice. Case CRUD, local evidence storage, and a "
            "local session are implemented; other product operations return "
            "FEATURE_UNAVAILABLE."
        ),
        lifespan=lifespan,
    )
    app.state.local_api_mode = enabled
    app.state.database_engine = engine
    app.state.db_sessions = db_sessions
    app.state.evidence_directory = storage_root

    if enabled:
        origins = [
            item.strip()
            for item in os.getenv(
                "ANCHORUM_LOCAL_CORS_ORIGINS",
                "http://localhost:5173,http://127.0.0.1:5173",
            ).split(",")
            if item.strip()
        ]
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "PATCH"],
            allow_headers=["Content-Type"],
        )

    def require_local_api() -> None:
        _local_api_guard(app.state.local_api_mode)

    def get_db():
        session = db_sessions()
        try:
            yield session
        finally:
            session.close()

    local_api = Depends(require_local_api)
    @app.exception_handler(HTTPException)
    async def http_error_handler(_, exc: HTTPException):
        detail = exc.detail
        if isinstance(detail, dict) and isinstance(detail.get("error"), str):
            return JSONResponse(status_code=exc.status_code, content=detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": "HTTP_ERROR", "message": str(detail)},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(_, exc: RequestValidationError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=jsonable_encoder(
                {"error": "INVALID_REQUEST", "detail": exc.errors()}
            ),
        )

    @app.get("/health")
    def health() -> dict[str, str]:
        with engine.connect() as connection:
            connection.exec_driver_sql("SELECT 1")
        return {"status": "ok"}

    if (DIST_ROOT / "assets").is_dir():
        app.mount(
            "/assets",
            StaticFiles(directory=DIST_ROOT / "assets", check_dir=False),
            name="assets",
        )

    @app.get("/")
    def product_shell():
        index = DIST_ROOT / "index.html"
        if index.is_file():
            return FileResponse(index)
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "error": "FRONTEND_BUILD_MISSING",
                "message": "Build the React app in interface/ before serving the product shell.",
            },
        )

    @app.get("/session", response_model=SessionResponse, dependencies=[local_api])
    def get_local_session() -> SessionResponse:
        role = os.getenv("ANCHORUM_LOCAL_ROLE", "case_admin")
        if role not in {"case_admin", "reviewer", "auditor"}:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "INVALID_LOCAL_ROLE", "message": "Invalid local role configuration."},
            )
        return SessionResponse(
            name=os.getenv("ANCHORUM_LOCAL_USER_NAME", "Local developer"),
            # `role` was just checked against exactly these three values.
            role=cast('Literal["case_admin", "reviewer", "auditor"]', role),
        )

    @app.get("/cases", dependencies=[local_api])
    def list_cases(db: Session = Depends(get_db)) -> list[dict]:
        cases = db.scalars(select(Case).order_by(Case.created_at.desc(), Case.id.desc()))
        return [_case_row(db, case) for case in cases]

    @app.post(
        "/cases",
        response_model=CaseCreated,
        status_code=status.HTTP_201_CREATED,
        dependencies=[local_api],
    )
    def create_case(
        payload: CaseCreate,
        db: Session = Depends(get_db),
    ) -> CaseCreated:
        if payload.member_ids:
            _not_implemented(
                "case_membership",
                "Case assignments are not supported by the local SQLite schema.",
            )
        case = Case(
            case_key=payload.key.strip(),
            title=payload.title.strip(),
            jurisdiction=payload.jurisdiction,
            matter_type=payload.matter_type,
            timezone=payload.timezone,
            description=payload.description,
            status="open",
            owner_user_id=os.getenv("ANCHORUM_LOCAL_USER_ID", "local-operator"),
        )
        db.add(case)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"error": "CASE_KEY_TAKEN", "message": "The case key is already in use."},
            ) from None
        db.refresh(case)
        return CaseCreated(id=_case_id(case), key=case.case_key)

    def find_case(db: Session, identifier: str) -> Case:
        case = db.scalar(select(Case).where(Case.case_key == identifier))
        if case is None and identifier.isdecimal():
            case = db.get(Case, int(identifier))
        if case is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Case not found."},
            )
        return case

    def stored_path(document: Document, suffix: str) -> Path | None:
        """Resolve a stored file for a document, or None if it is not safe to.

        One guard for both the original (`<key>.bin`) and the derived text
        sidecar (`<key>.txt`): the key must be a uuid4 hex digest and the
        resolved path must still be inside the evidence directory.
        """
        key = document.storage_key or ""
        if not STORAGE_KEY_PATTERN.fullmatch(key):
            return None
        path = (storage_root / f"{key}{suffix}").resolve()
        return path if path.parent == storage_root else None

    def stored_evidence_path(document: Document) -> Path | None:
        return stored_path(document, ".bin")

    def stored_text_path(document: Document) -> Path | None:
        return stored_path(document, ".txt")

    def run_analysis(document: Document) -> str:
        """Analyse a stored artifact and persist the outcome on its row.

        Tier 1 only: extraction, segmentation and projection need no signing
        material. The extracted text goes to a sidecar file next to the stored
        bytes, never into the database and never into the analysis record, so
        the record that travels and exports carries no case content.

        Returns the `documents.extract_status` value. Never raises for a
        document-level problem: the store already accepted the bytes, so a
        refusal or a failure is recorded and shown rather than returned as a
        500 for an upload that in fact succeeded.
        """
        document.analysed_at = datetime.now(timezone.utc)
        source = stored_evidence_path(document)
        if source is None or not source.is_file():
            document.extract_status = "failed"
            document.extract_error = "the locally stored original file is missing"
            document.extract_sha256 = ""
            document.extract_chars = 0
            document.extract_text_path = ""
            document.analysis_json = ""
            document.analysis_rules_hash = ""
            document.analysis_config_hash = ""
            text_path = stored_text_path(document)
            if text_path is not None:
                text_path.unlink(missing_ok=True)
            return document.extract_status

        data = source.read_bytes()
        record = analysis_service.analyse(
            data,
            document.filename,
            document.media_type or "",
        )
        document.extract_status = record["extract"]["status"]
        document.extract_error = record["reason"] or record["extract"]["error"]
        document.extract_sha256 = record["extract"]["sha256"]
        document.extract_chars = record["extract"]["chars"]
        document.analysis_rules_hash = record["projection"]["lexiconHash"]
        document.analysis_config_hash = record["projection"]["configHash"]
        document.analysis_json = json.dumps(record, separators=(",", ":"))

        text_path = stored_text_path(document)
        if text_path is None:
            return document.extract_status
        text = analysis_service.extract_or_empty(data, document.filename)
        if text:
            text_path.write_text(text, encoding="utf-8")
            document.extract_text_path = text_path.name
        else:
            text_path.unlink(missing_ok=True)
            document.extract_text_path = ""
        return document.extract_status

    def analysis_response(document: Document) -> dict:
        """The full analysis record for an item, or an honest placeholder.

        An item that was stored but not yet analysed reports `pending` with its
        own source facts. Nothing here fabricates a projection that did not run.
        """
        record = _decoded_analysis(document)
        if record is not None:
            response = dict(record)
            response["id"] = document.document_key
            response["analysedAt"] = (
                _datetime_text(document.analysed_at) if document.analysed_at else None
            )
            return response

        extract_status = document.extract_status or "stored"
        return {
            "id": document.document_key,
            "status": ANALYSIS_STATUS.get(extract_status, "pending"),
            "reason": document.extract_error or "",
            "source": {
                "sha256": document.content_hash,
                "bytes": document.byte_size,
                "mediaType": document.media_type or "",
                "filename": document.filename,
            },
            "extract": {
                "status": extract_status,
                "chars": document.extract_chars or 0,
                "sha256": document.extract_sha256 or "",
                "error": document.extract_error or "",
            },
            "projection": {
                "engineVersion": "",
                "lexiconHash": document.analysis_rules_hash or "",
                "configHash": document.analysis_config_hash or "",
            },
            "coverage": {
                "scopesTotal": 0,
                "scopesMatched": 0,
                "scopesFallback": 0,
                "scopesInsufficient": 0,
                "ratio": 0.0,
                "warning": None,
            },
            "scopes": [],
            "analysedAt": (
                _datetime_text(document.analysed_at) if document.analysed_at else None
            ),
        }

    def case_documents(db: Session, case: Case) -> list[Document]:
        return list(
            db.scalars(
                select(Document)
                .where(Document.case_id == case.id)
                .order_by(Document.id.asc())
            )
        )

    def search_documents(db: Session, case: Case, needle: str) -> list[dict]:
        """Case-scoped substring search over the extracted-text sidecars.

        Substring (`LIKE`) semantics, not token semantics: a query matches the
        same characters a reader would find with ctrl-F. The response header
        reports which method ran, because the two would not agree.
        """
        hits: list[dict] = []
        pattern = re.compile(re.escape(needle), re.IGNORECASE)
        for document in case_documents(db, case):
            if len(hits) >= SEARCH_HIT_LIMIT:
                break
            text_path = stored_text_path(document)
            if text_path is None or not text_path.is_file():
                continue
            text = text_path.read_text(encoding="utf-8", errors="replace")
            for match in pattern.finditer(text):
                window_start = max(0, match.start() - SEARCH_CONTEXT_CHARS)
                window_end = min(len(text), match.end() + SEARCH_CONTEXT_CHARS)
                excerpt = " ".join(text[window_start:window_end].split())
                hits.append({"id": document.document_key, "excerpt": excerpt})
                if len(hits) >= SEARCH_HIT_LIMIT:
                    break
        return hits

    def timeline_events(db: Session, case: Case) -> list[dict]:
        """The case's own events, in order, built from rows that exist.

        Every value here is something the API actually recorded. It is not a
        chronology read out of the documents: a filing's own dates are a
        different feature and the route does not pretend otherwise. `people` is
        always `["system"]` because every actor in this slice is `system`, and
        the interface must not present that as a person's action.
        """
        rows: list[tuple[datetime, str, dict]] = []

        rows.append(
            (
                case.created_at,
                f"case-{case.id}",
                {
                    "id": f"case-{case.id}",
                    "event": "case_created",
                    "date": _datetime_text(case.created_at),
                    "precision": "exact",
                    "people": ["system"],
                    "evidenceId": None,
                },
            )
        )

        for document in case_documents(db, case):
            rows.append(
                (
                    document.created_at,
                    f"doc-{document.id}",
                    {
                        "id": f"doc-{document.id}",
                        "event": "evidence_uploaded",
                        "date": _datetime_text(document.created_at),
                        "precision": "exact",
                        "people": ["system"],
                        "evidenceId": document.document_key,
                    },
                )
            )

        logs = db.scalars(
            select(AuditLog)
            .where(AuditLog.case_id == case.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
        for log in logs:
            event = TIMELINE_EVENTS.get(log.action)
            if event is None:
                continue
            details = json.loads(log.details or "{}")
            rows.append(
                (
                    log.created_at,
                    f"log-{log.id}",
                    {
                        "id": f"log-{log.id}",
                        "event": event,
                        "date": _datetime_text(log.created_at),
                        "precision": "exact",
                        "people": ["system"],
                        "evidenceId": details.get("evidenceId"),
                    },
                )
            )

        rows.sort(key=lambda row: (row[0], row[1]))
        return [row[2] for row in rows]

    @app.get("/cases/{case_id}", dependencies=[local_api])
    def get_case(case_id: str, db: Session = Depends(get_db)) -> dict:
        return _case_summary(find_case(db, case_id))

    @app.get("/cases/{case_id}/evidence", dependencies=[local_api])
    def list_evidence(case_id: str, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        documents = db.scalars(
            select(Document)
            .where(Document.case_id == case.id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
        return [_evidence_item(db, document) for document in documents]

    @app.post(
        "/cases/{case_id}/evidence",
        status_code=status.HTTP_201_CREATED,
        dependencies=[local_api],
    )
    def upload_evidence(
        case_id: str,
        file: UploadFile = File(...),
        db: Session = Depends(get_db),
    ):
        case = find_case(db, case_id)
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if not filename or "\x00" in filename or len(filename) > 255:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "INVALID_FILENAME",
                    "message": "Upload a file with a valid name of at most 255 characters.",
                },
            )

        storage_key = uuid.uuid4().hex
        temporary_path: Path | None = None
        stored_file = storage_root / f"{storage_key}.bin"
        digest = hashlib.sha256()
        byte_size = 0
        try:
            storage_root.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(
                mode="wb",
                prefix=".upload-",
                dir=storage_root,
                delete=False,
            ) as destination:
                temporary_path = Path(destination.name)
                while chunk := file.file.read(1024 * 1024):
                    destination.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
                destination.flush()
                os.fsync(destination.fileno())
            os.replace(temporary_path, stored_file)
            temporary_path = None

            content_hash = digest.hexdigest()
            duplicate = db.scalar(
                select(Document.id).where(
                    Document.case_id == case.id,
                    Document.content_hash == content_hash,
                )
            ) is not None
            document = Document(
                case_id=case.id,
                document_key=f"E-{storage_key}",
                filename=filename,
                content_hash=content_hash,
                storage_key=storage_key,
                media_type=file.content_type or "application/octet-stream",
                byte_size=byte_size,
            )
            db.add(document)
            db.flush()
            _custody_log(
                db,
                case_id=case.id,
                evidence_id=document.document_key,
                action="evidence_uploaded",
            )
            # The bytes and their custody row are committed before analysis
            # runs, so an analysis failure can never lose an accepted upload.
            db.commit()

            run_analysis(document)
            _custody_log(
                db,
                case_id=case.id,
                evidence_id=document.document_key,
                action="evidence_analysed",
            )
            db.commit()
            return {
                "id": document.document_key,
                "hash": content_hash,
                # The same value the pipeline records as `source_sha256`, so the
                # product path and the pipeline path bind the same artifact.
                "sourceSha256": content_hash,
                "duplicate": duplicate,
                "processingStatus": document.extract_status,
                # The same compact analysis view the evidence item carries, so
                # the intake screen can say *why* an artifact was not read
                # rather than only that it was not.
                "analysis": _analysis_summary(document),
            }
        except OSError:
            db.rollback()
            stored_file.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_507_INSUFFICIENT_STORAGE,
                detail={
                    "error": "EVIDENCE_STORAGE_FAILED",
                    "message": "The local evidence file could not be stored.",
                },
            ) from None
        except SQLAlchemyError:
            db.rollback()
            stored_file.unlink(missing_ok=True)
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "EVIDENCE_METADATA_FAILED",
                    "message": "The local evidence metadata could not be saved.",
                },
            ) from None
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)

    @app.get("/evidence/{evidence_id}", dependencies=[local_api])
    def get_evidence(evidence_id: str, db: Session = Depends(get_db)):
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )
        return _evidence_item(db, document)

    @app.get("/evidence/{evidence_id}/custody", dependencies=[local_api])
    def get_evidence_custody(evidence_id: str, db: Session = Depends(get_db)):
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )
        entries = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.case_id == document.case_id,
                AuditLog.action.in_(tuple(CUSTODY_ACTIONS)),
            )
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        )
        result = []
        for entry in entries:
            details = json.loads(entry.details)
            if details.get("evidenceId") != evidence_id:
                continue
            result.append(
                {
                    "id": str(entry.id),
                    "actor": entry.actor_username,
                    "action": CUSTODY_ACTIONS[entry.action],
                    "at": _datetime_text(entry.created_at),
                    "chain": CUSTODY_CHAIN,
                    "chainDetail": CUSTODY_CHAIN_DETAIL,
                }
            )
        return result

    @app.get("/evidence/{evidence_id}/download", dependencies=[local_api])
    def download_evidence(evidence_id: str, db: Session = Depends(get_db)):
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )
        stored_path = stored_evidence_path(document)
        if stored_path is None or not stored_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "error": "ORIGINAL_FILE_MISSING",
                    "message": "The locally stored original file is missing.",
                },
            )
        return FileResponse(
            stored_path,
            media_type=document.media_type or "application/octet-stream",
            filename=document.filename,
        )

    @app.post("/evidence/{evidence_id}/verify", dependencies=[local_api])
    def verify_evidence(evidence_id: str, db: Session = Depends(get_db)):
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )
        stored_path = stored_evidence_path(document)
        if stored_path is None or not stored_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "error": "ORIGINAL_FILE_MISSING",
                    "message": "The locally stored original file is missing.",
                },
            )
        actual_hash = hashlib.sha256()
        with stored_path.open("rb") as original:
            while chunk := original.read(1024 * 1024):
                actual_hash.update(chunk)
        passed = actual_hash.hexdigest() == document.content_hash
        verified_at = datetime.now(timezone.utc)
        _custody_log(
            db,
            case_id=document.case_id,
            evidence_id=document.document_key,
            action="evidence_verified",
        )
        db.commit()
        return {
            "result": "pass" if passed else "fail",
            "verifiedAt": _datetime_text(verified_at),
            "failingStep": None if passed else "hash_mismatch_at_readback",
            "steps": [{"id": "hash", "result": "pass" if passed else "fail"}],
        }

    def find_document(db: Session, evidence_id: str) -> Document:
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )
        return document

    @app.get("/evidence/{evidence_id}/analysis", dependencies=[local_api])
    def get_evidence_analysis(evidence_id: str, db: Session = Depends(get_db)):
        """What the analysis made of this item, scope by scope.

        Never 501: an item that has not been analysed answers `pending` with its
        source facts, which is a true statement about it.
        """
        return analysis_response(find_document(db, evidence_id))

    @app.post("/evidence/{evidence_id}/analyse", dependencies=[local_api])
    def analyse_evidence(evidence_id: str, db: Session = Depends(get_db)):
        """Re-run analysis without re-uploading.

        Needed when the lexicon changes: every stored analysis is then stale, and
        re-uploading case evidence to refresh it would break the custody chain.
        Idempotent: analysis is a pure function of the stored bytes.
        """
        document = find_document(db, evidence_id)
        run_analysis(document)
        _custody_log(
            db,
            case_id=document.case_id,
            evidence_id=document.document_key,
            action="evidence_analysed",
        )
        db.commit()
        return analysis_response(document)

    @app.get("/cases/{case_id}/timeline", dependencies=[local_api])
    def get_timeline(case_id: str, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        return timeline_events(db, case)

    @app.get("/cases/{case_id}/search", dependencies=[local_api])
    def search_case(
        case_id: str,
        q: str,
        response: Response,
        db: Session = Depends(get_db),
    ):
        case = find_case(db, case_id)
        needle = q.strip()
        if not needle:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "INVALID_QUERY",
                    "message": "Provide a non-empty search query.",
                },
            )
        # The body stays a bare array of {id, excerpt}: that is the contract the
        # search screen already consumes. Which method ran travels in a header,
        # because substring and token matching do not agree and the difference
        # has to stay visible.
        response.headers["X-Anchorum-Search-Method"] = SEARCH_METHOD_SUBSTRING
        return search_documents(db, case, needle)

    @app.post("/cases/{case_id}/export", dependencies=[local_api])
    def export_case(
        case_id: str,
        type: str,
        db: Session = Depends(get_db),
    ):
        find_case(db, case_id)
        _not_implemented(
            "case_export",
            "Case-scoped gated export generation is not implemented.",
        )

    @app.post("/cases/{case_id}/exports/preview", dependencies=[local_api])
    def preview_case_export(
        case_id: str,
        type: str,
        db: Session = Depends(get_db),
    ):
        find_case(db, case_id)
        _not_implemented(
            "export_preview",
            "The product export gates and Barreau validation are not implemented.",
        )

    @app.get("/cases/{case_id}/audit", dependencies=[local_api])
    def get_case_audit(case_id: str, db: Session = Depends(get_db)):
        find_case(db, case_id)
        _not_implemented("case_audit", "Case-scoped audit projections are not implemented.")

    @app.get("/admin/members", dependencies=[local_api])
    def list_members():
        _not_implemented("member_administration", "Member management is not implemented.")

    @app.post("/admin/members/invitations", dependencies=[local_api])
    def invite_member():
        _not_implemented("member_administration", "Member invitations are not implemented.")

    @app.patch("/admin/members/{member_id}/role", dependencies=[local_api])
    def change_member_role(member_id: str):
        _not_implemented("member_administration", "Audited role changes are not implemented.")

    return app


app = create_app()
