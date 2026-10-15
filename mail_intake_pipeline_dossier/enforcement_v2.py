"""
Dossier DOSSIER-PIPELINE Real Static Enforcement v2

AST-based enforcement for forbidden control writes and mutator reachability.
This implementation resolves imports, builds a light call graph, tracks aliases,
and detects dynamic-dispatch patterns that can hide forbidden writes.
"""

from __future__ import annotations

import ast
import dataclasses
import re
from dataclasses import dataclass
from pathlib import Path
from typing import (Any, Dict, Iterable, List, Mapping, Optional, Sequence,
                    Set, Tuple)

FORBIDDEN_CONTROL_WRITE_PATTERNS: tuple[str, ...] = (
    r"INSERT\s+INTO\s+control_records",
    r"INSERT\s+INTO\s+control_events",
)

FORBIDDEN_MUTATOR_NAMES: tuple[str, ...] = (
    "mark_seen",
    "ingest",
    "register_send",
    "record",
)

DANGEROUS_DYNAMIC_DISPATCH_NAMES: tuple[str, ...] = (
    "eval",
    "exec",
    "getattr",
    "locals",
    "partial",
)

DYNAMIC_SQL_PATTERNS: tuple[str, ...] = (
    r"INSERT\s+INTO\s+\w+",
    r"UPDATE\s+\w+",
    r"DELETE\s+FROM\s+\w+",
)


@dataclass(frozen=True)
class ForbiddenWriteViolation:
    path: str
    rule: str
    detail: str
    symbol: str = ""
    line_no: int = 0


@dataclass(frozen=True)
class ImportBinding:
    local_name: str
    canonical_name: str
    module: str
    line_no: int


@dataclass(frozen=True)
class FunctionSummary:
    name: str
    qualname: str
    calls: tuple[str, ...]
    imports: tuple[str, ...]


@dataclass(frozen=True)
class ReachabilityReport:
    reachable: bool
    path: tuple[str, ...]
    entry_points: tuple[str, ...]
    target: str


class ImportResolver(ast.NodeVisitor):
    def __init__(self) -> None:
        self.bindings: Dict[str, ImportBinding] = {}
        self.star_imports: Set[str] = set()
        self.module_aliases: Dict[str, str] = {}

    def visit_Import(self, node: ast.Import) -> Any:
        for alias in node.names:
            local = alias.asname or alias.name.split(".")[-1]
            self.bindings[local] = ImportBinding(
                local_name=local,
                canonical_name=alias.name,
                module=alias.name,
                line_no=getattr(node, "lineno", 0),
            )
            self.module_aliases[local] = alias.name

    def visit_ImportFrom(self, node: ast.ImportFrom) -> Any:
        module = node.module or ""
        for alias in node.names:
            if alias.name == "*":
                self.star_imports.add(module)
                continue
            local = alias.asname or alias.name
            canonical = f"{module}.{alias.name}" if module else alias.name
            self.bindings[local] = ImportBinding(
                local_name=local,
                canonical_name=canonical,
                module=module,
                line_no=getattr(node, "lineno", 0),
            )


class CallGraphBuilder(ast.NodeVisitor):
    def __init__(self, imports: Mapping[str, ImportBinding]) -> None:
        self.imports = imports
        self.current_stack: List[str] = []
        self.functions: Dict[str, FunctionSummary] = {}
        self.edges: Dict[str, Set[str]] = {}

    def visit_FunctionDef(self, node: ast.FunctionDef) -> Any:
        self._enter_function(node.name)
        self.generic_visit(node)
        self._leave_function()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> Any:
        self._enter_function(node.name)
        self.generic_visit(node)
        self._leave_function()

    def visit_Call(self, node: ast.Call) -> Any:
        if not self.current_stack:
            return
        caller = self.current_stack[-1]
        callee = self._resolve_call(node.func)
        if callee:
            self.edges.setdefault(caller, set()).add(callee)
        self.generic_visit(node)

    def _enter_function(self, name: str) -> None:
        qualname = ".".join(self.current_stack + [name]) if self.current_stack else name
        self.current_stack.append(qualname)
        self.functions.setdefault(qualname, FunctionSummary(name=name, qualname=qualname, calls=(), imports=()))

    def _leave_function(self) -> None:
        if self.current_stack:
            self.current_stack.pop()

    def _resolve_call(self, node: ast.AST) -> Optional[str]:
        if isinstance(node, ast.Name):
            if node.id in self.imports:
                return self.imports[node.id].canonical_name
            return node.id
        if isinstance(node, ast.Attribute):
            base = self._resolve_call(node.value)
            if base:
                return f"{base}.{node.attr}"
            return node.attr
        if isinstance(node, ast.Call):
            inner = self._resolve_call(node.func)
            return inner
        return None


class DynamicDispatchScanner(ast.NodeVisitor):
    def __init__(self) -> None:
        self.violations: List[ForbiddenWriteViolation] = []

    def visit_Call(self, node: ast.Call) -> Any:
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"eval", "exec", "getattr", "locals", "partial"}:
            self.violations.append(
                ForbiddenWriteViolation(
                    path="",
                    rule="dynamic_dispatch",
                    detail=func.id,
                    line_no=getattr(node, "lineno", 0),
                )
            )
        if isinstance(func, ast.Attribute) and func.attr in {"partial"}:
            self.violations.append(
                ForbiddenWriteViolation(
                    path="",
                    rule="dynamic_dispatch",
                    detail=func.attr,
                    line_no=getattr(node, "lineno", 0),
                )
            )
        self.generic_visit(node)

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        if isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name) and node.value.func.id == "locals":
            self.violations.append(
                ForbiddenWriteViolation(
                    path="",
                    rule="dynamic_dispatch",
                    detail="locals[]",
                    line_no=getattr(node, "lineno", 0),
                )
            )
        self.generic_visit(node)


def resolve_imports(source: str, module_name: str = "") -> Dict[str, ImportBinding]:
    tree = ast.parse(source)
    resolver = ImportResolver()
    resolver.visit(tree)
    return resolver.bindings


def build_call_graph(source: str, module_name: str = "") -> Dict[str, Set[str]]:
    tree = ast.parse(source)
    resolver = ImportResolver()
    resolver.visit(tree)
    builder = CallGraphBuilder(resolver.bindings)
    builder.visit(tree)
    return builder.edges


def scan_forbidden_control_writes(paths: Iterable[Path], allowed_files: Sequence[str]) -> List[ForbiddenWriteViolation]:
    violations: List[ForbiddenWriteViolation] = []
    allowed = {str(Path(path)) for path in allowed_files}
    for path in paths:
        if str(path) in allowed:
            continue
        source = path.read_text(encoding="utf-8")
        for pattern in FORBIDDEN_CONTROL_WRITE_PATTERNS:
            for match in re.finditer(pattern, source, flags=re.IGNORECASE):
                line_no = source.count("\n", 0, match.start()) + 1
                violations.append(
                    ForbiddenWriteViolation(
                        path=str(path),
                        rule="forbidden_control_write",
                        detail=pattern,
                        line_no=line_no,
                    )
                )
    return violations


def scan_forbidden_mutator_calls(paths: Iterable[Path], forbidden_names: Sequence[str] = FORBIDDEN_MUTATOR_NAMES) -> List[ForbiddenWriteViolation]:
    violations: List[ForbiddenWriteViolation] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        resolver = ImportResolver()
        resolver.visit(tree)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_names:
                    violations.append(
                        ForbiddenWriteViolation(
                            path=str(path),
                            rule="forbidden_mutator_call",
                            detail=func.attr,
                            line_no=getattr(node, "lineno", 0),
                        )
                    )
                if isinstance(func, ast.Name) and func.id in forbidden_names:
                    violations.append(
                        ForbiddenWriteViolation(
                            path=str(path),
                            rule="forbidden_mutator_call",
                            detail=func.id,
                            line_no=getattr(node, "lineno", 0),
                        )
                    )
    return violations


def scan_dynamic_dispatch(paths: Iterable[Path]) -> List[ForbiddenWriteViolation]:
    violations: List[ForbiddenWriteViolation] = []
    for path in paths:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        scanner = DynamicDispatchScanner()
        scanner.visit(tree)
        for violation in scanner.violations:
            violations.append(dataclasses.replace(violation, path=str(path)))
    return violations


def compute_reachability(call_graph: Mapping[str, Set[str]], entry_points: Sequence[str], target: str) -> ReachabilityReport:
    stack = [(entry, (entry,)) for entry in entry_points]
    visited: Set[str] = set()
    while stack:
        current, path = stack.pop()
        if current == target:
            return ReachabilityReport(True, path, tuple(entry_points), target)
        if current in visited:
            continue
        visited.add(current)
        for callee in call_graph.get(current, set()):
            if callee not in visited:
                stack.append((callee, path + (callee,)))
    return ReachabilityReport(False, tuple(), tuple(entry_points), target)


def scan_project_for_mutator_reachability(paths: Iterable[Path], entry_points: Sequence[str], target: str) -> ReachabilityReport:
    call_graph: Dict[str, Set[str]] = {}
    for path in paths:
        source = path.read_text(encoding="utf-8")
        call_graph.update(build_call_graph(source))
    return compute_reachability(call_graph, entry_points, target)
