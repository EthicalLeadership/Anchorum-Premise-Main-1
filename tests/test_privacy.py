import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.policy import default

from dossier_pipeline.contracts import EmailEnvelope
from dossier_pipeline.privacy import (PrivacyComplianceError,
                                       PrivacyComplianceLayer)


def build_envelope() -> EmailEnvelope:
    return EmailEnvelope(
        message_id="<privacy-test@example.com>",
        subject="Test subject",
        sender="sender@example.com",
        recipient="recipient@example.com",
        date="Fri, 1 May 2026 09:15:00 -0400",
        body_text="Test body",
        attachments=[],
        raw_sha256="abc123",
        message_key="msgkey-1",
        original_message_id="<privacy-test@example.com>",
        ingest_timestamp="2026-05-03T15:15:00+00:00",
    )


class PrivacyComplianceLayerTests(unittest.TestCase):
    def setUp(self):
        self.access_log = []
        self.layer = PrivacyComplianceLayer(access_log=self.access_log)
        self.envelope = build_envelope()
        self.future_retention = (datetime.now(timezone.utc) + timedelta(days=30)).isoformat()

    def test_validate_requires_legal_basis(self):
        with self.assertRaises(PrivacyComplianceError):
            self.layer.validate(
                self.envelope,
                {
                    "purpose": "governed_email_intake",
                    "retention_expiry": self.future_retention,
                    "reason": "inbound intake processing",
                },
            )

    def test_validate_requires_purpose(self):
        with self.assertRaises(PrivacyComplianceError):
            self.layer.validate(
                self.envelope,
                {
                    "legal_basis": "legitimate_interest",
                    "retention_expiry": self.future_retention,
                    "reason": "inbound intake processing",
                },
            )

    def test_validate_requires_retention_expiry(self):
        with self.assertRaises(PrivacyComplianceError):
            self.layer.validate(
                self.envelope,
                {
                    "legal_basis": "legitimate_interest",
                    "purpose": "governed_email_intake",
                    "reason": "inbound intake processing",
                },
            )

    def test_validate_rejects_past_retention_expiry(self):
        expired = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
        with self.assertRaises(PrivacyComplianceError):
            self.layer.validate(
                self.envelope,
                {
                    "legal_basis": "legitimate_interest",
                    "purpose": "governed_email_intake",
                    "retention_expiry": expired,
                    "reason": "inbound intake processing",
                },
            )

    def test_validate_rejects_excess_fields_when_minimization_is_configured(self):
        with self.assertRaises(PrivacyComplianceError):
            self.layer.validate(
                self.envelope,
                {
                    "legal_basis": "legitimate_interest",
                    "purpose": "governed_email_intake",
                    "retention_expiry": self.future_retention,
                    "reason": "inbound intake processing",
                    "allowed_fields": ["message_id", "subject"],
                },
            )

    def test_validate_records_access_log_reason(self):
        decision = self.layer.validate(
            self.envelope,
            {
                "legal_basis": "legitimate_interest",
                "purpose": "governed_email_intake",
                "retention_expiry": self.future_retention,
                "reason": "inbound intake processing",
            },
        )

        self.assertTrue(decision.allowed)
        self.assertEqual(decision.reason, "inbound intake processing")
        self.assertEqual(len(self.access_log), 1)
        self.assertEqual(self.access_log[0]["reason"], "inbound intake processing")
        self.assertEqual(self.access_log[0]["legal_basis"], "legitimate_interest")
        self.assertEqual(self.access_log[0]["purpose"], "governed_email_intake")


if __name__ == "__main__":
    unittest.main()
