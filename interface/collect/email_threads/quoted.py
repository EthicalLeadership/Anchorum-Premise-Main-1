import re

OUTLOOK_HEADER = re.compile(
    r"^\s*From:\s*(?P<from>.+?)\s*$\n"
    r"^\s*(?:Sent|Date):\s*(?P<date>.+?)\s*$\n"
    r"^\s*To:\s*(?P<to>.+?)\s*$\n"
    r"^\s*(?:Cc:\s*(?P<cc>.+?)\s*$\n)?"
    r"^\s*Subject:\s*(?P<subject>.+?)\s*$",
    re.I | re.M
)

GMAIL_HEADER = re.compile(
    r"^\s*On\s+(?P<date>.+?)\s+(?:at\s+[^<]+)?(?P<from>.+?)\s+wrote:\s*$",
    re.I | re.M
)

def extract_quoted(body_text: str) -> list[dict]:
    quoted = []
    for match in OUTLOOK_HEADER.finditer(body_text):
        quoted.append({
            "derivation": "QUOTED", "message_id": None, "from_raw": match.group("from"),
            "to_raw": match.group("to"), "cc_raw": match.group("cc"),
            "subject": match.group("subject"), "date_raw": match.group("date"), "body_text": ""
        })
    for match in GMAIL_HEADER.finditer(body_text):
        quoted.append({
            "derivation": "QUOTED", "message_id": None, "from_raw": match.group("from"),
            "to_raw": None, "cc_raw": None, "subject": None,
            "date_raw": match.group("date"), "body_text": ""
        })
    return quoted
