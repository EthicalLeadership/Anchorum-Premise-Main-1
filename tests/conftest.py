"""Test-run environment setup.

Production code no longer falls back to a hard-coded signing key
(see dossier_pipeline/control.py::_signing_key). Tests must therefore
provide one explicitly. This file sets it before any test module
imports the pipeline.
"""
import os

os.environ.setdefault("GDC_CONTROL_SIGNING_KEY", "test-signing-key")
os.environ.setdefault("GDC_CONTROL_SIGNING_KEY_ID", "test")
