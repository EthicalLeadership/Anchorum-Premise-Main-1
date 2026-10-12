"""F-18: JWT signing secrets are enforced, not stretched.

The behaviour under test is a refusal. These tests exist because the previous
implementation was quietly wrong: it hashed any secret shorter than
MIN_SECRET_KEY_LENGTH, so a five-character password silently became a
sixty-four-character digest. Nothing failed, nothing warned, and the resulting
key was exactly as guessable as the password.

That property is pinned here in both directions:

* a short secret is rejected rather than transformed, and
* a secret of sufficient length still round-trips, so rejecting weak keys did
  not break the tokens that were already safe.
"""
import unittest

from dossier_pipeline.auth import (MIN_SECRET_KEY_LENGTH, WeakSecretKey,
                                   decode_token, issue_token,
                                   validate_bearer_token)

# A secret that clears the policy.
STRONG_SECRET = "a-sufficiently-long-signing-secret-0123456789"
# The exact string the old implementation would have hashed into a usable key.
LEGACY_PLACEHOLDER = "test-secret-key"


class WeakSecretRejectedTests(unittest.TestCase):
    # _normalize_secret_key now reports a weak key instead of hiding it.

    def test_short_secret_is_rejected_when_issuing(self):
        with self.assertRaises(WeakSecretKey):
            issue_token("subject", LEGACY_PLACEHOLDER, roles=["viewer"])

    def test_short_secret_is_rejected_when_decoding(self):
        with self.assertRaises(WeakSecretKey):
            decode_token("not.a.token", LEGACY_PLACEHOLDER)

    def test_empty_secret_is_rejected(self):
        with self.assertRaises(WeakSecretKey):
            issue_token("subject", "", roles=["viewer"])

    def test_none_secret_is_rejected(self):
        # A config lookup that returns nothing is a common real cause.
        with self.assertRaises(WeakSecretKey):
            issue_token("subject", None, roles=["viewer"])

    def test_one_character_short_is_rejected(self):
        too_short = "x" * (MIN_SECRET_KEY_LENGTH - 1)
        with self.assertRaises(WeakSecretKey):
            issue_token("subject", too_short, roles=["viewer"])

    def test_refusal_is_a_value_error(self):
        # Callers that already catch ValueError keep working.
        with self.assertRaises(ValueError):
            issue_token("subject", LEGACY_PLACEHOLDER, roles=["viewer"])

    def test_the_legacy_padded_key_is_not_in_use(self):
        # The old code would have accepted this secret; the new code must not.
        #
        # Under the previous implementation a token signed with
        # "test-secret-key" verified against the SHA-256 digest of that string,
        # so anybody who knew the placeholder could mint tokens accepted as
        # valid. That path is gone: issuing with it raises.
        with self.assertRaises(WeakSecretKey):
            issue_token("attacker", LEGACY_PLACEHOLDER, roles=["admin"])


class StrongSecretAcceptedTests(unittest.TestCase):
    # Rejecting weak keys must not disturb keys that were already safe.

    def test_exact_minimum_length_is_accepted(self):
        secret = "y" * MIN_SECRET_KEY_LENGTH
        token = issue_token("subject", secret, roles=["viewer"])
        self.assertEqual(decode_token(token.access_token, secret)["sub"], "subject")

    def test_strong_secret_round_trips(self):
        token = issue_token("subject", STRONG_SECRET, roles=["admin"], expires_minutes=5)
        payload = validate_bearer_token(token.access_token, STRONG_SECRET, required_role="admin")
        self.assertEqual(payload["sub"], "subject")
        self.assertIn("admin", payload["roles"])

    def test_strong_secret_keeps_role_gate(self):
        token = issue_token("subject", STRONG_SECRET, roles=["viewer"], expires_minutes=5)
        with self.assertRaises(PermissionError):
            validate_bearer_token(token.access_token, STRONG_SECRET, required_role="admin")

    def test_a_different_strong_secret_does_not_verify(self):
        token = issue_token("subject", STRONG_SECRET, roles=["admin"], expires_minutes=5)
        with self.assertRaises(Exception):
            decode_token(token.access_token, "z" * MIN_SECRET_KEY_LENGTH)


if __name__ == "__main__":
    unittest.main()
