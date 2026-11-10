#!/usr/bin/env python3
"""Reproducible audit stamp for the tree.

Every figure is derived from git or from the AST, never from a walk of the
working directory. A filesystem walk counts untracked, ignored and generated
files, so two machines at the same commit report different numbers — which is
the opposite of what a stamp is for.

The counters measure the quantities the audit names:

    routes  ``@app.<method>("...")`` decorators parsed from
            ``interface/anchorum_api.py``. Two of them are declared across two
            physical lines; the AST does not care, a line-oriented grep does.
    tests   test *cases* collected by pytest, not test files.
    files   tracked ``*.py`` paths from ``git ls-files``.
    tree    ``git rev-parse HEAD^{tree}``, the real git tree object.

Nothing is written into the repository unless ``--output`` is passed. The
generator used to write ``docs/audit/AUDIT_STAMP.json`` on every invocation and
that file was committed, so a machine-local hash entered version control and
churned without the tree changing.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

HTTP_METHODS = frozenset({"get", "post", "put", "patch", "delete", "head", "options"})
ROUTES_MODULE = Path("interface") / "anchorum_api.py"
# pytest renders its summary inside a run of '=' characters, so the count is
# never at the start of the line: "==== 759 tests collected in 1.28s ====".
# Anchoring the pattern with ^ silently matches nothing and reports zero tests,
# which is worse than a failed count because zero is a plausible-looking number.
COLLECTED_PATTERN = re.compile(r"(\d+)\s+tests?\s+collected")
EXCLUDED_PARTS = frozenset({"node_modules", ".venv", ".git"})
PROGRAM_DESCRIPTION = "Generate a reproducible audit stamp from git and the AST."


def run_git(root: Path, *arguments: str) -> str:
    """Run a git command and return its stripped stdout."""
    completed = subprocess.run(
        ["git", "-C", str(root), *arguments],
        capture_output=True,
        text=True,
        check=True,
    )
    return completed.stdout.strip()


def count_tracked_python_files(root: Path) -> int:
    """Count tracked ``*.py`` paths, excluding vendored trees."""
    paths = run_git(root, "ls-files", "*.py").splitlines()
    return sum(
        1 for path in paths if not (EXCLUDED_PARTS & set(Path(path).parts))
    )


def count_routes(root: Path) -> int:
    """Count route registrations by walking the module's decorators.

    A route is a decorator of the form ``@app.<method>("<path>")``. Parsing the
    AST rather than grepping lines is what makes the two-line declarations
    count: ``@app.post(`` with the path on the next line is one ``ast.Call``
    either way.
    """
    module_path = root / ROUTES_MODULE
    if not module_path.is_file():
        return 0
    tree = ast.parse(module_path.read_text(encoding="utf-8"), filename=str(module_path))
    total = 0
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if _is_route_decorator(decorator):
                total += 1
    return total


def _is_route_decorator(decorator: ast.expr) -> bool:
    """True when the expression is ``app.<http-method>(<string>)``."""
    if not isinstance(decorator, ast.Call):
        return False
    function = decorator.func
    if not isinstance(function, ast.Attribute) or function.attr not in HTTP_METHODS:
        return False
    if not isinstance(function.value, ast.Name) or function.value.id != "app":
        return False
    return bool(decorator.args) and isinstance(decorator.args[0], ast.Constant)


def count_collected_tests(root: Path) -> int | None:
    """Count test cases pytest collects, or None when collection fails.

    A failure is reported as None rather than zero: zero would read as "there
    are no tests", which is a different and much worse claim than "collection
    did not complete".
    """
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    match = COLLECTED_PATTERN.search(completed.stdout)
    if match:
        return int(match.group(1))
    if completed.returncode != 0:
        return None
    return sum(1 for line in completed.stdout.splitlines() if "::" in line)


def tree_hash(root: Path) -> str:
    """The git tree object for HEAD, which is what identifies the content."""
    return run_git(root, "rev-parse", "HEAD^{tree}")


def commit_sha(root: Path) -> str:
    """The current HEAD commit, or ``unknown`` outside a repository."""
    try:
        return run_git(root, "rev-parse", "HEAD")
    except subprocess.CalledProcessError:
        return "unknown"


def build_report(root: Path) -> dict:
    """Assemble the stamp."""
    sha = commit_sha(root)
    return {
        "commit": sha,
        "commit_short": sha[:7],
        "tree": tree_hash(root),
        "counts": {
            "routes": count_routes(root),
            "tests": count_collected_tests(root),
            "tracked_python_files": count_tracked_python_files(root),
        },
    }


def parse_args(argv: list[str]) -> argparse.Namespace:
    """Parse arguments. ``--output`` takes a value; it is never positional."""
    parser = argparse.ArgumentParser(description=PROGRAM_DESCRIPTION)
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="write the JSON report here; omit to print it to stdout",
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="repository root (default: the parent of this script's directory)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Entry point."""
    arguments = parse_args(sys.argv[1:] if argv is None else argv)
    report = build_report(arguments.root)
    serialised = json.dumps(report, indent=2, sort_keys=True)
    if arguments.output is None:
        print(serialised)
        return 0
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(serialised + "\n", encoding="utf-8")
    print(f"wrote {arguments.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
