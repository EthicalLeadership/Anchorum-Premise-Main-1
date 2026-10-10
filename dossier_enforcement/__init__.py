"""
dossier_enforcement
~~~~~~~~~~~~~~~~~~~~
Deterministic enforcement layer for the dossier pipeline.

Provides execution locks, runtime assertions, and transaction gates
with full rollback support. All components are **failure-closed**
and **inspectable** for audit and forensic replay.

Quick start::

    from dossier_enforcement import (
        ExecutionLock, LockSpec, LockRegistry, LockMode,
        assert_that, invariant, precondition, postcondition,
        requires, ensures, FailureMode, AssertionRegistry,
        TransactionGate, NestedTransactionGate, GateState,
    )

    # Locking
    registry = LockRegistry()
    lock = registry.create_hierarchical_lock(
        LockSpec("pipeline.ingest", hierarchy_order=1)
    )
    with lock:
        ...

    # Assertions
    assert_that(x > 0, "x must be positive", assertion_id="INGEST-001")

    # Transaction gate
    with TransactionGate("batch-42") as gate:
        gate.execute_now(
            forward=lambda: db.insert(record),
            reverse=lambda: db.delete(record.id),
            description="insert record",
        )
"""

__version__ = "2026.05.03"
__all__ = [
    # Exceptions
    "EnforcementError",
    "LockError",
    "LockTimeoutError",
    "LockConflictError",
    "LockHierarchyError",
    "AssertionError",
    "InvariantError",
    "PreconditionError",
    "PostconditionError",
    "GateError",
    "GateOpenError",
    "GateCommitError",
    "RollbackError",
    "CheckpointError",
    # Locks
    "LockMode",
    "LockSpec",
    "ExecutionLock",
    "LockRegistry",
    "HierarchicalExecutionLock",
    # Assertions
    "FailureMode",
    "AssertionRecord",
    "assert_that",
    "invariant",
    "precondition",
    "postcondition",
    "requires",
    "ensures",
    "AssertionRegistry",
    # Gates
    "GateState",
    "GateStatusRecord",
    "OperationJournalEntry",
    "TransactionGate",
    "NestedTransactionGate",
    # Checklist
    "ChecklistEngine",
    "ControlScore",
    "Classification",
]

from .assertions import (AssertionRecord, AssertionRegistry, FailureMode,
                         assert_that, ensures, invariant, postcondition,
                         precondition, requires)
from .checklist import ChecklistEngine, Classification, ControlScore
from .exceptions import (AssertionError, CheckpointError, EnforcementError,
                         GateCommitError, GateError, GateOpenError,
                         InvariantError, LockConflictError, LockError,
                         LockHierarchyError, LockTimeoutError,
                         PostconditionError, PreconditionError, RollbackError)
from .gates import (GateState, GateStatusRecord, NestedTransactionGate,
                    OperationJournalEntry, TransactionGate)
from .locks import (ExecutionLock, HierarchicalExecutionLock, LockMode,
                    LockRegistry, LockSpec)
