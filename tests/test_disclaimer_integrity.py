import hashlib
import unittest

from dossier_pipeline.disclaimer import (DISCLAIMER_VERSION, build_disclaimer,
                                          format_disclaimer_block)


class DisclaimerIntegrityTests(unittest.TestCase):
    def test_disclaimer_has_version_and_stable_structure(self):
        disclaimer = build_disclaimer()
        block = format_disclaimer_block()

        self.assertEqual(disclaimer.version, DISCLAIMER_VERSION)
        self.assertIn("Output Governance Disclaimer", block)
        self.assertIn(f"Version: `{DISCLAIMER_VERSION}`", block)
        self.assertIn("Generated at:", block)
        self.assertTrue(block.startswith("\n---\n"))
        self.assertTrue(block.rstrip().endswith("filtered from outward-facing text."))

    def test_disclaimer_content_changes_are_detectable(self):
        disclaimer = build_disclaimer()
        canonical = "\n".join(
            [
                disclaimer.title,
                disclaimer.version,
                disclaimer.generated_at,
                disclaimer.text,
            ]
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

        self.assertEqual(len(digest), 64)
        self.assertNotEqual(
            digest,
            hashlib.sha256(
                "\n".join(
                    [
                        disclaimer.title,
                        disclaimer.version,
                        disclaimer.generated_at,
                        disclaimer.text + " tampered",
                    ]
                ).encode("utf-8")
            ).hexdigest(),
        )

    def test_disclaimer_is_not_duplicated_inside_block(self):
        block = format_disclaimer_block()
        self.assertEqual(block.count("Output Governance Disclaimer"), 1)
        self.assertEqual(block.count("Version: `1.0.0`"), 1)


if __name__ == "__main__":
    unittest.main()
