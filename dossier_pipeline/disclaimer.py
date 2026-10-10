"""
Dossier DOSSIER-PIPELINE — Output Disclaimer Generator

Centralized footer for outward-facing artifacts. Kept versioned so that every
rendered output can be traced to the exact disclaimer policy in effect.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

DISCLAIMER_VERSION = "1.0.0"
DISCLAIMER_TITLE = "Output Governance Disclaimer"


@dataclass(frozen=True)
class Disclaimer:
    version: str
    generated_at: str
    title: str
    text: str


def build_disclaimer() -> Disclaimer:
    generated_at = datetime.now(timezone.utc).isoformat()
    text = (
        "This artifact is generated from governed case-processing output. "
        "It is an administrative record, not legal advice, not a filing, "
        "and not a substitute for independent review. "
        "Internal reasoning, protected analysis, and non-public terminology "
        "have been filtered from outward-facing text."
    )
    return Disclaimer(
        version=DISCLAIMER_VERSION,
        generated_at=generated_at,
        title=DISCLAIMER_TITLE,
        text=text,
    )


def format_disclaimer_block() -> str:
    disclaimer = build_disclaimer()
    return (
        "\n---\n"
        f"**{disclaimer.title}**\n\n"
        f"- Version: `{disclaimer.version}`\n"
        f"- Generated at: `{disclaimer.generated_at}`\n\n"
        f"{disclaimer.text}\n"
    )
