from email.message import Message
from .abort import ParsingAbort

MAX_DEPTH = 10
MAX_TOTAL_BYTES = 500 * 1024 * 1024
MAX_REFERENCES = 1000
MAX_HEADERS = 200
MAX_HEADER_BYTES = 64 * 1024
MAX_ENCODED_WORDS = 50

def guard_headers(msg: Message) -> None:
    if len(msg.keys()) > MAX_HEADERS:
        raise ParsingAbort(f"HEADER_COUNT: {len(msg.keys())} > {MAX_HEADERS}")
    
    for k, v in msg.items():
        val_str = str(v)
        if len(val_str.encode('utf-8')) > MAX_HEADER_BYTES:
            raise ParsingAbort(f"HEADER_SIZE: {k} > {MAX_HEADER_BYTES} bytes")
        if val_str.count('=?') > MAX_ENCODED_WORDS:
            raise ParsingAbort(f"ENCODED_WORDS: {k} has > {MAX_ENCODED_WORDS} words")
