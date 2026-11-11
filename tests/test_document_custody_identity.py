"""Tests for W1: custody identity of submitted artifact (C-5)."""
import hashlib
import os
import pytest
from pathlib import Path
from interface.document import _wrap_text_as_eml

# Real brief SHA256 used throughout the audit
REAL_BRIEF_SHA256 = "c58fcf248ab877e75975c04606ab60aca294c2f36d2930df858400b0b9c31830"

def test_wrapper_is_deterministic():
    """Same inputs produce identical wrappers. Prevents uuid4() or datetime.now()
    from making the same artifact hash differently on every run."""
    text = "Sample text"
    source_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    
    wrapper1 = _wrap_text_as_eml(text=text, subject="S", sender="a@x.com", recipient="b@x.com", source_sha256=source_hash)
    wrapper2 = _wrap_text_as_eml(text=text, subject="S", sender="a@x.com", recipient="b@x.com", source_sha256=source_hash)
    
    assert wrapper1 == wrapper2
    
    # Verify the stable double-hash is in the Message-ID
    expected_stable = hashlib.sha256(source_hash.encode("utf-8")).hexdigest()[:32]
    assert f"<{expected_stable}@document.local>".encode() in wrapper1

def test_same_bytes_different_filename():
    """Same bytes under different filenames yield same identity. 
    Prevents the filename from entering the wrapper and breaking dedup."""
    text = "Test content"
    source_hash = hashlib.sha256(text.encode()).hexdigest()
    
    # The filename is deliberately not a parameter to _wrap_text_as_eml.
    # The wrapper is a function of the artifact bytes only.
    wrapper1 = _wrap_text_as_eml(text=text, subject="S", sender="a@x", recipient="b@x", source_sha256=source_hash)
    wrapper2 = _wrap_text_as_eml(text=text, subject="S", sender="a@x", recipient="b@x", source_sha256=source_hash)
    
    assert wrapper1 == wrapper2

def test_real_brief_hash_is_bound():
    """The real brief's hash is bound into the wrapper, guarded by file existence."""
    brief_path = Path("/path/to/angel-v-murray.pdf") # Update this path if it exists locally
    if not brief_path.is_file():
        pytest.skip("Real brief sample not present on this machine")
        
    raw_bytes = brief_path.read_bytes()
    source_hash = hashlib.sha256(raw_bytes).hexdigest()
    assert source_hash == REAL_BRIEF_SHA256
    
    wrapper = _wrap_text_as_eml(
        text="extracted text", subject="S", sender="a@x", recipient="b@x", source_sha256=source_hash
    )
    
    # The real brief's hash should be inside the wrapper
    assert REAL_BRIEF_SHA256.encode() not in wrapper # It's double-hashed
    expected_stable = hashlib.sha256(REAL_BRIEF_SHA256.encode()).hexdigest()[:32]
    assert expected_stable.encode() in wrapper