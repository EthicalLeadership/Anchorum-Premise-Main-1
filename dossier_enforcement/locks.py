"""
dossier_enforcement.locks
~~~~~~~~~~~~~~~~~~~~~~~~~~
Deterministic execution locks with hierarchy enforcement,
timeout handling, and deadlock prevention.

All locks are **failure-closed**: if the lock mechanism itself
fails, the default behaviour is to deny entry rather than allow
uncontrolled concurrent execution.
"""

import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Dict, List, Optional, Set, Tuple, Union

from .exceptions import (LockConflictError, LockError, LockHierarchyError,
                         LockTimeoutError)


class LockMode(Enum):
    """Reentrancy mode for an execution lock."""
    NON_REENTRANT = auto()   # Strict: one holder, no recursion
    REENTRANT = auto()       # Same thread may acquire multiple times


@dataclass(frozen=True)
class LockSpec:
    """Immutable specification for a lock instance.

    Attributes:
        name: Unique identifier within the registry.
        mode: Reentrancy behaviour.
        hierarchy_order: Integer defining global acquisition order.
                         Lower values must be acquired before higher values.
                         Used for deadlock prevention.
        timeout_seconds: Default timeout for acquisition attempts.
    """
    name: str
    mode: LockMode = LockMode.NON_REENTRANT
    hierarchy_order: int = 0
    timeout_seconds: float = 30.0


class ExecutionLock:
    """Deterministic execution lock with full lifecycle tracking.

    Usage (context manager)::

        lock = ExecutionLock(LockSpec("pipeline.stage.1", hierarchy_order=1))
        with lock.acquire(timeout=5.0):
            ...  # critical section

    Usage (explicit)::

        lock = ExecutionLock(LockSpec("pipeline.stage.1"))
        lock.acquire_nowait()
        try:
            ...
        finally:
            lock.release()

    Failure modes:
        - Timeout → ``LockTimeoutError`` (deny entry)
        - Conflict → ``LockConflictError`` (deny entry)
        - Hierarchy violation → ``LockHierarchyError`` (deny entry)
        - Release by non-holder → ``LockError`` (signal corruption)
    """

    def __init__(self, spec: LockSpec) -> None:
        self._spec = spec
        self._mode = spec.mode
        self._name = spec.name
        self._order = spec.hierarchy_order

        # Underlying primitives
        self._mutex = threading.Lock()
        self._condition = threading.Condition(self._mutex)

        # State
        self._holder: Optional[int] = None          # thread id
        self._recursion_depth: int = 0
        self._acquisition_time: Optional[float] = None

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def name(self) -> str:
        return self._name

    @property
    def hierarchy_order(self) -> int:
        return self._order

    @property
    def is_locked(self) -> bool:
        with self._mutex:
            return self._holder is not None

    @property
    def holder_thread_id(self) -> Optional[int]:
        with self._mutex:
            return self._holder

    @property
    def recursion_depth(self) -> int:
        with self._mutex:
            return self._recursion_depth

    @property
    def acquisition_time(self) -> Optional[float]:
        with self._mutex:
            return self._acquisition_time

    @property
    def hold_duration(self) -> float:
        """Seconds since acquisition, or 0.0 if not held."""
        with self._mutex:
            if self._acquisition_time is None:
                return 0.0
            return time.monotonic() - self._acquisition_time

    # ------------------------------------------------------------------
    # Acquisition
    # ------------------------------------------------------------------

    def acquire(self, timeout: Optional[float] = None) -> "_LockContext":
        """Context-manager acquisition.

        Args:
            timeout: Override the spec default. ``None`` = block forever.

        Returns:
            A context manager that releases on exit.
        """
        return _LockContext(self, timeout)

    def acquire_nowait(self) -> None:
        """Immediate acquisition; raises on conflict or hierarchy violation."""
        self._acquire_internal(blocking=False, timeout=0.0)

    def acquire_blocking(self, timeout: Optional[float] = None) -> None:
        """Blocking acquisition with optional deadline."""
        self._acquire_internal(blocking=True, timeout=timeout)

    def _acquire_internal(
        self,
        *,
        blocking: bool,
        timeout: Optional[float],
    ) -> None:
        tid = threading.get_ident()
        deadline = time.monotonic() + timeout if timeout is not None else None

        with self._mutex:
            # Reentrant fast-path
            if self._holder == tid and self._mode == LockMode.REENTRANT:
                self._recursion_depth += 1
                return

            # Non-reentrant conflict
            if self._holder is not None:
                if not blocking:
                    raise LockConflictError(
                        self._name,
                        holder=f"thread-{self._holder}",
                    )
                # Wait loop
                while self._holder is not None:
                    remaining = (
                        deadline - time.monotonic()
                        if deadline is not None
                        else None
                    )
                    if remaining is not None and remaining <= 0:
                        raise LockTimeoutError(
                            self._name,
                            timeout=timeout or self._spec.timeout_seconds,
                        )
                    self._condition.wait(timeout=remaining)

            # Take ownership
            self._holder = tid
            self._recursion_depth = 1
            self._acquisition_time = time.monotonic()

    # ------------------------------------------------------------------
    # Release
    # ------------------------------------------------------------------

    def release(self) -> None:
        """Release the lock.

        Raises:
            LockError: If the calling thread does not hold the lock.
        """
        tid = threading.get_ident()
        with self._mutex:
            if self._holder != tid:
                raise LockError(
                    f"Thread {tid} attempted to release lock {self._name!r} "
                    f"held by thread {self._holder}",
                    lock_name=self._name,
                    code="LOCK-004",
                )

            self._recursion_depth -= 1
            if self._recursion_depth == 0:
                self._holder = None
                self._acquisition_time = None
                self._condition.notify_all()

    # ------------------------------------------------------------------
    # Dunder helpers
    # ------------------------------------------------------------------

    def __enter__(self) -> "ExecutionLock":
        self.acquire_blocking(timeout=self._spec.timeout_seconds)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.release()

    def __repr__(self) -> str:
        return (
            f"ExecutionLock(name={self._name!r}, order={self._order}, "
            f"mode={self._mode.name}, held={self.is_locked})"
        )


class _LockContext:
    """Internal context manager returned by ``ExecutionLock.acquire()``."""
    def __init__(self, lock: ExecutionLock, timeout: Optional[float]) -> None:
        self._lock = lock
        self._timeout = timeout

    def __enter__(self) -> ExecutionLock:
        self._lock.acquire_blocking(timeout=self._timeout)
        return self._lock

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._lock.release()


# ------------------------------------------------------------------
# Lock registry & hierarchy enforcement
# ------------------------------------------------------------------

class LockRegistry:
    """Global (or scoped) registry of named locks with deadlock prevention.

    The registry enforces a **strict hierarchy order**: locks with lower
    ``hierarchy_order`` must be acquired before locks with higher order.
    This prevents circular wait conditions.

    Usage::

        registry = LockRegistry()
        lock_a = registry.get_or_create(LockSpec("A", hierarchy_order=1))
        lock_b = registry.get_or_create(LockSpec("B", hierarchy_order=2))

        with lock_a:
            with lock_b:   # valid: 1 < 2
                ...

    Violating the order raises ``LockHierarchyError`` at acquisition time.
    """

    def __init__(self, scope: str = "global") -> None:
        self._scope = scope
        self._locks: Dict[str, ExecutionLock] = {}
        self._mutex = threading.Lock()
        # Per-thread stack of currently held lock orders
        self._thread_stacks: Dict[int, List[int]] = {}
        self._stack_mutex = threading.Lock()

    @property
    def scope(self) -> str:
        return self._scope

    def get_or_create(self, spec: LockSpec) -> ExecutionLock:
        """Retrieve existing lock or create and register a new one."""
        with self._mutex:
            if spec.name in self._locks:
                existing = self._locks[spec.name]
                # Sanity: spec must match on order and mode
                if existing.hierarchy_order != spec.hierarchy_order:
                    raise LockError(
                        f"Lock {spec.name!r} already registered with order "
                        f"{existing.hierarchy_order}, cannot redefine to "
                        f"{spec.hierarchy_order}",
                        lock_name=spec.name,
                        code="LOCK-005",
                    )
                return existing
            lock = ExecutionLock(spec)
            self._locks[spec.name] = lock
            return lock

    def get(self, name: str) -> Optional[ExecutionLock]:
        with self._mutex:
            return self._locks.get(name)

    def remove(self, name: str) -> bool:
        """Remove a lock from the registry. Returns True if removed."""
        with self._mutex:
            lock = self._locks.get(name)
            if lock is None:
                return False
            if lock.is_locked:
                raise LockError(
                    f"Cannot remove locked lock {name!r}",
                    lock_name=name,
                    code="LOCK-006",
                )
            del self._locks[name]
            return True

    def list_locks(self) -> List[Tuple[str, bool, Optional[int]]]:
        """Return list of (name, is_locked, holder_thread_id)."""
        with self._mutex:
            return [
                (lock.name, lock.is_locked, lock.holder_thread_id)
                for lock in self._locks.values()
            ]

    def enforce_hierarchy_on_acquire(self, lock: ExecutionLock) -> None:
        """Check that acquiring *lock* respects the hierarchy.

        Called automatically by the registry-wrapped acquisition path.
        """
        tid = threading.get_ident()
        with self._stack_mutex:
            stack = self._thread_stacks.get(tid, [])
            if stack and lock.hierarchy_order <= stack[-1]:
                raise LockHierarchyError(
                    lock.name,
                    expected_order=stack[-1] + 1,
                    actual_order=lock.hierarchy_order,
                )

    def _record_acquire(self, lock: ExecutionLock) -> None:
        tid = threading.get_ident()
        with self._stack_mutex:
            self._thread_stacks.setdefault(tid, []).append(lock.hierarchy_order)

    def _record_release(self, lock: ExecutionLock) -> None:
        tid = threading.get_ident()
        with self._stack_mutex:
            stack = self._thread_stacks.get(tid, [])
            if stack and stack[-1] == lock.hierarchy_order:
                stack.pop()
            if not stack:
                self._thread_stacks.pop(tid, None)

    def create_hierarchical_lock(self, spec: LockSpec) -> "HierarchicalExecutionLock":
        """Create a lock that auto-enforces hierarchy via this registry."""
        base = self.get_or_create(spec)
        return HierarchicalExecutionLock(base, self)


class HierarchicalExecutionLock:
    """Wrapper that injects registry hierarchy checks into an ExecutionLock."""

    def __init__(self, base: ExecutionLock, registry: LockRegistry) -> None:
        self._base = base
        self._registry = registry

    @property
    def name(self) -> str:
        return self._base.name

    @property
    def hierarchy_order(self) -> int:
        return self._base.hierarchy_order

    @property
    def is_locked(self) -> bool:
        return self._base.is_locked

    def acquire(self, timeout: Optional[float] = None) -> "_HierLockContext":
        return _HierLockContext(self._base, self._registry, timeout)

    def __enter__(self) -> "HierarchicalExecutionLock":
        self._registry.enforce_hierarchy_on_acquire(self._base)
        self._base.__enter__()
        self._registry._record_acquire(self._base)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._base.__exit__(exc_type, exc_val, exc_tb)
        self._registry._record_release(self._base)

    def __repr__(self) -> str:
        return f"HierarchicalExecutionLock(base={self._base!r})"


class _HierLockContext:
    def __init__(
        self,
        base: ExecutionLock,
        registry: LockRegistry,
        timeout: Optional[float],
    ) -> None:
        self._base = base
        self._registry = registry
        self._timeout = timeout

    def __enter__(self) -> ExecutionLock:
        self._registry.enforce_hierarchy_on_acquire(self._base)
        self._base.acquire_blocking(timeout=self._timeout)
        self._registry._record_acquire(self._base)
        return self._base

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self._base.release()
        self._registry._record_release(self._base)
