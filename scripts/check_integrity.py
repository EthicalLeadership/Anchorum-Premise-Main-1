#!/usr/bin/env python3
"""Validate staged source integrity, or all tracked source with --all."""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
SOURCE_SUFFIXES = {".py", ".json", ".sh"}


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


def _check_pipeline(tree: ast.Module) -> list[str]:
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
            node for node in tree.body
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


def _check(path: str, content: bytes) -> list[str]:
    suffix = Path(path).suffix.lower()
    if suffix not in SOURCE_SUFFIXES and path != "interface/src/adapter.ts":
        return []

    errors: list[str] = []
    try:
        text = content.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"not valid UTF-8: {exc}"]

    if suffix == ".py":
        try:
            tree = ast.parse(text, filename=path)
        except SyntaxError as exc:
            errors.append(f"Python syntax error at line {exc.lineno}: {exc.msg}")
            return errors
        if path == "dossier_pipeline/pipeline.py":
            errors.extend(_check_pipeline(tree))
    elif suffix == ".json":
        try:
            json.loads(text)
        except json.JSONDecodeError as exc:
            errors.append(f"JSON syntax error at line {exc.lineno}, column {exc.colno}: {exc.msg}")
    elif suffix == ".sh":
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

    if path == "interface/src/adapter.ts":
        declarations = re.findall(
            r"(?m)^\s*export\s+interface\s+AdapterConfig\b",
            text,
        )
        if len(declarations) != 1:
            errors.append(
                f"expected exactly one exported AdapterConfig interface; found {len(declarations)}"
            )
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="check all tracked files from the working tree instead of the index",
    )
    args = parser.parse_args(argv)

    staged = not args.all
    paths = (
        _git_paths("ls-files", "-z")
        if args.all
        else _git_paths("diff", "--cached", "--name-only", "--diff-filter=ACMR", "-z")
    )
    failures: list[str] = []
    checked = 0
    for path in paths:
        if Path(path).suffix.lower() not in SOURCE_SUFFIXES and path != "interface/src/adapter.ts":
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
