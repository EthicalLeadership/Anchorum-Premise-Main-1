"""
Dossier DOSSIER-PIPELINE — DNSSEC TXT Anchoring

Cloudflare DNS TXT record publishing helper. This module keeps the public
anchor surface small and deterministic.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass(frozen=True)
class DNSSECAnchorResult:
    success: bool
    zone_id: str
    record_name: str
    record_content: str
    status: str
    response_text: str = ""


def _cloudflare_headers(api_token: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_token}",
        "Content-Type": "application/json",
    }


def publish_txt_record(
    zone_id: str,
    api_token: str,
    record_name: str,
    record_content: str,
    ttl: int = 120,
) -> DNSSECAnchorResult:
    url = f"https://api.cloudflare.com/client/v4/zones/{zone_id}/dns_records"
    payload = {
        "type": "TXT",
        "name": record_name,
        "content": record_content,
        "ttl": ttl,
        "proxied": False,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        method="POST",
        headers=_cloudflare_headers(api_token),
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            body = response.read().decode("utf-8", errors="replace")
        return DNSSECAnchorResult(
            success=True,
            zone_id=zone_id,
            record_name=record_name,
            record_content=record_content,
            status="created",
            response_text=body,
        )
    except Exception as exc:
        return DNSSECAnchorResult(
            success=False,
            zone_id=zone_id,
            record_name=record_name,
            record_content=record_content,
            status="failed",
            response_text=str(exc),
        )


def resolve_public_anchor_name(dossier_id: str, domain: str = "chain.creovate.digital") -> str:
    normalized = dossier_id.strip().lower().replace(" ", "-")
    return f"{normalized}.{domain}"


def get_credentials_from_env() -> Dict[str, Optional[str]]:
    return {
        "zone_id": os.getenv("CF_ZONE_ID"),
        "api_token": os.getenv("CF_API_TOKEN"),
    }
