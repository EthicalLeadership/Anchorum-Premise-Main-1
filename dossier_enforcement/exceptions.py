"""
dossier_enforcement.exceptions
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Exception hierarchy for the enforcement layer.

All enforcement failures descend from EnforcementError to allow
catch-all handling while preserving granularity for targeted
recovery or logging.
"""

from typing import Any, Optional


class EnforcementError(Exception):
    """Base for all enforcement-layer failures.

    Attributes:
        code: Machine-readable error code (e.g., ``LOCK-001``).
        detail: Human-readable explanation.
        context: Arbitrary runtime context captured at failure point.
    """
    def __init__(
        self,
        message: str,
        code: str = "ENF-000",
        detail: Optional[str] = None,
        context: Optional[Any] = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.detail = detail or message
        self.context = context

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"code={self.code!r}, message={self.args[0]!r}, "
            f"context={self.context!r})"
        )


# ------------------------------------------------------------------
# Locking failures
# ------------------------------------------------------------------

class LockError(EnforcementError):
    """Lock acquisition, release, or integrity failure."""
    def __init__(self, message: str, lock_name: str = "<unnamed>", code: str = "LOCK-000", **kwargs) -> None:
        super().__init__(message, code=code, **kwargs)
        self.lock_name = lock_name


class LockTimeoutError(LockError):
    """Lock could not be acquired within the requested deadline."""
    def __init__(self, lock_name: str, timeout: float, **kwargs) -> None:
        super().__init__(
            f"Timeout acquiring lock {lock_name!r} after {timeout}s",
            lock_name=lock_name,
            code="LOCK-001",
            **kwargs,
        )
        self.timeout = timeout


class LockConflictError(LockError):
    """Lock is already held by another execution context (non-reentrant)."""
    def __init__(self, lock_name: str, holder: str = "<unknown>", **kwargs) -> None:
        super().__init__(
            f"Lock {lock_name!r} already held by {holder}",
            lock_name=lock_name,
            code="LOCK-002",
            **kwargs,
        )
        self.holder = holder


class LockHierarchyError(LockError):
    """Lock acquisition order violates the configured hierarchy (deadlock prevention)."""
    def __init__(self, lock_name: str, expected_order: int, actual_order: int, **kwargs) -> None:
        super().__init__(
            f"Hierarchy violation on {lock_name!r}: "
            f"expected order {expected_order}, got {actual_order}",
            lock_name=lock_name,
            code="LOCK-003",
            **kwargs,
        )
        self.expected_order = expected_order
        self.actual_order = actual_order


# ------------------------------------------------------------------
# Assertion failures
# ------------------------------------------------------------------

class AssertionError(EnforcementError):
    """Runtime assertion violation.

    Deliberately named to shadow the built-in so that enforcement
    assertions are visually and behaviourally distinct from standard
    Python ``assert`` statements, which can be disabled with ``-O``.
    """
    def __init__(self, message: str, assertion_id: str = "<anon>", code: str = "AST-000", **kwargs) -> None:
        super().__init__(message, code=code, **kwargs)
        self.assertion_id = assertion_id


class InvariantError(AssertionError):
    """Structural or data invariant was violated."""
    def __init__(self, message: str, invariant_name: str = "<unnamed>", **kwargs) -> None:
        super().__init__(
            message,
            assertion_id=invariant_name,
            code="AST-001",
            **kwargs,
        )
        self.invariant_name = invariant_name


class PreconditionError(AssertionError):
    """Function/method precondition was not met on entry."""
    def __init__(self, message: str, fn_name: str = "<unknown>", **kwargs) -> None:
        super().__init__(
            message,
            assertion_id=f"pre:{fn_name}",
            code="AST-002",
            **kwargs,
        )
        self.fn_name = fn_name


class PostconditionError(AssertionError):
    """Function/method postcondition was not met on exit."""
    def __init__(self, message: str, fn_name: str = "<unknown>", **kwargs) -> None:
        super().__init__(
            message,
            assertion_id=f"post:{fn_name}",
            code="AST-003",
            **kwargs,
        )
        self.fn_name = fn_name


# ------------------------------------------------------------------
# Gate / transaction failures
# ------------------------------------------------------------------

class GateError(EnforcementError):
    """Transaction gate lifecycle or integrity failure."""
    def __init__(self, message: str, gate_id: str = "<unnamed>", code: str = "GATE-000", **kwargs) -> None:
        super().__init__(message, code=code, **kwargs)
        self.gate_id = gate_id


class GateOpenError(GateError):
    """Attempted operation on a gate that is not in a valid open state."""
    def __init__(self, gate_id: str, current_state: str, **kwargs) -> None:
        super().__init__(
            f"Gate {gate_id!r} is not open (state={current_state})",
            gate_id=gate_id,
            code="GATE-001",
            **kwargs,
        )
        self.current_state = current_state


class GateCommitError(GateError):
    """Commit phase failed; system may be in an inconsistent state."""
    def __init__(self, gate_id: str, partial_ops: int, **kwargs) -> None:
        super().__init__(
            f"Gate {gate_id!r} commit failed after {partial_ops} partial operations",
            gate_id=gate_id,
            code="GATE-002",
            **kwargs,
        )
        self.partial_ops = partial_ops


class RollbackError(GateError):
    """Rollback itself failed — worst-case failure mode."""
    def __init__(self, gate_id: str, original_error: Optional[Exception] = None, **kwargs) -> None:
        super().__init__(
            f"Gate {gate_id!r} rollback failed (original={original_error!r})",
            gate_id=gate_id,
            code="GATE-003",
            **kwargs,
        )
        self.original_error = original_error


class CheckpointError(GateError):
    """Checkpoint capture or restoration failed."""
    def __init__(self, gate_id: str, checkpoint_id: str, **kwargs) -> None:
        super().__init__(
            f"Gate {gate_id!r} checkpoint {checkpoint_id!r} failed",
            gate_id=gate_id,
            code="GATE-004",
            **kwargs,
        )
        self.checkpoint_id = checkpoint_id
