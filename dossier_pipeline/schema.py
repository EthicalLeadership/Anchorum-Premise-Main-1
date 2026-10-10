"""
Dossier DOSSIER-PIPELINE — SQLAlchemy Schema

Declarative ORM models for the core production entities: cases, documents,
users, audit logs, and jurisdiction stamps.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (Column, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint, create_engine)
from sqlalchemy.orm import Session, relationship, sessionmaker

try:
    # SQLAlchemy >= 2.0
    from sqlalchemy.orm import (DeclarativeBase, Mapped,  # type: ignore
                                mapped_column)

    class Base(DeclarativeBase):
        pass

except ImportError:
    # SQLAlchemy < 2.0 compatibility
    from typing import Any

    from sqlalchemy.ext.declarative import declarative_base

    Mapped = Any  # type: ignore

    def mapped_column(*args, **kwargs):
        return Column(*args, **kwargs)

    Base = declarative_base()


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_key: Mapped[str] = mapped_column(String(128), unique=True, nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    jurisdiction: Mapped[str] = mapped_column(String(64), nullable=False)
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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

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
    case_id: Mapped[int] = mapped_column(ForeignKey("cases.id", ondelete="CASCADE"), nullable=False, index=True)
    actor_username: Mapped[str] = mapped_column(String(128), nullable=False)
    action: Mapped[str] = mapped_column(String(128), nullable=False)
    details: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now, nullable=False)

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


def get_session(session_factory) -> Session:
    return session_factory()
