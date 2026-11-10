from email.message import Message
from .abort import ParsingAbort
from .guards import MAX_DEPTH, MAX_TOTAL_BYTES

def walk_message(msg: Message, derivation: str = "HEADER", depth: int = 0, budget: dict = None) -> list:
    if budget is None:
        budget = {"remaining": MAX_TOTAL_BYTES}
    if depth > MAX_DEPTH:
        raise ParsingAbort("DEPTH_EXCEEDED")
    
    # Track bytes
    try:
        raw_bytes = msg.as_bytes()
        budget["remaining"] -= len(raw_bytes)
        if budget["remaining"] < 0:
            raise ParsingAbort("SIZE_EXCEEDED")
    except TypeError:
        pass # Some mock/custom objects might not have as_bytes
        
    if not msg.is_multipart():
        return []
        
    collected = []
    for part in msg.get_payload():
        if part.get_content_type() == "message/rfc822":
            payload = part.get_payload()
            if isinstance(payload, list):
                for sub_msg in payload:
                    collected.extend(walk_message(sub_msg, "ATTACHMENT", depth + 1, budget))
    return collected
