import sys
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from dossier_pipeline.state_machine import load_default_spec
from tests.harness.pipeline_harness import PipelineTestHarness


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


class StateMachineInvariantTests(unittest.TestCase):
    def setUp(self):
        self.harness = PipelineTestHarness()
        self.spec = load_default_spec()

    def tearDown(self):
        self.harness.close()

    def test_no_duplicate_processing(self):
        sample = build_email(
            message_id="<dup@example.com>",
            subject="Status update",
            body="Regular informational message",
        )

        r1 = self.harness.ingest(sample)
        r2 = self.harness.ingest(sample)

        self.assertEqual(r1.status.value, "processed")
        self.assertEqual(r2.status.value, "duplicate")
        self.assertEqual(self.harness.state()["seen"], 1)

    def test_control_plane_append_only(self):
        sample = build_email(
            message_id="<append-only@example.com>",
            subject="Status update",
            body="Regular message body",
        )

        before = len(self.harness.state()["chain"])
        self.harness.ingest(sample)
        after = len(self.harness.state()["chain"])

        self.assertEqual(after, before + 1)

    def test_hash_chain_integrity(self):
        sample = build_email(
            message_id="<chain-integrity@example.com>",
            subject="Status update",
            body="Regular message body",
        )

        self.harness.ingest(sample)
        self.assertTrue(self.harness.state()["evidence"]["integrity_pass"])
        self.assertTrue(self.harness.pipeline.control.verify_chain()["integrity_pass"])

    def test_seen_only_after_control_record(self):
        sample = build_email(
            message_id="<seen-after-control@example.com>",
            subject="Status update",
            body="Regular message body",
        )

        result = self.harness.ingest(sample)
        chain = self.harness.state()["chain"]

        self.assertEqual(result.status.value, "processed")
        self.assertIsNotNone(result.record_hash)
        self.assertTrue(any(r["record_hash"] == result.record_hash for r in chain))

    def test_policy_blocks_control_write(self):
        risky = build_email(
            message_id="<policy-block@example.com>",
            subject="Re: Your file",
            subtype="html",
            body=(
                "<html><body><p>Client Company requires your response.</p>"
                "<p>This is mandatory and without fail.</p></body></html>"
            ),
        )

        result = self.harness.ingest(risky)

        self.assertEqual(result.status.value, "rejected_policy")
        self.assertEqual(len(self.harness.state()["chain"]), 0)
        self.assertEqual(self.harness.state()["pipeline_state"], "POLICY_REJECTED")

    def test_runtime_failure_never_masquerades_as_policy_rejection(self):
        original_parse = self.harness.pipeline.intake.parse_email_bytes

        def boom(_raw_bytes):
            raise RuntimeError("forced parse failure")

        self.harness.pipeline.intake.parse_email_bytes = boom
        try:
            result = self.harness.ingest(build_email(
                message_id="<runtime-failure@example.com>",
                subject="Test",
                body="Payload",
            ))
        finally:
            self.harness.pipeline.intake.parse_email_bytes = original_parse

        self.assertEqual(result.status.value, "failed_runtime")
        self.assertNotEqual(result.status.value, "rejected_policy")
        self.assertEqual(self.harness.state()["pipeline_state"], "FAILED_RUNTIME")

    def test_replay_log_records_deterministic_transition_sequence(self):
        sample = build_email(
            message_id="<replay@example.com>",
            subject="Status update",
            body="Regular message body",
        )

        result = self.harness.ingest(sample)
        self.assertEqual(result.status.value, "processed")

        replay_events = self.harness.pipeline.replay.load()
        event_types = [event.event_type for event in replay_events]

        self.assertEqual(
            event_types,
            [
                "pipeline.received",
                "intake.parsed",
                "intake.dedup_checked",
                "classification.completed",
                "provenance.completed",
                "adapter.completed",
                "policy.completed",
                "control.recorded",
                "seen.committed",
            ],
        )
        self.assertTrue(self.harness.pipeline.replay.verify().integrity_pass)
        self.assertTrue(self.harness.pipeline.replay.verify_against_spec())

    def test_replay_log_records_policy_rejection(self):
        risky = build_email(
            message_id="<replay-policy@example.com>",
            subject="Re: Your file",
            subtype="html",
            body=(
                "<html><body><p>Client Company requires your response.</p>"
                "<p>This is mandatory and without fail.</p></body></html>"
            ),
        )

        result = self.harness.ingest(risky)
        self.assertEqual(result.status.value, "rejected_policy")

        event_types = [event.event_type for event in self.harness.pipeline.replay.load()]
        self.assertEqual(
            event_types,
            [
                "pipeline.received",
                "intake.parsed",
                "intake.dedup_checked",
                "classification.completed",
                "provenance.completed",
                "adapter.completed",
                "policy.completed",
                "policy.rejected",
            ],
        )
        self.assertNotIn("control.recorded", event_types)

    def test_replay_log_records_duplicates(self):
        sample = build_email(
            message_id="<replay-dup@example.com>",
            subject="Status update",
            body="Regular informational message",
        )

        self.harness.ingest(sample)
        self.harness.ingest(sample)

        event_types = [event.event_type for event in self.harness.pipeline.replay.load()]
        self.assertEqual(
            event_types[-4:],
            [
                "pipeline.received",
                "intake.parsed",
                "intake.dedup_checked",
                "intake.duplicate",
            ],
        )
        self.assertTrue(self.harness.pipeline.replay.verify().integrity_pass)


if __name__ == "__main__":
    unittest.main()
