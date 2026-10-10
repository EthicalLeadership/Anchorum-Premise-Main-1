import sys
import tempfile
import types
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

# Isolate architectural equivalence tests from SQLAlchemy/runtime schema failures.
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


class EquivalenceAnchorTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_legacy_vs_orchestrated_control_record_equivalence(self):
        raw = build_email(
            message_id="<equivalence-anchor@example.com>",
            subject="Quarterly update to workplace policy handbook",
            body=(
                "Attached please find the quarterly update to the workplace policy handbook.\n"
                "The updated document is available in the shared drive. No action is required."
            ),
        )

        with DossierPipeline(dossier_id="ANCHOR-PREP", output_dir=str(Path(self.tempdir.name) / "prep")) as pipeline_prep:
            parsed_prep = pipeline_prep.intake.parse_email_bytes(raw)
            normalized_prep_email = pipeline_prep.intake.normalize(parsed_prep)
            self.assertIsNotNone(normalized_prep_email)
            classification_orch = pipeline_prep.classifier.classify(normalized_prep_email)
            provenance_orch = pipeline_prep.curator.curate(classification_orch, normalized_prep_email)
            adapted_orch = pipeline_prep.adapter.adapt(classification_orch, provenance_orch, normalized_prep_email)
            policy_orch = pipeline_prep.policy.evaluate(adapted_orch)

        with DossierPipeline(dossier_id="ANCHOR-ORCH", output_dir=str(Path(self.tempdir.name) / "orch")) as pipeline_orch:

            result_orch = pipeline_orch.process_email(raw)
            self.assertIn(result_orch.status.value, {"processed", "rejected_policy"})

            with DossierPipeline(dossier_id="ANCHOR-LEGACY", output_dir=str(Path(self.tempdir.name) / "legacy")) as pipeline_legacy:
                legacy_record = pipeline_legacy.control.execute(adapted_orch, policy_orch)
                legacy_record_dict = {
                    "record_hash": legacy_record.record_hash,
                    "previous_hash": legacy_record.previous_hash,
                    "timestamp": legacy_record.timestamp,
                    "decision": legacy_record.decision,
                    "route": legacy_record.route,
                    "payload": legacy_record.payload,
                }

            orch_record = pipeline_orch.control.get_record_by_hash(result_orch.record_hash)
            self.assertIsNotNone(orch_record)

            normalized_orch = normalize_public_record(pipeline_orch._public_record(orch_record))
            normalized_legacy = normalize_public_record(pipeline_orch._public_record(legacy_record_dict))
            orch_trace = orch_record["payload"].get("decision_trace", {})
            legacy_trace = legacy_record.payload.get("decision_trace", {})

            self.assertEqual(orch_trace.get("arbitration_mode"), "ORCHESTRATED")
            self.assertEqual(legacy_trace.get("arbitration_mode"), "LEGACY_FALLBACK")
            self.assertEqual(
                orch_trace.get("trust_boundary_version"),
                legacy_trace.get("trust_boundary_version"),
            )

            if normalized_orch != normalized_legacy:
                self.assertTrue(orch_trace.get("divergence_reason"))

    def test_divergence_shape_requires_declared_reason_and_schema_parity(self):
        raw = build_email(
            message_id="<equivalence-divergence@example.com>",
            subject="Routine insurer update",
            body="Insurer notice without urgency.",
            sender="Claims Intake <claims@insurer.example>",
        )

        with DossierPipeline(dossier_id="ANCHOR-DIV-PREP", output_dir=str(Path(self.tempdir.name) / "div_prep")) as pipeline_prep:
            parsed = pipeline_prep.intake.parse_email_bytes(raw)
            normalized = pipeline_prep.intake.normalize(parsed)
            self.assertIsNotNone(normalized)
            classification = pipeline_prep.classifier.classify(normalized)
            provenance = pipeline_prep.curator.curate(classification, normalized)
            adapted = pipeline_prep.adapter.adapt(classification, provenance, normalized)
            policy = pipeline_prep.policy.evaluate(adapted)

        with DossierPipeline(dossier_id="ANCHOR-DIV-ORCH", output_dir=str(Path(self.tempdir.name) / "div_orch")) as pipeline_orch:
            orch_record = pipeline_orch.control.execute(
                adapted,
                policy,
                route="quarantine_review",
                reasoning=["Decision scope: administrative routing only", "Final route: quarantine_review"],
                divergence_reason="test divergence induced for anchor",
            )

        with DossierPipeline(dossier_id="ANCHOR-DIV-LEGACY", output_dir=str(Path(self.tempdir.name) / "div_legacy")) as pipeline_legacy:
            legacy_record = pipeline_legacy.control.execute(adapted, policy)

        orch_trace = orch_record.payload.get("decision_trace", {})
        legacy_trace = legacy_record.payload.get("decision_trace", {})

        self.assertTrue(orch_trace.get("divergence_reason"))
        self.assertEqual(set(orch_trace.keys()), set(legacy_trace.keys()))
        self.assertEqual(orch_trace.get("trust_boundary_version"), legacy_trace.get("trust_boundary_version"))


if __name__ == "__main__":
    unittest.main()
