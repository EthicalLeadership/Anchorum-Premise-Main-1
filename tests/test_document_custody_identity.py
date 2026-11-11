import hashlib
import os
import pytest
from interface.document import _wrap_text_as_eml

def test_wrapper_is_deterministic():
    os.environ["ANCHORUM_ENV"] = "local"
    
    text = "Sample text for the deterministic wrapper."
    
    # 1. The artifact hash
    artifact_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
    
    # 2. The expected stable id (per the plan: sha256 of the source_sha256)
    expected_stable = hashlib.sha256(artifact_hash.encode("utf-8")).hexdigest()[:32]
    
    wrapper1 = _wrap_text_as_eml(
        text=text, 
        subject="Test", 
        sender="test@x.com", 
        recipient="user@x.com",
        source_sha256=artifact_hash
    )
    wrapper2 = _wrap_text_as_eml(
        text=text, 
        subject="Test", 
        sender="test@x.com", 
        recipient="user@x.com",
        source_sha256=artifact_hash
    )

    # Determinism check
    assert wrapper1 == wrapper2, "Wrapper is not deterministic! UUID or Date is still leaking."
    
    hash1 = hashlib.sha256(wrapper1.encode() if isinstance(wrapper1, str) else wrapper1).hexdigest()
    hash2 = hashlib.sha256(wrapper2.encode() if isinstance(wrapper2, str) else wrapper2).hexdigest()
    assert hash1 == hash2, "Byte-level hashes do not match. Deduplication will fail."
    
    # The correct check: verify the double-hash is in the Message-ID
    assert expected_stable in str(wrapper1), "The stable double-hash was not injected into the Message-ID header."
    print(f"\n✅ Deterministic Message-ID: {expected_stable}")
