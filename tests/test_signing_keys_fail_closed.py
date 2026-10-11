"""Signing keys must fail closed (audit findings F-01 and F-02).

F-01 (control chain) and F-02 (evidence chain) were both closed by making the
signer refuse to operate without key material. These are the tests that would
have caught the original defects: they assert the refusal itself, rather than
only that signing works when a key happens to be present.

With a hard-coded default (F-01) or an empty-string key (F-02) every signature
verified successfully, so a passing test suite proved nothing about whether the
chain was tamper-evident. Removing the fallback without a test asserting the
refusal would leave the same hole one edit later.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import tempfile
import unittest
from unittest.mock import patch

from dossier_pipeline.control import ControlPlane
from dossier_pipeline.evidence import EvidenceSigner, EvidenceSignerUnbound


class EvidenceSignerFailClosedTests(unittest.TestCase):
    """F-02: an unset evidence secret must not produce a usable signer."""

    def test_missing_secret_refuses_to_construct(self):
        with patch.dict(os.environ):
            os.environ.pop("GDC_EVIDENCE_SECRET", None)
            with self.assertRaises(EvidenceSignerUnbound):
                EvidenceSigner()

    def test_empty_secret_is_rejected(self):
        for blank in ("", "   ", "\t"):
            with self.subTest(blank=repr(blank)):
                with self.assertRaises(EvidenceSignerUnbound):
                    EvidenceSigner(secret=blank)

    def test_explicit_secret_signs_and_verifies(self):
        signer = EvidenceSigner(secret="unit-test-secret")
        signature = signer.sign("payload")
        self.assertTrue(signer.verify("payload", signature))
        self.assertFalse(signer.verify("payload-tampered", signature))

    def test_signature_forged_with_the_empty_key_is_rejected(self):
        # Reproduces the original F-02 defect: the key used to be the empty
        # string, so anyone could mint a signature the store accepted.
        signer = EvidenceSigner(secret="unit-test-secret")
        forged = hmac.new(b"", b"payload", hashlib.sha256).hexdigest()
        self.assertFalse(signer.verify("payload", forged))

    def test_fingerprint_cannot_be_unbound(self):
        fingerprint = EvidenceSigner(secret="unit-test-secret").fingerprint()
        self.assertNotEqual(fingerprint, "unbound")
        self.assertEqual(len(fingerprint), 64)
        self.assertNotEqual(
            EvidenceSigner(secret="secret-a").fingerprint(),
            EvidenceSigner(secret="secret-b").fingerprint(),
        )


class ControlSigningKeyFailClosedTests(unittest.TestCase):
    """F-01: the control chain must not sign with a hard-coded default."""

    def test_signing_key_is_required(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ):
                os.environ.pop("GDC_CONTROL_SIGNING_KEY", None)
                plane = ControlPlane(os.path.join(tmp, "chain.db"))
                try:
                    with self.assertRaises(RuntimeError):
                        plane._signing_key()
                finally:
                    plane.close()

    def test_signing_key_is_used_when_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(
                os.environ, {"GDC_CONTROL_SIGNING_KEY": "unit-control-key"}
            ):
                plane = ControlPlane(os.path.join(tmp, "chain.db"))
                try:
                    self.assertEqual(plane._signing_key(), b"unit-control-key")
                finally:
                    plane.close()


if __name__ == "__main__":
    unittest.main()
