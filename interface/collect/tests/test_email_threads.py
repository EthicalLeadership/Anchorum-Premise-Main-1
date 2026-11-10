import pytest
from email.message import Message
from interface.collect.email_threads import guard_headers, ParsingAbort

def test_header_count_guard_raises():
    msg = Message()
    for i in range(201):
        msg[f"X-Test-{i}"] = "value"
    with pytest.raises(ParsingAbort, match="header count"):
        guard_headers(msg)

def test_header_size_guard_raises():
    msg = Message()
    msg["X-Large"] = "A" * (64 * 1024 + 1)
    with pytest.raises(ParsingAbort, match="exceeds"):
        guard_headers(msg)

def test_encoded_words_guard_raises():
    msg = Message()
    msg["Subject"] = "=?utf-8?B?VEVTVA==?= " * 51
    with pytest.raises(ParsingAbort, match="too many encoded-words"):
        guard_headers(msg)

def test_normal_headers_pass():
    msg = Message()
    msg["Subject"] = "Hello"
    msg["From"] = "alice@example.com"
    guard_headers(msg) # Should NOT raise
