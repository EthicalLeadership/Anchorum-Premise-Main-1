import tempfile
import unittest
from pathlib import Path

from dossier_pipeline.disclaimer import (DISCLAIMER_VERSION, build_disclaimer,
                                          format_disclaimer_block)
from dossier_pipeline.output_gates import (GOVERNANCE_RULESET_VERSION,
                                            sanitize_output)
from dossier_pipeline.pipeline import DossierPipeline
from dossier_pipeline.trust_boundary import (BOUNDARY_CONTRACT_VERSION,
                                              classify_field,
                                              internal_only_fields,
                                              validate_export_fields)


class OutputGovernanceTests(unittest.TestCase):
    def test_disclaimer_is_versioned_and_formatted(self):
        disclaimer = build_disclaimer()
        self.assertEqual(disclaimer.version, DISCLAIMER_VERSION)
        self.assertTrue(disclaimer.generated_at)
        self.assertIn("Output Governance Disclaimer", format_disclaimer_block())
        self.assertIn("administrative record", disclaimer.text)

    def test_sanitize_output_redacts_internal_language(self):
        report = sanitize_output(
            "Decision reasoning: keep internal reasoning confidential. "
            "Payload hash and previous hash should not appear."
        )
        self.assertTrue(report.leakage_found)
        self.assertNotIn("decision_reasoning", report.sanitized_text.lower())
        self.assertNotIn("payload_hash", report.sanitized_text.lower())
        self.assertNotIn("previous_hash", report.sanitized_text.lower())
        self.assertTrue(report.redacted_terms)
        self.assertEqual(GOVERNANCE_RULESET_VERSION, "1.0.0")

    def test_sanitize_output_strips_hash_like_values(self):
        report = sanitize_output("Record hash 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef should not remain.")
        self.assertTrue(report.leakage_found)
        self.assertNotIn("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", report.sanitized_text)

    def test_trust_boundary_contract_classifies_fields(self):
        self.assertEqual(BOUNDARY_CONTRACT_VERSION, "1.0.0")
        self.assertEqual(classify_field(" decision_reasoning ").role, "internal_only")
        self.assertEqual(classify_field("subject").role, "exportable")
        self.assertEqual(classify_field("ingest_time").role, "regulated")
        self.assertIn("decision_reasoning", internal_only_fields())

    def test_validate_export_fields_rejects_internal_only_fields(self):
        rejected = validate_export_fields(["subject", "payload_hash", "route"])
        self.assertEqual(rejected, ("payload_hash",))

    def test_markdown_summary_appends_disclaimer(self):
        with tempfile.TemporaryDirectory() as tempdir:
            pipeline = DossierPipeline(dossier_id="TEST-DISCLOSURE", output_dir=tempdir)
            try:
                output_path = Path(tempdir) / "summary.md"
                pipeline.export_markdown_summary(str(output_path))
                content = output_path.read_text(encoding="utf-8")
            finally:
                pipeline.close()

        self.assertIn("Output Governance Disclaimer", content)
        self.assertIn("Version: `1.0.0`", content)
        self.assertIn("Generated at:", content)
        self.assertIn("This artifact is generated from governed case-processing output.", content)
        self.assertIn("Internal reasoning, protected analysis, and non-public terminology have been filtered from outward-facing text.", content)
        self.assertNotIn("decision_reasoning", content.lower())
        self.assertNotIn("payload_hash", content.lower())
        self.assertNotIn("previous_hash", content.lower())
        self.assertNotIn("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", content)

    def test_markdown_summary_does_not_expose_internal_fields(self):
        with tempfile.TemporaryDirectory() as tempdir:
            pipeline = DossierPipeline(dossier_id="TEST-BOUNDARY", output_dir=tempdir)
            try:
                output_path = Path(tempdir) / "summary.md"
                pipeline.export_markdown_summary(str(output_path))
                content = output_path.read_text(encoding="utf-8")
            finally:
                pipeline.close()

        self.assertEqual(validate_export_fields(["dossier_id", "record_hash", "decision_reasoning"]), ("decision_reasoning",))
        self.assertNotIn("payload_hash", content.lower())
        self.assertNotIn("decision_reasoning", content.lower())
        self.assertNotIn("previous_hash", content.lower())


if __name__ == "__main__":
    unittest.main()
