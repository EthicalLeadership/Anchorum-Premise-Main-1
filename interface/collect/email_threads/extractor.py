import hashlib
from email import policy
from email.parser import BytesParser
from email.utils import getaddresses, parsedate_to_datetime
from dataclasses import dataclass, field

from .guards import guard_headers, walk_message
from .headers import extract_headers
from .body import normalize_body
from .quoted import extract_quoted

@dataclass
class ParsedMessage:
    message_id: str | None = None
    in_reply_to: str | None = None
    references: list[str] = field(default_factory=list)
    sent_at: str | None = None
    sent_at_raw: str | None = None
    from_raw: list[tuple[str, str]] = field(default_factory=list)
    to_raw: list[tuple[str, str]] = field(default_factory=list)
    cc_raw: list[tuple[str, str]] = field(default_factory=list)
    subject: str | None = None
    body_text: str = ""
    derivation: str = "HEADER"
    content_hash: str | None = None
    trust_headers: list[dict] = field(default_factory=list)

def _parse_addresses(values):
    return [(name, addr) for name, addr in getaddresses(values) if addr or name]

def _to_parsed(msg, derivation: str) -> ParsedMessage:
    guard_headers(msg)
    msg_id = msg.get("Message-ID")
    in_reply_to = msg.get("In-Reply-To")
    refs_raw = msg.get("References")
    sent_at_raw = msg.get("Date")
    sent_at = None
    if sent_at_raw:
        try:
            sent_at = parsedate_to_datetime(str(sent_at_raw)).isoformat()
        except Exception:
            sent_at = None
    body_text = "" if msg.is_multipart() else normalize_body(msg)
    return ParsedMessage(
        message_id=str(msg_id).strip() if msg_id else None,
        in_reply_to=str(in_reply_to).strip() if in_reply_to else None,
        references=str(refs_raw).split() if refs_raw else [],
        sent_at=sent_at,
        sent_at_raw=str(sent_at_raw) if sent_at_raw else None,
        from_raw=_parse_addresses([msg.get("From", "")]),
        to_raw=_parse_addresses(msg.get_all("To", [])),
        cc_raw=_parse_addresses(msg.get_all("Cc", [])),
        subject=str(msg.get("Subject")) if msg.get("Subject") else None,
        body_text=body_text,
        derivation=derivation,
        content_hash=hashlib.sha256(msg.as_bytes()).hexdigest(),
        trust_headers=extract_headers(msg),
    )

def parse_email(raw: bytes) -> list[ParsedMessage]:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    results = [_to_parsed(msg, "HEADER")]
    for nested in walk_message(msg):
        try:
            results.append(_to_parsed(nested, "ATTACHMENT"))
        except Exception:
            pass
    for q in extract_quoted(results[0].body_text):
        results.append(ParsedMessage(
            from_raw=_parse_addresses([q["from_raw"]]) if q.get("from_raw") else [],
            to_raw=_parse_addresses([q["to_raw"]]) if q.get("to_raw") else [],
            subject=q.get("subject"),
            sent_at_raw=q.get("date_raw"),
            derivation="QUOTED",
            message_id=None,
        ))
    return results
