import unittest
from dataclasses import dataclass

import dossier_pipeline.invariants as invariants_module
from dossier_pipeline.assertion_reporter import AssertionReporter
from dossier_pipeline.assertions import (AssertionEngine, Invariant,
                                          InvariantViolation)


class AssertionEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = AssertionEngine()

    def test_register_and_validate_passes(self):
        self.engine.register(Invariant(id="ok", description="passes", check=lambda **ctx: True))
        self.engine.validate("ok", anything=1)

    def test_unknown_invariant_raises_key_error(self):
        with self.assertRaises(KeyError):
            self.engine.validate("missing")

    def test_strict_mode_raises_on_false(self):
        self.engine.register(Invariant(id="fail", description="fails", check=lambda **ctx: False))
        with self.assertRaises(InvariantViolation):
            self.engine.validate("fail", sample=1)


class AssertionReporterTests(unittest.TestCase):
    def test_record_and_summary(self):
        reporter = AssertionReporter()
        reporter.record("inv_001", {"x": 1})
        reporter.record("inv_002", {"y": 2})

        summary = reporter.summary()
        self.assertEqual(summary["total_failures"], 2)
        self.assertEqual(summary["failures"][0]["invariant"], "inv_001")
        self.assertEqual(summary["failures"][1]["context"], {"y": 2})


class RuntimeInvariantTests(unittest.TestCase):
    def test_inv_003_sha256_fallback(self):
        raw = b"hello world"
        envelope = {"message_id": "sha256:b94d27b9934d3e08a52e52d7da7dabfadeb7f3c5f6d9e2ff9f3d7a8e2e1f2a4b"}
        self.assertFalse(
            invariants_module.check_inv_003(raw_bytes=raw, envelope=envelope)
        )

    def test_inv_004_classifier_deterministic(self):
        @dataclass
        class DummyClassifier:
            def classify(self, envelope):
                return {"actor": "unknown", "labels": ["informational"]}

        self.assertTrue(
            invariants_module.check_inv_004(
                classifier=DummyClassifier(),
                envelope={"subject": "hello"},
            )
        )

    def test_inv_005_routes_critical_labels_to_quarantine(self):
        adapter = {"payload": {"labels": ["urgent", "informational"]}}
        decision = {"route": "QUARANTINE_REVIEW"}
        self.assertTrue(
            invariants_module.check_inv_005(adapter=adapter, decision=decision)
        )

    def test_inv_008_triggers_human_review_on_low_confidence(self):
        classification = {"confidence": 0.4, "actor": "unknown"}
        provenance = {"confidence": 0.4, "missing_fields": ["date"]}
        output = {"human_review_required": True}
        self.assertTrue(
            invariants_module.check_inv_008(
                classification=classification,
                provenance=provenance,
                output=output,
            )
        )


    def test_inv_008_actor_branch_fires_in_isolation(self):
        """The actor branch, with confidence and provenance both clean.

        The existing low-confidence test fires on the confidence branch and
        would pass even if the actor comparison were still the broken
        uppercase literal. This test isolates the actor: confidence 0.9,
        no missing fields, only the actor is UNKNOWN. The invariant must
        require human_review_required=True, so it must fail when the output
        says False.
        """
        from dossier_pipeline.contracts import ActorType

        classification = {"confidence": 0.9, "actor": ActorType.UNKNOWN.value}
        provenance = {"missing_fields": []}

        self.assertTrue(
            invariants_module.check_inv_008(
                classification=classification,
                provenance=provenance,
                output={"human_review_required": True},
            )
        )
        self.assertFalse(
            invariants_module.check_inv_008(
                classification=classification,
                provenance=provenance,
                output={"human_review_required": False},
            )
        )

    def test_inv_008_known_actor_with_clean_inputs_does_not_trigger(self):
        """Counterpoint: same shape, known actor, nothing fires."""
        from dossier_pipeline.contracts import ActorType

        classification = {"confidence": 0.9, "actor": ActorType.LEGAL.value}
        provenance = {"missing_fields": []}

        self.assertTrue(
            invariants_module.check_inv_008(
                classification=classification,
                provenance=provenance,
                output={"human_review_required": False},
            )
        )


if __name__ == "__main__":
    unittest.main()
