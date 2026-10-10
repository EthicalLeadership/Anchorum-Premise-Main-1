"""
Dossier DOSSIER-PIPELINE — Transaction / Rollback Layer

Provides a unit-of-work envelope across the pipeline's SQLite stores. The
implementation is intentionally conservative: it coordinates BEGIN/COMMIT/
ROLLBACK across the known store connections and exposes a journal for recovery
and replay visibility.
"""

from __future__ import annotations

import datetime
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Optional, Protocol,
                    runtime_checkable)


class StoreOpenError(RuntimeError):
    pass


class BeginError(RuntimeError):
    pass


class CommitError(RuntimeError):
    pass


class RollbackError(RuntimeError):
    pass


class JournalReplayError(RuntimeError):
    pass


@dataclass(frozen=True)
class JournalEntry:
    sequence_no: int
    timestamp_utc: str
    store_name: str
    operation: str
    payload: Dict[str, Any]


@dataclass
class TransactionJournal:
    entries: List[JournalEntry] = field(default_factory=list)

    def record(self, store_name: str, operation: str, payload: Dict[str, Any]) -> JournalEntry:
        entry = JournalEntry(
            sequence_no=len(self.entries) + 1,
            timestamp_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
            store_name=store_name,
            operation=operation,
            payload=payload,
        )
        self.entries.append(entry)
        return entry

    def to_json(self) -> List[Dict[str, Any]]:
        return [entry.__dict__ for entry in self.entries]


@runtime_checkable
class SupportsConnection(Protocol):
    conn: sqlite3.Connection


class PipelineTransaction:
    """
    Coordinates SQLite transactions across the pipeline stores.

    This layer is used as a unit-of-work boundary around the main pipeline run.
    It can only guarantee true atomicity if the participating stores honor the
    same transaction scope for their writes; otherwise it still provides a
    centralized recovery/journal interface and a consistent orchestration API.
    """

    def __init__(self, stores: Dict[str, SupportsConnection], journal_path: str):
        self.stores = stores
        self.journal_path = Path(journal_path)
        self.journal_path.parent.mkdir(parents=True, exist_ok=True)
        self.journal = TransactionJournal()
        self._active = False

    def begin(self) -> "PipelineTransaction":
        if self._active:
            return self

        try:
            for name, store in self.stores.items():
                store.conn.execute("BEGIN IMMEDIATE")
                self.journal.record(name, "begin", {})
            self._active = True
            return self
        except Exception as exc:
            self.rollback()
            raise BeginError(str(exc)) from exc

    def commit(self) -> None:
        if not self._active:
            return

        try:
            for name, store in self.stores.items():
                store.conn.commit()
                self.journal.record(name, "commit", {})
        except Exception as exc:
            self.rollback()
            raise CommitError(str(exc)) from exc
        finally:
            self._active = False
            self._persist_journal()

    def rollback(self) -> None:
        errors: list[str] = []
        for name, store in self.stores.items():
            try:
                store.conn.rollback()
                self.journal.record(name, "rollback", {})
            except Exception as exc:
                errors.append(f"{name}: {exc}")
        self._active = False
        self._persist_journal()
        if errors:
            raise RollbackError("; ".join(errors))

    def savepoint(self, name: str) -> None:
        if not self._active:
            raise RuntimeError("Transaction is not active")
        for store in self.stores.values():
            store.conn.execute(f"SAVEPOINT {name}")
        self.journal.record("system", "savepoint", {"name": name})

    def rollback_to_savepoint(self, name: str) -> None:
        if not self._active:
            raise RuntimeError("Transaction is not active")
        for store in self.stores.values():
            store.conn.execute(f"ROLLBACK TO SAVEPOINT {name}")
            store.conn.execute(f"RELEASE SAVEPOINT {name}")
        self.journal.record("system", "rollback_to_savepoint", {"name": name})
        self._persist_journal()

    def recover(self) -> List[str]:
        """
        Best-effort recovery hook.

        For each known store, we look for a journal and ensure the connection is
        left in a clean state. Since the stores already persist their own state,
        recovery is intentionally conservative and primarily meant to clear any
        orphaned in-flight transaction scope from a prior crash.
        """
        recovered: List[str] = []
        for name, store in self.stores.items():
            try:
                store.conn.rollback()
                recovered.append(name)
            except Exception:
                continue
        self._persist_journal()
        return recovered

    def _persist_journal(self) -> None:
        payload = {
            "exported_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "entries": self.journal.to_json(),
        }
        self.journal_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8")

    def __enter__(self) -> "PipelineTransaction":
        return self.begin()

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if exc_type is None:
            self.commit()
        else:
            self.rollback()
        return False


class TransactionalWriteRouter:
    """
    Compatibility wrapper that records intent in the journal before delegating
    to the underlying write router.
    """

    def __init__(self, router, transaction: PipelineTransaction):
        self.router = router
        self.transaction = transaction

    def mark_seen(self, message_id: str, sha256: str):
        self.transaction.journal.record("seen", "mark_seen", {"message_id": message_id, "sha256": sha256})
        return self.router.mark_seen(message_id, sha256)

    def register_send(self, **kwargs):
        self.transaction.journal.record("outbound", "register_send", dict(kwargs))
        return self.router.register_send(**kwargs)

    def ingest_evidence(self, **kwargs):
        self.transaction.journal.record("evidence", "ingest_evidence", dict(kwargs))
        return self.router.ingest_evidence(**kwargs)

    def record_replay(self, event_type: str, payload: dict[str, Any]):
        self.transaction.journal.record("replay", event_type, dict(payload))
        return self.router.record_replay(event_type, payload)
