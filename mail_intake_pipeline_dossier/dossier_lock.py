"""
Dossier DOSSIER-PIPELINE Dossier-Scoped Execution Lock

Provides a coarse-grained SQLite-backed mutual exclusion primitive that
serializes pipeline execution per dossier across processes and workers.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional


class DossierExecutionLock:
    """
    A dossier-scoped lock implemented with SQLite BEGIN IMMEDIATE.

    The connection is kept open for the duration of the critical section so the
    RESERVED lock remains held across the full pipeline execution.
    """

    def __init__(self, lock_path: str):
        self.lock_path = lock_path
        Path(lock_path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(lock_path, timeout=30, check_same_thread=False)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dossier_locks (
                dossier_id TEXT PRIMARY KEY,
                acquired_at TEXT NOT NULL
            )
            """
        )
        self.conn.commit()
        self._held_dossier_id: Optional[str] = None

    def acquire(self, dossier_id: str, acquired_at: str) -> None:
        if self._held_dossier_id is not None:
            raise RuntimeError("Lock already held")
        self.conn.execute("BEGIN IMMEDIATE")
        self.conn.execute(
            """
            INSERT OR REPLACE INTO dossier_locks (dossier_id, acquired_at)
            VALUES (?, ?)
            """,
            (dossier_id, acquired_at),
        )
        self._held_dossier_id = dossier_id

    def release(self) -> None:
        if self._held_dossier_id is None:
            return
        try:
            self.conn.rollback()
        finally:
            self._held_dossier_id = None

    def close(self) -> None:
        try:
            self.release()
        finally:
            self.conn.close()
