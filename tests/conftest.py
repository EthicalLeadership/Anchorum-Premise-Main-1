"""Test-run environment setup.

Production code does not fall back to a hard-coded or empty signing key:

  * ``dossier_pipeline/control.py::_signing_key`` requires
    ``GDC_CONTROL_SIGNING_KEY`` (F-01).
  * ``dossier_pipeline/evidence.py::EvidenceSigner`` requires
    ``GDC_EVIDENCE_SECRET`` (F-02).

Tests must therefore supply key material explicitly. This file sets it before
any test module imports the pipeline. Individual tests that assert the
fail-closed behaviour remove these variables themselves.
"""
import os
import shutil
import tempfile
from pathlib import Path

import pytest

os.environ.setdefault("GDC_CONTROL_SIGNING_KEY", "test-signing-key")
os.environ.setdefault("GDC_CONTROL_SIGNING_KEY_ID", "test")
os.environ.setdefault("GDC_EVIDENCE_SECRET", "test-evidence-secret")
os.environ.setdefault("GDC_AUDIT_SIGNING_KEY", "test-audit-signing-key")
os.environ.setdefault("GDC_AUDIT_SIGNING_KEY_ID", "test")

#: One private output directory per test session.
#:
#: The pipeline resolves its evidence store as
#: ``$OUTPUT_DIR/$DOSSIER_ID_evidence.db``, and that store is append-only with a
#: hash chain over every packet ever written to it. Sharing ``./output`` across
#: sessions accumulated thousands of packets, and every ``EvidenceStore`` open
#: re-verified all of them, so each test paid for the entire history of every
#: previous run. Worse, a run that signed with different key material left rows
#: the next run reports as mismatched: that marks the store LOCKED, and every
#: later upload is then refused. A session-private directory means each run
#: starts from an empty chain that only its own writes can contradict.
_SESSION_OUTPUT = Path(tempfile.mkdtemp(prefix="anchorum-tests-"))
os.environ.setdefault("OUTPUT_DIR", str(_SESSION_OUTPUT))

_OUTPUT = Path(__file__).resolve().parents[1] / "output"


@pytest.fixture(scope="session", autouse=True)
def _remove_session_output():
    """Delete the session's private output directory when the run ends."""
    yield
    shutil.rmtree(_SESSION_OUTPUT, ignore_errors=True)


@pytest.fixture(autouse=True)
def _wipe_test_output():
    """Wipe output/TEST-* before and after each test.

    Pipeline tests create DossierPipeline(dossier_id="TEST-*") which writes
    .db and .jsonl state under output/.  A second pytest invocation in the
    same working tree sees that state and treats every message as duplicate,
    causing the growth assertions to fail.  Function-scoped wipe keeps each
    test isolated regardless of invocation.
    """
    def wipe():
        if not _OUTPUT.exists():
            return
        for entry in list(_OUTPUT.iterdir()):
            if entry.name.startswith("TEST-"):
                if entry.is_dir():
                    shutil.rmtree(entry, ignore_errors=True)
                else:
                    try:
                        entry.unlink()
                    except FileNotFoundError:
                        pass
    wipe()
    yield
    wipe()
