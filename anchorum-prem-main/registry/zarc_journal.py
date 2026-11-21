"""
Plane 1 (kernel/domain/application/governance): Monotonic clock and chain journal.

Provides a side-effect-free monotonic nanosecond clock, collision-free
canonical chain-hash computation, chain verification, and monotonic journal
record tracking with injectable clocks.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
import time
from dataclasses import dataclass
from typing import Callable, ClassVar, List, Mapping, Optional, Sequence

ClockFn = Callable[[], int]

_HEX_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


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
        if clock_ns is not None and not callable(clock_ns):
            raise TypeError("clock_ns must be callable or None")
        self._clock_ns: ClockFn = clock_ns if clock_ns is not None else self._default_clock
        self._instance_lock = threading.Lock()
        self._history: List[JournalRecord] = []
        self._seq: int = 0
        self._last_record_ns: int = 0

    @classmethod
    def set_default_clock(cls, clock_ns: Optional[ClockFn]) -> None:
        """Override or reset (when None) the class-level clock provider."""
        if clock_ns is not None and not callable(clock_ns):
            raise TypeError("clock_ns must be callable or None")
        with cls._lock:
            cls._default_clock = clock_ns if clock_ns is not None else time.monotonic_ns
            cls._last_ns = 0

    @classmethod
    def now_ns(cls) -> int:
        """Return a strictly non-decreasing class-level nanosecond timestamp."""
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
        """Compute collision-free deterministic hash over structured chain fields."""
        key_bytes = bytes(public_key)
        if not key_bytes:
            raise ValueError("public_key must not be empty")

        canonical_obj = {
            "v": 1,
            "previous_chain_hash": previous_chain_hash,
            "predecessor_key_id": predecessor_key_id,
            "public_key_hex": key_bytes.hex(),
        }
        canonical_bytes = json.dumps(
            canonical_obj,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
        return hashlib.sha256(canonical_bytes).hexdigest()

    def record(
        self,
        key_id: str,
        public_key: bytes,
        predecessor_key_id: Optional[str] = None,
        previous_chain_hash: str = "",
        detail: str = "",
    ) -> JournalRecord:
        """Append a monotonic, chain-linked record to this journal instance."""
        if not isinstance(key_id, str) or not key_id.strip():
            raise ValueError("key_id must be a non-empty string")
        key_bytes = bytes(public_key)
        if not key_bytes:
            raise ValueError("public_key must not be empty")

        chain_hash = self.compute_chain_hash(
            predecessor_key_id=predecessor_key_id,
            public_key=key_bytes,
            previous_chain_hash=previous_chain_hash,
        )

        with self._instance_lock:
            raw_ts = int(self._clock_ns())
            if raw_ts < self._last_record_ns:
                raw_ts = self._last_record_ns
            self._last_record_ns = raw_ts

            self._seq += 1
            entry = JournalRecord(
                sequence=self._seq,
                timestamp_ns=raw_ts,
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

    @classmethod
    def verify_chain(
        cls,
        records: Sequence[JournalRecord],
        public_keys_by_id: Optional[Mapping[str, bytes]] = None,
    ) -> bool:
        """
        Verify sequence continuity, timestamp monotonicity, predecessor linkage,
        and hash-chain integrity across an ordered sequence of JournalRecords.
        """
        if not records:
            return True

        expected_prev_hash = ""
        prev_record: Optional[JournalRecord] = None

        for index, rec in enumerate(records, start=1):
            if rec.sequence != index:
                return False
            if not rec.key_id or not rec.key_id.strip():
                return False
            if not isinstance(rec.chain_hash, str) or not _HEX_SHA256_RE.match(rec.chain_hash):
                return False

            if prev_record is not None:
                if rec.timestamp_ns < prev_record.timestamp_ns:
                    return False
                if rec.predecessor_key_id != prev_record.key_id:
                    return False
            elif rec.predecessor_key_id is not None:
                return False

            if public_keys_by_id is not None:
                pub_key = public_keys_by_id.get(rec.key_id)
                if pub_key is None:
                    return False
                expected_hash = cls.compute_chain_hash(
                    predecessor_key_id=rec.predecessor_key_id,
                    public_key=pub_key,
                    previous_chain_hash=expected_prev_hash,
                )
                if not hmac.compare_digest(rec.chain_hash, expected_hash):
                    return False

            expected_prev_hash = rec.chain_hash
            prev_record = rec

        return True
