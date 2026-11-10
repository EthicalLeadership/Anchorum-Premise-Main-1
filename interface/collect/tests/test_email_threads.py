import pytest
from email.message import Message
from unittest.mock import MagicMock
from interface.collect.email_threads import guard_headers, walk_message, ParsingAbort

def test_header_count_guard_raises():
    msg = Message()
    msg._headers = [("Received", "test")] * 201
    with pytest.raises(ParsingAbort) as exc:
        guard_headers(msg)
    assert exc.value.reason == "HEADER_COUNT"

def test_header_size_guard_raises():
    msg = Message()
    msg._headers = [("Subject", "A" * 70000)]
    with pytest.raises(ParsingAbort) as exc:
        guard_headers(msg)
    assert exc.value.reason == "HEADER_SIZE"

def test_encoded_words_guard_raises():
    msg = Message()
    val = " ".join(["=?utf-8?q?test?="] * 51)
    msg._headers = [("Subject", val)]
    with pytest.raises(ParsingAbort) as exc:
        guard_headers(msg)
    assert exc.value.reason == "ENCODED_WORDS"

def test_depth_guard():
    current_msg = MagicMock()
    current_msg.as_bytes.return_value = b"test"
    current_msg.is_multipart.return_value = True
    
    for _ in range(11):
        part = MagicMock()
        part.get_content_type.return_value = "message/rfc822"
        part.get_payload.return_value = [current_msg]
        
        next_msg = MagicMock()
        next_msg.as_bytes.return_value = b"test"
        next_msg.is_multipart.return_value = True
        next_msg.get_payload.return_value = [part]
        
        current_msg = next_msg

    with pytest.raises(ParsingAbort) as exc:
        walk_message(current_msg)
    assert exc.value.reason == "DEPTH_EXCEEDED"

def test_size_guard():
    msg = MagicMock()
    msg.as_bytes.return_value = b"A" * 100
    msg.is_multipart.return_value = False
    
    budget = {"remaining": 10} 
    with pytest.raises(ParsingAbort) as exc:
        walk_message(msg, budget=budget)
    assert exc.value.reason == "SIZE_EXCEEDED"
