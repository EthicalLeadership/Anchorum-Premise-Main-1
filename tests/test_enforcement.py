"""
test_enforcement.py
~~~~~~~~~~~~~~~~~~~~
Validation suite for dossier_enforcement.

Run with::

    cd /mnt/agents/output
    python -m pytest tests/test_enforcement.py -v

Or directly::

    python tests/test_enforcement.py
"""

import sys
import threading
import time

sys.path.insert(0, "/mnt/agents/output")

from dossier_enforcement import (  # Locks; Assertions; Gates
    AssertionRegistry, ExecutionLock, FailureMode, GateCommitError, GateState,
    HierarchicalExecutionLock, InvariantError, LockConflictError,
    LockHierarchyError, LockMode, LockRegistry, LockSpec, LockTimeoutError,
    NestedTransactionGate, PostconditionError, PreconditionError,
    RollbackError, TransactionGate, assert_that, ensures, invariant,
    postcondition, precondition, requires)


def test_lock_basic():
    spec = LockSpec("test.basic", mode=LockMode.NON_REENTRANT, timeout_seconds=1.0)
    lock = ExecutionLock(spec)
    assert not lock.is_locked
    with lock:
        assert lock.is_locked
        assert lock.holder_thread_id == threading.get_ident()
    assert not lock.is_locked
    print("  [PASS] test_lock_basic")


def test_lock_reentrant():
    spec = LockSpec("test.reentrant", mode=LockMode.REENTRANT)
    lock = ExecutionLock(spec)
    with lock:
        with lock:
            assert lock.recursion_depth == 2
        assert lock.recursion_depth == 1
    assert not lock.is_locked
    print("  [PASS] test_lock_reentrant")


def test_lock_timeout():
    spec = LockSpec("test.timeout", timeout_seconds=0.1)
    lock = ExecutionLock(spec)
    lock.acquire_nowait()
    try:
        # Same lock instance, same thread, non-reentrant → should timeout
        lock.acquire_blocking(timeout=0.2)
        assert False, "Should have timed out"
    except LockTimeoutError as e:
        assert e.lock_name == "test.timeout"
        assert e.timeout == 0.2
    finally:
        lock.release()
    print("  [PASS] test_lock_timeout")


def test_lock_conflict():
    spec = LockSpec("test.conflict")
    lock = ExecutionLock(spec)
    lock.acquire_nowait()
    try:
        # Same lock instance, non-blocking → immediate conflict
        lock.acquire_nowait()
        assert False, "Should have conflicted"
    except LockConflictError as e:
        assert e.lock_name == "test.conflict"
    finally:
        lock.release()
    print("  [PASS] test_lock_conflict")


def test_registry_hierarchy():
    registry = LockRegistry(scope="test")
    lock_a = registry.create_hierarchical_lock(LockSpec("A", hierarchy_order=1))
    lock_b = registry.create_hierarchical_lock(LockSpec("B", hierarchy_order=2))

    with lock_a:
        with lock_b:
            pass

    try:
        with lock_b:
            with lock_a:
                pass
        assert False, "Should have hierarchy error"
    except LockHierarchyError as e:
        assert e.lock_name == "A"
        assert e.expected_order > e.actual_order
    print("  [PASS] test_registry_hierarchy")


def test_assertion_hard():
    AssertionRegistry.reset_default()
    try:
        assert_that(False, "must fail", assertion_id="T-001")
        assert False, "Should have raised"
    except Exception as e:
        assert "must fail" in str(e)
    reg = AssertionRegistry.get_default()
    assert reg.failure_count() == 1
    print("  [PASS] test_assertion_hard")


def test_assertion_soft():
    AssertionRegistry.reset_default()
    result = assert_that(False, "soft fail", assertion_id="T-002", mode=FailureMode.SOFT)
    assert result is False
    reg = AssertionRegistry.get_default()
    assert reg.failure_count() == 1
    print("  [PASS] test_assertion_soft")


def test_invariant():
    AssertionRegistry.reset_default()
    try:
        invariant(False, "data.integrity", expected="ok", actual="corrupt")
        assert False, "Should have raised"
    except InvariantError as e:
        assert e.invariant_name == "data.integrity"
    print("  [PASS] test_invariant")


def test_precondition_postcondition():
    AssertionRegistry.reset_default()

    @requires(lambda x: x > 0)
    @ensures(lambda result: result > 0)
    def safe_sqrt(x: float) -> float:
        return x ** 0.5

    result = safe_sqrt(4.0)
    assert result == 2.0

    try:
        safe_sqrt(-1.0)
        assert False, "Should have precondition error"
    except PreconditionError:
        pass

    print("  [PASS] test_precondition_postcondition")


def test_gate_basic():
    executed = []
    with TransactionGate("test.basic", auto_commit=True) as gate:
        gate.execute_now(
            forward=lambda: executed.append("fwd"),
            reverse=lambda: executed.append("rev"),
            description="append fwd",
        )
    assert gate.is_committed
    assert "fwd" in executed
    assert "rev" not in executed
    print("  [PASS] test_gate_basic")


def test_gate_rollback():
    executed = []
    reversed_ops = []
    try:
        with TransactionGate("test.rollback", auto_commit=False) as gate:
            gate.execute_now(
                forward=lambda: executed.append("op1"),
                reverse=lambda: reversed_ops.append("rev1"),
                description="op1",
            )
            gate.execute_now(
                forward=lambda: executed.append("op2"),
                reverse=lambda: reversed_ops.append("rev2"),
                description="op2",
            )
            raise RuntimeError("trigger rollback")
    except RuntimeError:
        pass

    assert "op1" in executed
    assert "op2" in executed
    assert "rev2" in reversed_ops
    assert "rev1" in reversed_ops
    print("  [PASS] test_gate_rollback")


def test_gate_checkpoint():
    with TransactionGate("test.checkpoint") as gate:
        gate.checkpoint("alpha", {"value": 42})
        gate.execute_now(
            forward=lambda: None,
            reverse=lambda: None,
            description="noop",
        )
        state = gate.restore_checkpoint("alpha")
        assert state["value"] == 42
    print("  [PASS] test_gate_checkpoint")


def test_nested_gate():
    parent_ops = []
    with TransactionGate("parent", auto_commit=False) as parent:
        with NestedTransactionGate("child", parent=parent) as child:
            child.execute_now(
                forward=lambda: parent_ops.append("child_fwd"),
                reverse=lambda: parent_ops.append("child_rev"),
                description="child op",
            )
        # child delegates to parent on exit
        parent.commit()

    assert "child_fwd" in parent_ops
    assert parent.is_committed
    print("  [PASS] test_nested_gate")


def test_gate_status_history():
    with TransactionGate("test.history") as gate:
        pass
    history = gate.status_history
    states = [h.to_state for h in history]
    assert GateState.PENDING in states
    assert GateState.OPEN in states
    assert GateState.COMMITTED in states
    print("  [PASS] test_gate_status_history")


def test_registry_list():
    registry = LockRegistry("list-test")
    registry.get_or_create(LockSpec("x", hierarchy_order=1))
    registry.get_or_create(LockSpec("y", hierarchy_order=2))
    locks = registry.list_locks()
    assert len(locks) == 2
    print("  [PASS] test_registry_list")


def test_assertion_registry_export():
    AssertionRegistry.reset_default()
    assert_that(True, "ok", assertion_id="E-001")
    assert_that(False, "fail", assertion_id="E-002", mode=FailureMode.SOFT)
    reg = AssertionRegistry.get_default()
    exported = reg.export()
    assert len(exported) == 2
    assert exported[1]["passed"] is False
    assert exported[1]["failure_mode"] == "SOFT"
    print("  [PASS] test_assertion_registry_export")


def run_all():
    print("\n=== dossier_enforcement validation suite ===")
    tests = [
        test_lock_basic,
        test_lock_reentrant,
        test_lock_timeout,
        test_lock_conflict,
        test_registry_hierarchy,
        test_registry_list,
        test_assertion_hard,
        test_assertion_soft,
        test_invariant,
        test_precondition_postcondition,
        test_assertion_registry_export,
        test_gate_basic,
        test_gate_rollback,
        test_gate_checkpoint,
        test_nested_gate,
        test_gate_status_history,
    ]
    passed = 0
    failed = 0
    for test in tests:
        try:
            test()
            passed += 1
        except Exception as exc:
            print(f"  [FAIL] {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            failed += 1
    print(f"\n=== Results: {passed} passed, {failed} failed ===")
    return failed == 0


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
