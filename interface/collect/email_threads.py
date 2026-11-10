from typing import Any


class ParsingAbort(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


def guard_headers(msg: Any) -> None:
    # Check count
    if len(msg._headers) > 200:
        raise ParsingAbort("HEADER_COUNT")

    for k, v in msg._headers:
        # Check size (must be > 64KB)
        if len(str(v).encode('utf-8')) > 65536:
            raise ParsingAbort("HEADER_SIZE")

        # Check encoded words (must be > 50)
        if str(v).count('=?') > 50:
            raise ParsingAbort("ENCODED_WORDS")
