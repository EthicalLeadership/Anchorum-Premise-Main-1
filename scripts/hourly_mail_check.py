#!/usr/bin/env python3
"""Hourly Proton mailbox audit for DOSSIER-PIPELINE.

Checks key mailboxes, updates actor response status, and writes JSON snapshots
so monitoring survives across conversations.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from email import message_from_bytes
from pathlib import Path

# Ensure local package import works when run as a script.
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from dossier_pipeline.main import _build_actor_audit_summary, load_config
from dossier_pipeline.proton_connector import ProtonMailConnector


def _sample_subjects(raw_messages: list[bytes], count: int = 3) -> list[str]:
    samples = []
    for raw in raw_messages[-count:]:
        try:
            msg = message_from_bytes(raw)
            subj = str(msg.get("Subject", "")).strip()
        except Exception:
            subj = ""
        samples.append(subj[:160])
    return samples


def run_hourly_mail_check() -> int:
    config = load_config()
    if not config.get("password"):
        print("ERROR: missing PROTON_IMAP_PASSWORD in env/.env")
        return 1

    mailboxes = ["INBOX", "Sent", "Drafts", "All Mail", "Archive"]
    limit = 1000

    connector = ProtonMailConnector(
        email=config["email"],
        password=config["password"],
        host=config["host"],
        port=config["port"],
        use_ssl=bool(config.get("use_ssl")),
    )

    fetched: dict[str, list[bytes]] = {}
    mailbox_errors: list[dict[str, str]] = []
    try:
        connector.connect()
        for box in mailboxes:
            try:
                fetched[box] = connector.fetch_all(limit=limit, mailbox=box)
            except Exception as exc:
                fetched[box] = []
                mailbox_errors.append({"mailbox": box, "error": str(exc)})
    finally:
        connector.disconnect()

    actor_summary = _build_actor_audit_summary(fetched, config["email"])
    actor_list = sorted(actor_summary.values(), key=lambda x: x["display"].lower())

    mailbox_snapshot = []
    for box in mailboxes:
        raw = fetched.get(box, [])
        mailbox_snapshot.append(
            {
                "mailbox": box,
                "message_count": len(raw),
                "sample_subjects": _sample_subjects(raw, count=3),
            }
        )

    no_response = [
        item["display"]
        for item in actor_list
        if item["sent_count"] > 0 and item["inbox_count"] == 0
    ]

    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_dir = ROOT / "output_proton" / "hourly_mail_audit"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_file = out_dir / f"hourly_mail_audit_{stamp}.json"

    payload = {
        "generated_at_utc": now.isoformat(),
        "dossier_id": config.get("dossier_id", "DOSSIER-PIPELINE"),
        "owner_email": config["email"],
        "mailboxes": mailbox_snapshot,
        "mailbox_errors": mailbox_errors,
        "actors": actor_list,
        "no_response": no_response,
        "source": "scripts/hourly_mail_check.py",
    }

    out_file.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Hourly mailbox audit saved: {out_file}")
    if mailbox_errors:
        print("Mailbox errors:")
        for err in mailbox_errors:
            print(f"  - {err['mailbox']}: {err['error']}")
    print("No-response actors:")
    if no_response:
        for actor in no_response:
            print(f"  - {actor}")
    else:
        print("  - none")

    latest = out_dir / "latest.json"
    latest.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(run_hourly_mail_check())
