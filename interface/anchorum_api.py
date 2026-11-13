"""Local/test HTTP API for the Anchorum Prem Main shell."""
from __future__ import annotations

import bisect
import hashlib
import io
import hmac
import json
import os
import re
import sqlite3
import tempfile
import uuid
import zipfile
from collections import Counter
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal, cast

from fastapi import Depends, FastAPI, File, Form, HTTPException, Response, UploadFile, status
from fastapi.encoders import jsonable_encoder

def _require_real_id(evidence_id: str) -> str:
    if not evidence_id or evidence_id == "null":
        raise HTTPException(422, "evidence id must be a real id, not 'null'")
    return evidence_id
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import create_engine, func, select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.engine import make_url

from dossier_enforcement.gates import TransactionGate
from dossier_pipeline.schema import AuditLog, Case, Document, JurisdictionStamp, User, init_schema
from dossier_pipeline.barreau_gate import BarreauGate, BarreauGateError
from dossier_pipeline.evidence import (
    CustodyAction,
    EvidenceSigner,
    EvidenceSignerUnbound,
    EvidenceStore,
)
from interface import analysis as analysis_service
from interface import anchoring
from interface import malware_scan
from interface import preflight, proofs
from interface.security.client_keys import get_or_create_deployment_key, get_or_create_api_key
from interface.security.auth import AuthMiddleware
from interface.collect.email_threads import email_router
from interface.board import board_router
from interface.analysis import analyse
from interface.pdf_text import extract_text, PdfTextError, looks_like_pdf
import logging
logger = logging.getLogger(__name__)

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

#: Ceiling on how much extracted text one response carries. A 25 MB scanned
#: exhibit can extract to millions of characters; returning all of it in JSON
#: would stall the browser and help nobody. The truncation is reported in the
#: payload rather than silent, because a reader who is shown part of a document
#: must know it is part of a document.
EXTRACTED_TEXT_LIMIT = 200_000

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

#: Audit actions that appear in an evidence item's custody list, and the word
#: the interface shows for each.
CUSTODY_ACTIONS = {
    "evidence_uploaded": "uploaded",
    "evidence_verified": "verified",
    "evidence_analysed": "analysed",
    "evidence_reanalysed": "reanalysed",
    # AI actions appear in the custody list because they read the whole
    # document and produce text a reader may act on. An output nobody can trace
    # to a moment and an actor is worse than no output.
    "evidence_consulted": "consulted",
    "evidence_summarised": "summarised",
    # Finding lifecycle events for the war room integration
    "finding_created": "created",
    "finding_superseded": "superseded",
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


def _decoded_consultation(document: Document) -> dict | None:
    """The stored second-opinion consultation, or None when there is none."""
    if not document.consultation_json:
        return None
    try:
        record = json.loads(document.consultation_json)
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
        # The artifact's own digest. The viewer prints it beside the HMAC so a
        # reader can check the file they were given; omitting it left the
        # metadata block reading "unavailable" for an item that has a hash.
        "sha256": document.content_hash,
        # Decoded, not the raw column text. `/consult` returns an object, and an
        # evidence item that returned the same answer as a JSON string meant the
        # interface had to parse a document to show a document type.
        "consultation": _decoded_consultation(document),
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


_EVIDENCE_SECRET = None

def _hmac_signer():
    """Return an EvidenceSigner, or None if GDC_EVIDENCE_SECRET is unset.

    Called per-request; construction is cheap. Absent env is tolerated: rows
    are stored with hmac="" (explicitly unsigned) and /export marks them
    rather than refusing. Every system with the secret configured gets real
    per-row HMACs, and /export fail-closes on any empty hmac.
    """
    try:
        from dossier_pipeline.evidence import EvidenceSigner
        if _EVIDENCE_SECRET:
            return EvidenceSigner(secret=_EVIDENCE_SECRET)
        return EvidenceSigner()
    except Exception:
        return None


def _append_audit(
    db: Session,
    *,
    case_id: int,
    action: str,
    details: dict,
    actor: str = "system",
    citations_valid: bool | None = None,
) -> None:
    """Append a chained audit row. All case-scoped logs go through here."""
    if citations_valid is not None:
        details = {**details, "citations_valid": citations_valid}
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
    _signer = _hmac_signer()
    record_hmac = _signer.sign(record_hash) if _signer else ""
    db.add(
        AuditLog(
            case_id=case_id,
            actor_username=actor,
            action=action,
            details=details_str,
            previous_hash=previous_hash,
            record_hash=record_hash,
            hmac=record_hmac,
            citations_valid=citations_valid,
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
    _append_audit(
        db,
        case_id=case_id,
        action=action,
        details={"evidenceId": evidence_id},
        actor="system",
    )


def _record_pipeline_custody(document: Document, *, case_id: int) -> None:
    from interface.document import resolve_evidence_db_path

    evidence_store = EvidenceStore(str(resolve_evidence_db_path()))
    try:
        if evidence_store.configured_signer() is None:
            # The evidence store signs every packet and custody event and
            # refuses to do so with an empty key (EvidenceSignerUnbound). With
            # no secret configured this step is skipped rather than failing the
            # upload: the audit chain still records it, and
            # /audit/verify-proofs reports the missing key as `not_checked`.
            return
        packet = evidence_store.ingest(
            evidence_id=document.document_key,
            event_type="document_upload",
            raw_payload={
                "content_hash": document.content_hash,
                "byte_size": document.byte_size,
            },
            normalized_payload={
                "filename": document.filename,
                "media_type": document.media_type,
                "category": document.category,
                "source": document.source,
            },
            metadata={
                "case_id": str(case_id),
                "document_key": document.document_key,
            },
        )
        evidence_store.add_custody_event(
            packet.evidence_id,
            "interface",
            CustodyAction.INGESTED,
        )
        valid, problems = evidence_store.verify_custody_chain(packet.evidence_id)
        if not valid:
            raise RuntimeError(
                f"Newly recorded evidence custody chain failed verification: {problems}"
            )
        evidence_store.add_custody_event(
            packet.evidence_id,
            "interface",
            CustodyAction.VERIFIED,
        )
    finally:
        evidence_store.close()


from interface.ledger.anchor_router import router as ledger_anchor_router

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
    app.add_middleware(AuthMiddleware)
    app.include_router(email_router)
    app.include_router(board_router)
    app.include_router(ledger_anchor_router)
    app.state.local_api_mode = enabled
    app.state.database_engine = engine
    app.state.db_sessions = db_sessions
    app.state.api_key = get_or_create_api_key(Path(storage_root) / "keys")
    app.state.evidence_directory = storage_root
    app.state.anchor_dir = Path(storage_root) / "anchors"

    # Per-client deployment key & HMAC secret
    global _EVIDENCE_SECRET
    try:

        from cryptography.hazmat.primitives import serialization
        _deployment_key = get_or_create_deployment_key(Path(storage_root) / "keys")
        _key_bytes = _deployment_key.private_bytes(
            encoding=serialization.Encoding.Raw,
            format=serialization.PrivateFormat.Raw,
            encryption_algorithm=serialization.NoEncryption(),
        )
        _EVIDENCE_SECRET = hashlib.sha256(_key_bytes).hexdigest()
        app.state.evidence_secret = _EVIDENCE_SECRET
        app.state.evidence_secret_error = None
        app.state.api_key = get_or_create_api_key(Path(storage_root) / "keys")
    except Exception as exc:
        # Key generation failed (permissions, disk, etc.).
        _EVIDENCE_SECRET = None
        app.state.evidence_secret = None
        app.state.evidence_secret_error = str(exc)
        app.state.api_key = None

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

    def evidence_pages(document: Document, data: bytes) -> list[str] | None:
        """Return source text split by page, or None when extraction has no page map."""
        from interface import submission

        text, spans = submission.extract_text_with_pages(data, document.filename)
        if looks_like_pdf(data) or document.filename.lower().endswith(".pdf"):
            if spans is None:
                return None
            return [text[start:end] for _page, start, end in spans]
        return [text]

    def case_source_pages(
        documents: list[Document],
        raw_by_key: dict[str, bytes] | None = None,
    ) -> dict[str, list[str]]:
        """Build an unambiguous exact-filename map for export citation checks."""
        from interface import submission

        filename_counts = Counter(document.filename for document in documents)
        sources: dict[str, list[str]] = {}
        for document in documents:
            if filename_counts[document.filename] != 1:
                continue
            raw = (raw_by_key or {}).get(document.document_key)
            if raw is None:
                path = stored_evidence_path(document)
                if path is None or not path.is_file():
                    continue
                raw = path.read_bytes()
            try:
                pages = evidence_pages(document, raw)
            except (PdfTextError, submission.UnsupportedSubmission):
                continue
            if pages is not None:
                sources[document.filename] = pages
        return sources

    def cited_source_text(
        narrative: str,
        sources: dict[str, list[str]],
    ) -> tuple[str | None, str | None]:
        """Extract only the page-local line spans named by a narrative."""
        from interface.citation_validator import validate_citations_against_sources

        report = validate_citations_against_sources(narrative, sources)
        if not report["valid"]:
            return None, "CITATION_REFERENCE_UNVERIFIED"
        citations = report["parsed_citations"]
        if not citations:
            return None, "NO_CITATIONS"
        excerpts = []
        for citation in citations:
            lines = sources[citation["file"]][citation["page"] - 1].splitlines()
            excerpts.append(
                f"[{citation['file']} page {citation['page']} lines "
                f"{citation['lines_start']}-{citation['lines_end']}]\n"
                + "\n".join(lines[citation["lines_start"] - 1 : citation["lines_end"]])
            )
        return "\n\n".join(excerpts), None

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

    def audit_proof_rows(db: Session, case: Case) -> list[proofs.AuditRow]:
        """The audit chain as plain rows, in the order it was written.

        `id ASC` and not `created_at ASC`: the chain is defined by insertion
        order, and two rows written inside one second would otherwise be
        compared in an order the chain never claimed.
        """
        rows = db.scalars(
            select(AuditLog)
            .where(AuditLog.case_id == case.id)
            .order_by(AuditLog.id.asc())
        ).all()
        return [
            proofs.AuditRow(
                id=int(row.id),
                action=row.action,
                details=row.details or "",
                previous_hash=row.previous_hash or "",
                record_hash=row.record_hash or "",
                hmac=row.hmac or "",
            )
            for row in rows
        ]

    def dossier_items(db: Session, case: Case) -> list[preflight.DossierItem]:
        items: list[preflight.DossierItem] = []
        for document in case_documents(db, case):
            curated = _curated_analysis(document) or {}
            metadata = curated.get("metadata") or {}
            items.append(
                preflight.DossierItem(
                    document_key=document.document_key,
                    filename=document.filename,
                    content_hash=document.content_hash,
                    date=str(metadata.get("date") or ""),
                    author=str(metadata.get("author") or ""),
                    issuer=str(metadata.get("issuer") or ""),
                )
            )
        return items

    def content_proof_items(db: Session, case: Case) -> list[proofs.ContentItem]:
        items: list[proofs.ContentItem] = []
        for document in case_documents(db, case):
            path = stored_evidence_path(document)
            data = path.read_bytes() if path is not None and path.is_file() else None
            items.append(
                proofs.ContentItem(
                    document_key=document.document_key,
                    content_hash=document.content_hash,
                    stored_bytes=data,
                )
            )
        return items

    def projection_proof_records(
        db: Session, case: Case
    ) -> list[proofs.ProjectionRecord]:
        return [
            proofs.ProjectionRecord(
                document_key=document.document_key,
                rules_hash=document.analysis_rules_hash or "",
                config_hash=document.analysis_config_hash or "",
            )
            for document in case_documents(db, case)
        ]

    def engine_hashes() -> tuple[str, str]:
        """The rules/config hashes the lexicon on disk derives right now.

        Empty on both when the engine cannot be built (lexicon missing): the
        projection proof then reports `not_checked` rather than a pass nobody
        earned or a failure nobody caused.
        """
        try:
            from interface import engine as engine_module

            return engine_module.fingerprint()
        except Exception:
            return "", ""

    def run_case_proofs(db: Session, case: Case) -> list[proofs.Proof]:
        rows = audit_proof_rows(db, case)
        signer = _hmac_signer()
        verify = signer.verify if signer is not None else None
        rules_hash, config_hash = engine_hashes()
        return [
            proofs.chain_proof(rows),
            proofs.hmac_proof(rows, verify),
            proofs.content_proof(content_proof_items(db, case)),
            proofs.projection_proof(
                projection_proof_records(db, case),
                expected_rules_hash=rules_hash,
                expected_config_hash=config_hash,
            ),
            proofs.control_chain_proof(os.getenv("ANCHORUM_CONTROL_DB_PATH")),
        ]

    def preflight_gates(db: Session, case: Case) -> list[preflight.Gate]:
        """Every gate a package must pass, from one place.

        Preview and export both call this, so a preview cannot promise an
        export that the export route then refuses — the divergence that made
        the old preview a decoration rather than a check.
        """
        by_id = {proof.id: proof for proof in run_case_proofs(db, case)}
        return [
            preflight.provenance_gate(dossier_items(db, case)),
            preflight.gate_from_proof(by_id["audit_chain"], blocking=True),
            preflight.gate_from_proof(by_id["audit_hmac"], blocking=True),
            preflight.gate_from_proof(by_id["evidence_content"], blocking=True),
            preflight.gate_from_proof(by_id["projection_rules"], blocking=False),
            preflight.gate_from_proof(by_id["control_chain"], blocking=False),
        ]

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
            # Built once per document, not per hit: a common word matches
            # thousands of times in one exhibit and re-scanning the text for
            # each of them would be quadratic for no gain.
            line_starts = [0] + [i + 1 for i, ch in enumerate(text) if ch == "\n"]
            for match in pattern.finditer(text):
                window_start = max(0, match.start() - SEARCH_CONTEXT_CHARS)
                window_end = min(len(text), match.end() + SEARCH_CONTEXT_CHARS)
                excerpt = " ".join(text[window_start:window_end].split())
                hits.append({
                    "id": document.document_key,
                    "excerpt": excerpt,
                    "offset": match.start(),
                    # 1-based, and the only part of a hit a reader can act on
                    # in a forty-page exhibit: the excerpt shows the words, the
                    # line says where they are.
                    "line": bisect.bisect_right(line_starts, match.start()),
                })
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

    #: Audit actions that record the anchor act itself. They are excluded from
    #: the digest's tip on purpose: publishing a record must not change the
    #: value it published, or the anchor would be stale the instant it existed.
    ANCHOR_ACTIONS = frozenset({"anchor_published", "anchor_failed"})

    def case_digest_now(db: Session, case: Case) -> str:
        """The digest this case's evidence produces right now."""
        hashes = [
            document.content_hash
            for document in case_documents(db, case)
            if document.content_hash
        ]
        tip = db.scalar(
            select(AuditLog)
            .where(
                AuditLog.case_id == case.id,
                AuditLog.action.notin_(tuple(ANCHOR_ACTIONS)),
            )
            .order_by(AuditLog.id.desc())
            .limit(1)
        )
        return anchoring.case_digest(hashes, tip.record_hash if tip else "")

    def anchor_state(db: Session, case: Case) -> dict:
        """What is published, what the evidence says now, and whether they differ.

        Both digests are returned rather than a single verdict: a reader told
        only "stale" cannot see what changed, and the whole point of an anchor
        is that the comparison is theirs to make.
        """
        stored = anchoring.load_record(case.anchor_json)
        current = case_digest_now(db, case)
        configured = anchoring.credentials_configured()
        expected = anchoring.record_name_for(case.case_key)
        if stored is None:
            return {
                "anchored": False,
                "configured": configured,
                "expectedName": expected,
                "currentDigest": current,
                "stale": False,
            }
        return {
            **stored.as_dict(),
            "configured": configured,
            "expectedName": expected,
            "currentDigest": current,
            "stale": stored.digest != current,
        }

    @app.get("/cases/{case_id}/anchor", dependencies=[local_api])
    def get_anchor(case_id: str, db: Session = Depends(get_db)) -> dict:
        return anchor_state(db, find_case(db, case_id))

    @app.post("/cases/{case_id}/anchor", dependencies=[local_api])
    def publish_anchor(case_id: str, db: Session = Depends(get_db)) -> dict:
        case = find_case(db, case_id)
        zone, token = anchoring.credentials()
        if not (zone and token):
            # 501 and not 500: nothing is broken, the deployment simply has no
            # zone to publish into, and the reader cannot fix it from here.
            raise HTTPException(
                status_code=status.HTTP_501_NOT_IMPLEMENTED,
                detail={
                    "error": "ANCHOR_NOT_CONFIGURED",
                    "message": (
                        "No DNS zone is configured for this deployment, so an "
                        "anchor cannot be published from here."
                    ),
                },
            )

        hashes = [d.content_hash for d in case_documents(db, case) if d.content_hash]
        if not hashes:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "ANCHOR_NO_EVIDENCE",
                    "message": "Add evidence before anchoring this case.",
                },
            )

        record = anchoring.build_record(case_digest_now(db, case), case.case_key, zone)
        published, reason = anchoring.publish(record, token)
        if not published:
            # A rejected publication is recorded as a failure and never stored
            # as the case's anchor: the database must not claim a record the
            # zone does not hold.
            _append_audit(
                db,
                case_id=case.id,
                action="anchor_failed",
                details={"reason": reason[:200]},
            )
            db.commit()
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": "ANCHOR_PUBLISH_FAILED",
                    "message": reason,
                },
            )

        case.anchor_json = record.to_json()
        _append_audit(
            db,
            case_id=case.id,
            action="anchor_published",
            details={"digest": record.digest, "recordName": record.record_name},
        )
        db.commit()
        return anchor_state(db, case)

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

        # No signing key is required to store evidence. An absent
        # GDC_EVIDENCE_SECRET means the audit rows for this upload are stored
        # explicitly unsigned (hmac=""), which /audit/verify-proofs reports as
        # `not_checked` / `no_signing_key` and /export refuses to call signed.
        # Refusing the upload instead would make the key a precondition for
        # recording evidence, and a system that cannot record bytes without a
        # key cannot be recovered into a state where one is set.
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

            content_hash = digest.hexdigest()

            # The two durable effects of an upload — the bytes on disk and the
            # row that describes them — are journaled as one unit. If the insert
            # or the commit fails, the reverse action removes the file instead of
            # leaving an orphan whose cleanup the `finally` block can only guess
            # at. This is the seam §6 records: `dossier_enforcement` reaching the
            # HTTP edge, rather than gates protecting the pipeline alone.
            upload_gate = TransactionGate(
                f"evidence-upload-{storage_key}",
                auto_commit=False,
            )
            try:
                upload_gate.__enter__()
                upload_gate.execute_now(
                    lambda: os.replace(temporary_path, stored_file),
                    lambda: stored_file.unlink(missing_ok=True),
                    description="store evidence bytes",
                )
                temporary_path = None
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
                upload_gate.commit()
            except BaseException:
                # Never reverse a gate that already committed: the row is
                # durable and unlinking the file would strand it.
                if not upload_gate.is_committed:
                    try:
                        upload_gate.rollback()
                    except Exception:
                        logger.exception(
                            "evidence upload rollback failed for %s", storage_key
                        )
                raise

            run_analysis(document)
            _custody_log(
                db,
                case_id=case.id,
                evidence_id=document.document_key,
                action="evidence_analysed",
            )
            _record_filed_date(db, case.id, document)
            db.commit()
            try:
                _record_pipeline_custody(document, case_id=case.id)
            except sqlite3.Error as exc:
                logger.exception("evidence was stored but custody recording failed: %s", exc)
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail={
                        "error": "CUSTODY_STORE_UNAVAILABLE",
                        "message": (
                            "Evidence was stored, but its signed custody record "
                            "could not be written."
                        ),
                    },
                ) from exc
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
        except SQLAlchemyError as _exc:
            db.rollback()
            stored_file.unlink(missing_ok=True)
            import logging as _logging
            _logging.getLogger("interface.anchorum_api").exception(
                "evidence metadata save failed: %s", _exc
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "EVIDENCE_METADATA_FAILED",
                    "message": "The local evidence metadata could not be saved.",
                },
            ) from _exc
        finally:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            if not committed:
                stored_file.unlink(missing_ok=True)

    @app.get("/evidence/{evidence_id}", dependencies=[local_api])
    def get_evidence(evidence_id: str, db: Session = Depends(get_db)):
        evidence_id = _require_real_id(evidence_id)
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
        evidence_id = _require_real_id(evidence_id)
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )

        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )
        # The custody list is the audit chain, not the evidence store. The store
        # records what happened to the bytes (INGESTED/VERIFIED); this list is
        # what a reader did with them, and CUSTODY_ACTIONS is its vocabulary.
        # Until this mapping was applied here it was dead code: every audit
        # action was written and none was ever shown.
        entries: list[dict] = []

        # What can honestly be said about the chain on this host. Custody rows
        # are hash-chained inside the audit log; whether those links were
        # *checked* depends on a control chain being present, and an entry that
        # claimed "linked" without one would be claiming a check nobody ran.
        chain_status = "not_checked"
        chain_detail = (
            "No control chain is configured on this host, so custody links "
            "were not checked."
        )
        audit_rows = db.scalars(
            select(AuditLog)
            .where(
                AuditLog.case_id == document.case_id,
                AuditLog.action.in_(tuple(CUSTODY_ACTIONS)),
            )
            .order_by(AuditLog.id.asc())
        ).all()
        for row in audit_rows:
            try:
                details = json.loads(row.details or "{}")
            except (TypeError, ValueError):
                continue
            if not isinstance(details, dict):
                continue
            if details.get("evidenceId") != evidence_id:
                continue
            at = _datetime_text(row.created_at)
            entries.append(
                {
                    "id": f"audit-{row.id}",
                    "custody_id": f"audit-{row.id}",
                    "evidence_id": evidence_id,
                    "actor": row.actor_username or "system",
                    "actor_id": row.actor_username or "system",
                    "action": CUSTODY_ACTIONS[row.action],
                    "at": at,
                    "timestamp_utc": at,
                    "created_at": at,
                    "signature": row.hmac or "",
                    "hmac": row.hmac or "",
                    "previous_custody_hash": row.previous_hash or "",
                    "record_hash": row.record_hash or "",
                    "content_hash": document.content_hash,
                    "chain": chain_status,
                    "chainDetail": chain_detail,
                }
            )

        entries.sort(key=lambda entry: entry.get("at") or "")
        return entries

    @app.get("/items/{evidence_id}/verify", dependencies=[local_api])
    def verify_evidence_custody(evidence_id: str, db: Session = Depends(get_db)):
        evidence_id = _require_real_id(evidence_id)
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "not_found", "message": "Evidence item not found."},
            )
        try:
            EvidenceSigner()
        except EvidenceSignerUnbound:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "signer_unbound",
                    "message": "Verification requires the evidence signing key.",
                },
            ) from None

        from interface.document import open_evidence_store

        try:
            evidence_store = open_evidence_store()
        except FileNotFoundError:
            return {"valid": False, "problems": ["no_custody_events"]}
        try:
            valid, problems = evidence_store.verify_custody_chain(evidence_id)
            return {"valid": valid, "problems": problems}
        except EvidenceSignerUnbound:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "signer_unbound",
                    "message": "Verification requires the evidence signing key.",
                },
            ) from None
        except sqlite3.Error as exc:
            logger.exception("custody verification failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": "CUSTODY_STORE_UNAVAILABLE",
                    "message": "The evidence custody store is unavailable.",
                },
            ) from exc
        finally:
            evidence_store.close()

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
        # Inline, not attachment: the viewer fetches this URL and renders the
        # PDF in place. Starlette defaults `filename=` to attachment, which
        # would still feed PDF.js (it ignores the header and reads the bytes)
        # but would make the plain <a href> fallback download rather than open.
        # "Download" stays an explicit, separate action in the toolbar.
        return FileResponse(
            stored_path,
            media_type=document.media_type or "application/octet-stream",
            filename=document.filename,
            content_disposition_type="inline",
        )

    @app.get("/evidence/{evidence_id}/text", dependencies=[local_api])
    def get_evidence_text(evidence_id: str, db: Session = Depends(get_db)) -> dict:
        """The text analysis extracted from this artifact.

        Every item reports its real extraction status, because the difference
        between "we read it and found nothing" and "we never read it" is the
        difference between a document with no text and a document nobody
        opened. Collapsing those into one empty result would tell a reader
        their exhibit is blank when the connector simply cannot read .docx.

        The text lives in a sidecar beside the stored bytes, never in the
        database, so the record that travels carries no case content.
        """
        document = db.scalar(
            select(Document).where(Document.document_key == evidence_id)
        )
        if document is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail={"error": "NOT_FOUND", "message": "Evidence item not found."},
            )

        extract_status = document.extract_status or "stored"
        payload = {
            "id": document.document_key,
            "status": extract_status,
            "chars": document.extract_chars or 0,
            "sha256": document.extract_sha256 or "",
            "reason": document.extract_error or "",
            "text": None,
            "truncated": False,
        }
        if extract_status != "extracted":
            return payload

        text_path = stored_text_path(document)
        if text_path is None or not text_path.is_file():
            # The row says the text was extracted but the sidecar is gone. That
            # is a storage fault, not an empty document, so it is reported as
            # one rather than as a successful empty read.
            raise HTTPException(
                status_code=status.HTTP_410_GONE,
                detail={
                    "error": "EXTRACTED_TEXT_MISSING",
                    "message": (
                        "The extracted text for this item is recorded but the "
                        "stored copy is missing."
                    ),
                },
            )

        text = text_path.read_text(encoding="utf-8", errors="replace")
        # `chars` is the length of the text actually served, not a value
        # recorded at extraction time. Those can differ — the DB row is a
        # historical record, the sidecar is what is here now — and a count
        # that disagrees with the text it labels is worse than no count.
        # Truncation deliberately leaves `chars` at the full length: a
        # reader needs "showing 200k of 450k", not "200k of 200k".
        payload["chars"] = len(text)
        if len(text) > EXTRACTED_TEXT_LIMIT:
            payload["text"] = text[:EXTRACTED_TEXT_LIMIT]
            payload["truncated"] = True
        else:
            payload["text"] = text
        return payload

    @app.post("/evidence/{evidence_id}/verify", dependencies=[local_api])
    def verify_evidence(evidence_id: str, db: Session = Depends(get_db)):
        evidence_id = _require_real_id(evidence_id)
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
        # Phase 4a: expose unverified_claims in response for fail-visible behavior
        if "unverified_claims" in result:
            return {"id": evidence_id, "consultation": result}
        else:
            return {"id": evidence_id, "consultation": result}

    @app.post("/evidence/{evidence_id}/summarize", dependencies=[local_api])
    def summarize_evidence(evidence_id: str, db: Session = Depends(get_db)):
        from interface import llm_classifier

        document = find_document(db, evidence_id)

        if os.environ.get("ANCHORUM_LLM_ENABLED") != "1":
            # This is a true statement about the installation, not a failure:
            # the button exists, the model is off, and the reader is told which.
            return {
                "id": evidence_id,
                "narrative": None,
                "claims": [],
                "validation": None,
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

        # The page markers let the model count lines within the cited page.
        source_pages = case_source_pages([document])
        pages = source_pages.get(document.filename)
        prompt_text = (
            "\n\n".join(
                f"[PAGE {page_number}]\n{page_text}"
                for page_number, page_text in enumerate(pages, start=1)
            )
            if pages is not None
            else text
        )
        result = llm_classifier.llm_summarize(
            prompt_text,
            filename=document.filename,
        )

        # Validate the source, not the narrative. Every explicit claim's quote
        # must be verbatim in the extracted text or it is rejected and shown as
        # rejected. The narrative is a readable guide; the claims below are what
        # a reader can actually check, and a summary whose claims were never
        # checked is a summary nobody can challenge.
        from interface import tools as _tools

        if result["error"]:
            # The narrative is absent, so there is nothing to check claims
            # against. Saying so is the honest answer; returning zero-verified
            # claims would read as "the model produced nothing worth quoting".
            claims: list[dict] = []
            validation: dict = {
                "verified": 0,
                "inferred": 0,
                "rejected": 0,
                "total": 0,
                "rejected_claims": [],
                "notRun": result["error"],
            }
        else:
            raw_claims, _meta = _tools.extract_claims(text, "inbound-analysis", "")
            claims, validation = _tools.validate_claims(raw_claims, text)

        citation_support: dict = {
            "valid": False,
            "claims": [],
            "validation": {"verified": 0, "inferred": 0, "rejected": 0, "total": 0},
            "error": "SOURCE_PAGE_EXTRACTION_UNAVAILABLE",
        }
        narrative_text = result.get("narrative", "")
        if isinstance(narrative_text, str) and narrative_text.strip():
            cited_text, citation_error = cited_source_text(
                narrative_text,
                source_pages,
            )
            if citation_error:
                citation_support["error"] = citation_error
            else:
                citation_support = _tools.review_narrative_support(
                    narrative_text,
                    cited_text or "",
                )
            if not citation_support.get("valid"):
                result["unverified_claims"] = [
                    *result.get("unverified_claims", []),
                    {
                        "error": citation_support.get("error")
                        or "NARRATIVE_SUPPORT_UNVERIFIED"
                    },
                ]

        generated_at = _datetime_text(datetime.now(timezone.utc))
        # Stored apart from `consultation_json`: the consultation is a
        # second-opinion document type, this is a cited narrative. Writing both
        # into one column meant whichever ran last erased the other.
        document.summary_json = json.dumps(
            {
                "narrative": result,
                "claims": claims,
                "validation": validation,
                "citation_support": citation_support,
                "generatedAt": generated_at,
                "filename": document.filename,
                "textSha256": document.extract_sha256 or "",
            },
            separators=(",", ":"),
        )
        _custody_log(
            db,
            case_id=document.case_id,
            evidence_id=document.document_key,
            action="evidence_summarised",
        )
        db.commit()
        # Phase 4a: expose unverified_claims in response for fail-visible behavior
        if "unverified_claims" in result:
            return {
                "id": evidence_id,
                "narrative": result,
                "claims": claims,
                "validation": validation,
                "citation_support": citation_support,
                "generatedAt": generated_at,
                "cached": bool(result.get("cached")),
                "unverified_claims": result.pop("unverified_claims"),
            }
        else:
            return {
                "id": evidence_id,
                "narrative": result,
                "claims": claims,
                "validation": validation,
                "citation_support": citation_support,
                "generatedAt": generated_at,
                "cached": bool(result.get("cached")),
            }

    @app.get("/evidence/{evidence_id}/summarize", dependencies=[local_api])
    def get_evidence_summary(evidence_id: str, db: Session = Depends(get_db)) -> dict:
        """The stored Saul narrative for this item, if one has been produced.

        A GET so the drawer can be reopened without paying for a second model
        call, and so a reader can see that a summary they were shown earlier is
        still the one on record. `generatedAt` is what makes that checkable.
        """
        document = find_document(db, evidence_id)
        if not document.summary_json:
            return {
                "id": evidence_id,
                "narrative": None,
                "claims": [],
                "validation": None,
                "reason": "NOT_GENERATED",
                "message": "No summary has been generated for this item.",
            }
        try:
            stored = json.loads(document.summary_json)
        except (TypeError, ValueError):
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail={
                    "error": "STORED_SUMMARY_CORRUPT",
                    "message": "The stored summary could not be read.",
                },
            ) from None
        # Phase 4a: expose unverified_claims in cached response for fail-visible behavior
        if "unverified_claims" in stored:
            return {"id": evidence_id, "cached": True, **stored}
        else:
            return {"id": evidence_id, "cached": True, **stored}

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
        response = analysis_response(document)
        # Add deterministic/epistemic metadata
        from interface import tools as _tools
        response = _tools.add_epistemic_fields_to_record(response)
        return response

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
        # The body is a bare array of {id, excerpt, offset}. `offset` is the
        # character position of the match in the sidecar, so a UI can point a
        # reader into a long document instead of leaving them to ctrl-F. Which
        # method ran travels in a header, because substring and token matching
        # do not agree and the difference has to stay visible.
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
    def export_case(
        case_id: str,
        include_summary: bool = True,
        format: str = "zip",
        db: Session = Depends(get_db),
    ):
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
        _raw_by_key: dict[str, bytes] = {}
        for _doc in documents:
            _p = stored_evidence_path(_doc)
            if _p is None or not _p.is_file():
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={"error": "INTEGRITY_CHECK_FAILED", "message": _doc.document_key + ": stored bytes missing"},
                )
            _raw = _p.read_bytes()
            _raw_by_key[_doc.document_key] = _raw
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
            # inv_007 checks only prev.record_hash == new.previous_hash; it
            # does not receive new.record_hash. A row with empty record_hash
            # can pass the invariant when the prior row's hash was also empty
            # (or for the first row). Reject empty hash explicitly so a
            # half-chained DB cannot export.
            if not _log.record_hash:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail={
                        "error": "CUSTODY_CHAIN_BROKEN",
                        "message": f"record {_log.id}: empty record_hash",
                    },
                )
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
            _signer = _hmac_signer()
            if _signer:
                if not _log.hmac:
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error": "AUDIT_HMAC_MISSING",
                            "message": f"record {_log.id}: hmac is empty",
                        },
                    )
                if not _signer.verify(_log.record_hash, _log.hmac):
                    raise HTTPException(
                        status_code=status.HTTP_409_CONFLICT,
                        detail={
                            "error": "AUDIT_HMAC_INVALID",
                            "message": f"record {_log.id}: HMAC mismatch",
                        },
                    )
            _prev = _log

        # Pre-flight, from the same function the preview calls. The chain and
        # content checks above already fail closed; this adds the control chain
        # and records the advisory verdicts inside the package itself, so what
        # a reader receives carries the caveats it was produced under.
        _gates = preflight_gates(db, case)

        # Citation validation gate: fail-closed on export per Critical finding C1
        # The system.txt prompt mandates citations for every factual claim; an
        # exported case must not contain unverified claims.
        _source_pages = case_source_pages(documents, _raw_by_key)
        _citation_gate = preflight.citation_validation_gate(
            documents,
            _source_pages,
        )
        _gates = _gates + [_citation_gate]

        _failed_gate = next(
            (g for g in _gates if g.blocking and g.result == preflight.RESULT_FAIL),
            None,
        )
        if _failed_gate is not None:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={
                    "error": "EXPORT_PREFLIGHT_FAILED",
                    "message": f"{_failed_gate.id}: {_failed_gate.detail or 'failed'}",
                },
            )
        manifest["preflight"] = preflight.manifest_record(_gates)

        if format not in ("zip", "pdf"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error": "INVALID_FORMAT",
                    "message": f"format must be 'zip' or 'pdf', got {format!r}",
                },
            )
        if format == "pdf":
            from interface.export_pdf import build_pdf
            try:
                from dossier_pipeline.disclaimer import format_disclaimer_block
                _disclaimer = format_disclaimer_block()
            except ImportError:
                _disclaimer = "This document is a preparation aid, not legal advice."
            _pdf_bytes = build_pdf(
                case_key=case.case_key,
                title=case.title,
                exported_at=_datetime_text(datetime.now(timezone.utc)),
                approved_by=stamp.approved_by,
                stamp_version=stamp.stamp_version,
                documents=[
                    {
                        "document_key": d.document_key,
                        "filename": d.filename,
                        "byte_size": d.byte_size,
                        "document_type": (_curated_analysis(d) or {}).get("documentType", "unknown"),
                    }
                    for d in documents
                ],
                gates=[g.as_dict() for g in _gates],
                disclaimer=_disclaimer,
            )
            _append_audit(
                db,
                case_id=case.id,
                action="export_produced",
                details={"format": "pdf", "docCount": len(documents)},
                actor="system",
                citations_valid=True,
            )
            db.commit()
            return Response(
                content=_pdf_bytes,
                media_type="application/pdf",
                headers={
                    "Content-Disposition": f'attachment; filename="case_{case.case_key}_report.pdf"'
                },
            )

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
                # The hash is printed beside the id because the narrative is the
                # human-readable half of the package: a reader who cannot match
                # a line here to a manifest entry has been handed two documents
                # about the same case and no way to join them.
                summary_lines.append(
                    f"- `{_doc.document_key}` — {_doc.filename} "
                    f"(type: {_type}, bytes: {_doc.byte_size}, "
                    f"sha256: {_doc.content_hash})"
                )

            summary_lines.extend(["", "## Pre-flight", ""])
            for _gate in _gates:
                _line = f"- {_gate.id}: {_gate.result}"
                if _gate.result != "pass" and _gate.detail:
                    _line += f" ({_gate.detail})"
                if not _gate.blocking:
                    _line += " — advisory"
                summary_lines.append(_line)

            raw_summary = "\n".join(summary_lines) + "\n"

            if sanitize_output is not None:
                # The ids and hashes just written are verification material, not
                # leaked state: they name artifacts this package ships. They are
                # handed over as an exact allowlist, so every *other* digest in
                # the prose is still redacted.
                _shipped = [
                    value
                    for _doc in documents
                    for value in (_doc.document_key, _doc.content_hash)
                    if value
                ]
                report = sanitize_output(raw_summary, trusted_hashes=_shipped)
                if report.leakage_found:
                    raw_summary = (
                        "> **Note**: some text was redacted before export "
                        f"({len(report.redacted_terms)} term(s)).\n\n"
                        + report.sanitized_text
                    )
                else:
                    raw_summary = report.sanitized_text

            if include_summary:
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
        
        _append_audit(
            db,
            case_id=case.id,
            action="export_produced",
            details={"format": "zip", "docCount": len(documents)},
            actor="system",
            citations_valid=True,
        )
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
                "blocking": True,
                "failingItem": restriction_fail,
            },
            {
                "id": "disclaimer",
                "result": "pass",
                "blocking": True,
                "failingItem": None,
            },
            {
                "id": "barreau",
                "result": "fail" if barreau_fail else "pass",
                "blocking": True,
                "failingItem": barreau_fail,
            },
        ]
        # The cryptographic and provenance gates come from the same function
        # the export route calls, so this preview is a prediction of the export
        # rather than a separate, friendlier opinion.
        gates.extend(gate.as_dict() for gate in preflight_gates(db, case))
        # Preview reports the same blocking citation verdict as the export.
        _citation_gate = preflight.citation_validation_gate(
            documents,
            case_source_pages(documents),
        )
        gates.append(_citation_gate.as_dict())
        return {
            "type": type,
            "gates": gates,
            "blocked": any(
                gate["result"] == "fail" and gate.get("blocking", True)
                for gate in gates
            ),
        }




    @app.post("/tools/analyse", dependencies=[local_api])
    async def tools_analyse(
        file: UploadFile = File(...),
        mode: str = Form("inbound-analysis"),
        contractType: str = Form(""),
    ):
        """Non-case, on-demand analysis with citation validation.

        The route uses module-level extract_text / looks_like_pdf / analyse
        (imported at top of this file) so tests can monkeypatch them.
        """
        from interface import tools

        if mode not in ("contract-review", "inbound-analysis"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "INVALID_MODE",
                        "message": "mode must be contract-review or inbound-analysis"},
            )

        data = await file.read()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "EMPTY_FILE", "message": "No bytes received."},
            )
        if len(data) > 20 * 1024 * 1024:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={"error": "FILE_TOO_LARGE",
                        "message": "Document exceeds 20 MB."},
            )

        text = ""
        try:
            if looks_like_pdf(data):
                text = extract_text(data)
            else:
                text = data.decode("utf-8", errors="replace")
        except PdfTextError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "EXTRACTION_FAILED", "message": str(exc)},
            ) from exc
        except Exception as exc:
            logger.warning("tools_analyse: extraction failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={"error": "EXTRACTION_FAILED", "message": type(exc).__name__},
            ) from exc

        analysis: dict = {}
        analysis_ok = False
        try:
            analysis = analyse(data, file.filename or "", file.content_type or "")
            analysis_ok = True
        except Exception as exc:
            logger.warning("tools_analyse: analysis failed: %s", exc)

        raw_claims, extraction_meta = tools.extract_claims(text, mode, contractType)
        claims, validation = tools.validate_claims(raw_claims, text)

        return {
            "document": {
                "filename": file.filename or "",
                "chars": len(text),
                "docType": (analysis.get("documentType") or "unknown"),
                "metadata": (analysis.get("metadata") or {}),
            },
            "extraction": {
                **extraction_meta,
                "analysis_ok": analysis_ok,
            },
            "claims": claims,
            "validation": validation,
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

    @app.post("/cases/{case_id}/audit/verify-proofs", dependencies=[local_api])
    def verify_case_proofs(case_id: str, db: Session = Depends(get_db)) -> dict:
        """Re-derive every cryptographic claim this case makes, and report.

        POST rather than GET because a successful run records an audit row:
        the fact that verification happened is itself part of the case's
        history, and a GET that writes would be a lie about the verb.

        Each proof is computed from the stored bytes and rows at the moment of
        the call. Nothing here consults a previously stored verdict.
        """
        case = find_case(db, case_id)
        results = run_case_proofs(db, case)
        status_value = proofs.overall_status(results)
        failed = [proof.id for proof in results if proof.status == proofs.STATUS_FAIL]
        payload = {
            "caseId": _case_id(case),
            "status": status_value,
            "verifiedAt": _datetime_text(datetime.now(timezone.utc)),
            "proofs": [proof.as_dict() for proof in results],
        }
        _append_audit(
            db,
            case_id=case.id,
            action="proofs_verified",
            details={"status": status_value, "failed": failed},
            actor="system",
        )
        db.commit()
        return payload

    @app.get("/cases/{case_id}/audit", dependencies=[local_api])
    def get_case_audit(case_id: str, db: Session = Depends(get_db)):
        case = find_case(db, case_id)
        logs = db.scalars(
            select(AuditLog)
            .where(AuditLog.case_id == case.id)
            .order_by(AuditLog.created_at.asc(), AuditLog.id.asc())
        ).all()
        rows = []
        prev_log = None
        for log in logs:
            try:
                details = json.loads(log.details or "{}")
            except (TypeError, ValueError):
                details = {}
            # `chain` = evidence-verification outcome for evidence_verified rows,
            # not_checked otherwise. Unchanged from the pre-2026 behaviour.
            chain = "not_checked"
            failing = None
            if log.action == "evidence_verified":
                failing = details.get("failingStep")
                chain = "broken" if failing else "linked"

            # `chainIntegrity` = audit-chain state, orthogonal to evidence
            # verification. A row is "linked" only if its own record_hash is
            # non-empty AND its previous_hash matches the prior row's
            # record_hash (or, for the first row, previous_hash is empty).
            prev_hash_matches = (
                (prev_log is None and not log.previous_hash)
                or (prev_log is not None and log.previous_hash == prev_log.record_hash)
            )
            has_hash = bool(log.record_hash)
            chain_integrity = "linked" if (prev_hash_matches and has_hash) else "broken"

            row = {
                "id": f"log-{log.id}",
                "event": log.action,
                "at": _datetime_text(log.created_at),
                "actor": log.actor_username,
                "evidenceId": details.get("evidenceId"),
                "chain": chain,
                "chainIntegrity": chain_integrity,
                "recordHash": log.record_hash,
                "previousHash": log.previous_hash,
            }
            if failing:
                row["failingStep"] = failing
            if log.action == "member_role_changed":
                row["memberId"] = details.get("memberId")
                row["previousRole"] = details.get("previousRole")
                row["role"] = details.get("role")
                row["reason"] = details.get("reason")
            rows.append(row)
            prev_log = log
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
        _append_audit(
            db,
            case_id=None,
            action="member_role_changed",
            details={"memberId": str(user.id), "previousRole": old_role, "role": role, "reason": reason},
            actor="system",
        )
        db.commit()
        return {
            "id": str(user.id),
            "name": user.username.split("@")[0],
            "email": user.username,
            "role": user.role,
            "status": "active",
            "caseIds": [],
        }

    # ------------------------------------------------------------------
    # Wire 8 — email intake (the case's front door for .eml)
    # ------------------------------------------------------------------

    def intake_seen_set(case: Case):
        """The per-case dedupe set for submitted messages.

        Kept on disk beside the evidence rather than in memory, because "have I
        already processed this email" is a question that has to survive a
        restart. The database is keyed by case so two cases can hold the same
        message without either hiding the other.
        """
        from dossier_pipeline.intake import EmailSeenSet

        directory = storage_root / "intake"
        directory.mkdir(parents=True, exist_ok=True)
        return EmailSeenSet(str(directory / f"case-{case.id}-seen.db"))

    def store_intake_message(
        db: Session,
        case: Case,
        raw_bytes: bytes,
        filename: str,
        body_text: str,
        source_sha256: str,
    ) -> Document:
        """Store a submitted .eml as case evidence, with its body readable.

        The bytes go through the same guard as any other artifact: a uuid4
        storage key, a hash of what was written, and a readback that must match.
        The difference is the extracted text: analysis has no MIME reader, so an
        .eml would otherwise open as an unreadable artifact even though the
        intake stage just parsed it. The body the parser produced is written as
        the text sidecar, which is the text that was actually read.
        """
        storage_key = uuid.uuid4().hex
        target = storage_root / f"{storage_key}.bin"
        storage_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="wb", prefix=".intake-", dir=storage_root, delete=False
        ) as destination:
            temporary = Path(destination.name)
            destination.write(raw_bytes)
            destination.flush()
            os.fsync(destination.fileno())
        try:
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)

        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        document = Document(
            case_id=case.id,
            document_key=f"E-{storage_key}",
            filename=filename,
            content_hash=digest,
            storage_key=storage_key,
            media_type="message/rfc822",
            category="correspondence",
            source="other",
            byte_size=len(raw_bytes),
        )
        db.add(document)
        db.flush()

        text_path = stored_text_path(document)
        if text_path is not None and body_text.strip():
            text_path.write_text(body_text, encoding="utf-8")
            document.extract_text_path = text_path.name
            document.extract_status = "extracted"
            document.extract_sha256 = hashlib.sha256(
                body_text.encode("utf-8")
            ).hexdigest()
            document.extract_chars = len(body_text)
            document.analysed_at = datetime.now(timezone.utc)
        else:
            # No readable body: run the ordinary analysis so the row says why
            # rather than claiming a read that produced nothing.
            run_analysis(document)

        _custody_log(
            db,
            case_id=case.id,
            evidence_id=document.document_key,
            action="evidence_uploaded",
        )
        return document

    @app.post("/cases/{case_id}/intake/email", dependencies=[local_api])
    async def intake_email(
        case_id: str,
        files: list[UploadFile] = File(...),
        db: Session = Depends(get_db),
    ) -> dict:
        """Run uploaded `.eml` files through envelope → classifier → policy.

        One message's failure does not abort the batch: each file is processed
        and reported on its own, because a reader dropping five emails expects
        four verdicts and one error, not one error.

        A message that passes policy is stored as case evidence and its custody
        recorded. A message that policy rejects is stored too — the point of a
        quarantine is that the artifact is kept and not acted on, and dropping it
        would destroy the evidence of the decision. A duplicate is neither
        stored again nor re-classified.
        """
        from interface import email_intake

        case = find_case(db, case_id)
        if not files:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "error": "EMPTY_INTAKE",
                    "message": "Attach at least one .eml file.",
                },
            )

        results: list[dict] = []
        seen = intake_seen_set(case)
        try:
            for upload in files:
                filename = (
                    (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1].strip()
                )
                if (
                    not filename
                    or filename in (".", "..")
                    or any(ord(c) < 0x20 or ord(c) == 0x7F for c in filename)
                    or len(filename) > MAX_FILENAME_LENGTH
                ):
                    results.append(
                        {
                            "filename": filename or "(unnamed)",
                            "status": email_intake.OUTCOME_FAILED,
                            "stages": [
                                {
                                    "id": email_intake.STAGE_RECEIVED,
                                    "status": email_intake.STATUS_FAILED,
                                    "detail": "Upload a file with a valid name.",
                                    "data": {"error": "INVALID_FILENAME"},
                                }
                            ],
                            "reason": "INVALID_FILENAME",
                        }
                    )
                    continue

                data = await upload.read()
                if not data:
                    results.append(
                        {
                            "filename": filename,
                            "status": email_intake.OUTCOME_FAILED,
                            "stages": [
                                {
                                    "id": email_intake.STAGE_RECEIVED,
                                    "status": email_intake.STATUS_FAILED,
                                    "detail": "The file is empty.",
                                    "data": {"error": "EMPTY_UPLOAD"},
                                }
                            ],
                            "reason": "EMPTY_UPLOAD",
                        }
                    )
                    continue
                if len(data) > MAX_UPLOAD_BYTES:
                    results.append(
                        {
                            "filename": filename,
                            "status": email_intake.OUTCOME_FAILED,
                            "stages": [
                                {
                                    "id": email_intake.STAGE_RECEIVED,
                                    "status": email_intake.STATUS_FAILED,
                                    "detail": (
                                        f"The message exceeds the "
                                        f"{MAX_UPLOAD_BYTES} byte limit."
                                    ),
                                    "data": {"error": "MESSAGE_TOO_LARGE"},
                                }
                            ],
                            "reason": "MESSAGE_TOO_LARGE",
                        }
                    )
                    continue

                outcome = email_intake.run(data, filename, seen)
                payload = outcome.as_dict()

                if outcome.status == email_intake.OUTCOME_DUPLICATE:
                    _append_audit(
                        db,
                        case_id=case.id,
                        action="email_intake_duplicate",
                        details={
                            "messageId": outcome.message_id,
                            "sourceSha256": outcome.source_sha256,
                            "filename": filename,
                        },
                    )
                    db.commit()
                    results.append(payload)
                    continue

                if outcome.status in (
                    email_intake.OUTCOME_PROCESSED,
                    email_intake.OUTCOME_REJECTED_POLICY,
                ):
                    # The raw message is the artifact; the body text is what the
                    # parser read out of it. Storing both keeps the exhibit and
                    # the text a reader can search in the same place.
                    document = store_intake_message(
                        db,
                        case,
                        data,
                        filename,
                        outcome.body_text,
                        outcome.source_sha256,
                    )
                    payload["evidenceId"] = document.document_key
                    seen.mark_seen(outcome.message_id, outcome.source_sha256)
                    _append_audit(
                        db,
                        case_id=case.id,
                        action=(
                            "email_intake_processed"
                            if outcome.status == email_intake.OUTCOME_PROCESSED
                            else "email_intake_rejected_policy"
                        ),
                        details={
                            "evidenceId": document.document_key,
                            "messageId": outcome.message_id,
                            "sourceSha256": outcome.source_sha256,
                            "subject": outcome.subject,
                            "sender": outcome.sender,
                            "actor": outcome.actor,
                            "labels": outcome.labels,
                            "policyAllowed": outcome.policy_allowed,
                            "policyQuarantine": outcome.policy_quarantine,
                            "reason": outcome.policy_reason,
                        },
                    )
                    db.commit()
                    results.append(payload)
                    continue

                _append_audit(
                    db,
                    case_id=case.id,
                    action="email_intake_failed",
                    details={
                        "messageId": outcome.message_id,
                        "sourceSha256": outcome.source_sha256,
                        "filename": filename,
                        "reason": outcome.reason,
                    },
                )
                db.commit()
                results.append(payload)
        finally:
            seen.close()

        counts = {
            "processed": sum(
                1 for r in results if r["status"] == email_intake.OUTCOME_PROCESSED
            ),
            "rejectedPolicy": sum(
                1
                for r in results
                if r["status"] == email_intake.OUTCOME_REJECTED_POLICY
            ),
            "duplicate": sum(
                1 for r in results if r["status"] == email_intake.OUTCOME_DUPLICATE
            ),
            "failed": sum(
                1 for r in results if r["status"] == email_intake.OUTCOME_FAILED
            ),
        }
        return {
            "caseId": _case_id(case),
            "files": results,
            "summary": counts,
        }

    return app


app = create_app()

# --- EMAIL INGESTION ROUTER ---
try:
    from interface.collect.email_threads.router import router as email_router
    app.add_middleware(AuthMiddleware)
    app.include_router(email_router)
    app.include_router(board_router)
except ImportError:
    pass
