"""
dossier_enforcement.checklist
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Lightweight inspection checklist engine used by the graft verifier.

The implementation is intentionally simple and deterministic:
- produces a formal report object
- exposes a markdown formatter
- defaults to a non-compliant classification in an empty workspace
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import List, Optional


class Classification(Enum):
    COMPLIANT = auto()
    NON_COMPLIANT = auto()
    NEEDS_REVIEW = auto()


@dataclass(frozen=True)
class ControlScore:
    control_id: str
    name: str
    passed: bool
    rationale: str = ""


@dataclass
class ChecklistReport:
    inspector_notes: str
    classification: Classification
    controls: List[ControlScore] = field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# Formal Legal System Inspection Report",
            "",
            f"**Classification:** {self.classification.name}",
            "",
            f"**Inspector notes:** {self.inspector_notes}",
            "",
        ]
        if self.controls:
            lines.append("## Controls")
            for control in self.controls:
                status = "PASS" if control.passed else "FAIL"
                lines.append(f"- {control.control_id} {control.name} [{status}] {control.rationale}".rstrip())
        else:
            lines.append("_No controls evaluated._")
        return "\n".join(lines)


class ChecklistEngine:
    def evaluate(self, inspector_notes: str = "") -> ChecklistReport:
        return ChecklistReport(
            inspector_notes=inspector_notes,
            classification=Classification.NON_COMPLIANT,
            controls=[],
        )
