import sys
import tempfile
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dossier_pipeline.intake import EmailIntake, EmailSeenSet
from dossier_pipeline.outbound import DocumentType, SendMethod
from dossier_pipeline.pipeline import DossierPipeline, ParseError, PolicyError


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


class IntakeClaimRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.seen = EmailSeenSet(str(Path(self.tempdir.name) / "seen.db"))
        self.intake = EmailIntake(self.seen)

    def tearDown(self):
        self.seen.close()
        self.tempdir.cleanup()

    def test_pending_claim_blocks_duplicate_before_mark_seen(self):
        raw_email = build_email(
            message_id="<pending-claim@example.com>",
            subject="Duplicate claim window",
            body="Client scheduling update",
        )

        envelope_1 = self.intake.parse_email_bytes(raw_email)
        envelope_2 = self.intake.parse_email_bytes(raw_email)

        self.assertIsNotNone(self.intake.normalize(envelope_1))
        self.assertIsNone(self.intake.normalize(envelope_2))


class PipelineRegressionTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.pipeline = DossierPipeline(
            dossier_id="TEST-DOSSIER-PIPELINE",
            output_dir=self.tempdir.name,
        )

    def assertStateHistory(self, expected_prefix):
        self.assertEqual(self.pipeline.state_history[: len(expected_prefix)], expected_prefix)

    def tearDown(self):
        self.pipeline.close()
        self.tempdir.cleanup()

    def test_conflict_variant_is_idempotent_and_keeps_original_id(self):
        raw_original = build_email(
            message_id="<same-message@example.com>",
            subject="Status update",
            body="Original body content",
        )
        raw_conflict = build_email(
            message_id="<same-message@example.com>",
            subject="Status update",
            body="Changed content for the same Message-ID",
        )

        first = self.pipeline.process_email(raw_original)
        second = self.pipeline.process_email(raw_conflict)
        third = self.pipeline.process_email(raw_conflict)

        self.assertEqual(first.status.value, "processed")
        self.assertEqual(second.status.value, "processed")
        self.assertEqual(third.status.value, "duplicate")
        self.assertTrue(second.data["message_id"].startswith("conflict-"))
        self.assertEqual(second.data["original_message_id"], "<same-message@example.com>")
        self.assertIn("CONTROL_RECORDED", self.pipeline.state_history)
        self.assertIn("SEEN_COMMITTED", self.pipeline.state_history)

        records = self.pipeline.control.get_all_records()
        self.assertEqual(len(records), 2)
        conflict_payload = records[-1]["payload"]
        self.assertEqual(
            conflict_payload["original_message_id"],
            "<same-message@example.com>",
        )
        self.assertEqual(conflict_payload["message_id"], second.data["message_id"])

    def test_html_only_employer_email_is_classified_from_html_body(self):
        raw_html = build_email(
            message_id="<html-only@example.com>",
            subject="Re: Your file",
            subtype="html",
            body=(
                "<html><body><p>Client Company requires your response.</p>"
                "<p>This is mandatory and without fail.</p></body></html>"
            ),
        )

        result = self.pipeline.process_email(raw_html)

        self.assertEqual(result.status.value, "rejected_policy")
        self.assertEqual(result.data["stage"], "policy")
        self.assertTrue(result.data["evidence_id"])
        self.assertIn("Employer pressure", result.reason)
        self.assertEqual(self.pipeline.current_state, "REJECTED_POLICY")
        self.assertIn("REJECTED_POLICY", self.pipeline.state_history)
        self.assertNotIn("CONTROL_RECORDED", self.pipeline.state_history)

        rejected_path = Path(self.tempdir.name) / "TEST-DOSSIER-PIPELINE_rejected.jsonl"
        rejected_lines = rejected_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertTrue(any(result.data["evidence_id"] in line for line in rejected_lines))

    def test_legal_counsel_email_routes_to_legal_analysis(self):
        raw_legal = build_email(
            message_id="<legal-route@example.com>",
            subject="Re: dossier review from counsel",
            sender="Cabinet juridique <assistant@lawfirm.example>",
            body=(
                "Bonjour,\n\n"
                "Please review this matter with counsel and the Barreau before responding.\n"
                "This matter is confidential and protected by solicitor-client privilege.\n\n"
                "Regards,\n"
                "Maître Example\n"
            ),
        )

        result = self.pipeline.process_email(raw_legal)

        self.assertEqual(result.actor, "legal")
        self.assertEqual(result.status.value, "rejected_policy")
        self.assertEqual(self.pipeline.current_state, "REJECTED_POLICY")
        self.assertIn("REJECTED_POLICY", self.pipeline.state_history)
        self.assertTrue(result.reason)
        self.assertEqual(self.pipeline.control.get_all_records(), [])

    def test_barreau_keywords_cannot_be_used_to_bypass_legal_routing(self):
        raw_adversarial = build_email(
            message_id="<barreau-bypass@example.com>",
            subject="URGENT: response required",
            sender="Unknown Sender <noreply@example.com>",
            body=(
                "BARREAU, attorney, counsel, lawyer.\n"
                "This notice is mandatory and you must respond.\n"
                "Legal consequence may follow if you fail to act.\n"
            ),
        )

        result = self.pipeline.process_email(raw_adversarial)

        self.assertEqual(result.status.value, "processed")
        self.assertEqual(result.actor, "legal")
        self.assertEqual(result.route, "escalate_legal")
        self.assertIn("legal_significant", result.data["labels"])
        self.assertIn("pressure_tactic", result.data["labels"])
        self.assertTrue(
            any(
                keyword in " ".join(result.data["decision_reasoning"]).lower()
                for keyword in ("barreau", "attorney", "counsel", "lawyer")
            )
        )

    def test_outbound_register_send_accepts_mixed_case_actor(self):
        doc_path = Path(self.tempdir.name) / "demand-letter.txt"
        doc_path.write_text("Formal demand letter content", encoding="utf-8")

        send = self.pipeline.outbound.register_send(
            actor="Employer",
            document_type=DocumentType.DEMAND_LETTER,
            document_path=str(doc_path),
            send_method=SendMethod.REGISTERED_MAIL,
            sender_address="123 Sender Street",
            recipient_address="456 Recipient Avenue",
        )

        self.assertEqual(send.actor, "employer")
        self.assertTrue(send.chain_record_hash)
        self.assertEqual(self.pipeline.outbound.get_all()[0]["actor"], "employer")
        self.assertTrue(self.pipeline.control.verify_chain()["integrity_pass"])
        self.assertTrue(self.pipeline.outbound.get_pending())

    def test_parse_failure_maps_to_failed_runtime_state(self):
        original_parse = self.pipeline.intake.parse_email_bytes

        def boom(_raw_bytes):
            raise ParseError("forced parse failure")

        self.pipeline.intake.parse_email_bytes = boom
        try:
            result = self.pipeline.process_email(build_email(
                message_id="<fail@example.com>",
                subject="Test",
                body="Payload",
            ))
        finally:
            self.pipeline.intake.parse_email_bytes = original_parse

        self.assertEqual(result.status.value, "failed_runtime")
        self.assertEqual(result.data["stage"], "parse")
        self.assertEqual(result.data["error_type"], "ParseError")
        self.assertFalse(result.retryable)
        self.assertEqual(self.pipeline.current_state, "FAILED_RUNTIME")
        self.assertIn("FAILED_RUNTIME", self.pipeline.state_history)
        self.assertEqual(self.pipeline.control.get_all_records(), [])

    def test_policy_failure_maps_to_failed_runtime_state(self):
        original_evaluate = self.pipeline.policy.evaluate

        def boom(_adapter):
            raise PolicyError("forced policy failure")

        self.pipeline.policy.evaluate = boom
        try:
            result = self.pipeline.process_email(build_email(
                message_id="<policy-fail@example.com>",
                subject="Test",
                body="Payload",
            ))
        finally:
            self.pipeline.policy.evaluate = original_evaluate

        self.assertEqual(result.status.value, "failed_runtime")
        self.assertEqual(result.data["stage"], "policy")
        self.assertEqual(result.data["error_type"], "PolicyError")
        self.assertFalse(result.retryable)
        self.assertEqual(self.pipeline.current_state, "FAILED_RUNTIME")
        self.assertIn("FAILED_RUNTIME", self.pipeline.state_history)
        self.assertEqual(self.pipeline.control.get_all_records(), [])

    def test_unexpected_failure_maps_to_failed_runtime_state(self):
        original_classify = self.pipeline.classifier.classify

        def boom(_envelope):
            raise RuntimeError("forced unexpected failure")

        self.pipeline.classifier.classify = boom
        try:
            result = self.pipeline.process_email(build_email(
                message_id="<unexpected-fail@example.com>",
                subject="Test",
                body="Payload",
            ))
        finally:
            self.pipeline.classifier.classify = original_classify

        self.assertEqual(result.status.value, "failed_runtime")
        self.assertEqual(result.data["stage"], "process_email")
        self.assertEqual(result.data["error_type"], "RuntimeError")
        self.assertTrue(result.retryable)
        self.assertEqual(self.pipeline.current_state, "FAILED_RUNTIME")
        self.assertIn("FAILED_RUNTIME", self.pipeline.state_history)
        self.assertEqual(self.pipeline.control.get_all_records(), [])


class ProcessDirectoryCounterTests(unittest.TestCase):
    """
    Regression: counters (duplicate_count, quarantined_count, failed_count)
    are maintained by process_email() and are therefore correct when emails
    are processed via process_directory(). These tests confirm the counters
    are accessible and accurate after a directory pass.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.email_dir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()
        self.email_dir.cleanup()

    def _write_eml(self, name: str, raw: bytes) -> None:
        Path(self.email_dir.name, name).write_bytes(raw)

    def test_duplicate_count_incremented_for_duplicate_emails(self):
        raw = build_email(
            message_id="<dir-dup@example.com>",
            subject="Duplicate test",
            body="Client HR memo",
        )
        self._write_eml("first.eml", raw)
        self._write_eml("second.eml", raw)

        pipeline = DossierPipeline(
            dossier_id="DIR-DUP-TEST",
            output_dir=self.tempdir.name,
        )
        try:
            results = pipeline.process_directory(self.email_dir.name)
            # first.eml → PROCESSED (returned), second.eml → DUPLICATE
            self.assertEqual(len(results), 1)
            self.assertEqual(pipeline.duplicate_count, 1)
        finally:
            pipeline.close()

    def test_quarantined_count_incremented_for_policy_rejections(self):
        # HTML employer-pressure email triggers Rule 2 → REJECTED_POLICY
        raw = build_email(
            message_id="<dir-quarantine@example.com>",
            subject="Your mandatory response",
            subtype="html",
            body=(
                "<html><body><p>Client Company requires your response.</p>"
                "<p>This is mandatory and without fail.</p></body></html>"
            ),
        )
        self._write_eml("policy_reject.eml", raw)

        pipeline = DossierPipeline(
            dossier_id="DIR-QUAR-TEST",
            output_dir=self.tempdir.name,
        )
        try:
            results = pipeline.process_directory(self.email_dir.name)
            self.assertEqual(len(results), 0)
            self.assertEqual(pipeline.quarantined_count, 1)
        finally:
            pipeline.close()

    def test_failed_count_incremented_for_runtime_errors(self):
        # Monkeypatch parse to force a RuntimeError on the specific file
        raw = build_email(
            message_id="<dir-fail@example.com>",
            subject="Will be force-failed",
            body="Payload",
        )
        self._write_eml("forced_fail.eml", raw)

        pipeline = DossierPipeline(
            dossier_id="DIR-FAIL-TEST",
            output_dir=self.tempdir.name,
        )
        original_parse = pipeline.intake.parse_email_bytes

        def boom(_raw_bytes):
            raise RuntimeError("forced parse failure")

        pipeline.intake.parse_email_bytes = boom
        try:
            results = pipeline.process_directory(self.email_dir.name)
            self.assertEqual(len(results), 0)
            self.assertEqual(pipeline.failed_count, 1)
        finally:
            pipeline.intake.parse_email_bytes = original_parse
            pipeline.close()


class ExportSummaryRouteCoverageTests(unittest.TestCase):
    """
    Regression: export_markdown_summary() must surface HOLD_SILENT and
    ESCALATE_LEGAL routed records in the High-Risk section, not only quarantine.
    """

    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.pipeline = DossierPipeline(
            dossier_id="EXPORT-ROUTE-TEST",
            output_dir=self.tempdir.name,
        )

    def tearDown(self):
        self.pipeline.close()
        self.tempdir.cleanup()

    def _process_and_get_markdown(self) -> str:
        output_path = Path(self.tempdir.name) / "summary.md"
        self.pipeline.export_markdown_summary(str(output_path))
        return output_path.read_text(encoding="utf-8")

    def test_quarantine_section_present(self):
        raw = build_email(
            message_id="<export-quar@example.com>",
            subject="Mandatory response required",
            subtype="html",
            body=(
                "<html><body><p>Client Company requires your response.</p>"
                "<p>This is mandatory and without fail.</p></body></html>"
            ),
        )
        self.pipeline.process_email(raw)
        md = self._process_and_get_markdown()
        self.assertIn("Human Review", md)
        self.assertIn("Quarantine", md)

    def test_high_risk_section_always_present(self):
        md = self._process_and_get_markdown()
        self.assertIn("HOLD_SILENT", md)
        self.assertIn("ESCALATE_LEGAL", md)
        self.assertIn("High-Risk Routed Records", md)


if __name__ == "__main__":
    unittest.main()
