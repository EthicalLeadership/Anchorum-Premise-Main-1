import unittest

from dossier_pipeline.output_gates import sanitize_output
from dossier_pipeline.trust_boundary import validate_export_fields


class ReconstructionResistanceTests(unittest.TestCase):
    def test_partial_hash_fragments_are_not_preserved(self):
        report = sanitize_output(
            "Export record hash abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890 "
            "with partial fragment abcdef1234567890 and metadata suffix."
        )
        self.assertTrue(report.leakage_found)
        self.assertNotIn("abcdef1234567890", report.sanitized_text.lower())
        self.assertNotIn("abcdef1234567890abcdef1234567890", report.sanitized_text.lower())

    def test_composed_export_fields_do_not_recreate_internal_state(self):
        export_fields = {
            "dossier_id": "TEST",
            "message_id": "<id@test>",
            "subject": "Review needed",
            "sender": "sender@example.com",
            "route": "quarantine_review",
            "record_hash": "record-123",
        }
        rejected = validate_export_fields(["dossier_id", "subject", "decision_reasoning"])
        self.assertEqual(rejected, ("decision_reasoning",))
        composed = " | ".join(f"{key}={value}" for key, value in export_fields.items())
        self.assertNotIn("decision_reasoning", composed.lower())
        self.assertNotIn("payload_hash", composed.lower())
        self.assertNotIn("previous_hash", composed.lower())

    def test_markdown_variants_still_strip_internal_terms(self):
        markdown = (
            "### Record\n"
            "- subject: Allowed text\n"
            "- decision_reasoning: hidden\n"
            "- payload_hash: 0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef\n"
        )
        report = sanitize_output(markdown)
        self.assertTrue(report.leakage_found)
        self.assertNotIn("decision_reasoning", report.sanitized_text.lower())
        self.assertNotIn("payload_hash", report.sanitized_text.lower())
        self.assertNotIn("0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef", report.sanitized_text)


if __name__ == "__main__":
    unittest.main()
