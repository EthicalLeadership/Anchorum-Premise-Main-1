import pytest
from interface.collect.email_threads.db import EmailMessage, get_engine, init_email_schema, get_session
from interface.collect.email_threads.ingest import ingest

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

@pytest.fixture
def session(tmp_path):
    engine = get_engine(str(tmp_path / "test.db"))
    init_email_schema(engine)
    s = get_session(engine)
    yield s
    s.close()

def test_ingest_persists(session):
    rows = ingest("case-1", "doc-1", REPLY, session)
    assert len(rows) == 2
    all_rows = session.query(EmailMessage).all()
    assert len(all_rows) == 2
    header = [r for r in all_rows if r.derivation == "HEADER"][0]
    quoted = [r for r in all_rows if r.derivation == "QUOTED"][0]
    assert header.message_id_raw == "<def456@example.com>"
    assert header.thread_id == "<abc123@example.com>"
    assert quoted.message_id_raw is None
    assert header.subject == "Re: Contract"
