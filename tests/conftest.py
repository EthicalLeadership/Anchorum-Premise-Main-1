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
from pathlib import Path

import pytest

os.environ.setdefault("GDC_CONTROL_SIGNING_KEY", "test-signing-key")
os.environ.setdefault("GDC_CONTROL_SIGNING_KEY_ID", "test")
os.environ.setdefault("GDC_EVIDENCE_SECRET", "test-evidence-secret")
os.environ.setdefault("GDC_AUDIT_SIGNING_KEY", "test-audit-signing-key")
os.environ.setdefault("GDC_AUDIT_SIGNING_KEY_ID", "test")

_OUTPUT = Path(__file__).resolve().parents[1] / "output"


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
