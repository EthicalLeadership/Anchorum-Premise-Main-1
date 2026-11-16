"""Tests for the ts_export module."""

import pytest
from pathlib import Path
from anchorum_ledger.tsa_export import (
    collect_tsa_artifacts,
)


def test_collect_tsa_artifacts_returns_dict():
    """Collecting TSA artifacts returns a dict mapping arcnames to paths."""
    # This is a placeholder - actual collection requires specific file structure
    result = collect_tsa_artifacts("/fake/path", [])
    assert isinstance(result, dict)
