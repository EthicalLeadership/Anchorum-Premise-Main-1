import unittest

from dossier_pipeline.auth import (decode_token, fingerprint_credential,
                                    issue_token, validate_bearer_token)
from dossier_pipeline.barreau_gate import BarreauGate, BarreauGateError
from dossier_pipeline.schema import Case, Document, JurisdictionStamp, User


class AuthBarreauTests(unittest.TestCase):
    def test_fingerprint_is_stable(self):
        self.assertEqual(
            fingerprint_credential("barreau-secret"),
            fingerprint_credential("barreau-secret"),
        )

    def test_jwt_issue_and_validate(self):
        token = issue_token("testuser", "test-secret-key", roles=["admin", "barreau"], expires_minutes=5)
        payload = validate_bearer_token(token.access_token, "test-secret-key", required_role="barreau")
        self.assertEqual(payload["sub"], "testuser")
        self.assertIn("barreau", payload["roles"])
        self.assertEqual(decode_token(token.access_token, "test-secret-key")["sub"], "testuser")

    def test_jwt_role_gate_rejects_missing_role(self):
        token = issue_token("testuser", "test-secret-key", roles=["viewer"], expires_minutes=5)
        with self.assertRaises(PermissionError):
            validate_bearer_token(token.access_token, "test-secret-key", required_role="barreau")

    def test_barreau_gate_accepts_known_credential(self):
        fingerprint = fingerprint_credential("member-card-123")
        gate = BarreauGate([fingerprint])
        result = gate.validate("member-card-123")
        self.assertTrue(result.allowed)
        self.assertEqual(result.credential_fingerprint, fingerprint)

    def test_barreau_gate_rejects_unknown_credential(self):
        gate = BarreauGate([])
        with self.assertRaises(BarreauGateError):
            gate.validate("unknown-member")

    def test_schema_models_have_expected_tablenames(self):
        self.assertEqual(Case.__tablename__, "cases")
        self.assertEqual(Document.__tablename__, "documents")
        self.assertEqual(User.__tablename__, "users")
        self.assertEqual(JurisdictionStamp.__tablename__, "jurisdiction_stamps")


if __name__ == "__main__":
    unittest.main()
