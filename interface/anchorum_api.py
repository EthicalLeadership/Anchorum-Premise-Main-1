"""Local/test HTTP API for the Anchorum Prem Main shell."""
from __future__ import annotations

import hashlib
import io
import hmac
import json
import os
import re
import tempfile
import uuid
import zipfile
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
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

from dossier_pipeline.schema import AuditLog, Case, Document, JurisdictionStamp, User, init_schema
from dossier_pipeline.barreau_gate import BarreauGate, BarreauGateError
from interface import analysis as analysis_service
from interface import malware_scan

ROOT = Path(__file__).resolve().parents[1]
INTERFACE_ROOT = Path(__file__).resolve().parent
DIST_ROOT = INTERFACE_ROOT / "dist"

#: The one guard for everything the API writes beside a stored artifact. The
#: storage key is a uuid4 hex digest; a name that does not match it never
#: reaches the filesystem.
STORAGE_KEY_PATTERN = re.compile(r"[0-9a-f]{32}")
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_FILENAME_LENGTH = 255
ALLOWED_CATEGORIES = frozenset({"medical", "payroll", "correspondence", "pleading", "other"})
ALLOWED_SOURCES = frozenset({"clinic", "insurer", "employer", "court", "other"})
ALLOWED_MEDIA_TYPES = frozenset({
    "application/pdf",
    "text/plain",
    "text/csv",
    "image/jpeg",
    "image/png",
    "image/tiff",
    "image/dicom",
    "application/dicom",
    "application/zip",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/octet-stream",
})

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
EVENT_EVIDENCE_FILED_WITH_DATE = "evidence_filed_with_date"

TIMELINE_EVENTS = {
    "evidence_verified": "evidence_verified",
    "evidence_analysed": "evidence_analysed",
    "evidence_reanalysed": "evidence_reanalysed",
    EVENT_EVIDENCE_FILED_WITH_DATE: EVENT_EVIDENCE_FILED_WITH_DATE,
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
    "evidence_reanalysed": "reanalysed",
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
        "documentType": record.get("documentType", "unknown"),
        "metadata": record.get("metadata", {}),
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
        "category": document.category,
        "source": document.source,
        "consultation": document.consultation_json,
    }


def _record_filed_date(db: Session, case_id: int, document: Document) -> None:
    """Extract a document date and write an audit row for the timeline.

    Expects `document.analysis_json` with a `metadata` object holding `date`.
    Normalizes to ISO 8601 and deduplicates so reanalysis does not duplicate rows.
    No row when there is no date — silence is honest.
    """
    record: dict = {}
    if document.analysis_json:
        try:
            parsed = json.loads(document.analysis_json)
            if isinstance(parsed, dict):
                record = parsed
        except (TypeError, ValueError):
            record = {}
    metadata = record.get("metadata") if isinstance(record, dict) else None
    if not isinstance(metadata, dict):
        metadata = {}

    date_value = metadata.get("date") or record.get("date")
    if not date_value or not str(date_value).strip():
        return

    date_str = str(date_value).strip()
    try:
        from datetime import datetime as _dt
        date_str = _dt.strptime(date_str[:10], "%Y-%m-%d").date().isoformat()
    except ValueError:
        pass

    existing = db.scalar(
        select(AuditLog.id).where(
            AuditLog.case_id == case_id,
            AuditLog.action == EVENT_EVIDENCE_FILED_WITH_DATE,
            AuditLog.details.like(f'%"evidenceId":"{document.document_key}"%'),
        )
    )
    if existing:
        return

    _append_audit(
        db,
        case_id=case_id,
        action=EVENT_EVIDENCE_FILED_WITH_DATE,
        details={
            "evidenceId": document.document_key,
            "date": date_str,
            "documentType": record.get("documentType"),
            "author": metadata.get("author"),
            "issuer": metadata.get("issuer"),
        },
    )


def _append_audit(
    db: Session,
    *,
    case_id: int,
    action: str,
    details: dict,
    actor: str = "system",
) -> None:
    """Append a chained audit row. All case-scoped logs go through here."""
    details_str = json.dumps(details, separators=(",", ":"))
    prev = db.scalar(
        select(AuditLog)
        .where(AuditLog.case_id == case_id)
        .order_by(AuditLog.id.desc())
        .limit(1)
    )
    previous_hash = prev.record_hash if prev else ""
    record_hash = hashlib.sha256(
        (previous_hash + "|" + action + "|" + details_str).encode("utf-8")
    ).hexdigest()
    db.add(
        AuditLog(
            case_id=case_id,
            actor_username=actor,
            action=action,
            details=details_str,
            previous_hash=previous_hash,
            record_hash=record_hash,
        )
    )
    db.flush()


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
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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
            # W5: the doctrine block is present on both branches of the
            # response, so a consumer reading the key does not need to know
            # whether analysis has run yet.
            "doctrine": {
                "conceptDistribution": {},
                "scopesMatched": 0,
                "engineVersion": "",
                "lexiconHash": "",
                "configHash": "",
                "classification": "",
                "fallbackReason": None,
            },
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
            date_text = _datetime_text(log.created_at)
            precision = "exact"
            if event == EVENT_EVIDENCE_FILED_WITH_DATE:
                extracted = details.get("date")
                if extracted:
                    date_text = extracted
                    precision = "day"
            rows.append(
                (
                    log.created_at,
                    f"log-{log.id}",
                    {
                        "id": f"log-{log.id}",
                        "event": event,
                        "date": date_text,
                        "precision": precision,
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

    @app.patch("/cases/{case_id}", dependencies=[local_api])
    def update_case(case_id: str, request: dict, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        new_status = request.get("status")
        if new_status and new_status in ("open", "closed", "on_hold"):
            case.status = new_status
            _append_audit(
                db,
                case_id=case.id,
                action="case_status_changed",
                details={"status": new_status},
            )
            db.commit()
        return _case_summary(case)

    @app.get("/cases/{case_id}/evidence", dependencies=[local_api])
    def list_evidence(
        case_id: str,
        status: str | None = None,
        category: str | None = None,
        source: str | None = None,
        document_type: str | None = None,
        author: str | None = None,
        date: str | None = None,
        db: Session = Depends(get_db),
    ):
        case = find_case(db, case_id)
        documents = db.scalars(
            select(Document)
            .where(Document.case_id == case.id)
            .order_by(Document.created_at.desc(), Document.id.desc())
        )
        items = [_evidence_item(db, document) for document in documents]

        if status == "hold":
            items = [i for i in items if i.get("status") == "integrity_hold"]
        elif status:
            items = [i for i in items if i.get("status") == status]
        if category:
            items = [i for i in items if i.get("category") == category]
        if source:
            items = [i for i in items if i.get("source") == source]
        if document_type:
            items = [
                i for i in items
                if (i.get("analysis") or {}).get("documentType") == document_type
            ]
        if author:
            needle = author.lower()
            items = [
                i for i in items
                if needle in ((((i.get("analysis") or {}).get("metadata") or {}).get("author")) or "").lower()
            ]
        if date:
            items = [
                i for i in items
                if ((i.get("analysis") or {}).get("metadata") or {}).get("date") == date
            ]

        return items

    @app.post(
        "/cases/{case_id}/evidence",
        status_code=status.HTTP_201_CREATED,
        dependencies=[local_api],
    )
    def upload_evidence(
        case_id: str,
        file: UploadFile = File(...),
        category: str | None = Form(None),
        source: str | None = Form(None),
        db: Session = Depends(get_db),
    ):
        case = find_case(db, case_id)

        def reject(status_code: int, error_code: str, message: str):
            _append_audit(
                db,
                case_id=case.id,
                action="evidence_upload_rejected",
                details={"reason": error_code},
            )
            db.commit()
            raise HTTPException(
                status_code=status_code,
                detail={"error": error_code, "message": message},
            )
        filename = (file.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
        if (
            not filename
            or filename in (".", "..")
            or any(ord(c) < 0x20 or ord(c) == 0x7F for c in filename)
            or len(filename) > MAX_FILENAME_LENGTH
        ):
            reject(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_FILENAME", "Upload a file with a valid name.")

        media_type = (file.content_type or "application/octet-stream").split(";")[0].strip().lower()
        if media_type not in ALLOWED_MEDIA_TYPES:
            reject(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "UNSUPPORTED_MEDIA_TYPE", "The declared media type is not allowed.")

        category = (category or "").strip() or None
        if category is not None and category not in ALLOWED_CATEGORIES:
            reject(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_CATEGORY", "The provided category is not allowed.")

        source = (source or "").strip() or None
        if source is not None and source not in ALLOWED_SOURCES:
            reject(status.HTTP_422_UNPROCESSABLE_CONTENT, "INVALID_SOURCE", "The provided source is not allowed.")

        storage_key = uuid.uuid4().hex
        temporary_path: Path | None = None
        stored_file = storage_root / f"{storage_key}.bin"
        digest = hashlib.sha256()
        byte_size = 0
        committed = False
        scanner = malware_scan.EicarScanner()
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
                    if byte_size + len(chunk) > MAX_UPLOAD_BYTES:
                        reject(status.HTTP_413_CONTENT_TOO_LARGE, "EVIDENCE_TOO_LARGE", f"Evidence exceeds the {MAX_UPLOAD_BYTES} byte limit.")
                    destination.write(chunk)
                    digest.update(chunk)
                    byte_size += len(chunk)
                    scanner.feed(chunk)
                if byte_size == 0:
                    reject(status.HTTP_422_UNPROCESSABLE_CONTENT, "EMPTY_UPLOAD", "Upload an evidence file with at least one byte.")
                destination.flush()
                os.fsync(destination.fileno())
            try:
                scan_result = scanner.finish()
            except Exception:
                reject(status.HTTP_422_UNPROCESSABLE_CONTENT, "EVIDENCE_REJECTED_BY_SCAN", "The file was rejected by the malware scanner.")
            
            if scan_result.status != "clean":
                reject(status.HTTP_422_UNPROCESSABLE_CONTENT, "EVIDENCE_REJECTED_BY_SCAN", "The file was rejected by the malware scanner.")

            readback = hashlib.sha256()
            with temporary_path.open("rb") as handle:
                while chunk := handle.read(1024 * 1024):
                    readback.update(chunk)
            size_on_disk = temporary_path.stat().st_size
            if not hmac.compare_digest(readback.hexdigest(), digest.hexdigest()) or size_on_disk != byte_size:
                reject(status.HTTP_507_INSUFFICIENT_STORAGE, "EVIDENCE_READBACK_FAILED", "The stored file could not be read back correctly.")

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
                media_type=media_type,
                category=category,
                source=source,
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
            committed = True

            run_analysis(document)
            _custody_log(
                db,
                case_id=case.id,
                evidence_id=document.document_key,
                action="evidence_analysed",
            )
            _record_filed_date(db, case.id, document)
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
                "category": category,
                "source": source,
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
            if not committed:
                stored_file.unlink(missing_ok=True)

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

    @app.delete("/evidence/{evidence_id}", dependencies=[local_api])
    def delete_evidence(evidence_id: str, db: Session = Depends(get_db)) -> dict:
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence not found."},
            )
        case_id = document.case_id
        for suffix in (".bin", ".txt"):
            stored = stored_path(document, suffix)
            if stored is not None:
                stored.unlink(missing_ok=True)
        _custody_log(
            db,
            case_id=case_id,
            evidence_id=evidence_id,
            action="evidence_removed",
        )
        db.delete(document)
        db.commit()
        return {"id": evidence_id, "removed": True}

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

    @app.post("/evidence/{evidence_id}/consult", dependencies=[local_api])
    def consult_evidence(evidence_id: str, db: Session = Depends(get_db)):
        from interface import llm_classifier

        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence not found."},
            )

        if os.environ.get("ANCHORUM_LLM_ENABLED") != "1":
            return {
                "id": evidence_id,
                "consultation": None,
                "reason": "LLM_DISABLED",
                "message": "Set ANCHORUM_LLM_ENABLED=1 to enable the AI consultant.",
            }

        text_path = stored_text_path(document)
        if text_path is None or not text_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "NO_EXTRACTED_TEXT",
                    "message": "This evidence item has no extracted text to classify.",
                },
            )

        try:
            text = text_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "TEXT_READ_FAILED",
                    "message": type(exc).__name__,
                },
            ) from None

        result = llm_classifier.llm_classify(text)
        document.consultation_json = json.dumps(result)
        db.commit()
        return {"id": evidence_id, "consultation": result}

    @app.post("/evidence/{evidence_id}/summarize", dependencies=[local_api])
    def summarize_evidence(evidence_id: str, db: Session = Depends(get_db)):
        from interface import llm_classifier

        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence not found."},
            )

        if os.environ.get("ANCHORUM_LLM_ENABLED") != "1":
            return {
                "id": evidence_id,
                "narrative": None,
                "reason": "LLM_DISABLED",
                "message": "Set ANCHORUM_LLM_ENABLED=1 to enable the AI summariser.",
            }

        text_path = stored_text_path(document)
        if text_path is None or not text_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "NO_EXTRACTED_TEXT",
                    "message": "This evidence item has no extracted text to summarize.",
                },
            )

        try:
            text = text_path.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "TEXT_READ_FAILED",
                    "message": type(exc).__name__,
                },
            ) from None

        result = llm_classifier.llm_summarize(text)
        document.consultation_json = json.dumps(result)
        db.commit()
        return {"id": evidence_id, "narrative": result}

    @app.post("/evidence/{evidence_id}/verify-doctrine", dependencies=[local_api])
    def verify_doctrine(evidence_id: str, db: Session = Depends(get_db)):
        from interface import analysis as analysis_service

        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence not found."},
            )

        if not document.analysis_json:
            return {"match": False, "reason": "not_analysed", "stored": None, "recomputed": None}

        try:
            stored_record = json.loads(document.analysis_json)
        except (TypeError, ValueError):
            return {"match": False, "reason": "corrupt_stored_json", "stored": None, "recomputed": None}

        stored_doctrine = stored_record.get("doctrine") or {}

        bin_path = stored_evidence_path(document)
        if bin_path is None or not bin_path.is_file():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "NO_STORED_BYTES", "message": "Stored bytes are missing."},
            )

        try:
            data = bin_path.read_bytes()
            recomputed_record = analysis_service.analyse(
                data, document.filename, document.media_type or ""
            )
            recomputed_doctrine = recomputed_record.get("doctrine") or {}
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={"error": "ANALYSIS_FAILED", "message": type(exc).__name__},
            ) from None

        # 1. Lexicon hash — if the lexicon changed, the projection is not comparable
        if stored_doctrine.get("lexiconHash") != recomputed_doctrine.get("lexiconHash"):
            return {"match": False, "reason": "lexicon_changed", "stored": stored_doctrine, "recomputed": recomputed_doctrine}

        # 2. Config hash — engine settings changed
        if stored_doctrine.get("configHash") != recomputed_doctrine.get("configHash"):
            return {"match": False, "reason": "config_changed", "stored": stored_doctrine, "recomputed": recomputed_doctrine}

        # 3. Top-level classification
        if stored_doctrine.get("classification") != recomputed_doctrine.get("classification"):
            return {"match": False, "reason": "classification_changed", "stored": stored_doctrine, "recomputed": recomputed_doctrine}

        # 4. Distribution of matched concepts
        if stored_doctrine.get("conceptDistribution") != recomputed_doctrine.get("conceptDistribution"):
            return {"match": False, "reason": "concepts_changed", "stored": stored_doctrine, "recomputed": recomputed_doctrine}

        return {"match": True, "reason": None, "stored": stored_doctrine, "recomputed": recomputed_doctrine}

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
            action="evidence_reanalysed",
        )
        _record_filed_date(db, document.case_id, document)
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
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
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



    def _curated_analysis(document: Document) -> dict | None:
        """The publicly safe subset of an analysis record.

        Excludes analysis_rules_hash, analysis_config_hash, and the full
        doctrine projection. Includes the deterministic documentType and the
        extracted metadata (date/author/issuer) — the two things a recipient
        of an exported case can defensibly see.
        """
        if not document.analysis_json:
            return None
        try:
            record = json.loads(document.analysis_json)
        except (TypeError, ValueError):
            return None
        if not isinstance(record, dict):
            return None
        out: dict = {}
        if "documentType" in record:
            out["documentType"] = record["documentType"]
        metadata = record.get("metadata")
        if isinstance(metadata, dict):
            out["metadata"] = {
                k: metadata[k] for k in ("date", "author", "issuer") if k in metadata
            }
        return out or None

    @app.post("/cases/{case_id}/export", dependencies=[local_api])
    def export_case(case_id: str, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        stamp = db.scalar(
            select(JurisdictionStamp).where(JurisdictionStamp.case_id == case.id)
        )
        if stamp is None:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "EXPORT_BLOCKED_BARREAU",
                    "message": "A Barreau stamp must be applied before export.",
                },
            )
        documents = db.scalars(select(Document).where(Document.case_id == case.id)).all()

        # inv_003: every file on disk must still hash to its recorded content_hash.
        # Refuse to package evidence that has been tampered with on disk.
        from interface import invariants_bridge as _ib
        for _doc in documents:
            _p = stored_evidence_path(_doc)
            if _p is None or not _p.is_file():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "INTEGRITY_CHECK_FAILED", "message": _doc.document_key + ": stored bytes missing"},
                )
            _raw = _p.read_bytes()
            _env = {"message_id": "sha256:" + _doc.content_hash}
            _r = _ib.run_one("inv_003", {"raw_bytes": _raw, "envelope": _env})
            if _r["status"] != "pass":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "INTEGRITY_CHECK_FAILED", "message": _doc.document_key + ": " + (_r.get("reason") or "mismatch")},
                )

        # Build the manifest
        manifest = {
            "schema_version": "1.0",
            "case": {
                "id": case.id,
                "key": case.case_key,
                "title": case.title,
                "status": case.status,
                "exported_at": _datetime_text(datetime.now(timezone.utc)),
            },
            "documents": [
                {
                    "document_key": doc.document_key,
                    "filename": doc.filename,
                    "category": doc.category,
                    "source": doc.source,
                    "content_hash": doc.content_hash,
                    "byte_size": doc.byte_size,
                    "analysis": _curated_analysis(doc),
                }
                for doc in documents
            ],
            "barreau_stamp": {
                "version": stamp.stamp_version,
                "approved_by": stamp.approved_by,
                "applied_at": _datetime_text(stamp.applied_at),
            },
        }

        # inv_007: verify the audit chain links from genesis to tip.
        from interface import invariants_bridge as _ib
        _logs = db.scalars(
            select(AuditLog)
            .where(AuditLog.case_id == case.id)
            .order_by(AuditLog.id.asc())
        ).all()
        _prev = None
        for _log in _logs:
            _ok = _ib.run_one(
                "inv_007",
                {
                    "prev_record": (
                        {"record_hash": _prev.record_hash} if _prev else None
                    ),
                    "new_record": {"previous_hash": _log.previous_hash},
                },
            )
            if _ok["status"] != "pass":
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "CUSTODY_CHAIN_BROKEN",
                        "message": f"record {_log.id}: " + (_ok.get("reason") or "chain break"),
                    },
                )
            _prev = _log
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("manifest.json", json.dumps(manifest, indent=2))

            # Governance disclaimer — versioned and timestamped by the engine
            # Human-readable summary. Goes through output_gates.sanitize_output
            # so any internal term that slipped into prose is redacted before
            # leaving the machine. The structured manifest is not passed through
            # sanitize_output because it must retain content_hash for verification.
            try:
                from dossier_pipeline.output_gates import sanitize_output
            except ImportError:
                sanitize_output = None

            summary_lines = [
                f"# Case {case.case_key}",
                "",
                f"**Title**: {case.title}",
                f"**Jurisdiction**: {case.jurisdiction}",
                f"**Status**: {case.status}",
                f"**Evidence files**: {len(documents)}",
                "",
                "## Barreau approval",
                "",
                f"- Approved by: {stamp.approved_by}",
                f"- Stamp version: {stamp.stamp_version}",
                "",
                "## Evidence",
                "",
            ]
            for _doc in documents:
                _cur = _curated_analysis(_doc) or {}
                _type = _cur.get("documentType", "unknown")
                summary_lines.append(
                    f"- `{_doc.document_key}` — {_doc.filename} "
                    f"(type: {_type}, bytes: {_doc.byte_size})"
                )

            raw_summary = "\n".join(summary_lines) + "\n"

            if sanitize_output is not None:
                report = sanitize_output(raw_summary)
                if report.leakage_found:
                    raw_summary = (
                        "> **Note**: some text was redacted before export "
                        f"({len(report.redacted_terms)} term(s)).\n\n"
                        + report.sanitized_text
                    )
                else:
                    raw_summary = report.sanitized_text

            zf.writestr("SUMMARY.md", raw_summary)

            try:
                from dossier_pipeline.disclaimer import format_disclaimer_block
                zf.writestr("DISCLAIMER.md", format_disclaimer_block())
            except ImportError:
                zf.writestr(
                    "DISCLAIMER.md",
                    "Disclaimer module unavailable in this build.",
                )
            
            for doc in documents:
                path = stored_evidence_path(doc)
                if path and path.is_file():
                    # Use the original filename inside the zip, prefixed with the document key to avoid collisions
                    arcname = f"evidence/{doc.document_key}_{doc.filename}"
                    zf.write(path, arcname)

        buffer.seek(0)
        
        db.add(AuditLog(
            case_id=case.id,
            actor_username="system",
            action="export_produced",
            details=json.dumps({"format": "zip", "docCount": len(documents)}),
        ))
        db.commit()

        return Response(
            content=buffer.getvalue(),
            media_type="application/zip",
            headers={
                "Content-Disposition": f'attachment; filename="case_{case.case_key}_export.zip"'
            },
        )

    @app.post("/cases/{case_id}/exports/preview", dependencies=[local_api])
    def preview_case_export(
        case_id: str,
        type: str = "evidence_index",
        db: Session = Depends(get_db),
    ):
        case = find_case(db, case_id)
        documents = db.scalars(
            select(Document).where(Document.case_id == case.id)
        ).all()

        restriction_fail = None
        for doc in documents:
            if (doc.extract_status or "") == "failed":
                restriction_fail = doc.document_key
                break

        # Barreau gate: a case must have evidence AND a JurisdictionStamp
        # before it can be exported. The stamp is a row in the
        # jurisdiction_stamps table, applied via POST /cases/{id}/stamp.
        stamp = db.scalar(
            select(JurisdictionStamp).where(JurisdictionStamp.case_id == case.id)
        )
        if not documents:
            barreau_fail = "(no evidence)"
        elif stamp is None:
            barreau_fail = "(no barreau stamp)"
        else:
            barreau_fail = None

        gates = [
            {
                "id": "restriction",
                "result": "fail" if restriction_fail else "pass",
                "failingItem": restriction_fail,
            },
            {
                "id": "disclaimer",
                "result": "pass",
                "failingItem": None,
            },
            {
                "id": "barreau",
                "result": "fail" if barreau_fail else "pass",
                "failingItem": barreau_fail,
            },
        ]
        return {
            "type": type,
            "gates": gates,
            "blocked": any(g["result"] == "fail" for g in gates),
        }


    @app.get("/cases/{case_id}/stamp", dependencies=[local_api])
    def get_stamp(case_id: str, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        stamp = db.scalar(
            select(JurisdictionStamp).where(JurisdictionStamp.case_id == case.id)
        )
        if stamp is None:
            return {"case_id": case.id, "stamped": False}
        return {
            "case_id": case.id,
            "stamped": True,
            "stamp_version": stamp.stamp_version,
            "approved_by": stamp.approved_by,
            "applied_at": _datetime_text(stamp.applied_at),
        }

    @app.post("/cases/{case_id}/stamp", dependencies=[local_api])
    def create_stamp(case_id: str, request: dict, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        approved_by = (request.get("approved_by") or "").strip()
        if not approved_by:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"error": "INVALID_FORM", "message": "approved_by is required."},
            )
        existing = db.scalar(
            select(JurisdictionStamp).where(JurisdictionStamp.case_id == case.id)
        )
        if existing is not None:
            return {
                "case_id": case.id,
                "stamped": True,
                "stamp_version": existing.stamp_version,
                "approved_by": existing.approved_by,
                "applied_at": _datetime_text(existing.applied_at),
                "already_stamped": True,
            }
        stamp = JurisdictionStamp(
            case_id=case.id,
            stamp_version="1.0.0",
            approved_by=approved_by,
        )
        db.add(stamp)
        _append_audit(
            db,
            case_id=case.id,
            action="barreau_stamp_applied",
            details={"stamp_version": "1.0.0"},
            actor=approved_by,
        )
        db.commit()
        return {
            "case_id": case.id,
            "stamped": True,
            "stamp_version": stamp.stamp_version,
            "approved_by": stamp.approved_by,
            "applied_at": _datetime_text(stamp.applied_at),
        }

    @app.get("/cases/{case_id}/audit", dependencies=[local_api])
    def get_case_audit(case_id: str, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        logs = db.scalars(
            select(AuditLog)
            .where(AuditLog.case_id == case.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        ).all()
        rows = []
        for log in logs:
            try:
                details = json.loads(log.details or "{}")
            except (TypeError, ValueError):
                details = {}
            chain = "not_checked"
            failing = None
            if log.action == "evidence_verified":
                failing = details.get("failingStep")
                chain = "broken" if failing else "linked"
            row = {
                "id": f"log-{log.id}",
                "event": log.action,
                "at": _datetime_text(log.created_at),
                "actor": log.actor_username,
                "evidenceId": details.get("evidenceId"),
                "chain": chain,
            }
            if failing:
                row["failingStep"] = failing
            if log.action == "member_role_changed":
                row["memberId"] = details.get("memberId")
                row["previousRole"] = details.get("previousRole")
                row["role"] = details.get("role")
                row["reason"] = details.get("reason")
            rows.append(row)
        return rows

    @app.get("/admin/members", dependencies=[local_api])
    def list_members(db: Session = Depends(get_db)):
        users = db.scalars(select(User)).all()
        return [
            {
                "id": str(u.id),
                "name": u.username.split("@")[0] if "@" in u.username else u.username,
                "email": u.username,
                "role": u.role,
                "status": "active",
                "caseIds": [],
            }
            for u in users
        ]

    @app.post("/admin/members/invitations", dependencies=[local_api])
    def invite_member(request: dict, db: Session = Depends(get_db)):
        email = request.get("email")
        role = request.get("role", "reviewer")
        credential = (request.get("credential") or "").strip()
        if not email:
            raise HTTPException(status_code=400, detail={"error": "INVALID_FORM", "message": "Email required."})

        existing = db.scalar(select(User).where(User.username == email))
        if existing:
            raise HTTPException(status_code=409, detail={"error": "MEMBER_ALREADY_EXISTS", "message": "Member already exists."})

        allowlist_raw = os.environ.get("ANCHORUM_BARREAU_ALLOWLIST", "").strip()
        allowlist = [f.strip() for f in allowlist_raw.split(",") if f.strip()]
        required = os.environ.get("ANCHORUM_BARREAU_REQUIRED", "0") == "1"

        if not credential:
            if required:
                _append_audit(
                    db,
                    case_id=None,
                    action="barreau_credential_rejected",
                    details={"email": email, "reason": "credential_missing"},
                    actor="system",
                )
                db.commit()
                raise HTTPException(status_code=400, detail={
                    "error": "BARREAU_CREDENTIAL_REQUIRED",
                    "message": "This install requires a Barreau credential to invite members.",
                })
            stored_fingerprint = "pending"
        else:
            gate = BarreauGate(allowlist)
            try:
                result = gate.validate(credential)
            except BarreauGateError:
                _append_audit(
                    db,
                    case_id=None,
                    action="barreau_credential_rejected",
                    details={"email": email, "reason": "not_in_allowlist"},
                    actor="system",
                )
                db.commit()
                raise HTTPException(status_code=403, detail={
                    "error": "BARREAU_CREDENTIAL_REJECTED",
                    "message": "This credential is not in the Barreau allowlist.",
                })
            stored_fingerprint = result.credential_fingerprint
            _append_audit(
                db,
                case_id=None,
                action="barreau_credential_verified",
                details={
                    "email": email,
                    "fingerprint_prefix": stored_fingerprint[:8],
                },
                actor="system",
            )

        user = User(username=email, role=role, credential_fingerprint=stored_fingerprint)
        db.add(user)
        db.flush()

        _append_audit(
            db,
            case_id=None,
            action="member_invited",
            details={"memberId": str(user.id), "email": email, "role": role},
            actor="system",
        )
        db.commit()
        return {
            "id": str(user.id),
            "name": user.username.split("@")[0],
            "email": user.username,
            "role": user.role,
            "status": "invited",
            "caseIds": [],
            "credentialFingerprint": stored_fingerprint,
        }
    @app.patch("/admin/members/{member_id}/role", dependencies=[local_api])
    def change_member_role(member_id: str, request: dict, db: Session = Depends(get_db)):
        role = request.get("role")
        reason = request.get("reason", "")
        user = db.get(User, int(member_id))
        if not user:
            raise HTTPException(status_code=404, detail={"error": "NOT_FOUND", "message": "Member not found."})
        
        old_role = user.role
        user.role = role
        db.add(AuditLog(
            case_id=None,
            actor_username="system",
            action="member_role_changed",
            details=json.dumps({"memberId": str(user.id), "previousRole": old_role, "role": role, "reason": reason}),
        ))
        db.commit()
        return {
            "id": str(user.id),
            "name": user.username.split("@")[0],
            "email": user.username,
            "role": user.role,
            "status": "active",
            "caseIds": [],
        }

    return app


app = create_app()
