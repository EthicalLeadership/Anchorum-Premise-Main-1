import unittest

from dossier_pipeline.output_gates import sanitize_output


class OutputRedactionAdversarialTests(unittest.TestCase):
    def test_split_hash_with_separators_is_redacted(self):
        text = (
            "Record token: "
            "01 23 45 67 89 ab cd ef 01 23 45 67 89 ab cd ef "
            "01 23 45 67 89 ab cd ef 01 23 45 67 89 ab cd ef"
        )

        report = sanitize_output(text)

        self.assertTrue(report.leakage_found)
        self.assertNotIn("01 23 45 67", report.sanitized_text.lower())
        self.assertIn("[redacted-hash]", report.sanitized_text)

    def test_hyphenated_internal_markers_are_removed(self):
        text = (
            "decision-reasoning: internal details\n"
            "payload-hash: 0123456789abcdef0123456789abcdef"
        )

        report = sanitize_output(text)

        self.assertTrue(report.leakage_found)
        self.assertNotIn("decision-reasoning", report.sanitized_text.lower())
        self.assertNotIn("payload-hash", report.sanitized_text.lower())

    def test_markdown_link_with_hash_target_is_sanitized(self):
        text = "See [artifact](https://example.invalid/a/0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef)"

        report = sanitize_output(text)

        self.assertTrue(report.leakage_found)
        self.assertNotIn(
            "0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef",
            report.sanitized_text.lower(),
        )


if __name__ == "__main__":
    unittest.main()
