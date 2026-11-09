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


def _find_audit_or_fail(repo, second):
    """Locate the file in the isolated repo that contains the freshness stamp.

    Matches on content, not path — make_repo creates docs/audit/SPEC.md
    with the 'Findings reflect commit `<sha>`' format, but the parent
    repo uses docs/audit/CAPABILITY_AUDIT.md with the '**Tree stamp:**'
    format. Both must be discoverable without hardcoding either path.
    """
    for f in sorted(repo.rglob("*.md")):
        if ".git" in f.parts:
            continue
        try:
            text = f.read_text(encoding="utf-8")
        except Exception:
            continue
        if "Findings reflect commit" in text or "Tree stamp" in text:
            return f

    dump = []
    for f in sorted(repo.rglob("*")):
        if f.is_file() and ".git" not in f.parts:
            try:
                preview = f.read_text(encoding="utf-8", errors="replace")[:200]
            except Exception:
                preview = "<binary>"
            dump.append(f"--- {f.relative_to(repo)} ---\n{preview}\n")
    raise AssertionError(
        "No file with a freshness stamp in isolated repo.\n"
        f"make_repo second={second!r}\n" + "\n".join(dump)
    )


def _stamp_deadbeef_and_commit(audit, repo):
    """Rewrite the freshness stamp SHA to a fabricated value and commit it.

    Supports both formats observed in practice:
      Findings reflect commit `<sha>`     (make_repo's isolated repo)
      **Tree stamp:** `<sha>`             (parent repo, current)
      **Tree stamp:** commit `<sha>`      (parent repo, prior)
    """
    original = audit.read_text(encoding="utf-8")
    fake = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    patterns = [
        (r"(Findings reflect commit `)[0-9a-f]{7,40}(`)", rf"\g<1>{fake}\g<2>"),
        (r"(\*\*Tree stamp:\*\*\s*(?:commit\s*)?`?)[0-9a-f]{7,40}(`?)", rf"\g<1>{fake}\g<2>"),
    ]
    new_text, n = original, 0
    for pattern, repl in patterns:
        new_text, n = re.subn(pattern, repl, original, count=1)
        if n > 0:
            break
    if n == 0:
        raise AssertionError(
            f"No freshness stamp pattern matched in {audit}.\n"
            f"first 500 chars:\n{original[:500]}"
        )
    audit.write_text(new_text, encoding="utf-8")
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "test",
        "GIT_AUTHOR_EMAIL": "test@example.com",
        "GIT_COMMITTER_NAME": "test",
        "GIT_COMMITTER_EMAIL": "test@example.com",
    }
    rel = str(audit.relative_to(repo))
    subprocess.run(["git", "add", rel], cwd=repo, check=True, env=env)
    subprocess.run(
        ["git", "commit", "-m", "test: stamp unknown sha"],
        cwd=repo, check=True, env=env,
    )


def test_unknown_stamp_fails_strict(tmp_path):
    """A stamp pointing at an unknown commit must be STALE under --strict."""
    repo, second = make_repo(tmp_path)
    audit = _find_audit_or_fail(repo, second)
    _stamp_deadbeef_and_commit(audit, repo)
    r = run("--strict", cwd=repo)
    assert r.returncode == 1, f"expected 1, got {r.returncode}: {r.stdout!r}"
    assert "STALE" in r.stdout, f"expected STALE: {r.stdout!r}"


def test_unknown_stamp_warns_without_strict(tmp_path):
    """Same as strict but without --strict: exit 0, warning present."""
    repo, second = make_repo(tmp_path)
    audit = _find_audit_or_fail(repo, second)
    _stamp_deadbeef_and_commit(audit, repo)
    r = run(cwd=repo)
    assert r.returncode == 0, f"expected 0, got {r.returncode}: {r.stdout!r}"
    assert "STALE" in r.stdout, f"expected STALE: {r.stdout!r}"


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
