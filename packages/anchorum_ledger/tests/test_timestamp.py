"""Tests for the timestamp module."""

import pytest
from pathlib import Path
from anchorum_ledger.timestamp import TimestampError, stamp_bytes, verify


def test_timestamp_error_on_missing_config():
    """Missing TSA config raises TimestampError."""
    with pytest.raises(TimestampError):
        stamp_bytes(b"test data", Path("/tmp/test_ts"))


class MockFile:
    """Mock file system for testing."""
    
    def __init__(self):
        self.files = {}
    
    def write(self, path, content):
        self.files[path] = content
    
    def read(self, path):
        return self.files.get(path)


def test_verify_returns_boolean():
    """Verification returns a boolean."""
    # This is a placeholder test - actual verification requires OpenSSL and certs
    result = verify(Path("/dev/null"), Path("/dev/null"))
    assert isinstance(result, bool)
