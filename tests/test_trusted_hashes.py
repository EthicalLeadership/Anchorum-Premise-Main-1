"""The sanitizer's allowlist: verification material survives, everything else does not."""
from __future__ import annotations

import hashlib

from dossier_pipeline.output_gates import sanitize_output

ARTIFACT = hashlib.sha256(b"exhibit").hexdigest()
INTERNAL = hashlib.sha256(b"internal-record").hexdigest()


def test_untrusted_hashes_are_still_redacted():
    report = sanitize_output(f"line with {INTERNAL} hash")
    assert INTERNAL not in report.sanitized_text
    assert "[redacted-hash]" in report.sanitized_text
    assert report.leakage_found is True


def test_hashing_still_works_without_an_allowlist():
    """The default call is unchanged: every earlier caller keeps its behaviour."""
    text = "artifact " + ARTIFACT
    assert ARTIFACT not in sanitize_output(text).sanitized_text


def test_trusted_hash_survives_redaction():
    report = sanitize_output(
        f"- `E-1` — letter.pdf (sha256: {ARTIFACT})",
        trusted_hashes=[ARTIFACT],
    )
    assert ARTIFACT in report.sanitized_text
    assert "[redacted-hash]" not in report.sanitized_text


def test_trusted_hash_keeps_its_whole_line():
    """The line-drop step must not remove a line whose only hash is allowed."""
    report = sanitize_output(
        f"- `E-1` — letter.pdf (sha256: {ARTIFACT})\ntrailing prose",
        trusted_hashes=[ARTIFACT],
    )
    assert "letter.pdf" in report.sanitized_text
    assert "trailing prose" in report.sanitized_text


def test_an_untrusted_hash_on_the_same_line_is_still_redacted():
    report = sanitize_output(
        f"- `E-1` — sha256: {ARTIFACT} record: {INTERNAL}",
        trusted_hashes=[ARTIFACT],
    )
    assert ARTIFACT in report.sanitized_text
    assert INTERNAL not in report.sanitized_text


def test_allowlist_entries_that_are_not_hex_are_ignored():
    """A pasted token must not be re-inserted into outward text."""
    report = sanitize_output("hello world", trusted_hashes=["not-a-hash; drop table"])
    assert "hello world" in report.sanitized_text
    assert "drop table" not in report.sanitized_text
