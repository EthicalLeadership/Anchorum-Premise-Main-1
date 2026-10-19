import pytest
from interface.classifier import classify_text, DOCUMENT_TYPES
from interface.analysis import analyse

def test_medical_note_exact():
    assert classify_text("Ordonnance du médecin traitant") == "medical_note"
    # Accent folding: médecin -> medecin
    assert classify_text("Ordonnance du medecin traitant") == "medical_note"

def test_payroll_exact():
    assert classify_text("Payroll summary. Gross pay: 5000. Deductions: 1200.") == "payroll"

def test_insurer_letter_exact():
    assert classify_text("Your insurance policy claim is approved.") == "insurer_letter"

def test_official_report_exact():
    assert classify_text("Official government report on the incident.") == "official_report"

def test_correspondence_exact():
    assert classify_text("Dear Sir, Sincerely yours.") == "correspondence"

def test_unknown_fallthrough():
    assert classify_text("Lorem ipsum dolor sit amet") == "unknown"
    assert classify_text("") == "unknown"
    assert classify_text("   \n  ") == "unknown"
    assert classify_text("XYZ random noise 123") == "unknown"

def test_determinism():
    t1 = classify_text("Payroll summary")
    t2 = classify_text("Payroll summary")
    assert t1 == t2
    for dt in DOCUMENT_TYPES:
        assert isinstance(dt, str)

def test_ambiguity_tie_break():
    # 1 payroll ("payroll"), 1 insurer ("insurance") -> alphabetical -> insurer_letter
    assert classify_text("payroll and insurance") == "insurer_letter"

def test_score_beats_alphabetical():
    # 2 payroll ("payroll", "salary"), 1 insurer ("insurance") -> payroll
    assert classify_text("payroll and salary and insurance") == "payroll"

def test_analyse_integration():
    res = analyse(b"Payroll summary. Gross pay: 5000.", "payroll.txt")
    assert res["documentType"] == "payroll"

    res = analyse(b"", "empty.txt")
    assert res["documentType"] == "unknown"

    res = analyse(b"X" * (25 * 1024 * 1024 + 1), "big.txt")
    assert res["documentType"] == "unknown"
# ---------------------------------------------------------------------------
# Metadata extraction.
#
# These were absent, and the two regex defects they now pin were live: a bare
# re.IGNORECASE made `[A-Z]` match lowercase (so "Ministry of Health" captured
# "of Health"), and the issuer pattern stopped at the first capitalised word
# (so "Hopital General de Montreal" came back as "General"). The issuer and the
# author are rendered in the timeline route and used by author search, so both
# were user-visible.
# ---------------------------------------------------------------------------

from interface.classifier import extract_metadata


def test_metadata_iso_date():
    assert extract_metadata("Rapport du 2026-03-12.")["date"] == "2026-03-12"


def test_metadata_numeric_date():
    assert extract_metadata("Fait le 12/03/2026 a Quebec.")["date"] == "2026-03-12"


def test_metadata_two_digit_year():
    assert extract_metadata("Fait le 12/03/26.")["date"] == "2026-03-12"


def test_metadata_text_date_french():
    assert extract_metadata("Quebec, le 12 mars 2026.")["date"] == "2026-03-12"


def test_metadata_text_date_english():
    assert extract_metadata("Issued 3 March 2026.")["date"] == "2026-03-03"


def test_metadata_author_french_title():
    assert extract_metadata("Docteur Marie Gagnon, medecin.")["author"] == "Marie Gagnon"


def test_metadata_author_short_title():
    assert extract_metadata("Dr Jean Tremblay a examine le patient.")["author"] == "Jean Tremblay"


def test_metadata_author_all_caps_survives_ocr():
    assert extract_metadata("Dr JEAN TREMBLAY.")["author"] == "JEAN TREMBLAY"


def test_metadata_issuer_is_not_truncated():
    # The regression: this used to come back as "General".
    issuer = extract_metadata("Hopital General de Montreal, cardiologie.")["issuer"]
    assert issuer == "Hopital General de Montreal"


def test_metadata_issuer_keeps_lowercase_connectors():
    issuer = extract_metadata("Cour Superieure du Quebec.")["issuer"]
    assert issuer == "Cour Superieure du Quebec"


def test_metadata_issuer_does_not_capture_lowercase_prose():
    # The regression: a bare IGNORECASE made this capture "of Health".
    issuer = extract_metadata("Issued by the Ministry of Health.")["issuer"]
    assert issuer == "Ministry of Health"
    assert not issuer.startswith("of ")


def test_metadata_strips_sentence_punctuation():
    issuer = extract_metadata("Clinique Sante du Nord.")["issuer"]
    author = extract_metadata("Dr Jean Tremblay.")["author"]
    assert issuer is not None and not issuer.endswith(".")
    assert author is not None and not author.endswith(".")


def test_metadata_absent_returns_none():
    assert extract_metadata("Lorem ipsum dolor sit amet.") == {
        "date": None,
        "author": None,
        "issuer": None,
    }
    assert extract_metadata("") == {"date": None, "author": None, "issuer": None}
    assert extract_metadata("   \n ") == {"date": None, "author": None, "issuer": None}


def test_metadata_is_deterministic():
    text = "Quebec, le 12 mars 2026. Hopital General de Montreal. Dr Jean Tremblay."
    results = {tuple(sorted(extract_metadata(text).items())) for _ in range(50)}
    assert len(results) == 1


def test_metadata_survives_analyse():
    record = analyse(
        "Quebec, le 12 mars 2026. Clinique Sante du Nord. Dr Jean Tremblay.".encode(),
        "note.txt",
    )
    metadata = record["metadata"]
    assert metadata["date"] == "2026-03-12"
    assert metadata["author"] == "Jean Tremblay"
    assert metadata["issuer"].startswith("Clinique Sante du Nord")
