"""Publish a case's evidence digest to a public DNS TXT record.

An anchor is the one claim in this product that a reader can check without
trusting the machine that produced it: the digest is published outside the
database, at a name the case names, and any later change to the evidence makes
the published value disagree with the local one.

The split here mirrors the export pre-flight: this module computes and
publishes, and knows nothing about HTTP. Publishing is an explicit act with an
external side effect, so it is never triggered by viewing, exporting, or
verifying — only by the operator asking for it.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional, Sequence

#: Where the TXT record goes unless a deployment names its own zone.
DEFAULT_ANCHOR_DOMAIN = "anchorumzero-trust.com"

#: Anchoring needs a zone and a token. Reported as "not configured" rather than
#: attempted and failed, because the operator cannot fix a wrong token from a
#: generic failure message.
ZONE_ENV = "CF_ZONE_ID"
TOKEN_ENV = "CF_API_TOKEN"


@dataclass(frozen=True)
class AnchorRecord:
    """What was published, kept so the case can show it later."""

    digest: str
    record_name: str
    record_content: str
    zone_id: str
    published_at: str

    def as_dict(self) -> dict:
        return {
            "anchored": True,
            "digest": self.digest,
            "recordName": self.record_name,
            "recordContent": self.record_content,
            "zoneId": self.zone_id,
            "publishedAt": self.published_at,
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), separators=(",", ":"))


def case_digest(content_hashes: Sequence[str], audit_tip: str) -> str:
    """One digest over the whole case.

    Sorted so the value does not depend on the order documents were uploaded,
    and salted with the audit chain's tip so an anchor also covers the history
    that produced the evidence list, not only the bytes.
    """
    material = "\n".join(sorted(set(content_hashes))) + "|" + audit_tip
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def record_name_for(case_key: str, domain: Optional[str] = None) -> str:
    zone = (domain or os.getenv("ANCHORUM_ANCHOR_DOMAIN") or DEFAULT_ANCHOR_DOMAIN).strip()
    label = case_key.strip().lower()
    safe = "".join(ch if ch.isalnum() or ch in "-." else "-" for ch in label)
    return f"{safe}.{zone}"


def credentials() -> tuple[Optional[str], Optional[str]]:
    return os.getenv(ZONE_ENV), os.getenv(TOKEN_ENV)


def credentials_configured() -> bool:
    zone, token = credentials()
    return bool(zone and token)


def build_record(digest: str, case_key: str, zone_id: str) -> AnchorRecord:
    name = record_name_for(case_key)
    return AnchorRecord(
        digest=digest,
        record_name=name,
        record_content=f"anchor={digest}",
        zone_id=zone_id,
        published_at=datetime.now(timezone.utc).isoformat(),
    )


def publish(record: AnchorRecord, api_token: str) -> tuple[bool, str]:
    """Send the TXT record to Cloudflare. Returns (published, reason).

    Imports the publisher lazily so this module stays importable in a test
    process that never touches the network.
    """
    from dossier_pipeline.anchor_dnssec import publish_txt_record

    result = publish_txt_record(
        zone_id=record.zone_id,
        api_token=api_token,
        record_name=record.record_name,
        record_content=record.record_content,
    )
    if not result.success:
        # The provider's own message is passed through: "invalid token" and
        # "record already exists" need different actions from the operator.
        return False, (result.response_text or "publish failed")[:500]
    return True, ""


def load_record(raw: Optional[str]) -> Optional[AnchorRecord]:
    """The stored anchor, or None. A corrupt value reads as "not anchored"."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
    except (TypeError, ValueError):
        return None
    if not isinstance(data, dict) or not data.get("digest"):
        return None
    return AnchorRecord(
        digest=str(data["digest"]),
        record_name=str(data.get("recordName") or ""),
        record_content=str(data.get("recordContent") or ""),
        zone_id=str(data.get("zoneId") or ""),
        published_at=str(data.get("publishedAt") or ""),
    )
