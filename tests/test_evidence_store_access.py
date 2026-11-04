"""Opening the evidence store must not require the signing key.

`EvidenceStore` used to resolve its signer inside `__init__` and verify every
signature while opening. That made every read-only command fail without
`GDC_EVIDENCE_SECRET` - including commands that never look at an evidence
signature - which is a false requirement rather than a control. A hash link is
arithmetic over stored bytes and needs no key; a signature can only be checked
with the key that made it. The two were conflated.

The store now opens without a key, and the two operations that genuinely need
one - signing, and signature verification - still fail closed.

These pins exist because the distinction is easy to erase by accident. Making
`verify()` tolerate a missing key, or making `__init__` require one again, would
each look like a small cleanup and would each quietly remove a control: the
first would report a pass it cannot support, the second the false requirement
that was just removed.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from unittest.mock import patch

from dossier_pipeline.evidence import (CustodyAction, EvidenceSigner,
                                       EvidenceSignerUnbound, EvidenceStore)
from dossier_pipeline.pipeline import DossierPipeline

SECRET_ENV = "GDC_EVIDENCE_SECRET"


def _without_evidence_secret():
    """Patch the environment with the evidence secret removed."""
    return patch.dict(os.environ, {}, clear=False)


class StoreOpensWithoutASecretTests(unittest.TestCase):
    """The store must be readable without key material."""

    def test_store_opens_without_a_secret(self):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with tempfile.TemporaryDirectory() as tmp:
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    self.assertIsNone(store.configured_signer())
                finally:
                    store.close()

    def test_structural_verify_needs_no_secret(self):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with tempfile.TemporaryDirectory() as tmp:
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    report = store.verify(verify_signatures=False)
                    self.assertTrue(report.integrity_pass)
                    self.assertEqual(report.total_packets, 0)
                finally:
                    store.close()

    def test_pipeline_can_be_built_without_the_evidence_secret(self):
        """The headline case: read-only commands must not need the key.

        `verify-chain` and `enforce` verify the control chain and the
        projections. Neither reads an evidence signature, so neither has any use
        for the evidence secret - yet both used to fail without it, because
        building the pipeline opened the store.
        """
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            os.environ.setdefault("GDC_CONTROL_SIGNING_KEY", "unit-control-key")
            with tempfile.TemporaryDirectory() as tmp:
                pipeline = DossierPipeline(dossier_id="TEST-NO-EVIDENCE-KEY", output_dir=tmp)
                try:
                    self.assertTrue(pipeline.control.verify_chain()["integrity_pass"])
                finally:
                    pipeline.close()


class SigningOperationsStillFailClosedTests(unittest.TestCase):
    """Removing the open-time requirement must not remove the signing one."""

    def test_ingest_requires_the_secret(self):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with tempfile.TemporaryDirectory() as tmp:
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    with self.assertRaises(EvidenceSignerUnbound):
                        store.ingest(
                            event_type="test",
                            raw_payload={"a": 1},
                            normalized_payload={"a": 1},
                            metadata={"dossier_id": "d"},
                        )
                finally:
                    store.close()

    def test_custody_event_requires_the_secret(self):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with tempfile.TemporaryDirectory() as tmp:
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    with self.assertRaises(EvidenceSignerUnbound):
                        store.add_custody_event("evidence-id", "actor", CustodyAction.VIEWED)
                finally:
                    store.close()

    def test_export_requires_the_secret(self):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with tempfile.TemporaryDirectory() as tmp:
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    with self.assertRaises(EvidenceSignerUnbound):
                        store.export_bundle(os.path.join(tmp, "bundle"), exporter_id="tester")
                finally:
                    store.close()

    def test_explicit_verify_requires_the_secret(self):
        """verify() asserts authenticity, so it must not run without the key."""
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with tempfile.TemporaryDirectory() as tmp:
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    with self.assertRaises(EvidenceSignerUnbound):
                        store.verify()
                finally:
                    store.close()


class TamperDetectionTests(unittest.TestCase):
    """Deferring the signature check must not lose the detection."""

    def _store_with_one_packet(self, tmp: str, secret: str):
        with patch.dict(os.environ, {SECRET_ENV: secret}):
            store = EvidenceStore(os.path.join(tmp, "evidence.db"))
            packet = store.ingest(
                event_type="test",
                raw_payload={"a": 1},
                normalized_payload={"a": 1},
                metadata={"dossier_id": "d"},
            )
            store.close()
        return packet

    def _tamper_signature(self, tmp: str, evidence_id: str):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            store = EvidenceStore(os.path.join(tmp, "evidence.db"))
            try:
                store.conn.execute(
                    "UPDATE evidence_packets SET signature_system = ? WHERE evidence_id = ?",
                    ("0" * 64, evidence_id),
                )
                store.conn.commit()
            finally:
                store.close()

    def test_tampered_signature_is_caught_with_the_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            packet = self._store_with_one_packet(tmp, "unit-test-evidence-secret")
            self._tamper_signature(tmp, packet.evidence_id)

            with patch.dict(os.environ, {SECRET_ENV: "unit-test-evidence-secret"}):
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    report = store.verify()
                    self.assertFalse(report.integrity_pass)
                    self.assertEqual(len(report.mismatches), 1)
                    self.assertEqual(report.mismatches[0]["field"], "signature_system")
                finally:
                    store.close()

    def test_structural_check_cannot_see_a_forged_signature(self):
        """The honest limit, pinned so it is never mistaken for coverage.

        A structural check reads stored bytes; it cannot tell a valid signature
        from a forged one. If this test ever starts failing, it means the
        structural path began claiming authenticity it cannot establish.
        """
        with tempfile.TemporaryDirectory() as tmp:
            packet = self._store_with_one_packet(tmp, "unit-test-evidence-secret")
            self._tamper_signature(tmp, packet.evidence_id)

            with _without_evidence_secret():
                os.environ.pop(SECRET_ENV, None)
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    report = store.verify(verify_signatures=False)
                    self.assertTrue(report.integrity_pass)
                finally:
                    store.close()

    def test_a_different_key_does_not_verify(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store_with_one_packet(tmp, "unit-test-evidence-secret")

            with patch.dict(os.environ, {SECRET_ENV: "some-other-secret"}):
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    self.assertFalse(store.verify().integrity_pass)
                finally:
                    store.close()

    def test_the_right_key_still_verifies(self):
        with tempfile.TemporaryDirectory() as tmp:
            self._store_with_one_packet(tmp, "unit-test-evidence-secret")

            with patch.dict(os.environ, {SECRET_ENV: "unit-test-evidence-secret"}):
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    report = store.verify()
                    self.assertTrue(report.integrity_pass)
                    self.assertEqual(report.total_packets, 1)
                finally:
                    store.close()


class CustodyChainTests(unittest.TestCase):
    def test_custody_chain_verifies_and_filters_by_evidence_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {SECRET_ENV: "unit-test-evidence-secret"}):
                store = EvidenceStore(os.path.join(tmp, "evidence.db"))
                try:
                    packet = store.ingest(
                        event_type="test",
                        raw_payload={"a": 1},
                        normalized_payload={"a": 1},
                        metadata={"dossier_id": "d"},
                    )
                    first = store.add_custody_event(
                        packet.evidence_id, "operator", CustodyAction.VIEWED
                    )
                    second = store.add_custody_event(
                        packet.evidence_id, "operator", CustodyAction.EXPORTED
                    )

                    events = store.get_custody_events(packet.evidence_id)
                    self.assertEqual([event.custody_id for event in events], [
                        first.custody_id,
                        second.custody_id,
                    ])
                    self.assertEqual(first.previous_custody_hash, "0" * 64)
                    self.assertEqual(second.previous_custody_hash, first.record_hash)
                    self.assertEqual(first.content_hash, packet.hash_self)
                    self.assertEqual(
                        store.verify_custody_chain(packet.evidence_id),
                        (True, []),
                    )

                    report = store.verify()
                    self.assertTrue(report.integrity_pass)
                    self.assertTrue(report.custody_chain_ok)
                    self.assertEqual(report.custody_chain_problems, [])
                finally:
                    store.close()

    def test_existing_custody_table_gets_chain_columns(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "evidence.db")
            store = EvidenceStore(db_path)
            store.conn.execute("ALTER TABLE custody_events RENAME TO custody_events_current")
            store.conn.execute(
                """
                CREATE TABLE custody_events (
                    custody_id TEXT PRIMARY KEY,
                    evidence_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    signature TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(evidence_id) REFERENCES evidence_packets(evidence_id)
                )
                """
            )
            store.conn.execute("DROP TABLE custody_events_current")
            store.conn.commit()
            store.close()

            migrated = EvidenceStore(db_path)
            try:
                columns = {
                    row[1]
                    for row in migrated.conn.execute("PRAGMA table_info(custody_events)")
                }
                self.assertTrue(
                    {
                        "previous_custody_hash",
                        "record_hash",
                        "content_hash",
                    }.issubset(columns)
                )
            finally:
                migrated.close()


class CustodyChainTamperTests(unittest.TestCase):
    def _store_with_two_custody_events(self, db_path: str):
        store = EvidenceStore(db_path)
        packet = store.ingest(
            event_type="test",
            raw_payload={"a": 1},
            normalized_payload={"a": 1},
            metadata={"dossier_id": "d"},
        )
        first = store.add_custody_event(
            packet.evidence_id, "operator", CustodyAction.INGESTED
        )
        second = store.add_custody_event(
            packet.evidence_id, "operator", CustodyAction.VERIFIED
        )
        return store, packet, first, second

    def _assert_chain_problem(self, store, evidence_id: str, *prefixes: str):
        valid, problems = store.verify_custody_chain(evidence_id)
        self.assertFalse(valid)
        self.assertTrue(any(problem.startswith(prefixes) for problem in problems), problems)

    def test_delete_event_breaks_chain(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet, first, _ = self._store_with_two_custody_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "DELETE FROM custody_events WHERE custody_id = ?", (first.custody_id,)
            )
            store.conn.commit()
            self._assert_chain_problem(
                store, packet.evidence_id, "chain_link_broken:", "record_hash_mismatch:"
            )

    def test_reorder_events_breaks_chain(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet, _, second = self._store_with_two_custody_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "UPDATE custody_events SET created_at = ? WHERE custody_id = ?",
                ("0000-01-01T00:00:00+00:00", second.custody_id),
            )
            store.conn.commit()
            self._assert_chain_problem(store, packet.evidence_id, "chain_link_broken:")

    def test_tampered_actor_detected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet, _, second = self._store_with_two_custody_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "UPDATE custody_events SET actor_id = ? WHERE custody_id = ?",
                ("tampered", second.custody_id),
            )
            store.conn.commit()
            self._assert_chain_problem(store, packet.evidence_id, "record_hash_mismatch:")

    def test_mutated_content_detected(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet, _, _ = self._store_with_two_custody_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "UPDATE evidence_packets SET hash_self = ? WHERE evidence_id = ?",
                ("f" * 64, packet.evidence_id),
            )
            store.conn.commit()
            self._assert_chain_problem(store, packet.evidence_id, "content_hash_mismatch:")

    def test_wrong_key_signature_detected(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "evidence.db")
            with patch.dict(os.environ, {SECRET_ENV: "key-a"}):
                store, packet, _, _ = self._store_with_two_custody_events(db_path)
                store.close()
            with patch.dict(os.environ, {SECRET_ENV: "key-b"}):
                store = EvidenceStore(db_path)
                self.addCleanup(store.close)
                self._assert_chain_problem(store, packet.evidence_id, "signature_invalid:")

    def test_pipeline_custody_idempotency(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet, _, _ = self._store_with_two_custody_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            # Repeated recording adds additional events; it is not idempotent.
            store.add_custody_event(packet.evidence_id, "operator", CustodyAction.INGESTED)
            store.add_custody_event(packet.evidence_id, "operator", CustodyAction.VERIFIED)
            self.assertEqual(len(store.get_custody_events(packet.evidence_id)), 4)
            self.assertEqual(store.verify_custody_chain(packet.evidence_id), (True, []))

    # Hash chains detect tampering of events that are present. They do not
    # detect truncation of suffix events. Deleting the terminal VERIFIED
    # event leaves a valid one-event chain and verification returns
    # (True, []). This is a known limitation without external anchoring,
    # which is deferred. See v1-scope-deferral.md.
    def test_terminal_deletion_is_a_known_limitation(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet, _, verified = self._store_with_two_custody_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "DELETE FROM custody_events WHERE custody_id = ?", (verified.custody_id,)
            )
            store.conn.commit()
            self.assertEqual(store.verify_custody_chain(packet.evidence_id), (True, []))


class SignerItselfTests(unittest.TestCase):
    """F-02 is unchanged: the signer still refuses to exist without a key."""

    def test_signer_still_refuses_without_a_secret(self):
        with _without_evidence_secret():
            os.environ.pop(SECRET_ENV, None)
            with self.assertRaises(EvidenceSignerUnbound):
                EvidenceSigner()


if __name__ == "__main__":
    unittest.main()
