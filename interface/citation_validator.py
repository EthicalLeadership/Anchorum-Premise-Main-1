"""Citation validator for Anchorum-Prem LLM responses.

This module implements validation of citations in the format:
[source: file, page X, lines Y-Z]

As mandated by prompts/v1/system.txt rule 2, each factual claim must be
accompanied by an auditable citation. This validator parses and validates
that format before it reaches the user.

The contract is simple but non-negotiable in legal contexts:
- Every `[source: ...]` token must match the pattern exactly
- The file name must be a valid path component (no .., no null bytes)
- Page and line numbers must be positive integers
- Lines Y-Z must have Y <= Z

Invalid citations are logged as warnings (quality issues), not blockers.
This preserves the user experience while maintaining auditability.
"""

import re
from typing import List, Dict, Any, Optional
import logging

logger = logging.getLogger(__name__)


# Regex pattern for citation format: [source: file, page X, lines Y-Z]
CITATION_PATTERN = re.compile(
    r'\[source:\s*([^,\s]+),\s*page\s*(\d+),\s*lines\s*(\d+)-(\d+)\]'
)


def parse_citations(text: str) -> List[Dict[str, Any]]:
    """Parse all citations from response text.

    Args:
        text: The LLM response text to parse for citations.

    Returns:
        List of dicts with keys: file, page, lines_start, lines_end.
        Empty list if no citations found.
    """
    citations = []
    for match in CITATION_PATTERN.finditer(text):
        try:
            file_path = match.group(1).strip()
            page = int(match.group(2))
            lines_start = int(match.group(3))
            lines_end = int(match.group(4))

            citations.append({
                "file": file_path,
                "page": page,
                "lines_start": lines_start,
                "lines_end": lines_end,
            })
        except (ValueError, IndexError) as e:
            # Malformed citation - will be caught by validate_citation
            logger.warning("Malformed citation found: %s", match.group(0))

    return citations


def validate_citation(citation: Dict[str, Any]) -> bool:
    """Validate a single citation against the system.txt contract.

    Args:
        citation: Dict with keys file, page, lines_start, lines_end.

    Returns:
        True if valid, False otherwise.
    """
    try:
        # Check that all required fields exist and are non-empty
        if not citation.get("file"):
            return False
        if not citation.get("page") or citation["page"] <= 0:
            return False
        if not citation.get("lines_start") or not citation.get("lines_end"):
            return False

        # Check line ordering
        if citation["lines_start"] > citation["lines_end"]:
            return False

        # Validate file path (no .., no null bytes, reasonable length)
        file_path = citation["file"]
        if ".." in file_path:
            return False
        if "\x00" in file_path:
            return False
        if len(file_path) > 256:
            return False

        # Page and lines must be reasonable bounds
        if citation["page"] < 1 or citation["page"] > 10000:
            return False
        if citation["lines_start"] < 1 or citation["lines_end"] > 100000:
            return False

        return True
    except Exception as e:
        logger.error("Citation validation error: %s", e)
        return False


def validate_all_citations(text: str) -> Dict[str, Any]:
    """Validate all citations in response text.

    Args:
        text: The LLM response text containing citations.

    Returns:
        Dict with keys:
        - valid: bool, True if all citations are valid
        - invalid_citations: list of dicts with citation and error reason
        - warning_count: int, number of warnings generated
        - parsed_citations: list of all parsed citations (valid and invalid)
    """
    result = {
        "valid": True,
        "invalid_citations": [],
        "warning_count": 0,
        "parsed_citations": [],
    }

    try:
        citations = parse_citations(text)
        result["parsed_citations"] = citations

        for citation in citations:
            if not validate_citation(citation):
                result["valid"] = False
                error_reason = _get_error_reason(citation)
                result["invalid_citations"].append({
                    "citation": citation,
                    "error": error_reason,
                })
                result["warning_count"] += 1

        return result
    except Exception as e:
        logger.error("Citation validation failed with exception: %s", e)
        result["valid"] = False
        result["invalid_citations"].append({
            "citation": {"file": "<unknown>", "page": 0, "lines_start": 0, "lines_end": 0},
            "error": f"Validation exception: {e}",
        })
        result["warning_count"] += 1

    return result


def _get_error_reason(citation: Dict[str, Any]) -> str:
    """Get human-readable error reason for invalid citation.

    Args:
        citation: The invalid citation dict.

    Returns:
        Error message string.
    """
    try:
        file_path = citation.get("file", "<unknown>")
        page = citation.get("page", 0)
        lines_start = citation.get("lines_start", 0)
        lines_end = citation.get("lines_end", 0)

        if not file_path:
            return "Missing or empty file path"
        if ".." in file_path:
            return f"File path contains '..': {file_path}"
        if "\x00" in file_path:
            return "File path contains null byte"
        if len(file_path) > 256:
            return f"File path too long ({len(file_path)} chars)"
        if page < 1 or page > 10000:
            return f"Page number out of bounds: {page}"
        if lines_start < 1 or lines_end > 100000:
            return "Line numbers out of reasonable bounds"
        if lines_start > lines_end:
            return f"Lines start ({lines_start}) > end ({lines_end})"

        return "Unknown validation failure"
    except Exception as e:
        return f"Error determining error reason: {e}"


def enrich_citation_with_context(
    citation: Dict[str, Any],
    file_content: Optional[str] = None,
) -> Dict[str, Any]:
    """Enrich a citation with context from the referenced file.

    This is optional functionality for advanced use cases where you want
    to verify that the cited content actually exists in the file.

    Args:
        citation: The citation dict.
        file_content: Optional content of the referenced file.

    Returns:
        Citation dict with additional context fields if file_content provided.
    """
    enriched = citation.copy()

    if not file_content:
        return enriched

    try:
        lines = file_content.splitlines()
        page_lines = lines[citation["page"] - 1 : citation["page"]]
        cited_lines = lines[
            citation["lines_start"] - 1 : citation["lines_end"]
        ]

        enriched.update(
            {
                "context_available": True,
                "cited_content_preview": "\n".join(cited_lines[:50]),
                "total_cited_lines": len(cited_lines),
            }
        )
    except Exception as e:
        logger.warning("Failed to enrich citation with context: %s", e)
        enriched["context_available"] = False

    return enriched


def format_validation_report(validation_result: Dict[str, Any]) -> str:
    """Format a human-readable validation report.

    Args:
        validation_result: Result from validate_all_citations().

    Returns:
        Formatted string report.
    """
    lines = [
        "=" * 60,
        "Citation Validation Report",
        "=" * 60,
        f"Overall Status: {'VALID' if validation_result['valid'] else 'INVALID'}",
        f"Warning Count: {validation_result['warning_count']}",
        "",
    ]

    if validation_result["parsed_citations"]:
        lines.append(f"Parsed Citations: {len(validation_result['parsed_citations'])}")
        for i, citation in enumerate(validation_result["parsed_citations"], 1):
            status = "✓" if validate_citation(citation) else "✗"
            lines.append(
                f"  [{i}] {status} {citation['file']} (page {citation['page']}, lines {citation['lines_start']}-{citation['lines_end']})"
            )

    if validation_result["invalid_citations"]:
        lines.append("")
        lines.append("Invalid Citations:")
        for item in validation_result["invalid_citations"]:
            citation = item.get("citation", {})
            error = item.get("error", "Unknown error")
            lines.append(f"  ✗ {citation.get('file', 'unknown')}")
            lines.append(f"    Error: {error}")

    return "\n".join(lines)


# Export public API
__all__ = [
    "CITATION_PATTERN",
    "parse_citations",
    "validate_citation",
    "validate_all_citations",
    "_get_error_reason",
    "enrich_citation_with_context",
    "format_validation_report",
]
