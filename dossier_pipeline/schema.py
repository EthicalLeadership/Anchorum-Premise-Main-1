"""
Dossier DOSSIER-PIPELINE SQLAlchemy Schema

Declarative ORM models for the core production entities: cases, documents,
users, audit logs, and jurisdiction stamps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional, TypeAlias

from sqlalchemy import (Boolean, CheckConstraint, Column, DateTime, Float,
                        ForeignKey, Integer, String, Text, UniqueConstraint,
                        create_engine, inspect)
from sqlalchemy.orm import Mapped, Session, relationship, sessionmaker

try:
    # SQLAlchemy >= 2.0
    from sqlalchemy.orm import DeclarativeBase, mapped_column  # type: ignore

    class Base(DeclarativeBase):
        pass

except ImportError:
    # SQLAlchemy < 2.0 compatibility
    from typing import Any

    from sqlalchemy.ext.declarative import declarative_base

    # Keep the fallback compatible with SQLAlchemy's typing API for static
    # analyzers, while avoiding a runtime variable redefinition that pyright
    # treats as an invalid type expression when used in `Mapped[...]` fields.
    if TYPE_CHECKING:
        Mapped: TypeAlias = Any  # type: ignore[assignment]
    else:
        Mapped = Any

    # SQLAlchemy < 2.0 does not provide mapped_column(), but Column is a
    # compatible drop-in for the model definitions used here.
    mapped_column: Any = Column  # type: ignore[assignment]

    Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
    matter_type: Mapped[str] = mapped_column(String(64), nullable=False, default="general")
    description: Mapped[str] = mapped_column(Text, nullable=False, default="")
    timezone: Mapped[str] = mapped_column(String(128), nullable=False, default="UTC")
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="open")
    owner_user_id: Mapped[str] = mapped_column(String(128), nullable=False, default="local-operator")
    #: The exported anchor record (JSON), once an operator has published this
    #: case's digest to a public zone. Empty means "not anchored" — never "we
    #: tried and it probably worked".
    anchor_json: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    documents: Mapped[list["Document"]] = relationship(
        "Document",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    audit_logs: Mapped[list["AuditLog"]] = relationship(
        "AuditLog",
        back_populates="case",
        cascade="all, delete-orphan",
    )
    jurisdiction_stamp: Mapped[Optional["JurisdictionStamp"]] = relationship(
        "JurisdictionStamp",
        back_populates="case",
        cascade="all, delete-orphan",
        uselist=False,
    )


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    document_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    storage_key: Mapped[Optional[str]] = mapped_column(String(64), unique=True, nullable=True)
    media_type: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    category: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    source: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    consultation_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    #: The Saul narrative for this document, stored apart from
    #: `consultation_json`. The two are different answers to different
    #: questions — a second-opinion document type, and a cited summary — and
    #: keeping them in one column meant whichever ran last erased the other.
    summary_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    byte_size: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    # W3 analysis fields
    extract_status: Mapped[str] = mapped_column(String(32), default="stored", nullable=False)
    extract_error: Mapped[str] = mapped_column(Text, default="", nullable=False)
    extract_sha256: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    extract_chars: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    extract_text_path: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    analysis_json: Mapped[str] = mapped_column(Text, default="", nullable=False)
    analysis_rules_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    analysis_config_hash: Mapped[str] = mapped_column(String(64), default="", nullable=False)
    analysed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="documents")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    role: Mapped[str] = mapped_column(String(64), nullable=False, default="viewer")
    credential_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)


class AuditLog(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[Optional[int]] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=True, index=True)
    actor_username: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    previous_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    record_hash: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    hmac: Mapped[str] = mapped_column(String(64), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)
    citations_valid: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    case: Mapped["Case"] = relationship("Case", back_populates="audit_logs")


class JurisdictionStamp(Base):
    __tablename__ = "jurisdiction_stamps"
    __table_args__ = (UniqueConstraint("case_id", name="uq_jurisdiction_stamp_case_id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    stamp_version: Mapped[str] = mapped_column(String(32), nullable=False)
    approved_by: Mapped[str] = mapped_column(String(128), nullable=False)
    applied_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

    case: Mapped["Case"] = relationship("Case", back_populates="jurisdiction_stamp")


def create_engine_and_session(database_url: str):
    engine = create_engine(database_url, future=True)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return engine, session_factory


def init_schema(engine) -> None:
    Base.metadata.create_all(bind=engine)
    if engine.dialect.name == "sqlite":
        additions = {
            "matter_type": "VARCHAR(64) NOT NULL DEFAULT 'general'",
            "description": "TEXT NOT NULL DEFAULT ''",
            "timezone": "VARCHAR(128) NOT NULL DEFAULT 'UTC'",
            "status": "VARCHAR(32) NOT NULL DEFAULT 'open'",
            "owner_user_id": "VARCHAR(128) NOT NULL DEFAULT 'local-operator'",
            "anchor_json": "TEXT NOT NULL DEFAULT ''",
        }
        existing = {
            column["name"] for column in inspect(engine).get_columns("cases")
        }
        with engine.begin() as connection:
            for name, definition in additions.items():
                if name not in existing:
                    connection.exec_driver_sql(
                        f"ALTER TABLE cases ADD COLUMN {name} {definition}"
                    )
        document_additions = {
            "storage_key": "VARCHAR(64)",
            "media_type": "VARCHAR(255)",
            "byte_size": "INTEGER NOT NULL DEFAULT 0",
            "extract_status": "VARCHAR(32) NOT NULL DEFAULT 'stored'",
            "extract_error": "TEXT NOT NULL DEFAULT ''",
            "extract_sha256": "VARCHAR(64) NOT NULL DEFAULT ''",
            "extract_chars": "INTEGER NOT NULL DEFAULT 0",
            "extract_text_path": "VARCHAR(255) NOT NULL DEFAULT ''",
            "analysis_json": "TEXT NOT NULL DEFAULT ''",
            "analysis_rules_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "analysis_config_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "analysed_at": "DATETIME",
            "category": "VARCHAR(64)",
            "source": "VARCHAR(64)",
            "consultation_json": "TEXT",
            "summary_json": "TEXT",
            "previous_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
            "record_hash": "VARCHAR(64) NOT NULL DEFAULT ''",
        }
        existing_documents = {
            column["name"] for column in inspect(engine).get_columns("documents")
        }
        with engine.begin() as connection:
            for name, definition in document_additions.items():
                if name not in existing_documents:
                    connection.exec_driver_sql(
                        f"ALTER TABLE documents ADD COLUMN {name} {definition}"
                    )
        existing_audit_logs = {
            column["name"] for column in inspect(engine).get_columns("audit_logs")
        }
        if "citations_valid" not in existing_audit_logs:
            with engine.begin() as connection:
                connection.exec_driver_sql(
                    "ALTER TABLE audit_logs ADD COLUMN citations_valid BOOLEAN"
                )


def get_session(session_factory) -> Session:
    return session_factory()
class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True)
    case_id = Column(Integer, ForeignKey("cases.id"), nullable=False, index=True)
    message_key = Column(String(256), nullable=False, unique=True)
    timestamp_occurred = Column(DateTime(timezone=True), nullable=True)
    timestamp_captured = Column(DateTime(timezone=True), nullable=False)
    source_hash = Column(String(64), nullable=False, index=True)
    source_filename = Column(String(256), nullable=False)
    source_locator_json = Column(Text, nullable=False, default="{}")
    body_text = Column(Text, nullable=True)
    subject = Column(String(512), nullable=True)
    sender = Column(String(256), nullable=True)
    recipient = Column(String(256), nullable=True)
    message_type = Column(String(64), nullable=False)
    previous_hash = Column(String(64), nullable=False, default="")
    current_hash = Column(String(64), nullable=False, default="")

    __table_args__ = (
        CheckConstraint("length(source_hash) = 64", name="ck_source_hash_length"),
    )

class Finding(Base):
    __tablename__ = "findings"

    id = Column(Integer, primary_key=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=False, index=True)
    finding_key = Column(String(256), nullable=False, unique=True)
    category = Column(String(128), nullable=False)
    severity = Column(String(64), nullable=True)
    confidence = Column(Float, nullable=True)
    description = Column(Text, nullable=False)
    evidence_refs = Column(Text, nullable=True)
    analyzed_at = Column(DateTime(timezone=True), nullable=False)
    analyzer = Column(String(256), nullable=True)
    analysis_version = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="candidate")

class Decision(Base):
    __tablename__ = "decisions"

    id = Column(Integer, primary_key=True)
    finding_id = Column(Integer, ForeignKey("findings.id"), nullable=False, index=True)
    decision_key = Column(String(256), nullable=False, unique=True)
    decided_by = Column(String(256), nullable=False)
    decided_at = Column(DateTime(timezone=True), nullable=False)
    decision_version = Column(String(32), nullable=False)
    reasoning = Column(Text, nullable=False)
    outcome = Column(String(128), nullable=False)
    policy_refs = Column(Text, nullable=True)
    status = Column(String(32), nullable=False)
    revoked_by = Column(String(256), nullable=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)