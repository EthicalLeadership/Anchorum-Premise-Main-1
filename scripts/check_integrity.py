#!/usr/bin/env python3
"""Validate source integrity: staged files by default, all tracked with --all.

Generic checks (path-independent), in the order they run:

  1. syntax     - ``ast.parse`` / ``json.loads`` / ``bash -n``
  2. dupdecl    - a Python module defining the same top-level def/class twice
  3. docimport  - an import statement stranded inside a module docstring
  4. dupcontent - a file whose own content repeats (whole-file or block)
  5. dupexport  - a TypeScript module exporting the same name twice
  6. emptyfile  - a zero-byte tracked source file

Checks 2-6 exist because three files in this repository were silently
corrupted by a text writer that duplicated or displaced content, and all
three still parsed cleanly - so a syntax check alone did not catch them:

  * ``dossier_pipeline/contracts.py``   duplicated wholesale (exactly 2x)
  * ``dossier_pipeline/pipeline.py``    import displaced into the docstring
  * ``interface/src/adapter.ts``        content repeated with mangled seams

Targeted regression guards for those specific files are kept at the end.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Iterable, Sequence


ROOT = Path(__file__).resolve().parent.parent

PYTHON_SUFFIXES = {".py"}
SCRIPT_SUFFIXES = {".sh"}
TYPESCRIPT_SUFFIXES = {".ts", ".tsx"}
JSON_SUFFIXES = {".json"}
SOURCE_SUFFIXES = (
    PYTHON_SUFFIXES | SCRIPT_SUFFIXES | TYPESCRIPT_SUFFIXES | JSON_SUFFIXES
)

# Files that are legitimately empty.
EMPTY_FILE_ALLOWLIST = {"__init__.py", ".gitkeep", "py.typed", "__init__.pyi"}

# A repeated block must be this many non-blank lines and this many characters
# before it is treated as duplicated content rather than coincidence.
REPEATED_BLOCK_LINES = 15
REPEATED_BLOCK_CHARS = 300

# Files larger than this are syntax-checked only (huge generated JSON blobs
# are not worth the memory or the false-positive risk).
MAX_DEEP_CHECK_BYTES = 2_000_000

ASSIGNMENT_IMPORT_RE = re.compile(r"^\s*(import|from)\s+")
TS_EXPORT_RE = re.compile(
    r"^\s*export\s+(?:declare\s+)?(?:default\s+)?(?:async\s+)?"
    r"(?:abstract\s+)?(?:function|class|interface|type|enum|const|let|var)\s+"
    r"([A-Za-z_$][A-Za-z0-9_$]*)",
    re.MULTILINE,
)


def _git_paths(*args: str) -> list[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
    )
    return [
        path.decode("utf-8", errors="surrogateescape")
        for path in result.stdout.split(b"\0")
        if path
    ]


def _content(path: str, *, staged: bool) -> bytes:
    if staged:
        result = subprocess.run(
            ["git", "show", f":{path}"],
            cwd=ROOT,
            check=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        return result.stdout
    return (ROOT / path).read_bytes()


def _is_source(path: str) -> bool:
    return Path(path).suffix.lower() in SOURCE_SUFFIXES


def _duplicate_names(names: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)
    return sorted(duplicates)


# --------------------------------------------------------------------------
# check 2 + 3: python structure
# --------------------------------------------------------------------------

def _python_duplicate_definitions(tree: ast.Module) -> list[str]:
    names = [
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    ]
    return _duplicate_names(names)


def _module_docstring(tree: ast.Module) -> ast.Constant | None:
    if not tree.body:
        return None
    first = tree.body[0]
    if (
        isinstance(first, ast.Expr)
        and isinstance(first.value, ast.Constant)
        and isinstance(first.value.value, str)
    ):
        return first.value
    return None


def _imports_inside_docstring(tree: ast.Module, text: str) -> list[int]:
    """Return line numbers of import statements stranded in the docstring.

    A line is only flagged when it both looks like an import and actually
    parses as one, so prose such as "import cleanly. Catches ..." is ignored.
    """
    docstring = _module_docstring(tree)
    if docstring is None:
        return []
    start = docstring.lineno
    end = docstring.end_lineno or start
    lines = text.splitlines()
    flagged: list[int] = []
    for lineno in range(start, min(end, len(lines)) + 1):
        line = lines[lineno - 1]
        if not ASSIGNMENT_IMPORT_RE.match(line):
            continue
        try:
            parsed = ast.parse(line)
        except SyntaxError:
            continue
        if any(isinstance(node, (ast.Import, ast.ImportFrom)) for node in parsed.body):
            flagged.append(lineno)
    return flagged


def _check_python(path: str, text: str) -> tuple[list[str], ast.Module | None]:
    try:
        tree = ast.parse(text, filename=path)
    except SyntaxError as exc:
        return [f"Python syntax error at line {exc.lineno}: {exc.msg}"], None

    errors: list[str] = []

    duplicates = _python_duplicate_definitions(tree)
    if duplicates:
        errors.append(
            "duplicate top-level definition(s): " + ", ".join(duplicates)
        )

    for lineno in _imports_inside_docstring(tree, text):
        errors.append(
            f"line {lineno}: import statement inside the module docstring"
        )

    return errors, tree


# --------------------------------------------------------------------------
# check 5: typescript structure
# --------------------------------------------------------------------------

def _check_typescript(path: str, text: str) -> list[str]:
    names = [match.group(1) for match in TS_EXPORT_RE.finditer(text)]
    duplicates = _duplicate_names(names)
    if not duplicates:
        return []
    return ["duplicate exported declaration(s): " + ", ".join(duplicates)]


# --------------------------------------------------------------------------
# check 4: repeated content
# --------------------------------------------------------------------------

def _repeated_block(text: str) -> tuple[int, int] | None:
    """Return (offset, occurrences) when a leading block repeats, else None."""
    non_blank = [line.rstrip() for line in text.splitlines() if line.strip()]
    window = REPEATED_BLOCK_LINES
    if len(non_blank) < window * 2:
        return None

    last_start = len(non_blank) - window
    for offset in range(min(40, last_start + 1)):
        block = non_blank[offset : offset + window]
        if sum(len(line) for line in block) < REPEATED_BLOCK_CHARS:
            continue
        occurrences = sum(
            1
            for start in range(last_start + 1)
            if non_blank[start : start + window] == block
        )
        if occurrences >= 2:
            return offset, occurrences
    return None


# --------------------------------------------------------------------------
# targeted regression guards
# --------------------------------------------------------------------------

def _check_pipeline_regression(tree: ast.Module) -> list[str]:
    errors: list[str] = []
    has_fpdf_import = any(
        isinstance(node, ast.ImportFrom)
        and node.module == "fpdf"
        and any(alias.name == "FPDF" for alias in node.names)
        for node in tree.body
    )
    if not has_fpdf_import:
        errors.append("pipeline.py must import FPDF at module scope")

    pipeline_class = next(
        (
            node
            for node in tree.body
            if isinstance(node, ast.ClassDef) and node.name == "DossierPipeline"
        ),
        None,
    )
    has_pdf_method = pipeline_class is not None and any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "_generate_pdf"
        for node in pipeline_class.body
    )
    if not has_pdf_method:
        errors.append("DossierPipeline must define _generate_pdf directly")
    return errors


def _check_adapter_regression(text: str) -> list[str]:
    declarations = re.findall(
        r"(?m)^\s*export\s+interface\s+AdapterConfig\b",
        text,
    )
    if len(declarations) != 1:
        return [
            "expected exactly one exported AdapterConfig interface; "
            f"found {len(declarations)}"
        ]
    return []


# --------------------------------------------------------------------------
# dispatch
# --------------------------------------------------------------------------

def _check(path: str, content: bytes) -> list[str]:
    suffix = Path(path).suffix.lower()
    if suffix not in SOURCE_SUFFIXES:
        return []

    name = Path(path).name
    if not content:
        if name in EMPTY_FILE_ALLOWLIST:
            return []
        return [f"tracked source file is empty ({name})"]

    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"not valid UTF-8: {exc}"]

    errors: list[str] = []
    tree: ast.Module | None = None

    if suffix in PYTHON_SUFFIXES:
        python_errors, tree = _check_python(path, text)
        errors.extend(python_errors)
    elif suffix in JSON_SUFFIXES:
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(
                f"JSON syntax error at line {exc.lineno}, column {exc.colno}: {exc.msg}"
            )
    elif suffix in SCRIPT_SUFFIXES:
        result = subprocess.run(
            ["bash", "-n"],
            input=content,
            cwd=ROOT,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if result.returncode:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            errors.append(f"shell syntax error: {detail}")
    elif suffix in TYPESCRIPT_SUFFIXES:
        errors.extend(_check_typescript(path, text))

    # Repeated-content detection is meaningful for authored source only;
    # generated/dependency JSON is legitimately repetitive.
    if suffix != ".json" and len(content) <= MAX_DEEP_CHECK_BYTES:
        repeated = _repeated_block(text)
        if repeated is not None:
            offset, occurrences = repeated
            errors.append(
                "content appears duplicated: a "
                f"{REPEATED_BLOCK_LINES}-line block repeats {occurrences} times "
                f"(first seen at non-blank line {offset + 1})"
            )

    if path == "dossier_pipeline/pipeline.py" and tree is not None:
        errors.extend(_check_pipeline_regression(tree))
    if path == "interface/src/adapter.ts":
        errors.extend(_check_adapter_regression(text))

    return errors


# --------------------------------------------------------------------------
# self-test: prove every check actually fires
# --------------------------------------------------------------------------

def _duplicated_module_sample() -> str:
    """A realistically sized module, used doubled, mirroring contracts.py.

    Lines must be substantial: the repeated-block check requires a 15-line
    window of at least REPEATED_BLOCK_CHARS characters, so a fixture built
    from very short lines would not represent real source.
    """
    return "".join(
        f"class Record{index:02d}:\n"
        f"    name: str = 'record-{index:02d}'\n"
        f"    label: str = 'label-{index:02d}'\n\n\n"
        for index in range(12)
    )


_SELFTEST_CASES: tuple[tuple[str, str, bytes, str], ...] = (
    (
        "zero-byte tracked source file",
        "interface/src/empty.ts",
        b"",
        "is empty",
    ),
    (
        "python syntax error",
        "pkg/broken.py",
        b"def broken(:\n    pass\n",
        "Python syntax error",
    ),
    (
        "duplicate top-level definitions",
        "pkg/duplicate.py",
        b"def alpha():\n    return 1\n\n\n"
        b"class Beta:\n    pass\n\n\n"
        b"def alpha():\n    return 2\n",
        "duplicate top-level definition",
    ),
    (
        "import inside the module docstring",
        "pkg/docstring_import.py",
        b'"""Title.\n\nfrom fpdf import FPDF\nBody text.\n"""\n\nimport os\n',
        "import statement inside the module docstring",
    ),
    (
        "duplicated file content",
        "pkg/doubled.py",
        (_duplicated_module_sample() * 2).encode(),
        "content appears duplicated",
    ),
    (
        "duplicate typescript export",
        "interface/src/duplicate.tsx",
        b"export interface Foo {\n  a: string;\n}\n\n"
        b"export interface Foo {\n  b: string;\n}\n",
        "duplicate exported declaration",
    ),
)


def _selftest() -> int:
    missing = 0
    for label, path, content, expected in _SELFTEST_CASES:
        findings = _check(path, content)
        if any(expected in finding for finding in findings):
            print(f"PASS selftest: {label}")
        else:
            missing += 1
            detail = (findings or ["no findings"])[0]
            print(
                f"FAIL selftest: {label} was not detected ({detail})",
                file=sys.stderr,
            )
    if missing:
        print(
            f"FAIL {missing} integrity selftest case(s) did not fire",
            file=sys.stderr,
        )
        return 1
    print(f"OK integrity selftest passed ({len(_SELFTEST_CASES)} cases)")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="check all tracked files from the working tree instead of the index",
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run the built-in corruption fixtures and verify every check fires",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    staged = not args.all
    paths = (
        _git_paths("ls-files", "-z")
        if args.all
        else _git_paths("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    )

    failures: list[str] = []
    checked = 0
    for path in paths:
        if not _is_source(path):
            continue
        try:
            content = _content(path, staged=staged)
        except (OSError, subprocess.CalledProcessError) as exc:
            failures.append(f"{path}: could not read source: {exc}")
            continue
        checked += 1
        failures.extend(f"{path}: {error}" for error in _check(path, content))

    if failures:
        for failure in failures:
            print(f"FAIL {failure}", file=sys.stderr)
        return 1
    print(f"OK integrity checks passed ({checked} source files)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
