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
                                       EvidenceSignerUnbound, EvidenceStore,
                                       SystemState)
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


class VerifyDetectsCustodyTamperTests(unittest.TestCase):
    """`verify()` must detect custody tampering, not only the per-item check.

    Every other custody-tamper pin in this module asserts through
    `verify_custody_chain()`, which checks one item on demand. `verify()`
    covers the whole store and is what actually runs - on every open, every
    ingest and every custody write - so a regression there would report a
    tampered chain as intact while every single-item pin stayed green. That
    is the failure this class exists to make loud.

    `verify()` groups the events it has already loaded by evidence_id instead
    of re-querying each item, so the multi-item pins are the ones that matter:
    they fail if grouping ever attributes one item's events to another, drops
    an item, or multiplies the work per item.
    """

    def _store_with_events(self, db_path: str, *, label: str = "a"):
        store = EvidenceStore(db_path)
        packet = store.ingest(
            event_type="test",
            raw_payload={label: 1},
            normalized_payload={label: 1},
            metadata={"dossier_id": "d"},
        )
        store.add_custody_event(packet.evidence_id, "operator", CustodyAction.INGESTED)
        store.add_custody_event(packet.evidence_id, "operator", CustodyAction.VERIFIED)
        return store, packet

    def test_intact_store_reports_no_chain_problems(self):
        """A false positive here would condemn every store it touched."""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, _ = self._store_with_events(os.path.join(tmp, "evidence.db"))
            self.addCleanup(store.close)
            report = store.verify()
            self.assertTrue(report.custody_chain_ok, report.custody_chain_problems)
            self.assertEqual(report.custody_chain_problems, [])

    def test_broken_link_is_reported_by_verify(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            store, packet = self._store_with_events(os.path.join(tmp, "evidence.db"))
            self.addCleanup(store.close)
            first = store.get_custody_events(packet.evidence_id)[0]
            store.conn.execute(
                "DELETE FROM custody_events WHERE custody_id = ?", (first.custody_id,)
            )
            store.conn.commit()

            report = store.verify()
            self.assertFalse(report.custody_chain_ok)
            self.assertTrue(
                any(p.startswith("chain_link_broken:") for p in report.custody_chain_problems),
                report.custody_chain_problems,
            )

    def test_a_clean_item_contributes_no_problems(self):
        """Tamper one of two items; the other must stay silent.

        The tampered item is chosen by sorted evidence_id - the order verify()
        walks - so that a regression which looks at only some of the items
        fails here every time. Picking by creation order instead would leave
        this test passing whenever the two happened to sort that way, which is
        a coin flip because the ids are random.
        """
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            db_path = os.path.join(tmp, "evidence.db")
            store, first_packet = self._store_with_events(db_path, label="a")
            self.addCleanup(store.close)
            other, second_packet = self._store_with_events(db_path, label="b")
            self.addCleanup(other.close)

            clean_packet, tampered = sorted(
                (first_packet, second_packet), key=lambda packet: packet.evidence_id
            )

            first_event = store.get_custody_events(tampered.evidence_id)[0]
            store.conn.execute(
                "DELETE FROM custody_events WHERE custody_id = ?", (first_event.custody_id,)
            )
            store.conn.commit()

            self.assertTrue(store.verify_custody_chain(clean_packet.evidence_id)[0])
            report = store.verify()
            self.assertFalse(report.custody_chain_ok)
            self.assertEqual(len(report.custody_chain_problems), 1, report.custody_chain_problems)

    def test_verify_agrees_with_the_per_item_check(self):
        """The grouped pass and the single-item pass must reach one verdict.

        This is the contract behind grouping the events: same rules, same
        problems, same order. If the two ever disagree, one of them is lying
        about a chain and there is no way to tell which from the outside.
        """
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "tamper-test-secret"}
        ):
            db_path = os.path.join(tmp, "evidence.db")
            store, _ = self._store_with_events(db_path, label="a")
            self.addCleanup(store.close)
            other, other_packet = self._store_with_events(db_path, label="b")
            self.addCleanup(other.close)

            store.conn.execute(
                "UPDATE custody_events SET actor_id = ? WHERE evidence_id = ?",
                ("tampered", other_packet.evidence_id),
            )
            store.conn.commit()

            report = store.verify()
            per_item: list[str] = []
            per_item_ok = True
            for evidence_id in sorted(
                {event.evidence_id for event in store.get_custody_events()}
            ):
                ok, problems = store.verify_custody_chain(evidence_id)
                per_item_ok = per_item_ok and ok
                per_item.extend(problems)

            self.assertEqual(per_item_ok, report.custody_chain_ok)
            self.assertEqual(per_item, report.custody_chain_problems)


class VerificationSeverityTests(unittest.TestCase):
    """What each kind of damage does, and what it deliberately does not do.

    `verify()` used to fold only the stored bytes into `integrity_pass` and
    drop the custody chain on the floor, so a store whose custody log had been
    altered reported PASS to every caller. These pins fix the mapping in place:
    a pass means every check passed, and the store's severity says which check
    failed. The four outcomes are separated on purpose because their innocent
    causes differ, and two of them would be unrecoverable if conflated.
    """

    def _store_with_two_events(self, db_path: str):
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

    def test_broken_chain_fails_the_integrity_pass(self):
        """The defect this class exists for: a tampered chain must not pass."""
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "severity-test-secret"}
        ):
            store, packet, first, _ = self._store_with_two_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "DELETE FROM custody_events WHERE custody_id = ?", (first.custody_id,)
            )
            store.conn.commit()

            report = store.verify()
            self.assertFalse(report.custody_chain_ok)
            self.assertFalse(
                report.integrity_pass,
                "a broken custody chain reported integrity_pass",
            )
            self.assertEqual(report.system_state, SystemState.COMPROMISED)

    def test_broken_chain_does_not_lock_the_store(self):
        """A compromised chain is loud, but still writable.

        Locking here would be unrecoverable - no unlock exists - and a chain
        can break for reasons other than tampering. The store keeps accepting
        evidence and keeps reporting that its chain of custody is broken.
        """
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "severity-test-secret"}
        ):
            store, packet, first, _ = self._store_with_two_events(
                os.path.join(tmp, "evidence.db")
            )
            self.addCleanup(store.close)
            store.conn.execute(
                "DELETE FROM custody_events WHERE custody_id = ?", (first.custody_id,)
            )
            store.conn.commit()

            store.verify()
            self.assertEqual(store.state, SystemState.COMPROMISED)
            packet_after = store.ingest(
                event_type="test",
                raw_payload={"b": 2},
                normalized_payload={"b": 2},
                metadata={"dossier_id": "d"},
            )
            self.assertIsNotNone(packet_after)

    def test_content_tamper_locks_the_store_and_survives_a_reopen(self):
        """Editing a stored row must stop the store accepting more evidence.

        The lock was previously a per-process side effect: reopening the
        database re-derived the state as COMPROMISED and the store silently
        became writable again, so the gate in `ingest` never fired after a
        restart. Reopening is the whole test.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "evidence.db")
            with patch.dict(os.environ, {SECRET_ENV: "severity-test-secret"}):
                store, packet, _, _ = self._store_with_two_events(db_path)
                store.conn.execute(
                    "UPDATE evidence_packets SET hash_self = ? WHERE evidence_id = ?",
                    ("f" * 64, packet.evidence_id),
                )
                store.conn.commit()
                store.close()

                reopened = EvidenceStore(db_path)
                self.addCleanup(reopened.close)
                self.assertEqual(reopened.state, SystemState.LOCKED)
                with self.assertRaises(RuntimeError):
                    reopened.ingest(
                        event_type="test",
                        raw_payload={"c": 3},
                        normalized_payload={"c": 3},
                        metadata={"dossier_id": "d"},
                    )

    def test_a_rotated_key_compromises_but_does_not_lock(self):
        """Key rotation must not brick an evidence store.

        Every older signature fails under a new key, but nothing was altered.
        Treating that as tampering would refuse all further evidence on a
        store whose only problem is that its operator rotated the key, and
        there is no unlock to recover with.
        """
        with tempfile.TemporaryDirectory() as tmp:
            db_path = os.path.join(tmp, "evidence.db")
            with patch.dict(os.environ, {SECRET_ENV: "key-before-rotation"}):
                store, _, _, _ = self._store_with_two_events(db_path)
                store.close()

            with patch.dict(os.environ, {SECRET_ENV: "key-after-rotation"}):
                reopened = EvidenceStore(db_path)
                self.addCleanup(reopened.close)
                self.assertEqual(reopened.state, SystemState.COMPROMISED)
                self.assertIsNot(
                    reopened.state,
                    SystemState.LOCKED,
                    "key rotation locked the store; there is no unlock",
                )
                packet = reopened.ingest(
                    event_type="test",
                    raw_payload={"d": 4},
                    normalized_payload={"d": 4},
                    metadata={"dossier_id": "d"},
                )
                self.assertIsNotNone(packet)

    def test_legacy_unlinked_events_degrade_rather_than_compromise(self):
        """Rows written before the chain columns existed are not tampering.

        The migration adds `record_hash` with DEFAULT '', so older events stay
        blank. That is unverifiable, which must be reported, but calling it
        compromised would condemn every pre-migration store.
        """
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "severity-test-secret"}
        ):
            store = EvidenceStore(os.path.join(tmp, "evidence.db"))
            self.addCleanup(store.close)
            packet = store.ingest(
                event_type="test",
                raw_payload={"a": 1},
                normalized_payload={"a": 1},
                metadata={"dossier_id": "d"},
            )
            store.conn.execute(
                """
                INSERT INTO custody_events (
                    custody_id, evidence_id, actor_id, action, timestamp_utc, signature,
                    previous_custody_hash, record_hash, content_hash, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    "legacy-event-1",
                    packet.evidence_id,
                    "operator",
                    CustodyAction.VIEWED.value,
                    "2020-01-01T00:00:00+00:00",
                    "",
                    "",
                    "",
                    "",
                    "2020-01-01T00:00:00+00:00",
                ),
            )
            store.conn.commit()

            report = store.verify(verify_signatures=False)
            self.assertTrue(report.custody_chain_problems)
            self.assertTrue(
                all(p.startswith("legacy_unlinked_event:") for p in report.custody_chain_problems),
                report.custody_chain_problems,
            )
            self.assertEqual(report.system_state, SystemState.DEGRADED)
            self.assertFalse(report.integrity_pass)


class VerifyCommandTests(unittest.TestCase):
    """`verify` must not print PASS for a store whose custody log was altered."""

    def test_verify_command_fails_on_a_broken_custody_chain(self):
        import contextlib
        import io
        import sys

        from dossier_pipeline.main import main

        with tempfile.TemporaryDirectory() as tmp, patch.dict(
            os.environ, {SECRET_ENV: "cli-verify-secret"}
        ):
            os.environ.setdefault("GDC_CONTROL_SIGNING_KEY", "unit-control-key")
            pipeline = DossierPipeline(dossier_id="TEST-VERIFY", output_dir=tmp)
            try:
                packet = pipeline.evidence.ingest(
                    event_type="test",
                    raw_payload={"a": 1},
                    normalized_payload={"a": 1},
                    metadata={"dossier_id": "d"},
                )
                first = pipeline.evidence.add_custody_event(
                    packet.evidence_id, "operator", CustodyAction.INGESTED
                )
                pipeline.evidence.add_custody_event(
                    packet.evidence_id, "operator", CustodyAction.VERIFIED
                )
                pipeline.evidence.conn.execute(
                    "DELETE FROM custody_events WHERE custody_id = ?", (first.custody_id,)
                )
                pipeline.evidence.conn.commit()
            finally:
                pipeline.close()

            printed = io.StringIO()
            argv = sys.argv
            sys.argv = ["main", "--dossier", "TEST-VERIFY", "--output-dir", tmp, "verify"]
            try:
                with contextlib.redirect_stdout(printed):
                    with self.assertRaises(SystemExit) as raised:
                        main()
            finally:
                sys.argv = argv

            output = printed.getvalue()
            self.assertEqual(raised.exception.code, 2, output)
            self.assertIn("Evidence integrity: FAIL", output)
            self.assertIn("Custody chain:      FAIL", output)


if __name__ == "__main__":
    unittest.main()
