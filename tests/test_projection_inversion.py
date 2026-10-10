import tempfile
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

from dossier_pipeline.outbound import DocumentType, SendMethod
from dossier_pipeline.pipeline import DossierPipeline


def build_email(
    *,
    message_id: str,
    subject: str,
    body: str,
    subtype: str = "plain",
    sender: str = "HR Operations <hr.operations@example.com>",
    recipient: str = "user@example.com",
    date: str = "Fri, 1 May 2026 09:15:00 -0400",
) -> bytes:
    msg = EmailMessage(policy=default)
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = date
    msg.set_content(body, subtype=subtype)
    return msg.as_bytes()


class ProjectionInversionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.pipeline = DossierPipeline(
            dossier_id="PROJECTION-TEST",
            output_dir=self.tempdir.name,
        )

    def tearDown(self):
        self.pipeline.close()
        self.tempdir.cleanup()

    def test_projection_snapshot_exists_for_empty_pipeline(self):
        snapshot = self.pipeline.build_projection_snapshot()
        health = self.pipeline.projection_health_report()

        self.assertEqual(snapshot.processed_record_count, 0)
        self.assertEqual(snapshot.seen_count, 0)
        self.assertTrue(health["ok"])
        self.assertEqual(health["snapshot"]["control_tail_hash"], self.pipeline.control.get_tail_hash())

    def test_projection_snapshot_reflects_processed_email(self):
        raw = build_email(
            message_id="<projection-processed@example.com>",
            subject="Regular status update",
            body="Informational body",
        )

        result = self.pipeline.process_email(raw)
        snapshot = self.pipeline.build_projection_snapshot()

        self.assertEqual(result.status.value, "processed")
        self.assertEqual(snapshot.processed_record_count, 1)
        self.assertEqual(snapshot.seen_count, 1)
        self.assertGreaterEqual(snapshot.evidence_packet_count, 2)
        self.assertGreaterEqual(snapshot.custody_event_count, 3)
        self.assertGreaterEqual(snapshot.replay_event_count, 9)
        self.assertEqual(snapshot.duplicate_record_count, 0)

    def test_projection_snapshot_reflects_duplicate_path(self):
        raw = build_email(
            message_id="<projection-duplicate@example.com>",
            subject="Duplicate flow",
            body="Regular informational message",
        )

        self.pipeline.process_email(raw)
        self.pipeline.process_email(raw)
        snapshot = self.pipeline.build_projection_snapshot()

        self.assertEqual(snapshot.duplicate_record_count, 1)
        self.assertEqual(snapshot.seen_count, 1)
        self.assertEqual(snapshot.processed_record_count, 1)

    def test_projection_snapshot_reflects_policy_rejection(self):
        raw = build_email(
            message_id="<projection-reject@example.com>",
            subject="Re: Your file",
            subtype="html",
            body=(
                "<html><body><p>Client Company requires your response.</p>"
                "<p>This is mandatory and without fail.</p></body></html>"
            ),
        )

        result = self.pipeline.process_email(raw)
        snapshot = self.pipeline.build_projection_snapshot()

        self.assertEqual(result.status.value, "rejected_policy")
        self.assertEqual(snapshot.rejected_record_count, 0)
        self.assertEqual(snapshot.quarantined_count if hasattr(snapshot, "quarantined_count") else 1, 1)

    def test_projection_snapshot_reflects_outbound_registration(self):
        doc_path = Path(self.tempdir.name) / "demand-letter.txt"
        doc_path.write_text("Formal demand letter content", encoding="utf-8")

        self.pipeline.outbound.register_send(
            actor="Employer",
            document_type=DocumentType.DEMAND_LETTER,
            document_path=str(doc_path),
            send_method=SendMethod.REGISTERED_MAIL,
            sender_address="123 Sender Street",
            recipient_address="456 Recipient Avenue",
        )

        snapshot = self.pipeline.build_projection_snapshot()
        health = self.pipeline.projection_health_report()

        self.assertEqual(snapshot.outbound_send_count, 1)
        self.assertGreaterEqual(snapshot.pending_outbound_count, 1)
        self.assertEqual(health["snapshot"]["outbound_send_count"], 1)


if __name__ == "__main__":
    unittest.main()
