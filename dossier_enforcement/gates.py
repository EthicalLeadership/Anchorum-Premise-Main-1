"""
dossier_enforcement.gates
~~~~~~~~~~~~~~~~~~~~~~~~~~
Transaction-safe execution gates with rollback, checkpointing,
and nested transaction support.

Design principles:
- **Failure-closed**: A gate that cannot determine its own state
  defaults to rolled-back / uncommitted.
- **Deterministic**: Operations inside a gate are journaled in
  strict sequence; rollback replays the journal in reverse.
- **Observable**: Every gate transition emits an immutable status
  record for audit and forensic replay.

Usage::

    with TransactionGate("ingest-batch-42") as gate:
        gate.record(lambda: db.insert(...), lambda: db.delete(...))
        gate.record(lambda: fs.write(...), lambda: fs.unlink(...))
        gate.commit()   # or auto-commit on clean exit
"""

import time
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

from .exceptions import (CheckpointError, GateCommitError, GateError,
                         GateOpenError, RollbackError)

# ------------------------------------------------------------------
# Status model
# ------------------------------------------------------------------

class GateState(Enum):
    """Lifecycle states of a transaction gate."""
    PENDING = auto()      # Allocated, not yet entered
    OPEN = auto()         # Context entered, operations accepted
    COMMITTING = auto()   # Commit in progress
    COMMITTED = auto()    # All operations durable
    ROLLING_BACK = auto() # Rollback in progress
    ROLLED_BACK = auto()  # All operations reversed
    FAILED = auto()       # Unrecoverable failure (manual intervention required)


@dataclass(frozen=True)
class GateStatusRecord:
    """Immutable snapshot of a gate state transition."""
    gate_id: str
    timestamp: datetime
    from_state: GateState
    to_state: GateState
    operation_index: int
    detail: Optional[str] = None


@dataclass
class OperationJournalEntry:
    """Single journaled operation with forward and reverse actions."""
    index: int
    forward_fn: Callable[[], Any]
    reverse_fn: Callable[[], Any]
    description: str = "<unnamed>"
    forward_result: Any = None
    reverse_result: Any = None
    forward_exception: Optional[Exception] = None
    reverse_exception: Optional[Exception] = None
    executed: bool = False
    reversed: bool = False


# ------------------------------------------------------------------
# TransactionGate
# ------------------------------------------------------------------

class TransactionGate:
    """Deterministic transaction gate with full rollback capability.

    Attributes:
        gate_id: Unique identifier (auto-generated if omitted).
        auto_commit: If ``True``, successful context exit triggers commit.
                     If ``False``, caller must call ``commit()`` explicitly.
        max_retries: Maximum retry attempts for individual operations.

    Raises:
        GateOpenError: Operation attempted while gate not OPEN.
        GateCommitError: Commit phase failed partially.
        RollbackError: Rollback itself failed (worst-case).
    """

    def __init__(
        self,
        gate_id: Optional[str] = None,
        *,
        auto_commit: bool = True,
        max_retries: int = 0,
    ) -> None:
        self._gate_id = gate_id or f"gate-{uuid.uuid4().hex[:12]}"
        self._auto_commit = auto_commit
        self._max_retries = max_retries

        self._state = GateState.PENDING
        self._journal: List[OperationJournalEntry] = []
        self._checkpoints: Dict[str, Dict[str, Any]] = {}
        self._status_history: List[GateStatusRecord] = []
        self._enter_time: Optional[float] = None

        self._transition(GateState.PENDING, "initialized")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def gate_id(self) -> str:
        return self._gate_id

    @property
    def state(self) -> GateState:
        return self._state

    @property
    def is_open(self) -> bool:
        return self._state == GateState.OPEN

    @property
    def is_committed(self) -> bool:
        return self._state == GateState.COMMITTED

    @property
    def is_rolled_back(self) -> bool:
        return self._state == GateState.ROLLED_BACK

    @property
    def is_failed(self) -> bool:
        return self._state == GateState.FAILED

    @property
    def operation_count(self) -> int:
        return len(self._journal)

    @property
    def status_history(self) -> List[GateStatusRecord]:
        return list(self._status_history)

    @property
    def duration_seconds(self) -> float:
        if self._enter_time is None:
            return 0.0
        return time.monotonic() - self._enter_time

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def __enter__(self) -> "TransactionGate":
        if self._state != GateState.PENDING:
            raise GateOpenError(
                self._gate_id,
                current_state=self._state.name,
                detail="Gate already entered or terminal",
            )
        self._transition(GateState.OPEN, "context entered")
        self._enter_time = time.monotonic()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Context exit handler.

        If no exception and auto_commit is True → commit.
        If exception → rollback (unless already terminal).

        Returns:
            ``False`` to propagate any original exception.
        """
        if self._state == GateState.OPEN:
            if exc_type is None and self._auto_commit:
                try:
                    self.commit()
                except GateCommitError:
                    # Commit failed → attempt rollback
                    try:
                        self.rollback()
                    except RollbackError:
                        self._transition(GateState.FAILED, "commit and rollback both failed")
            else:
                # Exception path or manual commit mode
                try:
                    self.rollback()
                except RollbackError:
                    self._transition(GateState.FAILED, "rollback failed on exception path")
        return False  # Never swallow the original exception

    # ------------------------------------------------------------------
    # Operation recording
    # ------------------------------------------------------------------

    def record(
        self,
        forward: Callable[[], Any],
        reverse: Callable[[], Any],
        *,
        description: str = "<unnamed>",
    ) -> "TransactionGate":
        """Register an operation pair without executing.

        The forward action is **not** run until ``commit()`` is called.
        The reverse action is used during ``rollback()``.

        Returns:
            Self for fluent chaining.
        """
        if self._state != GateState.OPEN:
            raise GateOpenError(
                self._gate_id,
                current_state=self._state.name,
                detail="Cannot record operations outside OPEN state",
            )
        entry = OperationJournalEntry(
            index=len(self._journal),
            forward_fn=forward,
            reverse_fn=reverse,
            description=description,
        )
        self._journal.append(entry)
        return self

    def execute_now(
        self,
        forward: Callable[[], Any],
        reverse: Callable[[], Any],
        *,
        description: str = "<unnamed>",
    ) -> Any:
        """Execute immediately and journal for rollback.

        This is the preferred pattern for imperative code:
        the forward action runs right now, but the reverse
        action is captured in case the gate rolls back later.

        Returns:
            Result of the forward action.
        """
        if self._state != GateState.OPEN:
            raise GateOpenError(
                self._gate_id,
                current_state=self._state.name,
                detail="Cannot execute outside OPEN state",
            )
        entry = OperationJournalEntry(
            index=len(self._journal),
            forward_fn=forward,
            reverse_fn=reverse,
            description=description,
        )
        self._journal.append(entry)

        # Execute forward with optional retry
        for attempt in range(self._max_retries + 1):
            try:
                entry.forward_result = forward()
                entry.executed = True
                break
            except Exception as exc:
                entry.forward_exception = exc
                if attempt == self._max_retries:
                    # Forward failed definitively → rollback everything so far
                    self.rollback()
                    raise GateError(
                        f"Operation {entry.description!r} failed after "
                        f"{self._max_retries + 1} attempts",
                        gate_id=self._gate_id,
                        code="GATE-005",
                    ) from exc
        return entry.forward_result

    # ------------------------------------------------------------------
    # Commit
    # ------------------------------------------------------------------

    def commit(self) -> None:
        """Execute all journaled forward operations and mark committed.

        If any forward operation fails, previously successful operations
        are **not** auto-rolled-back by this method; the caller must
        handle partial state or call ``rollback()`` explicitly.

        Raises:
            GateCommitError: If any operation fails during commit.
        """
        if self._state != GateState.OPEN:
            raise GateOpenError(
                self._gate_id,
                current_state=self._state.name,
                detail="Cannot commit outside OPEN state",
            )

        self._transition(GateState.COMMITTING, f"committing {len(self._journal)} operations")
        partial = 0

        for entry in self._journal:
            if entry.executed:
                partial += 1
                continue  # Already executed via execute_now
            for attempt in range(self._max_retries + 1):
                try:
                    entry.forward_result = entry.forward_fn()
                    entry.executed = True
                    partial += 1
                    break
                except Exception as exc:
                    entry.forward_exception = exc
                    if attempt == self._max_retries:
                        self._transition(
                            GateState.FAILED,
                            f"commit failed at operation {entry.index} ({entry.description})",
                        )
                        raise GateCommitError(
                            self._gate_id,
                            partial_ops=partial,
                        ) from exc

        self._transition(GateState.COMMITTED, f"all {partial} operations committed")

    # ------------------------------------------------------------------
    # Rollback
    # ------------------------------------------------------------------

    def rollback(self) -> None:
        """Reverse all executed operations in LIFO order.

        Rollback is **best-effort**: if a reverse action itself fails,
        the failure is recorded but rollback continues for remaining
        entries. If any reverse fails, the final state is ``FAILED``.

        Raises:
            RollbackError: If any reverse operation fails.
        """
        if self._state in (GateState.ROLLED_BACK, GateState.PENDING):
            return  # Idempotent / nothing to do

        self._transition(GateState.ROLLING_BACK, f"rolling back {len(self._journal)} operations")
        reverse_failures: List[Tuple[int, Exception]] = []

        # Reverse in LIFO order
        for entry in reversed(self._journal):
            if not entry.executed:
                continue
            try:
                entry.reverse_result = entry.reverse_fn()
                entry.reversed = True
            except Exception as exc:
                entry.reverse_exception = exc
                reverse_failures.append((entry.index, exc))

        if reverse_failures:
            self._transition(
                GateState.FAILED,
                f"rollback completed with {len(reverse_failures)} reverse failures",
            )
            raise RollbackError(
                self._gate_id,
                original_error=reverse_failures[0][1] if reverse_failures else None,
            )

        self._transition(GateState.ROLLED_BACK, "all operations reversed")

    # ------------------------------------------------------------------
    # Checkpoints
    # ------------------------------------------------------------------

    def checkpoint(self, checkpoint_id: str, state: Dict[str, Any]) -> None:
        """Capture a named checkpoint of arbitrary state.

        Checkpoints are **not** automatically restored on rollback;
        they are advisory snapshots for manual recovery or audit.
        """
        if self._state != GateState.OPEN:
            raise GateOpenError(
                self._gate_id,
                current_state=self._state.name,
                detail="Cannot checkpoint outside OPEN state",
            )
        self._checkpoints[checkpoint_id] = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "operation_index": len(self._journal),
            "state": dict(state),
        }

    def restore_checkpoint(self, checkpoint_id: str) -> Dict[str, Any]:
        """Return the state captured at a checkpoint.

        Raises:
            CheckpointError: If the checkpoint does not exist.
        """
        if checkpoint_id not in self._checkpoints:
            raise CheckpointError(self._gate_id, checkpoint_id)
        return dict(self._checkpoints[checkpoint_id]["state"])

    def list_checkpoints(self) -> List[str]:
        return list(self._checkpoints.keys())

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _transition(self, to_state: GateState, detail: Optional[str] = None) -> None:
        from_state = self._state
        self._state = to_state
        record = GateStatusRecord(
            gate_id=self._gate_id,
            timestamp=datetime.now(timezone.utc),
            from_state=from_state,
            to_state=to_state,
            operation_index=len(self._journal),
            detail=detail,
        )
        self._status_history.append(record)

    def __repr__(self) -> str:
        return (
            f"TransactionGate(id={self._gate_id!r}, state={self._state.name}, "
            f"ops={self.operation_count}, duration={self.duration_seconds:.3f}s)"
        )


# ------------------------------------------------------------------
# Nested gate support
# ------------------------------------------------------------------

class NestedTransactionGate(TransactionGate):
    """Transaction gate that participates in a parent gate's lifecycle.

    On commit, the nested gate delegates to the parent rather than
    committing independently. On rollback, it rolls back its own
    operations and signals the parent.

    Usage::

        with TransactionGate("parent") as parent:
            with NestedTransactionGate("child", parent=parent) as child:
                child.execute_now(...)
            # child auto-commits into parent on clean exit
            parent.commit()
    """

    def __init__(
        self,
        gate_id: Optional[str] = None,
        *,
        parent: TransactionGate,
        auto_commit: bool = False,  # Nested gates never auto-commit independently
    ) -> None:
        super().__init__(gate_id=gate_id, auto_commit=auto_commit)
        self._parent = parent
        self._committed_to_parent = False

    def commit(self) -> None:
        """Commit by delegating journaled operations to the parent.

        The parent gate must still call its own ``commit()`` to make
        all nested operations durable.
        """
        if self._state != GateState.OPEN:
            raise GateOpenError(
                self._gate_id,
                current_state=self._state.name,
                detail="Nested gate not open",
            )
        for entry in self._journal:
            self._parent.record(
                forward=entry.forward_fn,
                reverse=entry.reverse_fn,
                description=f"[nested:{self._gate_id}] {entry.description}",
            )
        self._transition(GateState.COMMITTED, "delegated to parent")
        self._committed_to_parent = True

    def rollback(self) -> None:
        """Rollback own operations; do not delegate to parent."""
        if self._committed_to_parent:
            raise GateError(
                f"Nested gate {self._gate_id!r} already committed to parent; "
                f"rollback must be performed at parent level",
                gate_id=self._gate_id,
                code="GATE-006",
            )
        super().rollback()
