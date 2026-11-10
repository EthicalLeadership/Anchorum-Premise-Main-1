import pytest
from email.message import Message, EmailMessage
from unittest.mock import MagicMock
from interface.collect.email_threads import (
    guard_headers, walk_message, extract_headers, normalize_body, extract_quoted, build_threads, ParsingAbort
)

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
    with pytest.raises(ParsingAbort) as exc:
        walk_message(msg, budget={"remaining": 10})
    assert exc.value.reason == "SIZE_EXCEEDED"

def test_extract_headers_trust_classes():
    msg = Message()
    msg["From"] = "alice@example.com"
    msg["Received"] = "from mail.example.com"
    msg["Authentication-Results"] = "dkim=pass"
    msg["X-Custom-Header"] = "random"
    extracted = extract_headers(msg)
    header_map = {h["name"]: h["trust"] for h in extracted}
    assert header_map["From"] == "SENDER_CLAIM"
    assert header_map["Received"] == "RELAY_OBSERVATION"
    assert header_map["Authentication-Results"] == "PERIMETER_VERDICT"
    assert header_map["X-Custom-Header"] == "UNKNOWN"

def test_normalize_body_quoted_printable():
    msg = Message()
    msg["Content-Transfer-Encoding"] = "quoted-printable"
    msg.set_payload("=3E This is a quote\r\n=3E More text")
    normalized = normalize_body(msg)
    assert "> This is a quote" in normalized

def test_normalize_body_base64():
    msg = Message()
    msg["Content-Transfer-Encoding"] = "base64"
    msg.set_payload("SGVsbG8gV29ybGQ=") 
    normalized = normalize_body(msg)
    assert normalized == "Hello World"

def test_extract_quoted_outlook():
    body = """
    Yes, I agree.
    
    From: Alice <alice@example.com>
    Sent: Monday, October 23, 2023 10:00 AM
    To: Bob <bob@example.com>
    Subject: Re: The Contract
    
    Are we still on for the meeting?
    """
    quotes = extract_quoted(body)
    assert len(quotes) == 1
    assert quotes[0]["derivation"] == "QUOTED"
    assert quotes[0]["message_id"] is None
    assert "alice@example.com" in quotes[0]["from_raw"]
    assert "The Contract" in quotes[0]["subject"]

def test_extract_quoted_gmail():
    body = """
    I will bring the papers.
    
    On Mon, Oct 23, 2023 at 10:00 AM Alice <alice@example.com> wrote:
    > Are we still on for the meeting?
    """
    quotes = extract_quoted(body)
    assert len(quotes) == 1
    assert quotes[0]["derivation"] == "QUOTED"
    assert quotes[0]["message_id"] is None
    assert "Alice" in quotes[0]["from_raw"]
    assert "Oct 23, 2023" in quotes[0]["date_raw"]

def test_build_threads_empty():
    assert build_threads([]) == {}

def test_build_threads_single():
    msgs = [{"message_id": "A"}]
    assert build_threads(msgs) == {"A": "A"}

def test_build_threads_reply_chain():
    msgs = [
        {"message_id": "C", "in_reply_to": "B", "references": ["A", "B"]},
        {"message_id": "A"},
        {"message_id": "B", "in_reply_to": "A", "references": ["A"]}
    ]
    result = build_threads(msgs)
    assert result["A"] == "A"
    assert result["B"] == "A"
    assert result["C"] == "A"

def test_build_threads_missing_root():
    msgs = [{"message_id": "B", "in_reply_to": "A", "references": ["A"]}]
    result = build_threads(msgs)
    assert result["B"] == "A"

def test_build_threads_cycle():
    msgs = [{"message_id": "A", "in_reply_to": "B"}, {"message_id": "B", "in_reply_to": "A"}]
    result = build_threads(msgs)
    assert result["A"] == "A"
    assert result["B"] == "A"

def test_build_threads_dos_bound():
    with pytest.raises(ParsingAbort) as exc:
        build_threads([{"message_id": "A", "references": ["B"] * 1001}])
    assert exc.value.reason == "REFERENCES_CHAIN"
