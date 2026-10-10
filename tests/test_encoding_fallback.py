import sys
import tempfile
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dossier_pipeline.intake import EmailIntake, EmailSeenSet


def build_email_with_charset(*, message_id: str, subject: str, body: str, subtype: str, charset: str) -> bytes:
    msg = EmailMessage(policy=default)
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = "Sender <sender@example.com>"
    msg["To"] = "Recipient <recipient@example.com>"
    msg["Date"] = "Fri, 1 May 2026 09:15:00 -0400"
    msg.set_content(body, subtype=subtype, charset=charset)
    return msg.as_bytes()


def build_raw_with_unknown_charset(*, message_id: str, subject: str, body_ascii: str) -> bytes:
    return (
        f"Message-ID: {message_id}\r\n"
        f"Subject: {subject}\r\n"
        "From: Sender <sender@example.com>\r\n"
        "To: Recipient <recipient@example.com>\r\n"
        "Date: Fri, 1 May 2026 09:15:00 -0400\r\n"
        "MIME-Version: 1.0\r\n"
        "Content-Type: text/plain; charset=unknown-charset-xyz\r\n"
        "Content-Transfer-Encoding: 8bit\r\n"
        "\r\n"
        f"{body_ascii}\r\n"
    ).encode("ascii")


class EncodingFallbackTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.seen = EmailSeenSet(str(Path(self.tempdir.name) / "seen.db"))
        self.intake = EmailIntake(self.seen)

    def tearDown(self):
        self.seen.close()
        self.tempdir.cleanup()

    def test_utf16_plain_text_is_decoded(self):
        raw = build_email_with_charset(
            message_id="<utf16-plain@example.com>",
            subject="UTF16 plain",
            body="Bonjour - preuve medicale",
            subtype="plain",
            charset="utf-16",
        )

        envelope = self.intake.parse_email_bytes(raw)

        self.assertIn("Bonjour", envelope.body_text)
        self.assertIn("preuve medicale", envelope.body_text)

    def test_utf16_html_is_decoded_and_stripped(self):
        raw = build_email_with_charset(
            message_id="<utf16-html@example.com>",
            subject="UTF16 html",
            body="<html><body><p>Client requires response</p></body></html>",
            subtype="html",
            charset="utf-16",
        )

        envelope = self.intake.parse_email_bytes(raw)

        self.assertIn("Client requires response", envelope.body_text)
        self.assertNotIn("<html>", envelope.body_text)

    def test_unknown_charset_falls_back_and_keeps_ascii_text(self):
        raw = build_raw_with_unknown_charset(
            message_id="<unknown-charset@example.com>",
            subject="Unknown charset",
            body_ascii="ASCII fallback remains readable",
        )

        envelope = self.intake.parse_email_bytes(raw)

        self.assertEqual(envelope.body_text.strip(), "ASCII fallback remains readable")


if __name__ == "__main__":
    unittest.main()
