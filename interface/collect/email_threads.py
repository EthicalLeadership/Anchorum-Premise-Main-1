from typing import Any
import quopri
import base64

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
    extracted = []
    for key, value in msg.items():
        trust = TRUST_MAP.get(key, "UNKNOWN")
        extracted.append({
            "name": key,
            "value": str(value),
            "trust": trust
        })
    return extracted

def normalize_body(part: Any) -> str:
    raw_payload = part.get_payload(decode=False)
    if raw_payload is None or isinstance(raw_payload, list):
        return ""
        
    cte = str(part.get("Content-Transfer-Encoding", "")).lower()
    
    if cte == "quoted-printable":
        try:
            decoded_bytes = quopri.decodestring(raw_payload.encode('utf-8', errors='replace'))
            return decoded_bytes.decode('utf-8', errors='replace')
        except Exception:
            return raw_payload
    elif cte == "base64":
        try:
            decoded_bytes = base64.b64decode(raw_payload)
            return decoded_bytes.decode('utf-8', errors='replace')
        except Exception:
            return raw_payload
            
    return raw_payload

# --- LAYER 5: JWZ THREADING (UNION-FIND) ---

def build_threads(messages: list[dict]) -> dict[str, str]:
    """
    Groups messages into threads using In-Reply-To and References.
    Returns a mapping of message_id -> thread_id (the root message_id).
    """
    parent = {}
    
    def find(x):
        if x not in parent:
            parent[x] = x
        if parent[x] != x:
            parent[x] = find(parent[x])
        return parent[x]
        
    def union(x, y):
        if x not in parent: parent[x] = x
        if y not in parent: parent[y] = y
        root_x = find(x)
        root_y = find(y)
        if root_x != root_y:
            # Deterministic: pick the lexicographically smaller ID as root
            if root_x < root_y:
                parent[root_y] = root_x
            else:
                parent[root_x] = root_y
                
    for msg in messages:
        mid = msg.get("message_id")
        if not mid:
            continue
        find(mid)
        
        in_reply = msg.get("in_reply_to")
        if in_reply:
            union(mid, in_reply)
            
        refs = msg.get("references", [])
        for ref in refs:
            union(mid, ref)
            
    # Return mapping of mid -> root
    return {mid: find(mid) for mid in parent}
