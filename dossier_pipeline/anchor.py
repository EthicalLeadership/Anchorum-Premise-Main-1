"""
Dossier DOSSIER-PIPELINE — Unified Anchoring Orchestrator

Coordinates control-chain anchoring, optional OpenTimestamps stamping, and
optional Cloudflare TXT publication.

Two integrity layers are provided, with different threat models:

  * Local self-hash. Every anchor file carries an `anchor_hash` field
    computed over the rest of the payload. verify_anchor_file() recomputes
    it and refuses to return if the file's content does not match. This
    detects accidental corruption and naive field edits.

  * External witnesses. The OpenTimestamps proof (Bitcoin) and the DNSSEC
    TXT record are independent attestations that a given anchor existed
    at a given time. Neither is required for local verification; both are
    optional and degrade to an honest non-verified status when their
    infrastructure is unavailable (see anchor_opentimestamps).

verify_anchor_file() does NOT provide adversarial tamper detection on its
own: an attacker who edits a field and recomputes anchor_hash produces a
self-consistent file. Adversarial attestation requires the external
witnesses.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Optional

from .anchor_core import (build_anchor_payload, canonical_json, hash_payload,
                          merkle_root)
from .anchor_dnssec import (DNSSECAnchorResult, get_credentials_from_env,
                            publish_txt_record, resolve_public_anchor_name)
from .anchor_opentimestamps import create_timestamp_request
from .anchor_opentimestamps import is_available as ots_available


class AnchorFileTampered(Exception):
    """Raised when an anchor file's self-hash does not match its content.

    Distinct from FileNotFoundError (missing) and json.JSONDecodeError
    (malformed). Callers that treat "tampered" as an alarm condition and
    "missing" as a setup condition can distinguish them.
    """


@dataclass(frozen=True)
class AnchorResult:
    success: bool
    dossier_id: str
    tail_hash: str
    merkle_root: str
    record_count: int
    ots_status: str
    dns_status: str
    dns_record_name: str = ""
    ots_path: str = ""
    message: str = ""


def build_control_anchor(control_plane) -> Dict[str, Any]:
    records = control_plane.get_all_records()
    leaf_hashes = [record["record_hash"] for record in records]
    root = merkle_root(leaf_hashes)
    tail_hash = control_plane.get_tail_hash()
    dossier_id = Path(control_plane.db_path).stem.replace("_chain", "")
    payload = build_anchor_payload(dossier_id, tail_hash, len(records), root)
    payload["control_db_path"] = control_plane.db_path
    payload["anchor_hash"] = hash_payload(payload)
    return payload


def write_anchor_file(control_plane, output_dir: Optional[str] = None) -> str:
    payload = build_control_anchor(control_plane)
    base_dir = Path(output_dir or Path(control_plane.db_path).parent)
    base_dir.mkdir(parents=True, exist_ok=True)
    path = base_dir / f"{payload['dossier_id']}_anchor.json"
    path.write_text(canonical_json(payload), encoding="utf-8")
    return str(path)


def anchor_path_for(dossier_id: str, output_dir: str) -> Path:
    """Return the canonical on-disk anchor path for a dossier."""
    return Path(output_dir) / f"{dossier_id}_anchor.json"


def anchor_now(control_plane, output_dir: Optional[str] = None) -> AnchorResult:
    payload = build_control_anchor(control_plane)
    anchor_path = write_anchor_file(control_plane, output_dir=output_dir)
    ots_path = create_timestamp_request(anchor_path)

    creds = get_credentials_from_env()
    dns_status = "SKIPPED"
    dns_record_name = ""
    if creds.get("zone_id") and creds.get("api_token"):
        dns_record_name = resolve_public_anchor_name(payload["dossier_id"])
        dns_result: DNSSECAnchorResult = publish_txt_record(
            creds["zone_id"],
            creds["api_token"],
            dns_record_name,
            payload["tail_hash"],
        )
        dns_status = "SUCCESS" if dns_result.success else "FAILED"

    return AnchorResult(
        success=True,
        dossier_id=payload["dossier_id"],
        tail_hash=payload["tail_hash"],
        merkle_root=payload["merkle_root"],
        record_count=payload["record_count"],
        ots_status="AVAILABLE" if ots_available() else "PENDING_CONFIRMATION",
        dns_status=dns_status,
        dns_record_name=dns_record_name,
        ots_path=ots_path,
        message=f"Anchor artifacts written to {anchor_path}",
    )


def verify_anchor_file(anchor_path: str) -> Dict[str, Any]:
    """Load an anchor file and verify its self-consistency.

    Recomputes anchor_hash = hash_payload(payload without anchor_hash) and
    compares to the value stored in the file. Returns the parsed payload
    (including anchor_hash) if the check passes.

    Raises:
        FileNotFoundError    file does not exist
        json.JSONDecodeError file is not valid JSON
        AnchorFileTampered   JSON object with no anchor_hash, or hash mismatch

    This checks integrity against accidental corruption and naive field
    edits. It does not provide adversarial tamper detection; see the module
    docstring.
    """
    path = Path(anchor_path)
    if not path.exists():
        raise FileNotFoundError(f"Anchor file not found: {anchor_path}")

    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise AnchorFileTampered(
            f"Anchor file must be a JSON object: {anchor_path}"
        )
    if "anchor_hash" not in data:
        raise AnchorFileTampered(
            f"Anchor file has no anchor_hash field: {anchor_path}"
        )

    claimed = data["anchor_hash"]
    body = {k: v for k, v in data.items() if k != "anchor_hash"}
    computed = hash_payload(body)
    if computed != claimed:
        raise AnchorFileTampered(
            f"Anchor hash mismatch for {anchor_path}: "
            f"claimed={str(claimed)[:16]}... computed={computed[:16]}..."
        )
    return data
