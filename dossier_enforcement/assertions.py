"""
dossier_enforcement.assertions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Runtime assertion layer that is **immune to ``python -O``** and
defaults to **failure-closed** (hard failure).

Provides:
- ``assert_that`` — general predicate assertions
- ``invariant`` — structural/data invariants
- ``precondition`` / ``postcondition`` — function entry/exit guards
- ``AssertionRegistry`` — global tracking and audit logging

All assertion failures raise descendants of ``AssertionError``
(from ``exceptions``) and capture runtime context for forensic
replay.
"""

import functools
import inspect
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum, auto
from typing import Any, Callable, Dict, List, Optional, Tuple, TypeVar, Union

from .exceptions import AssertionError as EnforcementAssertionError
from .exceptions import InvariantError, PostconditionError, PreconditionError

F = TypeVar("F", bound=Callable[..., Any])


class FailureMode(Enum):
    """Severity of an assertion failure."""
    HARD = auto()      # Raise exception immediately (default)
    SOFT = auto()      # Log and continue (use only in recovery paths)
    AUDIT = auto()     # Log only, never raise (for passive monitoring)


@dataclass(frozen=True)
class AssertionRecord:
    """Immutable snapshot of a single assertion evaluation."""
    assertion_id: str
    timestamp: datetime
    passed: bool
    predicate: str
    actual_value: Any
    expected_value: Any
    context: Dict[str, Any]
    failure_mode: FailureMode
    exception: Optional[EnforcementAssertionError] = None


# ------------------------------------------------------------------
# Core assertion primitives
# ------------------------------------------------------------------

def assert_that(
    predicate: bool,
    message: str,
    *,
    assertion_id: str = "<anon>",
    mode: FailureMode = FailureMode.HARD,
    context: Optional[Dict[str, Any]] = None,
    expected: Any = None,
    actual: Any = None,
) -> bool:
    """Evaluate a boolean predicate and react according to *mode*.

    Args:
        predicate: The condition to enforce.
        message: Human-readable explanation on failure.
        assertion_id: Unique identifier for audit correlation.
        mode: ``HARD`` raises immediately; ``SOFT`` logs and returns;
              ``AUDIT`` logs silently.
        context: Arbitrary key/value pairs captured at failure time.
        expected: Reference value for forensic diff.
        actual: Observed value for forensic diff.

    Returns:
        ``True`` if predicate is truthy; ``False`` only in SOFT/AUDIT
        modes when the predicate is falsy.

    Raises:
        EnforcementAssertionError: If predicate is falsy and mode is HARD.
    """
    now = datetime.now(timezone.utc)
    passed = bool(predicate)
    ctx = context or {}
    exc: Optional[EnforcementAssertionError] = None

    if not passed:
        exc = EnforcementAssertionError(
            message,
            assertion_id=assertion_id,
            detail=f"expected={expected!r}, actual={actual!r}",
            context=ctx,
        )

    record = AssertionRecord(
        assertion_id=assertion_id,
        timestamp=now,
        passed=passed,
        predicate=message,
        actual_value=actual,
        expected_value=expected,
        context=ctx,
        failure_mode=mode,
        exception=exc,
    )
    AssertionRegistry.get_default()._append(record)

    if not passed and mode == FailureMode.HARD:
        raise exc

    return passed


def invariant(
    predicate: bool,
    invariant_name: str,
    *,
    mode: FailureMode = FailureMode.HARD,
    context: Optional[Dict[str, Any]] = None,
    expected: Any = None,
    actual: Any = None,
) -> bool:
    """Assert a structural or data invariant.

    Invariants are expected to hold at all observable states of the
    system. A broken invariant signals corruption or logic failure.
    """
    now = datetime.now(timezone.utc)
    passed = bool(predicate)
    ctx = context or {}
    exc: Optional[InvariantError] = None

    if not passed:
        exc = InvariantError(
            f"Invariant '{invariant_name}' violated",
            invariant_name=invariant_name,
            detail=f"expected={expected!r}, actual={actual!r}",
            context=ctx,
        )

    record = AssertionRecord(
        assertion_id=invariant_name,
        timestamp=now,
        passed=passed,
        predicate=f"Invariant: {invariant_name}",
        actual_value=actual,
        expected_value=expected,
        context=ctx,
        failure_mode=mode,
        exception=exc,
    )
    AssertionRegistry.get_default()._append(record)

    if not passed and mode == FailureMode.HARD:
        raise exc

    return passed


def precondition(
    predicate: bool,
    fn_or_name: Union[str, Callable[..., Any]],
    *,
    mode: FailureMode = FailureMode.HARD,
    context: Optional[Dict[str, Any]] = None,
    expected: Any = None,
    actual: Any = None,
) -> bool:
    """Assert a function entry precondition.

    Args:
        predicate: Condition that must hold on function entry.
        fn_or_name: Function object or name string.
    """
    name = fn_or_name if isinstance(fn_or_name, str) else getattr(fn_or_name, "__name__", "<unknown>")
    now = datetime.now(timezone.utc)
    passed = bool(predicate)
    ctx = context or {}
    exc: Optional[PreconditionError] = None

    if not passed:
        exc = PreconditionError(
            f"Precondition failed for {name!r}",
            fn_name=name,
            detail=f"expected={expected!r}, actual={actual!r}",
            context=ctx,
        )

    record = AssertionRecord(
        assertion_id=f"pre:{name}",
        timestamp=now,
        passed=passed,
        predicate=f"Precondition for {name}",
        actual_value=actual,
        expected_value=expected,
        context=ctx,
        failure_mode=mode,
        exception=exc,
    )
    AssertionRegistry.get_default()._append(record)

    if not passed and mode == FailureMode.HARD:
        raise exc

    return passed


def postcondition(
    predicate: bool,
    fn_or_name: Union[str, Callable[..., Any]],
    *,
    mode: FailureMode = FailureMode.HARD,
    context: Optional[Dict[str, Any]] = None,
    expected: Any = None,
    actual: Any = None,
) -> bool:
    """Assert a function exit postcondition."""
    name = fn_or_name if isinstance(fn_or_name, str) else getattr(fn_or_name, "__name__", "<unknown>")
    now = datetime.now(timezone.utc)
    passed = bool(predicate)
    ctx = context or {}
    exc: Optional[PostconditionError] = None

    if not passed:
        exc = PostconditionError(
            f"Postcondition failed for {name!r}",
            fn_name=name,
            detail=f"expected={expected!r}, actual={actual!r}",
            context=ctx,
        )

    record = AssertionRecord(
        assertion_id=f"post:{name}",
        timestamp=now,
        passed=passed,
        predicate=f"Postcondition for {name}",
        actual_value=actual,
        expected_value=expected,
        context=ctx,
        failure_mode=mode,
        exception=exc,
    )
    AssertionRegistry.get_default()._append(record)

    if not passed and mode == FailureMode.HARD:
        raise exc

    return passed


# ------------------------------------------------------------------
# Decorators
# ------------------------------------------------------------------

def requires(
    *predicates: Callable[..., bool],
    mode: FailureMode = FailureMode.HARD,
) -> Callable[[F], F]:
    """Decorator that enforces preconditions via callable predicates.

    Each predicate receives the same ``*args, **kwargs`` as the
    wrapped function and must return ``True`` for the call to proceed.

    Example::

        @requires(lambda x: x > 0)
        def sqrt(x: float) -> float:
            return x ** 0.5
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            sig = inspect.signature(fn)
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            for pred in predicates:
                result = pred(**bound.arguments)
                precondition(
                    result,
                    fn,
                    mode=mode,
                    context={"predicate": pred.__name__ if hasattr(pred, "__name__") else str(pred)},
                )
            return fn(*args, **kwargs)
        return wrapper  # type: ignore[return-value]
    return decorator


def ensures(
    *predicates: Callable[[Any], bool],
    mode: FailureMode = FailureMode.HARD,
) -> Callable[[F], F]:
    """Decorator that enforces postconditions on the return value.

    Each predicate receives the return value and must return ``True``.

    Example::

        @ensures(lambda result: result >= 0)
        def abs_value(x: int) -> int:
            return abs(x)
    """
    def decorator(fn: F) -> F:
        @functools.wraps(fn)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            result = fn(*args, **kwargs)
            for pred in predicates:
                ok = pred(result)
                postcondition(
                    ok,
                    fn,
                    mode=mode,
                    context={"predicate": pred.__name__ if hasattr(pred, "__name__") else str(pred)},
                    actual=result,
                )
            return result
        return wrapper  # type: ignore[return-value]
    return decorator


# ------------------------------------------------------------------
# Registry
# ------------------------------------------------------------------

class AssertionRegistry:
    """Global registry of assertion evaluations for audit and replay.

    Thread-safe singleton by default. Scoped instances supported for
    multi-tenant or test isolation.
    """

    _default: Optional["AssertionRegistry"] = None
    _lock = __import__("threading").Lock()

    def __init__(self, scope: str = "default") -> None:
        self._scope = scope
        self._records: List[AssertionRecord] = []
        self._mutex = __import__("threading").Lock()

    @classmethod
    def get_default(cls) -> "AssertionRegistry":
        if cls._default is None:
            with cls._lock:
                if cls._default is None:
                    cls._default = cls("default")
        return cls._default

    @classmethod
    def reset_default(cls) -> None:
        with cls._lock:
            cls._default = None

    def _append(self, record: AssertionRecord) -> None:
        with self._mutex:
            self._records.append(record)

    def records(
        self,
        *,
        passed_only: bool = False,
        failed_only: bool = False,
        assertion_id: Optional[str] = None,
    ) -> List[AssertionRecord]:
        """Query the registry.

        Args:
            passed_only: Filter to passed evaluations.
            failed_only: Filter to failed evaluations.
            assertion_id: Filter to a specific assertion identifier.
        """
        with self._mutex:
            out = list(self._records)
        if passed_only:
            out = [r for r in out if r.passed]
        if failed_only:
            out = [r for r in out if not r.passed]
        if assertion_id is not None:
            out = [r for r in out if r.assertion_id == assertion_id]
        return out

    def last_failure(self) -> Optional[AssertionRecord]:
        """Return the most recent failed record, or None."""
        with self._mutex:
            for r in reversed(self._records):
                if not r.passed:
                    return r
        return None

    def failure_count(self) -> int:
        with self._mutex:
            return sum(1 for r in self._records if not r.passed)

    def clear(self) -> None:
        with self._mutex:
            self._records.clear()

    def export(self) -> List[Dict[str, Any]]:
        """Serialize all records to plain dicts for JSON/logging."""
        with self._mutex:
            return [
                {
                    "assertion_id": r.assertion_id,
                    "timestamp": r.timestamp.isoformat(),
                    "passed": r.passed,
                    "predicate": r.predicate,
                    "actual_value": repr(r.actual_value),
                    "expected_value": repr(r.expected_value),
                    "context": r.context,
                    "failure_mode": r.failure_mode.name,
                    "exception": repr(r.exception) if r.exception else None,
                }
                for r in self._records
            ]

    def __len__(self) -> int:
        with self._mutex:
            return len(self._records)

    def __repr__(self) -> str:
        return (
            f"AssertionRegistry(scope={self._scope!r}, "
            f"records={len(self)}, failures={self.failure_count()})"
        )
