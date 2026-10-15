"""F-10: revocation has exactly one mechanism, and it is the trust anchor.

`dossier_pipeline/registry/keys.py` used to carry a second revocation
implementation: it appended signer IDs to a `revoked_keys.txt` file next to the
key directory and offered `revoke`, `revoked_signers` and `is_revoked` to read
it back. Nothing called it, nothing enforced it, and no test covered it while
`registry/store.py` refused entries from a revoked signer on the basis of
`anchor.revoked_at`, and `trust.revoke` was the operation that set it.

Two mechanisms for one question is worse than one, because the loser of the
argument is still importable. These tests exist so the deleted half cannot
return without a deliberate, visible decision: they fail if the file-based API
reappears, if the anchor API disappears, or if key generation starts writing a
revocation file again.
"""
import unittest
from pathlib import Path

from dossier_pipeline.registry import keys as registry_keys
from dossier_pipeline.registry import store as registry_store
from dossier_pipeline.registry import trust


class FileBasedRevocationIsGoneTests(unittest.TestCase):
    def test_keys_module_does_not_expose_the_file_based_api(self):
        for name in ("revoke", "revoked_signers", "is_revoked", "revocation_file"):
            self.assertFalse(
                hasattr(registry_keys, name),
                f"registry.keys.{name} reintroduces the file-based revocation "
                "path that F-10 removed; revocation belongs to the anchor "
                "(trust.revoke) and is enforced by store",
            )

    def test_generating_keys_writes_no_revocation_file(self):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "keys"
            registry_keys.generate_keypair("signer-guard", root=root)
            stray = [
                str(p)
                for p in Path(tmp).rglob("*")
                if p.is_file() and "revoked" in p.name
            ]
            self.assertEqual(
                stray,
                [],
                f"key generation produced a revocation file: {stray}",
            )

    def test_surviving_key_api_still_works(self):
        # Removing revocation must not have disturbed key generation or listing.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "keys"
            pair = registry_keys.generate_keypair("signer-guard", root=root)
            self.assertEqual(pair.signer_id, "signer-guard")
            self.assertEqual(registry_keys.list_signers(root=root), ["signer-guard"])
            loaded = registry_keys.load_public_key("signer-guard", root=root)
            self.assertEqual(
                loaded.public_bytes_raw(),
                pair.public_key.public_bytes_raw(),
            )


class AnchorIsTheRevocationSourceTests(unittest.TestCase):
    def test_trust_revoke_exists(self):
        self.assertTrue(callable(getattr(trust, "revoke", None)))

    def test_anchor_carries_revocation_state(self):
        self.assertTrue(callable(getattr(trust.TrustAnchor, "revoked_at", None)))

    def test_store_enforces_revocation(self):
        # The enforcement half the docs point at must exist by name.
        self.assertTrue(issubclass(registry_store.RevokedSigner, Exception))


if __name__ == "__main__":
    unittest.main()
