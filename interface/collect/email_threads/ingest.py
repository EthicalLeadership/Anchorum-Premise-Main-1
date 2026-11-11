import json
import uuid
from datetime import datetime
from .extractor import parse_email
from .threading import build_threads
from .db import EmailMessage, ExpectedSource

def ingest(case_id: str, document_id: str, raw: bytes, session) -> list[EmailMessage]:
    parsed = parse_email(raw)

    msg_dicts = [
        {"message_id": m.message_id, "in_reply_to": m.in_reply_to, "references": m.references}
        for m in parsed if m.message_id
    ]
    thread_map = build_threads(msg_dicts) if msg_dicts else {}

    rows = []
    for pm in parsed:
        thread_id = thread_map.get(pm.message_id) if pm.message_id else None
        row = EmailMessage(
            id=str(uuid.uuid4()),
            case_id=case_id,
            document_id=document_id,
            message_id_raw=pm.message_id,
            thread_id=thread_id,
            in_reply_to=pm.in_reply_to,
            references=json.dumps(pm.references),
            sent_at_raw=pm.sent_at_raw,
            sent_at=datetime.fromisoformat(pm.sent_at) if pm.sent_at else None,
            from_raw=json.dumps(pm.from_raw),
            to_raw=json.dumps(pm.to_raw),
            cc_raw=json.dumps(pm.cc_raw),
            subject=pm.subject,
            body_text=pm.body_text,
            derivation=pm.derivation,
            content_hash=pm.content_hash,
            trust_headers=json.dumps(pm.trust_headers),
        )
        session.add(row)
        rows.append(row)

        # GAP BOARD LOGIC: if this row is a quoted block, the original message
        # is proven to exist but was not collected. Record the gap.
        if pm.derivation == "QUOTED":
            sender = pm.from_raw[0][1] if pm.from_raw else "unknown sender"
            gap = ExpectedSource(
                id=str(uuid.uuid4()),
                case_id=case_id,
                description=f"Missing original email quoted in thread: '{pm.subject or 'No Subject'}' from {sender}",
                status="REFERENCED",
                referenced_in_message_id=row.id,
            )
            session.add(gap)

    session.commit()
    return rows
