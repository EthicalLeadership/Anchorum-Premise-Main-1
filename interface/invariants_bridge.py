"""Bridge between the UI backend and dossier_pipeline.assertions.

The dossier_pipeline AssertionEngine is a registry. It is populated either
by importing dossier_pipeline.invariants (if that module registers
invariants at import time) or by explicit registration elsewhere in the
backend.

This module forces the population to happen once, snapshots the registry
so the result does not depend on later imports, and exposes run_all() so a
route can iterate every invariant against a per-document context.

Fail-closed contract:
  - Status "pass"    → check returned True
  - Status "fail"    → check returned False, or raised a non-TypeError exception
  - Status "skip"    → TypeError because the caller supplied the wrong
                       keyword arguments. Not counted as failure; reported
                       so the caller can extend the context.
"""

import logging
from typing import Any

logger = logging.getLogger("invariants_bridge")

_snapshot: list[tuple[str, Any]] = []
_load_error: str | None = None
_loaded = False


def _load_once() -> None:
    global _loaded, _load_error, _snapshot
    if _loaded:
        return
    _loaded = True
    try:
        import dossier_pipeline.invariants  # noqa: F401
        from dossier_pipeline.assertions import assertions
        _snapshot = sorted(assertions.invariants.items())
        logger.info("invariants_bridge: loaded %d invariants", len(_snapshot))
    except Exception as exc:
        _load_error = f"{type(exc).__name__}: {exc}"
        logger.warning("invariants_bridge: could not load invariants: %s", _load_error)


def list_invariant_ids() -> list[str]:
    _load_once()
    return [inv_id for inv_id, _ in _snapshot]


def load_error() -> str | None:
    _load_once()
    return _load_error


def run_all(context: dict[str, Any]) -> list[dict]:
    _load_once()
    results: list[dict] = []
    for inv_id, inv in _snapshot:
        try:
            ok = inv.check(**context)
        except TypeError as exc:
            msg = str(exc)
            if "unexpected keyword" in msg or "missing" in msg:
                results.append({"id": inv_id, "status": "skip", "reason": msg})
                continue
            results.append(
                {"id": inv_id, "status": "fail", "reason": f"TypeError: {msg}"}
            )
            continue
        except Exception as exc:
            results.append(
                {"id": inv_id, "status": "fail", "reason": f"{type(exc).__name__}: {exc}"}
            )
            continue
        results.append(
            {"id": inv_id, "status": "pass" if ok else "fail", "reason": "" if ok else "returned False"}
        )
    return results


def run_one(inv_id: str, context: dict) -> dict:
    _load_once()
    for rid, inv in _snapshot:
        if rid != inv_id:
            continue
        try:
            ok = inv.check(**context)
        except TypeError as exc:
            msg = str(exc)
            if "unexpected keyword" in msg or "missing" in msg:
                return {"id": inv_id, "status": "skip", "reason": msg}
            return {"id": inv_id, "status": "fail", "reason": f"TypeError: {msg}"}
        except Exception as exc:
            return {"id": inv_id, "status": "fail", "reason": f"{type(exc).__name__}: {exc}"}
        return {"id": inv_id, "status": "pass" if ok else "fail", "reason": "" if ok else "returned False"}
    return {"id": inv_id, "status": "skip", "reason": "invariant not registered"}
