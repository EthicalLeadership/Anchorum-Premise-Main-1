"""Tests for scripts/check_audit_freshness.py.

The end-to-end tests run against a throwaway repository in `tmp_path`, not this
one. That isolation is deliberate: pytest runs inside the pre-commit hook, where
the index is not clean by definition and where staging a probe file would risk
adding it to the commit under construction. An earlier version of this file
assumed a clean index and failed at commit time for exactly that reason.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "check_audit_freshness.py"
AUDIT = Path("docs/audit/CAPABILITY_AUDIT.md")

GIT_ENV = {
    **os.environ,
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@example.invalid",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@example.invalid",
}


def stamp_line_in(text: str) -> str:
    r"""Return the exact `Findings reflect commit \`<sha>\`` line in text."""
    m = re.search(r"Findings reflect commit `[0-9a-f]{7,40}`", text)
    assert m, "fixture: no stamp line in audit doc"
    return m.group(0)


def run(*args: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        capture_output=True, text=True, cwd=cwd or Path.cwd(),
    )


def make_repo(tmp_path: Path) -> tuple[Path, str]:
    """A repo whose audit is stamped at the commit before it was added."""
    repo = tmp_path / "repo"
    repo.mkdir()

    def g(*a: str) -> None:
        subprocess.run(["git", *a], cwd=repo, check=True,
                       capture_output=True, env=GIT_ENV)

    g("init", "-q")
    (repo / "code.py").write_text("x = 1\n", encoding="utf-8")
    g("add", ".")
    g("commit", "-qm", "code")
    stamp = subprocess.check_output(
        ["git", "rev-parse", "--short", "HEAD"], cwd=repo, text=True,
        env=GIT_ENV,
    ).strip()

    (repo / "docs" / "audit").mkdir(parents=True)
    (repo / "docs" / "audit" / "SPEC.md").write_text(
        f"# Spec\n\nFindings reflect commit `{stamp}`.\n", encoding="utf-8"
    )
    g("add", ".")
    g("commit", "-qm", "audit")
    return repo, stamp


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


def test_isolated_repo_is_clean_then_committed_drift_is_detected(tmp_path):
    """HEAD mode: clean right after the audit commit, STALE after a code commit."""
    repo, _ = make_repo(tmp_path)

    r = run("--strict", cwd=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout

    (repo / "code.py").write_text("x = 2\n", encoding="utf-8")
    subprocess.run(["git", "commit", "-qam", "code change"], cwd=repo,
                   check=True, capture_output=True, env=GIT_ENV)

    r = run("--strict", cwd=repo)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "STALE" in r.stdout
    assert "code.py" in r.stdout


def test_staged_mode_detects_drift_that_head_cannot_see(tmp_path):
    """The regression this flag exists for.

    A staged change is invisible to `stamp..HEAD`, because HEAD still points at
    the previous commit. `--staged` must see it, or the pre-commit hook's check
    can never fire.
    """
    repo, _ = make_repo(tmp_path)

    (repo / "code.py").write_text("x = 3\n", encoding="utf-8")
    subprocess.run(["git", "add", "code.py"], cwd=repo, check=True,
                   capture_output=True, env=GIT_ENV)

    head_mode = run("--strict", cwd=repo)
    assert head_mode.returncode == 0, head_mode.stdout
    assert "STALE" not in head_mode.stdout

    staged_mode = run("--staged", "--strict", cwd=repo)
    assert staged_mode.returncode == 1, staged_mode.stdout
    assert "STALE" in staged_mode.stdout
    assert "code.py" in staged_mode.stdout


def test_audit_document_does_not_make_itself_stale(tmp_path):
    """Each audit is excluded from its own check, so editing it stays clean."""
    repo, _ = make_repo(tmp_path)
    doc = repo / "docs" / "audit" / "SPEC.md"

    doc.write_text(
        doc.read_text(encoding="utf-8") + "\nA later note.\n", encoding="utf-8"
    )
    subprocess.run(["git", "commit", "-qam", "audit note"], cwd=repo,
                   check=True, capture_output=True, env=GIT_ENV)

    r = run("--strict", cwd=repo)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "OK" in r.stdout
