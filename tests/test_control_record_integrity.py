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

import hashlib
import json
import multiprocessing
import sys
import tempfile
import unittest
from datetime import datetime
from email.message import EmailMessage
from email.policy import default
from pathlib import Path
from unittest.mock import patch

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


class ArtifactIdentityInCommittedRecordTests(unittest.TestCase):
    """W1: The artifact hash must be explicitly exported, not blocked by the denylist.

    W1: the record must name the artifact that was actually submitted.

    Before this, ``raw_sha256`` was the only identity on the record, and for a
    document submission the bytes it hashed were a wrapper this system
    synthesised around the text. The record therefore described nothing the
    submitter handed over and could not be tied back to the file. These tests
    pin both halves: the identity travels, and the invented fields are named.
    """

    def test_source_sha256_is_exportable(self):
        from dossier_pipeline.trust_boundary import DEFAULT_CONTRACT

        self.assertIn(
            "source_sha256",
            DEFAULT_CONTRACT.exportable_fields,
            "source_sha256 must be in exportable_fields so it travels with the record",
        )

    SOURCE_FIELDS = (
        "message_id",
        "subject",
        "sender",
        "recipient",
        "date",
    )

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _wrapped(self, artifact: bytes, digest: str) -> bytes:
        wrapper = EmailMessage(policy=default)
        wrapper["Message-ID"] = f"<{digest[:32]}@document.local>"
        wrapper["Subject"] = "(interface submission)"
        wrapper["From"] = "interface@localhost"
        wrapper["To"] = "interface@localhost"
        wrapper["Date"] = "Thu, 01 Jan 1970 00:00:00 +0000"
        wrapper.set_content(artifact.decode("utf-8", "replace"))
        return wrapper.as_bytes()

    def test_committed_record_carries_the_submitted_artifact(self) -> None:
        artifact = b"Angel v. Murray case brief, submitted as a document."
        digest = hashlib.sha256(artifact).hexdigest()

        with DossierPipeline(
            dossier_id="TEST-ARTIFACT-IDENTITY", output_dir=self.tempdir.name
        ) as pipeline:
            result = pipeline.process_email(
                self._wrapped(artifact, digest),
                source={
                    "source_sha256": digest,
                    "source_bytes": len(artifact),
                    "source_filename": "brief.txt",
                    "source_media_type": "text/plain",
                    "transport": "document",
                    "synthesised_fields": self.SOURCE_FIELDS,
                },
            )
            self.assertEqual(result.status.value, "processed")

            records = pipeline.control.get_all_records()
            self.assertTrue(records)
            payload = records[-1]["payload"]

            # The signed record, not merely the pipeline's return value.
            self.assertEqual(payload["source_sha256"], digest)
            self.assertEqual(payload["source_bytes"], len(artifact))
            self.assertEqual(payload["source_filename"], "brief.txt")
            self.assertEqual(payload["transport"], "document")
            self.assertEqual(
                tuple(payload["synthesised_fields"]), self.SOURCE_FIELDS
            )
            # The wrapper is not the artifact, and the record now distinguishes
            # them: `raw_sha256` hashes the bytes that were parsed, the artifact
            # hash is what the submitter actually handed over.
            self.assertNotEqual(payload["raw_sha256"], payload["source_sha256"])

    def test_record_does_not_invent_an_actor_for_a_document(self) -> None:
        """A court brief is not an insurer, and a filing has no correspondent."""
        artifact = b"The insurance claim and the insurer are discussed at length."
        digest = hashlib.sha256(artifact).hexdigest()

        with DossierPipeline(
            dossier_id="TEST-ACTOR-SCOPE", output_dir=self.tempdir.name
        ) as pipeline:
            result = pipeline.process_email(
                self._wrapped(artifact, digest),
                source={
                    "source_sha256": digest,
                    "source_bytes": len(artifact),
                    "source_filename": "brief.txt",
                    "source_media_type": "text/plain",
                    "transport": "document",
                    "synthesised_fields": self.SOURCE_FIELDS,
                },
            )
            self.assertEqual(result.status.value, "processed")
            payload = pipeline.control.get_all_records()[-1]["payload"]

            self.assertEqual(payload["actor"], "unknown")
            self.assertTrue(
                payload["classification_scope_warning"],
                "a scoped actor classification must travel as a field: the "
                "reasoning trace is internal-only and is stripped from exports",
            )
            # The honesty signal is the synthesised-field list: it names every
            # envelope field this system invented, which is what makes the
            # completeness of the record checkable from the record itself.
            self.assertEqual(
                tuple(payload["synthesised_fields"]), self.SOURCE_FIELDS
            )
            # Provenance is correspondingly incomplete. Provenance is bound into
            # the chain through the adapter payload hash rather than repeated as
            # a nested block in the control payload, so it is asserted on the
            # pipeline's own result.
            self.assertFalse(result.data["provenance_complete"])
            self.assertIn("message_id (synthesised)", result.data["missing_fields"])

    def test_email_submission_keeps_its_own_identity(self) -> None:
        """The email path must not regress: there the artifact IS the message."""
        with DossierPipeline(
            dossier_id="TEST-EMAIL-IDENTITY", output_dir=self.tempdir.name
        ) as pipeline:
            raw = build_email(
                message_id="<email-identity@example.com>",
                subject="Scheduling update",
                body="Client scheduling update",
            )
            result = pipeline.process_email(raw)
            self.assertEqual(result.status.value, "processed")
            payload = pipeline.control.get_all_records()[-1]["payload"]

            self.assertEqual(payload["raw_sha256"], hashlib.sha256(raw).hexdigest())
            self.assertEqual(payload["source_sha256"], payload["raw_sha256"])
            self.assertEqual(payload["transport"], "email")
            self.assertEqual(tuple(payload["synthesised_fields"]), ())
            self.assertEqual(payload["classification_scope_warning"], "")


class DocumentResubmissionIdentityTests(unittest.TestCase):
    """W1: the same document must ingest to the same identity, twice running.

    The synthetic wrapper carried a `uuid4()` Message-ID and the wall clock in
    its Date. Resubmitting unchanged bytes therefore built a brand-new message
    each time: deduplication could never fire on a document, and one file could
    occupy the chain with a fresh record on every attempt.
    """

    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.artifact = b"Angel v. Murray: a case brief submitted as a document."
        self.brief = Path(self.tempdir.name) / "brief.txt"
        self.brief.write_bytes(self.artifact)
        self.config = patch(
            "interface.document._config",
            return_value={
                "dossier_id": "TEST-DOCUMENT-IDENTITY",
                "output_dir": self.tempdir.name,
                "email": "interface@localhost",
            },
        )
        self.config.start()
    def test_document_bridge_populates_synthesised_fields(self) -> None:
        """W2: The document bridge itself must inject the synthetic field list."""
        from interface import document

        first = document.process(file_path=str(self.brief), filename=self.brief.name)
        self.assertEqual(first["status"], "processed")
        
        expected_fields = ("message_id", "subject", "sender", "recipient", "date")
        self.assertEqual(
            tuple(first["data"]["synthesised_fields"]),
            expected_fields,
            "The document bridge must populate synthesised_fields so the record is honest."
        )
    def tearDown(self) -> None:
        self.config.stop()
        self.tempdir.cleanup()

    def test_unchanged_bytes_are_recognised_as_a_resubmission(self) -> None:
        from interface import document

        digest = hashlib.sha256(self.artifact).hexdigest()

        first = document.process(file_path=str(self.brief), filename=self.brief.name)
        self.assertEqual(first["status"], "processed")
        self.assertEqual(first["data"]["source_sha256"], digest)
        self.assertEqual(first["data"]["transport"], "document")

        second = document.process(file_path=str(self.brief), filename=self.brief.name)
        self.assertEqual(
            second["status"],
            "duplicate",
            "unchanged bytes must be recognised as a resubmission rather than "
            "ingested as new evidence",
        )
        self.assertEqual(second["raw_sha256"], first["raw_sha256"])


if __name__ == "__main__":
    unittest.main()
