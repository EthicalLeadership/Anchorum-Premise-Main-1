"""
Dossier DOSSIER-PIPELINE Runtime Assertion Engine

Composable invariant registry with strict/warn behavior controlled by
ASSERT_STRICT. Intended to be imported by pipeline stages and invariant
definitions so violations are attributable, logged, and actionable.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import Any, Callable, Dict, Mapping

logger = logging.getLogger("assertions")
STRICT_MODE = os.getenv("ASSERT_STRICT", "true").lower() == "true"


class InvariantViolation(Exception):
    """Raised when a registered invariant fails in strict mode."""


@dataclass(frozen=True)
class Invariant:
    id: str
    description: str
    check: Callable[..., bool]


class AssertionEngine:
    def __init__(self) -> None:
        self.invariants: Dict[str, Invariant] = {}

    def register(self, invariant: Invariant) -> None:
        self.invariants[invariant.id] = invariant

    def validate(self, invariant_id: str, **context: Any) -> None:
        if invariant_id not in self.invariants:
            raise KeyError(f"Unknown invariant: {invariant_id}")

        invariant = self.invariants[invariant_id]

        try:
            result = invariant.check(**context)
        except Exception as exc:
            self._handle_failure(invariant, context, f"Exception during check: {exc}")
            return

        if not result:
            self._handle_failure(invariant, context, "Returned False")

    def _handle_failure(self, invariant: Invariant, context: Mapping[str, Any], reason: str) -> None:
        msg = f"[{invariant.id}] {invariant.description} FAILED: {reason} | context={dict(context)}"
        if STRICT_MODE:
            raise InvariantViolation(msg)
        logger.error(msg)


assertions = AssertionEngine()
