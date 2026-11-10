from email.message import Message

def normalize_body(part: Message) -> str:
    # decode=True natively handles base64 and quoted-printable
    payload = part.get_payload(decode=True)
    if payload is None:
        return ""
    
    charset = part.get_content_charset() or "utf-8"
    try:
        return payload.decode(charset, errors="replace")
    except LookupError:
        return payload.decode("utf-8", errors="replace")
