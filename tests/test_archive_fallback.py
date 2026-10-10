import io
import tempfile
import unittest
import zipfile
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

from dossier_pipeline.intake import EmailIntake, EmailSeenSet


def build_email_with_attachment(*, message_id: str, filename: str, payload: bytes, content_type: str = "application/octet-stream") -> bytes:
    msg = EmailMessage(policy=default)
    msg["Message-ID"] = message_id
    msg["Subject"] = "Attachment test"
    msg["From"] = "Sender <sender@example.com>"
    msg["To"] = "Recipient <recipient@example.com>"
    msg["Date"] = "Fri, 1 May 2026 09:15:00 -0400"
    msg.set_content("attachment body")

    maintype, subtype = content_type.split("/", 1)
    msg.add_attachment(payload, maintype=maintype, subtype=subtype, filename=filename)
    return msg.as_bytes()


def build_zip_with_member(member_name: str, content: bytes = b"x") -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(member_name, content)
    return buffer.getvalue()


class ArchiveFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.seen = EmailSeenSet(str(Path(self.tempdir.name) / "seen.db"))
        self.intake = EmailIntake(self.seen)

    def tearDown(self):
        self.seen.close()
        self.tempdir.cleanup()

    def _single_attachment(self, raw_email: bytes) -> dict:
        envelope = self.intake.parse_email_bytes(raw_email)
        self.assertEqual(len(envelope.attachments), 1)
        return envelope.attachments[0]

    def test_corrupt_zip_attachment_is_marked_corrupt_archive(self):
        raw = build_email_with_attachment(
            message_id="<corrupt-zip@example.com>",
            filename="evidence.zip",
            payload=b"this-is-not-a-valid-zip",
            content_type="application/zip",
        )

        attachment = self._single_attachment(raw)

        self.assertTrue(attachment["archive"])
        self.assertEqual(attachment["archive_status"], "corrupt_archive")
        self.assertIn("archive_error", attachment)

    def test_oversize_archive_is_skipped(self):
        self.intake.ARCHIVE_MAX_BYTES = 64
        raw = build_email_with_attachment(
            message_id="<oversize-zip@example.com>",
            filename="oversize.zip",
            payload=b"a" * 128,
            content_type="application/zip",
        )

        attachment = self._single_attachment(raw)

        self.assertEqual(attachment["archive_status"], "skipped_oversize")
        self.assertEqual(attachment["archive_size_bytes"], 128)

    def test_deep_archive_path_is_capped(self):
        self.intake.ARCHIVE_MAX_PATH_DEPTH = 3
        deep_zip = build_zip_with_member("a/b/c/d/e.txt", b"nested")
        raw = build_email_with_attachment(
            message_id="<deep-path-zip@example.com>",
            filename="deep.zip",
            payload=deep_zip,
            content_type="application/zip",
        )

        attachment = self._single_attachment(raw)

        self.assertEqual(attachment["archive_status"], "path_depth_exceeded")
        self.assertGreater(attachment["archive_max_path_depth"], 3)


if __name__ == "__main__":
    unittest.main()
