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

# --- LAYER 3: TRUST CLASSES ---

TRUST_MAP = {
    "From": "SENDER_CLAIM",
    "Sender": "SENDER_CLAIM",
    "Reply-To": "SENDER_CLAIM",
    "To": "SENDER_CLAIM",
    "Cc": "SENDER_CLAIM",
    "Subject": "SENDER_CLAIM",
    "Date": "SENDER_CLAIM",
    "Received": "RELAY_OBSERVATION",
    "Authentication-Results": "PERIMETER_VERDICT",
    "ARC-Authentication-Results": "PERIMETER_VERDICT",
    "DKIM-Signature": "CRYPTOGRAPHIC_SIGNATURE",
}

def extract_headers(msg: Any) -> list:
    """Extracts headers and classifies them by trust level."""
    extracted = []
    for key, value in msg.items():
        trust = TRUST_MAP.get(key, "UNKNOWN")
        extracted.append({
            "name": key,
            "value": str(value),
            "trust": trust
        })
    return extracted
