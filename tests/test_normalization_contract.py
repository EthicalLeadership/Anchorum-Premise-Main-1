import unittest

from tests.harness.normalization import normalize_public_record


class NormalizationContractTests(unittest.TestCase):
    def test_normalization_is_projection_only(self):
        record = {
            "decision": "policy clear",
            "route": "archive",
            "payload": {
                "actor": "insurer",
                "labels": ["requires_response", "privileged"],
                "payload_hash": "abc",
                "trace": ["internal"],
                "decision_trace": {
                    "arbitration_mode": "ORCHESTRATED",
                    "trust_boundary_version": "1.0.0",
                    "divergence_reason": None,
                },
            },
        }
        normalized = normalize_public_record(record)

        self.assertEqual(normalized["decision"], "policy clear")
        self.assertEqual(normalized["route"], "archive")
        self.assertEqual(normalized["payload"]["actor"], "insurer")
        self.assertEqual(normalized["payload"]["labels"], ["privileged", "requires_response"])
        self.assertNotIn("payload_hash", normalized["payload"])
        self.assertNotIn("trace", normalized["payload"])
        self.assertNotIn("decision_trace", normalized["payload"])

    def test_normalization_does_not_rewrite_route_or_decision(self):
        record = {
            "decision": "some decision",
            "route": "hold_silent",
            "payload": {"labels": ["pressure_tactic"]},
        }
        normalized = normalize_public_record(record)
        self.assertEqual(normalized["decision"], "some decision")
        self.assertEqual(normalized["route"], "hold_silent")


if __name__ == "__main__":
    unittest.main()
