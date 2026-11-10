import pytest
from email.message import EmailMessage, Message
from interface.collect.email_threads import (
    guard_headers, walk_message, extract_headers, normalize_body, extract_quoted, build_threads, ParsingAbort
)

# --- LAYER 1: GUARDS ---
def test_header_count_guard_raises():
    msg = EmailMessage()
    for i in range(201): msg[f"X-Test-{i}"] = "val"
    with pytest.raises(ParsingAbort, match="HEADER_COUNT"):
        guard_headers(msg)

def test_header_size_guard_raises():
    msg = EmailMessage()
    msg["Subject"] = "A" * (64 * 1024 + 1)
    with pytest.raises(ParsingAbort, match="HEADER_SIZE"):
        guard_headers(msg)

def test_encoded_words_guard_raises():
    msg = EmailMessage()
    msg["Subject"] = "=?utf-8?q?test?=" * 51
    with pytest.raises(ParsingAbort, match="ENCODED_WORDS"):
        guard_headers(msg)

# --- LAYER 2: PARSER ---
def test_depth_guard():
    # Create a real, deeply nested message/rfc822 structure
    root = EmailMessage()
    root.set_content("Root")
    current = root
    for _ in range(11):
        sub = EmailMessage()
        sub.set_content("Sub")
        current.add_attachment(sub, maintype="message", subtype="rfc822")
        current = sub

    with pytest.raises(ParsingAbort, match="DEPTH_EXCEEDED"):
        walk_message(root)

# --- LAYER 3: HEADERS ---
def test_extract_headers_trust_classes():
    msg = EmailMessage()
    msg["From"] = "alice@example.com"
    msg["Received"] = "from mail.example.com"
    msg["Authentication-Results"] = "dkim=pass"
    msg["X-Custom-Header"] = "random"
    extracted = extract_headers(msg)
    trust_map = {h["name"]: h["trust"] for h in extracted}
    assert trust_map["From"] == "SENDER_CLAIM"
    assert trust_map["Received"] == "RELAY_OBSERVATION"
    assert trust_map["Authentication-Results"] == "PERIMETER_VERDICT"
    assert trust_map["X-Custom-Header"] == "UNKNOWN"

# --- LAYER 4: BODY ---
def test_normalize_body_quoted_printable():
    msg = EmailMessage()
    msg.set_content("=3E Are we on for tomorrow?", cte="quoted-printable")
    assert normalize_body(msg) == "> Are we on for tomorrow?"

def test_normalize_body_base64():
    msg = EmailMessage()
    msg.set_content("Hello World", cte="base64")
    assert normalize_body(msg) == "Hello World"

# --- LAYER 4.5: QUOTED ---
def test_extract_quoted_outlook():
    body = "From: Alice <alice@example.com>\nSent: Mon, Oct 23\nTo: Bob\nSubject: Re: Contract\n\nText"
    quotes = extract_quoted(body)
    assert len(quotes) == 1
    assert quotes[0]["message_id"] is None
    assert quotes[0]["derivation"] == "QUOTED"

def test_extract_quoted_gmail():
    body = "On Mon, Oct 23, 2023 at 10:00 AM Alice <alice@example.com> wrote:\n> Text"
    quotes = extract_quoted(body)
    assert len(quotes) == 1
    assert "Alice" in quotes[0]["from_raw"]

# --- LAYER 5: THREADING ---
def test_build_threads_empty():
    assert build_threads([]) == {}

def test_build_threads_single():
    assert build_threads([{"message_id": "A"}]) == {"A": "A"}

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
    assert build_threads(msgs)["B"] == "A"

def test_build_threads_cycle():
    msgs = [{"message_id": "A", "in_reply_to": "B"}, {"message_id": "B", "in_reply_to": "A"}]
    result = build_threads(msgs)
    assert result["A"] == "A"
    assert result["B"] == "A"

def test_build_threads_dos_bound():
    msgs = [{"message_id": "A", "references": ["X"] * 1001}]
    with pytest.raises(ParsingAbort, match="REFERENCES_CHAIN"):
        build_threads(msgs)
