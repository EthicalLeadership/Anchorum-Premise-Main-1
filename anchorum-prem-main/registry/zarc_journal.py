"""
Plane 1 (kernel/domain/application/governance): Monotonic clock and chain journal.

Provides a side-effect-free monotonic nanosecond clock, deterministic chain
hash computation, and optional journal history tracking with injectable clocks.
"""

from __future__ import annotations

import hashlib
import threading
import time
from dataclasses import dataclass
from typing import Callable, ClassVar, List, Optional

ClockFn = Callable[[], int]


@dataclass(frozen=True)
class JournalRecord:
    """Immutable audit/chain record tracked by ZarcJournal."""

    sequence: int
    timestamp_ns: int
    key_id: str
    predecessor_key_id: Optional[str]
    chain_hash: str
    detail: str = ""


class ZarcJournal:
    """
    Monotonic nanosecond clock and chain-hash helper for Anchorum-prem.

    Performs no clock or I/O side effects at module import time.
    """

    _lock: ClassVar[threading.Lock] = threading.Lock()
    _default_clock: ClassVar[ClockFn] = time.monotonic_ns
    _last_ns: ClassVar[int] = 0

    def __init__(self, clock_ns: Optional[ClockFn] = None) -> None:
        self._clock_ns: ClockFn = clock_ns or self._default_clock
        self._instance_lock = threading.Lock()
        self._history: List[JournalRecord] = []
        self._seq: int = 0

    @classmethod
    def set_default_clock(cls, clock_ns: Optional[ClockFn]) -> None:
        """Override or reset (when None) the class-level clock provider."""
        with cls._lock:
            cls._default_clock = clock_ns if clock_ns is not None else time.monotonic_ns
            cls._last_ns = 0

    @classmethod
    def now_ns(cls) -> int:
        """Return a strictly non-decreasing nanosecond timestamp."""
        with cls._lock:
            raw_ns = int(cls._default_clock())
            if raw_ns < cls._last_ns:
                raw_ns = cls._last_ns
            cls._last_ns = raw_ns
            return raw_ns

    @staticmethod
    def compute_chain_hash(
        predecessor_key_id: Optional[str],
        public_key: bytes,
        previous_chain_hash: str = "",
    ) -> str:
        """Compute deterministic hash linking predecessor, public key, and prior chain."""
        pub_hex = public_key.hex()
        prefix = f"{previous_chain_hash}|" if previous_chain_hash else ""
        if predecessor_key_id is None:
            raw = f"{prefix}root|{pub_hex}".encode("utf-8")
        else:
            raw = f"{prefix}{predecessor_key_id}:{pub_hex}".encode("utf-8")
        return hashlib.sha256(raw).hexdigest()

    def record(
        self,
        key_id: str,
        public_key: bytes,
        predecessor_key_id: Optional[str] = None,
        previous_chain_hash: str = "",
        detail: str = "",
    ) -> JournalRecord:
        """Append a chain-linked record to this journal instance."""
        with self._instance_lock:
            ts = int(self._clock_ns())
            self._seq += 1
            chain_hash = self.compute_chain_hash(
                predecessor_key_id=predecessor_key_id,
                public_key=public_key,
                previous_chain_hash=previous_chain_hash,
            )
            entry = JournalRecord(
                sequence=self._seq,
                timestamp_ns=ts,
                key_id=key_id,
                predecessor_key_id=predecessor_key_id,
                chain_hash=chain_hash,
                detail=detail,
            )
            self._history.append(entry)
            return entry

    def get_key_history(self) -> List[JournalRecord]:
        """Return a shallow copy of recorded journal entries."""
        with self._instance_lock:
            return self._history.copy()
