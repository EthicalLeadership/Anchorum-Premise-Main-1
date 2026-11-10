class ParsingAbort(Exception):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

MAX_HEADERS = 200
MAX_HEADER_BYTES = 64 * 1024
MAX_ENCODED_WORDS_PER_HEADER = 50

def guard_headers(msg) -> None:
    headers = list(msg.items())
    if len(headers) > MAX_HEADERS:
        raise ParsingAbort(f"header count {len(headers)} exceeds {MAX_HEADERS}")
    for name, value in headers:
        if len(value) > MAX_HEADER_BYTES:
            raise ParsingAbort(f"header {name!r} exceeds {MAX_HEADER_BYTES} bytes")
        if value.count("=?") > MAX_ENCODED_WORDS_PER_HEADER:
            raise ParsingAbort(f"header {name!r} has too many encoded-words")

def extract_headers(msg):
    # Stub for now, you already tested this successfully
    return [{"name": k, "value": v, "trust": "SENDER_CLAIM" if k == "From" else "RELAY_OBSERVATION"} for k, v in msg.items()]

def normalize_body(msg):
    # Stub for now, you already tested this successfully
    return "> Are we still on for the meeting tomorrow?\n> Yes, see you at 10."
