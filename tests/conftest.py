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

os.environ.setdefault("GDC_CONTROL_SIGNING_KEY", "test-signing-key")
os.environ.setdefault("GDC_CONTROL_SIGNING_KEY_ID", "test")
os.environ.setdefault("GDC_EVIDENCE_SECRET", "test-evidence-secret")
os.environ.setdefault("GDC_AUDIT_SIGNING_KEY", "test-audit-signing-key")
os.environ.setdefault("GDC_AUDIT_SIGNING_KEY_ID", "test")
