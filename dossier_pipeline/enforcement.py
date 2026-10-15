"""
Dossier DOSSIER-PIPELINE Mutation Lattice Enforcement

Centralized forbidden-edge definitions and static guards for the write-path
lattice. The intent is to make the architectural contract testable in CI.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Sequence

FORBIDDEN_CONTROL_WRITE_PATTERNS: tuple[str, ...] = (
    "INSERT INTO control_records",
    "INSERT INTO control_events",
)

FORBIDDEN_MUTATOR_NAMES: tuple[str, ...] = (
    "mark_seen",
    "ingest",
    "register_send",
    "record",
)


@dataclass(frozen=True)
class ForbiddenWriteViolation:
    path: str
    rule: str
    detail: str


def scan_forbidden_control_writes(paths: Iterable[Path], allowed_files: Sequence[str]) -> List[ForbiddenWriteViolation]:
    violations: List[ForbiddenWriteViolation] = []
    allowed = {str(Path(path)) for path in allowed_files}
    for path in paths:
        if str(path) in allowed:
            continue
        text = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_CONTROL_WRITE_PATTERNS:
            if pattern.lower() in text.lower():
                violations.append(
                    ForbiddenWriteViolation(
                        path=str(path),
                        rule="forbidden_control_write",
                        detail=pattern,
                    )
                )
    return violations


def scan_forbidden_mutator_calls(paths: Iterable[Path], forbidden_names: Sequence[str] = FORBIDDEN_MUTATOR_NAMES) -> List[ForbiddenWriteViolation]:
    violations: List[ForbiddenWriteViolation] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_names:
                    violations.append(
                        ForbiddenWriteViolation(
                            path=str(path),
                            rule="forbidden_mutator_call",
                            detail=func.attr,
                        )
                    )
    return violations
