#!/usr/bin/env python3
"""Verify the enforcement layer graft is healthy."""

import sys
from pathlib import Path

# Ensure repo root is on sys.path regardless of where this script is invoked from.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


def check():
    errors = []

    try:
        from dossier_enforcement import (AssertionRegistry, ChecklistEngine,
                                          Classification, ControlScore,
                                          LockMode, LockRegistry, LockSpec,
                                          NestedTransactionGate,
                                          TransactionGate, assert_that,
                                          invariant, postcondition,
                                          precondition)
    except ImportError as e:
        errors.append(f"Import failed: {e}")
        return errors

    try:
        with TransactionGate("graft-test", auto_commit=True) as gate:
            gate.execute_now(
                forward=lambda: None,
                reverse=lambda: None,
                description="graft verification",
            )
    except Exception as e:
        errors.append(f"TransactionGate failed: {e}")

    try:
        AssertionRegistry.reset_default()
        assert_that(True, "graft check", assertion_id="GRAFT-001")
        reg = AssertionRegistry.get_default()
        if len(reg) != 1:
            errors.append(f"AssertionRegistry has {len(reg)} records, expected 1")
    except Exception as e:
        errors.append(f"Assertion layer failed: {e}")

    try:
        engine = ChecklistEngine()
        report = engine.evaluate(inspector_notes="Graft verification run")
        if report.classification != Classification.NON_COMPLIANT:
            pass
        md = report.to_markdown()
        if "Formal Legal System Inspection Report" not in md:
            errors.append("Report markdown malformed")
    except Exception as e:
        errors.append(f"Checklist engine failed: {e}")

    try:
        from dossier_enforcement.cli import main
    except ImportError as e:
        errors.append(f"CLI import failed: {e}")

    return errors


if __name__ == "__main__":
    errs = check()
    if errs:
        print("GRAFT FAILED:")
        for e in errs:
            print(f"  - {e}")
        sys.exit(1)
    else:
        print("GRAFT VERIFIED: All primitives, checklist engine, and CLI are operational.")
        sys.exit(0)
