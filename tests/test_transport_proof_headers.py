import tempfile
import unittest
from email.message import EmailMessage
from email.policy import default
from pathlib import Path

from dossier_pipeline.pipeline import DossierPipeline


def build_email_with_received_headers(
    *,
    message_id: str,
    subject: str,
    sender: str,
    recipient: str,
    date: str,
    body: str,
    received_headers: list[str],
) -> bytes:
    msg = EmailMessage(policy=default)
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = date

    # Add multiple Received hops.
    for rh in received_headers:
        msg.add_header("Received", rh)

    msg.set_content(body)
    return msg.as_bytes()


def build_email_without_received_headers(
    *,
    message_id: str,
    subject: str,
    sender: str,
    recipient: str,
    date: str,
    body: str,
) -> bytes:
    msg = EmailMessage(policy=default)
    msg["Message-ID"] = message_id
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = date
    msg.set_content(body)
    return msg.as_bytes()


class TransportProofHeadersTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory()
        self.pipeline = DossierPipeline(
            dossier_id="TRANSPORT-PROOF-TEST",
            output_dir=self.tempdir.name,
        )

    def tearDown(self) -> None:
        self.pipeline.close()
        self.tempdir.cleanup()

    def test_received_headers_extracted_and_visible_in_exports(self) -> None:
        raw = build_email_with_received_headers(
            message_id="<transport-proof-received@example.com>",
            subject="Re: Meeting confirmation",
            sender="Union 501 <delegate@union501.ca>",
            recipient="owner@example.com",
            date="Fri, 1 May 2026 09:15:00 -0400",
            body="Hello, following our discussion we will hold a meeting next week. Please confirm your availability.",
            received_headers=[
                "from mail.example.net by mx.example.org with ESMTP; Fri, 01 May 2026 09:10:00 -0400",
                "from relay.example.net by mail.example.net with ESMTP; Fri, 01 May 2026 09:09:00 -0400",
            ],
        )

        result = self.pipeline.process_email(raw)
        self.assertEqual(result.status.value, "processed")

        # JSON export should include fields (trust boundary export path).
        json_path = Path(self.tempdir.name) / "export.json"
        self.pipeline.export_json(str(json_path))
        exported = json_path.read_text(encoding="utf-8")
        self.assertIn('"received_count":', exported)
        self.assertIn('"received_first_ts":', exported)

        # Markdown export should show received_count and received_first_ts in index table.
        md_path = Path(self.tempdir.name) / "summary.md"
        self.pipeline.export_markdown_summary(str(md_path))
        md = md_path.read_text(encoding="utf-8")
        self.assertIn("Received count", md)
        self.assertIn("Received first ts", md)
        self.assertIn(" | 2 | ", md)

        # We also expect the first parsed timestamp to be present (best-effort).
        self.assertTrue(
            ("2026-05-01T09:09:00" in md) or ("2026-05-01T09:10:00" in md),
            msg="Expected one of the parsed received timestamps to appear in markdown export.",
        )

    def test_no_received_headers_defaults_to_zero_and_blanks(self) -> None:
        raw = build_email_without_received_headers(
            message_id="<transport-proof-none@example.com>",
            subject="Re: Meeting confirmation",
            sender="Union 501 <delegate@union501.ca>",
            recipient="owner@example.com",
            date="Fri, 1 May 2026 09:15:00 -0400",
            body="Hello, following our discussion we will hold a meeting next week. Please confirm your availability.",
        )

        result = self.pipeline.process_email(raw)
        self.assertEqual(result.status.value, "processed")

        md_path = Path(self.tempdir.name) / "summary.md"
        self.pipeline.export_markdown_summary(str(md_path))
        md = md_path.read_text(encoding="utf-8")

        # received_count should appear as 0 for the processed record.
        self.assertIn(" | 0 | ", md)


if __name__ == "__main__":
    unittest.main()
