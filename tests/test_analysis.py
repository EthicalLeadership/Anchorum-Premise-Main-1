"""Pins for the Tier 1 analysis record.

`interface.analysis` is the layer that answers "what did we actually read, and
did the engine cover it?". Nothing about that answer may be implicit:

* an artifact the connector cannot read is recorded as ``unsupported`` with the
  dispatcher's own message, never decoded as text and silently projected;
* an artifact above the ceiling is recorded as ``skipped_oversize``, so a
  hostile upload cannot turn the local API into a hang;
* an unexpected failure is recorded as ``failed`` with the exception type and
  message, so an item never sits in a plausible-looking state;
* a majority of scopes falling back is surfaced as a coverage warning, because
  the engine reporting "no match" is legitimate while the product staying quiet
  about it is not;
* the document's text never enters the record, which is what gets persisted.
"""

import hashlib
import json
from unittest.mock import patch

from interface import analysis

#: Long enough to clear the warning threshold, and deliberately free of any
#: word the lexicon could match, so a fallback is the only possible outcome.
NEUTRAL_TEXT = "plinth quartz zebra " * 40

MARKER = "ZQXMARKER42"


def _scope_keys(record: dict) -> set:
    return set(record.keys())


def test_source_identity_is_hashed_and_echoed():
    data = b"a case brief"
    record = analysis.analyse(data, "brief.txt", "text/plain")

    assert record["source"] == {
        "sha256": hashlib.sha256(data).hexdigest(),
        "bytes": len(data),
        "mediaType": "text/plain",
        "filename": "brief.txt",
    }


def test_processed_record_carries_scopes_and_a_projection():
    record = analysis.analyse(NEUTRAL_TEXT.encode(), "brief.txt", "text/plain")

    assert record["status"] == analysis.STATUS_PROCESSED
    assert record["extract"]["status"] == analysis.EXTRACT_EXTRACTED
    assert record["extract"]["sha256"] == hashlib.sha256(NEUTRAL_TEXT.encode()).hexdigest()
    assert record["projection"]["engineVersion"], "the engine version must be recorded"

    scopes = record["scopes"]
    assert scopes, "a non-empty document must produce at least one scope"
    assert _scope_keys(scopes[0]) == {
        "scope",
        "chars",
        "conceptId",
        "classification",
        "admissible",
        "matchedConcepts",
        "fallbackReason",
    }


def test_coverage_counts_agree_with_the_scope_records():
    record = analysis.analyse(NEUTRAL_TEXT.encode(), "brief.txt", "text/plain")
    coverage = record["coverage"]
    scopes = record["scopes"]

    assert coverage["scopesTotal"] == len(scopes)
    matched = sum(1 for scope in scopes if scope["conceptId"] is not None)
    fallback = sum(
        1 for scope in scopes if scope["classification"] == analysis.FALLBACK
    )
    assert coverage["scopesMatched"] == matched
    assert coverage["scopesFallback"] == fallback
    assert coverage["ratio"] == matched / len(scopes)


def test_uncovered_language_is_surfaced_as_a_warning():
    record = analysis.analyse(NEUTRAL_TEXT.encode(), "brief.txt", "text/plain")
    warning = record["coverage"]["warning"]

    assert warning, "a document the lexicon cannot cover must not pass silently"
    assert "matched no concept" in warning
    assert str(record["coverage"]["scopesTotal"]) in warning


def test_short_documents_do_not_raise_a_coverage_warning():
    """Below the threshold, "no concepts found" is unremarkable."""
    record = analysis.analyse(b"zebra plinth", "note.txt", "text/plain")

    assert record["coverage"]["warning"] is None


def test_oversize_artifact_is_skipped_rather_than_attempted():
    data = b"x" * 10
    record = analysis.analyse(data, "big.bin", "application/octet-stream", max_bytes=4)

    assert record["status"] == analysis.STATUS_SKIPPED_OVERSIZE
    assert "10 bytes" in record["reason"]
    assert "4 byte" in record["reason"]
    assert record["scopes"] == []
    assert record["extract"]["chars"] == 0


def test_unsupported_artifact_is_recorded_with_the_reason_that_names_it():
    record = analysis.analyse(b"PK\x03\x04 binary", "manifest.docx", "")

    assert record["status"] == analysis.STATUS_UNSUPPORTED
    assert "docx" in record["reason"].lower()
    assert record["scopes"] == []


def test_artifact_without_text_is_recorded_as_empty():
    record = analysis.analyse(b"   \n  ", "blank.txt", "text/plain")

    assert record["status"] == analysis.STATUS_EMPTY
    assert record["scopes"] == []


def test_unexpected_failure_is_recorded_as_failed_not_swallowed():
    with patch.object(
        analysis.submission,
        "extract_text",
        side_effect=RuntimeError("reader exploded"),
    ):
        record = analysis.analyse(b"anything", "brief.txt", "text/plain")

    assert record["status"] == analysis.STATUS_FAILED
    assert "RuntimeError" in record["reason"]
    assert "reader exploded" in record["reason"]
    assert "RuntimeError" in record["extract"]["error"]


def test_segmentation_failure_is_recorded_as_failed():
    with patch.object(
        analysis.scopes,
        "split_scopes",
        side_effect=ValueError("no cue found"),
    ):
        record = analysis.analyse(b"a case brief", "brief.txt", "text/plain")

    assert record["status"] == analysis.STATUS_FAILED
    assert "ValueError" in record["reason"]


def test_document_text_never_enters_the_record():
    """The record is what gets persisted, exported and signed."""
    text = f"The brief says {MARKER} and nothing else of note."
    record = analysis.analyse(text.encode(), "brief.txt", "text/plain")

    assert record["status"] == analysis.STATUS_PROCESSED
    assert MARKER not in json.dumps(record)


def test_extract_or_empty_returns_empty_instead_of_raising():
    assert analysis.extract_or_empty(b"PK\x03\x04 binary", "manifest.docx") == ""
    assert analysis.extract_or_empty(b"plain text", "note.txt") == "plain text"


def test_extract_or_empty_tolerates_an_unexpected_extractor_failure():
    """The bytes and their custody row are already committed by this point.

    `analyse` records the same failure on the same artifact, so raising here
    would convert a recorded outcome into a 500 after the upload was accepted.
    """
    with patch.object(
        analysis.submission,
        "extract_text",
        side_effect=RuntimeError("reader exploded"),
    ):
        assert analysis.extract_or_empty(b"anything", "brief.txt") == ""


def test_extract_raises_the_dispatchers_refusal():
    """The API needs the text itself; the refusal is not hidden from it."""
    try:
        analysis.extract(b"PK\x03\x04 binary", "manifest.docx")
    except analysis.submission.UnsupportedSubmission as exc:
        assert "docx" in str(exc).lower()
    else:
        raise AssertionError("extract must raise on an artifact it cannot read")
