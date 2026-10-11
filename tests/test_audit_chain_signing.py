"""The audit chain must be signed, locked, and honest about legacy entries.

F-03: the log was hash-chained but unsigned, so anyone able to write the file
could rewrite it end to end, recompute every hash, and ``verify_chain()`` still
returned no errors (audit probe ``audit.chain.full_rewrite_undetected``).
``test_full_rewrite_without_the_key_is_detected`` is that probe, inverted: it
rewrites history, recomputes every hash correctly, and signs with a different
key. The chain must reject it.
"""
from __future__ import annotations

import json
import os
import threading
import unittest
from dataclasses import asdict
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from dossier_pipeline.registry.audit import (
    LEGACY_UNSIGNED,
    AuditEntry,
    AuditLog,
    AuditSigner,
    AuditSigningKeyMissing,
    _entry_hash,
    _record_hash,
)


class AuditSigningTests(unittest.TestCase):
    def test_entries_are_signed_and_chain_verifies(self):
        with TemporaryDirectory() as tmp:
            log = AuditLog(Path(tmp) / "audit.jsonl")
            first = log.append({"projection_id": "p1"})
            second = log.append({"projection_id": "p2"})
            self.assertTrue(first.signature)
            self.assertEqual(second.prev_hash, first.entry_hash)
            self.assertEqual(log.verify_chain(), [])

    def test_full_rewrite_without_the_key_is_detected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            log = AuditLog(path)
            log.append({"projection_id": "p1"})

            # The attacker recomputes every hash correctly but does not hold
            # the audit signing key, so they sign with their own.
            rogue = AuditSigner(key="attacker-key", key_id="attacker")
            record = {"projection_id": "forged"}
            record_hash = _record_hash(record)
            entry_hash = _entry_hash(0, "", record_hash)
            forged = AuditEntry(
                seq=0,
                prev_hash="",
                record=record,
                record_hash=record_hash,
                entry_hash=entry_hash,
                signature=rogue.sign(0, entry_hash),
                key_id="attacker",
            )
            path.write_text(
                json.dumps(asdict(forged), sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            errors = log.verify_chain()
            self.assertTrue(errors, "a forged rewrite must not verify clean")
            messages = [message for _, message in errors]
            self.assertIn("signature mismatch", messages)

    def test_recomputing_hashes_but_keeping_old_signature_is_detected(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            log = AuditLog(path)
            original = log.append({"projection_id": "p1"})

            record = {"projection_id": "forged"}
            record_hash = _record_hash(record)
            entry_hash = _entry_hash(0, "", record_hash)
            forged = AuditEntry(
                seq=0,
                prev_hash="",
                record=record,
                record_hash=record_hash,
                entry_hash=entry_hash,
                signature=original.signature,
                key_id=original.key_id,
            )
            path.write_text(
                json.dumps(asdict(forged), sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            messages = [message for _, message in log.verify_chain()]
            self.assertIn("signature mismatch", messages)

    def test_unsigned_legacy_entry_is_reported_not_accepted(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            record = {"projection_id": "legacy"}
            record_hash = _record_hash(record)
            entry_hash = _entry_hash(0, "", record_hash)
            legacy = {
                "seq": 0,
                "prev_hash": "",
                "record": record,
                "record_hash": record_hash,
                "entry_hash": entry_hash,
            }
            path.write_text(
                json.dumps(legacy, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
            )

            messages = [message for _, message in AuditLog(path).verify_chain()]
            self.assertIn(LEGACY_UNSIGNED, messages)

    def test_missing_key_refuses_to_open_the_log(self):
        with TemporaryDirectory() as tmp:
            with patch.dict(os.environ):
                os.environ.pop("GDC_AUDIT_SIGNING_KEY", None)
                with self.assertRaises(AuditSigningKeyMissing):
                    AuditLog(Path(tmp) / "audit.jsonl")

    def test_blank_key_is_rejected(self):
        for blank in ("", "   "):
            with self.subTest(blank=repr(blank)):
                with self.assertRaises(AuditSigningKeyMissing):
                    AuditSigner(key=blank)

    def test_path_can_be_configured(self):
        with TemporaryDirectory() as tmp:
            target = Path(tmp) / "configured" / "audit.jsonl"
            with patch.dict(os.environ, {"GDC_AUDIT_PATH": str(target)}):
                log = AuditLog()
                self.assertEqual(log.path, target)


class AuditConcurrencyTests(unittest.TestCase):
    def test_concurrent_appends_produce_one_contiguous_chain(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / "audit.jsonl"
            writers = 8
            per_writer = 5
            barrier = threading.Barrier(writers)

            def write(worker: int) -> None:
                log = AuditLog(path)
                barrier.wait()
                for index in range(per_writer):
                    log.append({"worker": worker, "index": index})

            threads = [
                threading.Thread(target=write, args=(worker,))
                for worker in range(writers)
            ]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()

            log = AuditLog(path)
            entries = list(log)
            self.assertEqual(len(entries), writers * per_writer)
            self.assertEqual([entry.seq for entry in entries], list(range(len(entries))))
            self.assertEqual(log.verify_chain(), [])


if __name__ == "__main__":
    unittest.main()
