"""Tests for scripts/check_audit_freshness.py."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_audit_freshness.py"
AUDIT = Path("docs/audit/CAPABILITY_AUDIT.md")


def stamp_line_in(text: str) -> str:
    r"""Return the exact `Findings reflect commit \`<sha>\`` line in text."""
    m = re.search(r"Findings reflect commit `[0-9a-f]{7,40}`", text)
    assert m, "fixture: no stamp line in audit doc"
    return m.group(0)


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=Path.cwd(),
    )


def test_current_tree_passes():
    r = run("--strict")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "STALE" not in r.stdout
    assert "OK" in r.stdout


def test_unknown_stamp_fails_strict():
    original = AUDIT.read_text(encoding="utf-8")
    try:
        AUDIT.write_text(
            original.replace(
                stamp_line_in(original),
                "Findings reflect commit `deadbeef`",
            ),
            encoding="utf-8",
        )
        r = run("--strict")
        assert r.returncode == 1
        assert "STALE" in r.stdout
    finally:
        AUDIT.write_text(original, encoding="utf-8")


def test_unknown_stamp_warns_without_strict():
    original = AUDIT.read_text(encoding="utf-8")
    try:
        AUDIT.write_text(
            original.replace(
                stamp_line_in(original),
                "Findings reflect commit `deadbeef`",
            ),
            encoding="utf-8",
        )
        r = run()
        assert r.returncode == 0
        assert "STALE" in r.stdout
    finally:
        AUDIT.write_text(original, encoding="utf-8")
