"""Regression pins for control-record integrity, clock provenance and locking.

Each test here exists because the corresponding remediation was, until now,
pinned by nothing: a fix no test can fail is one refactor away from being undone.

* F-04 - the accessor that defines what the control chain contains must return
  every committed record. The removed filter dropped rows whose payload had
  ``policy_allowed is False``.
* F-13 - every record must say which clock produced its timestamp, and that
  timestamp must be offset-aware UTC rather than naive local time.
* F-03 - the append lock must hold between separate processes, not merely
  between threads, because the threat is two concurrent invocations.
"""

import json
import multiprocessing
import sys
import tempfile
import unittest
from datetime import datetime
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dossier_pipeline.control import TIME_SOURCE_SYSTEM_CLOCK_UTC, _utc_now_iso
from dossier_pipeline.pipeline import DossierPipeline
from dossier_pipeline.registry.audit import AuditLog


def build_email(
    *,
    message_id: str,
    subject: str,
    body: str,
    sender: str = "HR Operations <hr.operations@example.com>",
    recipient: str = "user@example.com",
    date: str = "Fri, 1 May 2026 09:15:00 -0400",
) -> bytes:
    msg = EmailMessage(policy=default)
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = date
    msg.set_content(body)
    return msg.as_bytes()


def _committed_row_count(pipeline: DossierPipeline) -> int:
    """Count rows directly, bypassing the accessor under test."""
    cur = pipeline.control.conn.execute("SELECT COUNT(*) FROM control_records")
    return int(cur.fetchone()[0])


class ControlAccessorTests(unittest.TestCase):
    """F-04: the integrity accessor must not filter the chain it defines."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_accessor_returns_every_committed_row(self) -> None:
        with DossierPipeline(
            dossier_id="TEST-ACCESSOR-COMPLETE", output_dir=self.tempdir.name
        ) as pipeline:
            pipeline.process_email(
                build_email(
                    message_id="<accessor-complete@example.com>",
                    subject="Scheduling update",
                    body="Client scheduling update",
                )
            )

            rows = _committed_row_count(pipeline)
            self.assertGreaterEqual(rows, 1)
            self.assertEqual(
                len(pipeline.control.get_all_records()),
                rows,
                "the accessor must return one record per committed row",
            )

    def test_record_with_policy_not_allowed_is_still_returned(self) -> None:
        """Reconstruct the exact condition the removed filter keyed on.

        ``policy_allowed is False`` is normally unreachable in this table
        a policy rejection writes no control record at all so the old filter
        was dead code that only invited the behaviour to be re-derived. This
        test makes the condition live: it writes the flag into a committed
        payload and requires the accessor to keep returning the record.
        """
        with DossierPipeline(
            dossier_id="TEST-ACCESSOR-UNFILTERED", output_dir=self.tempdir.name
        ) as pipeline:
            pipeline.process_email(
                build_email(
                    message_id="<accessor-unfiltered@example.com>",
                    subject="Scheduling update",
                    body="Client scheduling update",
                )
            )

            records = pipeline.control.get_all_records()
            self.assertTrue(records)
            rows = _committed_row_count(pipeline)

            denied_payload = dict(records[0]["payload"])
            denied_payload["policy_allowed"] = False
            pipeline.control.conn.execute(
                "UPDATE control_records SET payload = ? WHERE sequence_no = ?",
                (json.dumps(denied_payload, sort_keys=True), records[0]["sequence_no"]),
            )
            pipeline.control.conn.commit()

            after = pipeline.control.get_all_records()
            self.assertEqual(
                len(after),
                rows,
                "a record whose payload says policy_allowed is False must not be "
                "dropped: the anchor would then cover only part of the chain",
            )
            self.assertIs(after[0]["payload"]["policy_allowed"], False)


class RecordClockProvenanceTests(unittest.TestCase):
    """F-13: a timestamp is only trustworthy if it says which clock made it."""

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def test_utc_now_iso_is_offset_aware(self) -> None:
        value = _utc_now_iso()
        self.assertTrue(value.endswith("+00:00"), f"expected UTC offset, got {value!r}")
        parsed = datetime.fromisoformat(value)
        self.assertIsNotNone(parsed.tzinfo)

    def test_committed_records_name_their_time_source(self) -> None:
        with DossierPipeline(
            dossier_id="TEST-CLOCK-PROVENANCE", output_dir=self.tempdir.name
        ) as pipeline:
            pipeline.process_email(
                build_email(
                    message_id="<clock-provenance@example.com>",
                    subject="Scheduling update",
                    body="Client scheduling update",
                )
            )

            records = pipeline.control.get_all_records()
            self.assertTrue(records)
            for record in records:
                self.assertEqual(
                    record["payload"].get("time_source"),
                    TIME_SOURCE_SYSTEM_CLOCK_UTC,
                    "every committed payload must name the clock it used",
                )
                timestamp = datetime.fromisoformat(record["timestamp"])
                self.assertIsNotNone(
                    timestamp.tzinfo,
                    f"record timestamp must be offset-aware, got {record['timestamp']!r}",
                )


def _append_batch(path: str, worker: int, count: int) -> None:
    """Module-level so it is picklable for the process pool below."""
    log = AuditLog(Path(path))
    for index in range(count):
        log.append({"worker": worker, "index": index})


class AuditLockAcrossProcessesTests(unittest.TestCase):
    """F-03: the append lock must serialise separate processes."""

    def test_concurrent_processes_produce_one_contiguous_chain(self) -> None:
        workers = 6
        per_worker = 4
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "audit.jsonl")

            # "fork" is required: the children inherit the signing key that the
            # test configuration places in the environment. Without the lock two
            # processes could read the same tail and write the same sequence
            # number, which is exactly the corruption this guards against.
            context = multiprocessing.get_context("fork")
            processes = [
                context.Process(target=_append_batch, args=(path, worker, per_worker))
                for worker in range(workers)
            ]
            for process in processes:
                process.start()
            for process in processes:
                process.join(timeout=120)
                self.assertEqual(
                    process.exitcode, 0, "an append worker failed under contention"
                )

            log = AuditLog(Path(path))
            entries = list(log)
            self.assertEqual(len(entries), workers * per_worker)
            self.assertEqual(
                [entry.seq for entry in entries],
                list(range(len(entries))),
                "sequence numbers must be contiguous with no duplicates or gaps",
            )
            self.assertEqual(log.verify_chain(), [])


if __name__ == "__main__":
    unittest.main()
