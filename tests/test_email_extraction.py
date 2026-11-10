import pytest
from interface.collect.email_threads import parse_email

SIMPLE = b"""From: Alice <alice@example.com>
To: Bob <bob@example.com>
Subject: Contract
Date: Mon, 23 Oct 2023 10:00:00 +0000
Message-ID: <abc123@example.com>
Content-Type: text/plain

Hello Bob.
"""

REPLY = b"""From: Bob <bob@example.com>
To: Alice <alice@example.com>
Subject: Re: Contract
Date: Mon, 23 Oct 2023 11:00:00 +0000
Message-ID: <def456@example.com>
In-Reply-To: <abc123@example.com>
References: <abc123@example.com>
Content-Type: text/plain

Sounds good.

On Mon, 23 Oct 2023 at 10:00 AM Alice <alice@example.com> wrote:
> Hello Bob.
"""

def test_parse_simple():
    msgs = parse_email(SIMPLE)
    assert len(msgs) == 1
    m = msgs[0]
    assert m.message_id == "<abc123@example.com>"
    assert m.subject == "Contract"
    assert m.derivation == "HEADER"
    assert "Hello Bob" in m.body_text
    assert ("Alice", "alice@example.com") in m.from_raw

def test_parse_reply_with_quote():
    msgs = parse_email(REPLY)
    assert len(msgs) == 2
    header = [m for m in msgs if m.derivation == "HEADER"][0]
    quoted = [m for m in msgs if m.derivation == "QUOTED"][0]
    assert header.message_id == "<def456@example.com>"
    assert header.in_reply_to == "<abc123@example.com>"
    assert quoted.message_id is None
    assert "Alice" in str(quoted.from_raw)
