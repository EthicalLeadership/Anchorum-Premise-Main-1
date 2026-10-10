import sys
import tempfile
import types
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

schema_stub = types.ModuleType("dossier_pipeline.schema")
for _name in [
    "AuditLog",
    "Base",
    "Case",
    "Document",
    "JurisdictionStamp",
    "User",
    "create_engine_and_session",
    "get_session",
    "init_schema",
]:
    setattr(schema_stub, _name, object())
sys.modules.setdefault("dossier_pipeline.schema", schema_stub)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dossier_pipeline.pipeline import DossierPipeline
from tests.harness.normalization import normalize_public_record


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


class TraceIndependenceTests(unittest.TestCase):
    def test_public_export_projection_is_trace_independent(self):
        with tempfile.TemporaryDirectory() as tempdir:
            pipeline = DossierPipeline(dossier_id="TRACE-INDEP", output_dir=tempdir)
            try:
                raw = build_email(
                    message_id="<trace-indep@example.com>",
                    subject="Employer policy notice",
                    body="Please respond to this policy notice.",
                )
                result = pipeline.process_email(raw)
                self.assertIn(result.status.value, {"processed", "rejected_policy"})

                record = pipeline.control.get_record_by_hash(result.record_hash)
                self.assertIsNotNone(record)
                public_record = pipeline._public_record(record)
                normalized_with_trace = normalize_public_record(public_record)

                mutated = dict(record)
                mutated_payload = dict(record["payload"])
                mutated_payload.pop("decision_trace", None)
                mutated["payload"] = mutated_payload
                public_record_without_trace = pipeline._public_record(mutated)
                normalized_without_trace = normalize_public_record(public_record_without_trace)

                self.assertEqual(normalized_with_trace, normalized_without_trace)
            finally:
                pipeline.close()


if __name__ == "__main__":
    unittest.main()
