from typing import Any

MAX_DEPTH = 10
MAX_TOTAL_BYTES = 500 * 1024 * 1024

class ParsingAbort(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

def guard_headers(msg: Any) -> None:
    if len(msg._headers) > 200:
        raise ParsingAbort("HEADER_COUNT")
        
    for k, v in msg._headers:
        if len(str(v).encode('utf-8')) > 65536:
            raise ParsingAbort("HEADER_SIZE")
        if str(v).count('=?') > 50:
            raise ParsingAbort("ENCODED_WORDS")

def walk_message(msg: Any, derivation: str = "HEADER", depth: int = 0, budget: dict = None) -> list:
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
