import quopri
import base64

def normalize_body(part) -> str:
    raw = part.get_payload(decode=False)
    if raw is None or isinstance(raw, list):
        return ""
    cte = str(part.get("Content-Transfer-Encoding", "")).lower()
    if cte == "quoted-printable":
        try:
            return quopri.decodestring(raw.encode('utf-8', errors='replace')).decode('utf-8', errors='replace')
        except Exception:
            return raw
    elif cte == "base64":
        try:
            return base64.b64decode(raw).decode('utf-8', errors='replace')
        except Exception:
            return raw
    return raw
