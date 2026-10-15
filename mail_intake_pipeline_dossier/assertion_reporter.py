"""
Dossier DOSSIER-PIPELINE Assertion Reporting

Collects runtime invariant violations for structured audit output without
introducing a persistence dependency into the assertion engine itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List


@dataclass
class AssertionReporter:
    failures: List[Dict[str, Any]] = field(default_factory=list)

    def record(self, invariant_id: str, context: Dict[str, Any]) -> None:
        self.failures.append(
            {
                "invariant": invariant_id,
                "context": context,
            }
        )

    def summary(self) -> Dict[str, Any]:
        return {
            "total_failures": len(self.failures),
            "failures": list(self.failures),
        }
