import tempfile
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

from dossier_pipeline.enforcement import (scan_forbidden_control_writes,
                                           scan_forbidden_mutator_calls)
from dossier_pipeline.intake import EmailSeenSet
from dossier_pipeline.outbound import DocumentType, SendMethod
from dossier_pipeline.pipeline import DossierPipeline
from dossier_pipeline.projections import (compare_evidence_projection,
                                           compare_outbound_projection,
                                           compare_seen_projection)


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


class ProjectionEnforcementTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.pipeline = DossierPipeline(
            dossier_id="ENFORCEMENT-TEST",
            output_dir=self.tempdir.name,
        )

    def tearDown(self):
        self.pipeline.close()
        self.tempdir.cleanup()

    def test_seen_projection_matches_legacy_store(self):
        raw = build_email(
            message_id="<seen-projection@example.com>",
            subject="Status update",
            body="Regular informational message",
        )
        self.pipeline.process_email(raw)

        comparison = compare_seen_projection(self.pipeline.seen)
        self.assertTrue(comparison["matches"])
        self.assertEqual(comparison["legacy_count"], 1)
        self.assertEqual(comparison["snapshot_count"], 1)

    def test_outbound_projection_matches_legacy_store(self):
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

        comparison = compare_outbound_projection(self.pipeline.outbound)
        self.assertTrue(comparison["matches"])
        self.assertEqual(comparison["legacy_send_count"], 1)
        self.assertEqual(comparison["snapshot_send_count"], 1)

    def test_evidence_projection_matches_legacy_store(self):
        raw = build_email(
            message_id="<evidence-projection@example.com>",
            subject="Regular status update",
            body="Informational body",
        )
        self.pipeline.process_email(raw)

        comparison = compare_evidence_projection(self.pipeline.evidence)
        self.assertTrue(comparison["matches"])
        self.assertEqual(comparison["legacy_packet_count"], 2)
        self.assertEqual(comparison["snapshot"]["packet_count"], 2)

    def test_control_plane_is_only_chain_writer_surface(self):
        raw = build_email(
            message_id="<chain-writer@example.com>",
            subject="Regular status update",
            body="Informational body",
        )
        result = self.pipeline.process_email(raw)

        self.assertEqual(result.status.value, "processed")
        self.assertEqual(self.pipeline.control.get_all_records()[0]["record_hash"], result.record_hash)
        self.assertTrue(self.pipeline.control.verify_chain()["integrity_pass"])
        self.assertTrue(self.pipeline.replay.replay_projection()["spec_ok"])

    def test_no_non_control_module_writes_control_chain_tables(self):
        allowed_files = (
            "dossier_pipeline/control.py",
            "dossier_pipeline/pipeline.py",
        )
        root = Path("dossier_pipeline")
        paths = [
            path
            for path in root.rglob("*.py")
            if path.name != "enforcement.py"
        ]
        violations = scan_forbidden_control_writes(paths, allowed_files)
        self.assertEqual(
            violations,
            [],
            f"Non-control modules must not write control chain tables: {violations}",
        )

    def test_projection_modules_do_not_call_forbidden_mutators(self):
        root = Path("dossier_pipeline")
        paths = [
            path
            for path in root.rglob("*.py")
            if path.name in {"projections.py", "evidence.py", "intake.py"}
        ]
        violations = scan_forbidden_mutator_calls(paths)
        self.assertEqual(
            violations,
            [],
            f"Forbidden mutator calls found in projection modules: {violations}",
        )


if __name__ == "__main__":
    unittest.main()
