import pytest
from email.message import Message
from interface.collect.email_threads import guard_headers, ParsingAbort


def test_header_count_guard_raises():
    msg = Message()
    msg._headers = [("Received", "test")] * 201
    with pytest.raises(ParsingAbort) as exc:
        guard_headers(msg)
    assert exc.value.reason == "HEADER_COUNT"


def test_header_size_guard_raises():
    msg = Message()
    # 70,000 is definitely > 65,536
    msg._headers = [("Subject", "A" * 70000)]
    with pytest.raises(ParsingAbort) as exc:
        guard_headers(msg)
    assert exc.value.reason == "HEADER_SIZE"


def test_encoded_words_guard_raises():
    msg = Message()
    # 51 encoded words
    val = " ".join(["=?utf-8?q?test?="] * 51)
    msg._headers = [("Subject", val)]
    with pytest.raises(ParsingAbort) as exc:
        guard_headers(msg)
    assert exc.value.reason == "ENCODED_WORDS"