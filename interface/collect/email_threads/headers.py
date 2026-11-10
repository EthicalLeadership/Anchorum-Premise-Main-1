TRUST_MAP = {
    "From": "SENDER_CLAIM", "Sender": "SENDER_CLAIM", "Reply-To": "SENDER_CLAIM",
    "To": "SENDER_CLAIM", "Cc": "SENDER_CLAIM", "Subject": "SENDER_CLAIM",
    "Date": "SENDER_CLAIM", "Received": "RELAY_OBSERVATION",
    "Authentication-Results": "PERIMETER_VERDICT", "ARC-Authentication-Results": "PERIMETER_VERDICT",
    "DKIM-Signature": "CRYPTOGRAPHIC_SIGNATURE",
}

def extract_headers(msg) -> list:
    return [
        {"name": k, "value": str(v), "trust": TRUST_MAP.get(k, "UNKNOWN")}
        for k, v in msg.items()
    ]
