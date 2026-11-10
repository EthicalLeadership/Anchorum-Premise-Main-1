from .abort import ParsingAbort

MAX_DEPTH = 10
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_REFERENCES = 1000
MAX_HEADERS = 200
MAX_HEADER_BYTES = 64 * 1024
MAX_ENCODED_WORDS_PER_HEADER = 50

def guard_headers(msg) -> None:
    if len(msg._headers) > MAX_HEADERS:
        raise ParsingAbort("HEADER_COUNT")
    for k, v in msg._headers:
        if len(str(v).encode('utf-8')) > MAX_HEADER_BYTES:
            raise ParsingAbort("HEADER_SIZE")
        if str(v).count('=?') > MAX_ENCODED_WORDS_PER_HEADER:
            raise ParsingAbort("ENCODED_WORDS")

def walk_message(msg, derivation="HEADER", depth=0, budget=None) -> list:
    if budget is None:
        budget = {"remaining": MAX_TOTAL_BYTES}
    if depth > MAX_DEPTH:
        raise ParsingAbort("DEPTH_EXCEEDED")
    try:
        raw_bytes = msg.as_bytes()
        size = len(raw_bytes) if isinstance(raw_bytes, (bytes, str)) else 0
    except Exception:
        size = 0
    budget["remaining"] -= size
    if budget["remaining"] < 0:
        raise ParsingAbort("SIZE_EXCEEDED")
    if not msg.is_multipart():
        return []
    collected = []
    for part in msg.get_payload():
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list):
                for sub_msg in payload:
                    collected.extend(walk_message(sub_msg, "ATTACHMENT", depth + 1, budget))
            else:
                collected.extend(walk_message(payload, "ATTACHMENT", depth + 1, budget))
    return collected
