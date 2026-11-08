"""Tests for citation validation module.

These tests verify that the citation validator correctly parses and validates
citations in the format mandated by prompts/v1/system.txt:
[source: file, page X, lines Y-Z]
"""

import pytest
from interface.citation_validator import (
    parse_citations,
    validate_citation,
    validate_all_citations,
    _get_error_reason,
    enrich_citation_with_context,
    format_validation_report,
)


class TestParseCitations:
    """Test citation parsing from response text."""

    def test_parse_valid_citation(self):
        """Parse a single valid citation."""
        text = "This is a factual claim [source: dossier.pdf, page 1, lines 10-25]."
        citations = parse_citations(text)
        
        assert len(citations) == 1
        assert citations[0]["file"] == "dossier.pdf"
        assert citations[0]["page"] == 1
        assert citations[0]["lines_start"] == 10
        assert citations[0]["lines_end"] == 25

    def test_parse_multiple_citations(self):
        """Parse multiple citations in one text."""
        text = (
            "First claim [source: file1.txt, page 1, lines 1-10]. "
            "Second claim [source: file2.txt, page 2, lines 20-30]."
        )
        citations = parse_citations(text)
        
        assert len(citations) == 2
        assert citations[0]["file"] == "file1.txt"
        assert citations[1]["file"] == "file2.txt"

    def test_parse_no_citations(self):
        """Parse text with no citations."""
        text = "This text has no citations at all."
        citations = parse_citations(text)
        
        assert citations == []

    def test_parse_malformed_citation(self):
        """Parse malformed citation - should not match pattern."""
        text = "Bad citation [source: file.txt, page abc, lines 1-2]."
        citations = parse_citations(text)
        
        # The regex requires digits for page and lines, so this won't match
        assert len(citations) == 0

    def test_parse_partial_citation(self):
        """Parse citation with partial data."""
        text = "Claim [source: file.pdf, page 1, lines 1-2]."
        citations = parse_citations(text)
        
        assert len(citations) == 1


class TestValidateCitation:
    """Test individual citation validation."""

    def test_valid_citation(self):
        """Validate a properly formed citation."""
        citation = {
            "file": "dossier.pdf",
            "page": 1,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is True

    def test_missing_file(self):
        """Reject citation with missing file."""
        citation = {
            "file": "",
            "page": 1,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is False

    def test_invalid_page(self):
        """Reject citation with invalid page number."""
        citation = {
            "file": "dossier.pdf",
            "page": 0,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is False

    def test_invalid_page_too_high(self):
        """Reject citation with page number out of bounds."""
        citation = {
            "file": "dossier.pdf",
            "page": 10001,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is False

    def test_invalid_line_order(self):
        """Reject citation where start > end."""
        citation = {
            "file": "dossier.pdf",
            "page": 1,
            "lines_start": 50,
            "lines_end": 10,
        }
        assert validate_citation(citation) is False

    def test_file_with_dotdot(self):
        """Reject citation with .. in file path."""
        citation = {
            "file": "../dossier.pdf",
            "page": 1,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is False

    def test_file_with_null_byte(self):
        """Reject citation with null byte in file path."""
        citation = {
            "file": "dossier\x00.pdf",
            "page": 1,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is False

    def test_file_too_long(self):
        """Reject citation with file path too long."""
        citation = {
            "file": "a" * 300 + ".pdf",
            "page": 1,
            "lines_start": 10,
            "lines_end": 25,
        }
        assert validate_citation(citation) is False


class TestGetErrorReason:
    """Test error reason generation."""

    def test_missing_file_error(self):
        """Get error for missing file."""
        citation = {"file": "", "page": 1, "lines_start": 10, "lines_end": 25}
        error = _get_error_reason(citation)
        assert "Missing or empty file path" in error

    def test_dotdot_error(self):
        """Get error for .. in file path."""
        citation = {"file": "../dossier.pdf", "page": 1, "lines_start": 10, "lines_end": 25}
        error = _get_error_reason(citation)
        assert ".." in error

    def test_line_order_error(self):
        """Get error for invalid line order."""
        citation = {"file": "dossier.pdf", "page": 1, "lines_start": 50, "lines_end": 10}
        error = _get_error_reason(citation)
        assert "Lines start" in error


class TestValidateAllCitations:
    """Test batch validation of all citations."""

    def test_all_valid(self):
        """Validate text with only valid citations."""
        text = "Claim [source: file.pdf, page 1, lines 1-10]."
        result = validate_all_citations(text)
        
        assert result["valid"] is True
        assert result["warning_count"] == 0
        assert len(result["parsed_citations"]) == 1

    def test_some_invalid(self):
        """Validate text with some invalid citations."""
        text = (
            "Valid [source: file.pdf, page 1, lines 1-10]. "
            "Invalid [source: ../bad.pdf, page 1, lines 1-10]."
        )
        result = validate_all_citations(text)
        
        assert result["valid"] is False
        assert len(result["invalid_citations"]) == 1
        assert result["warning_count"] >= 1

    def test_no_citations(self):
        """Validate text with no citations."""
        text = "This text has no citations."
        result = validate_all_citations(text)
        
        assert result["valid"] is True
        assert result["parsed_citations"] == []


class TestEnrichCitationWithContext:
    """Test citation enrichment with file context."""

    def test_enrich_with_valid_content(self):
        """Enrich citation when file content is provided."""
        citation = {
            "file": "test.txt",
            "page": 1,
            "lines_start": 10,
            "lines_end": 20,
        }
        content = "\n".join([f"Line {i}" for i in range(1, 30)])
        
        enriched = enrich_citation_with_context(citation, content)
        
        assert enriched["context_available"] is True
        assert "cited_content_preview" in enriched

    def test_enrich_without_content(self):
        """Enrich citation when no file content provided."""
        citation = {"file": "test.txt", "page": 1, "lines_start": 10, "lines_end": 20}
        
        enriched = enrich_citation_with_context(citation)
        
        # When no content is provided, context_available should not be set
        assert "context_available" not in enriched


class TestFormatValidationReport:
    """Test validation report formatting."""

    def test_report_all_valid(self):
        """Format report for all valid citations."""
        result = {
            "valid": True,
            "invalid_citations": [],
            "warning_count": 0,
            "parsed_citations": [
                {"file": "file.pdf", "page": 1, "lines_start": 10, "lines_end": 20},
            ],
        }
        report = format_validation_report(result)
        
        assert "VALID" in report
        assert "file.pdf" in report

    def test_report_with_invalid(self):
        """Format report with invalid citations."""
        result = {
            "valid": False,
            "invalid_citations": [
                {"citation": {"file": "../bad.pdf"}, "error": "File path contains '..'"},
            ],
            "warning_count": 1,
            "parsed_citations": [],
        }
        report = format_validation_report(result)
        
        assert "INVALID" in report
        assert "bad.pdf" in report


class TestIntegrationWithLLMClassifier:
    """Test that citation validation integrates correctly with LLM classifier."""

    def test_llm_classify_returns_citation_report(self):
        """Verify llm_classify includes citation validation report."""
        from interface.llm_classifier import llm_classify
        
        result = llm_classify("medical note about patient symptoms")
        
        # The result should have the citation validation report field
        assert "_citation_validation_report" in result

    def test_llm_summarize_returns_citation_report(self):
        """Verify llm_summarize includes citation validation report."""
        from interface.llm_classifier import llm_summarize
        
        result = llm_summarize("Patient has fever and cough")
        
        # The result should have the citation validation report field
        assert "_citation_validation_report" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
