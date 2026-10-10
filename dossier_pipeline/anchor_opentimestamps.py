"""
Dossier DOSSIER-PIPELINE — OpenTimestamps Integration

Best-effort Bitcoin-backed timestamp proof generation. This module is
intentionally optional and degrades cleanly when the OpenTimestamps CLI or
Python package is not available.

Verify semantics (F-class fix):

    verify_timestamp() returns (TimestampStatus, message), not (bool, str).
    A caller that requires Bitcoin-verified proof must check for
    TimestampStatus.VERIFIED explicitly. The other statuses
    (PENDING, UNAVAILABLE, FAILED) are all non-verification outcomes.

    The previous signature returned (True, "...") when the OTS CLI was
    absent, which meant a caller doing `if ok: proceed` would proceed on
    unverified data. That is the fail-open this fix removes.
"""

from __future__ import annotations

import enum
import json
import shutil
import subprocess
from pathlib import Path
from typing import Optional, Tuple

from .anchor_core import sha256_hex


PLACEHOLDER_STATUS = "PENDING_CONFIRMATION"


class TimestampStatus(enum.Enum):
    """Result of verifying an OpenTimestamps proof.

    Only VERIFIED means a Bitcoin-backed proof was confirmed. Every other
    value is a non-verification outcome and the caller must decide how to
    proceed.
    """
    VERIFIED = "VERIFIED"
    PENDING = "PENDING"
    UNAVAILABLE = "UNAVAILABLE"
    FAILED = "FAILED"


def is_available() -> bool:
    return shutil.which("ots") is not None


def _is_placeholder(path: Path) -> bool:
    """Detect the JSON placeholder written by create_timestamp_request
    when the OpenTimestamps CLI is not available."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError, UnicodeDecodeError):
        return False
    if not isinstance(data, dict):
        return False
    return data.get("status") == PLACEHOLDER_STATUS


def create_timestamp_request(
    anchor_input_path: str,
    output_path: Optional[str] = None,
) -> str:
    """Request an OpenTimestamps proof for an anchor file.

    Returns the path to the created file. If the OTS CLI is available,
    the file is a real .ots proof. If not, a JSON placeholder is written
    with status PENDING_CONFIRMATION — verify_timestamp() on that file
    returns TimestampStatus.PENDING, never VERIFIED.
    """
    source = Path(anchor_input_path)
    if not source.exists():
        raise FileNotFoundError(f"Anchor input not found: {anchor_input_path}")

    if output_path is None:
        output_path = str(source.with_suffix(source.suffix + ".ots"))

    if is_available():
        subprocess.run(["ots", "stamp", str(source)], check=True)
        stamped = source.with_suffix(source.suffix + ".ots")
        if stamped.exists():
            stamped.replace(output_path)
            return output_path

    fallback = {
        "input_sha256": sha256_hex(source.read_bytes()),
        "status": PLACEHOLDER_STATUS,
        "note": "OpenTimestamps CLI not available; local placeholder generated",
    }
    Path(output_path).write_text(
        json.dumps(fallback, sort_keys=True, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return output_path


def verify_timestamp(ots_path: str) -> Tuple[TimestampStatus, str]:
    """Verify an OpenTimestamps proof.

    Returns (TimestampStatus, message).

    Check order:
      1. File missing              -> FAILED
      2. File is a placeholder     -> PENDING
      3. OTS CLI not available     -> UNAVAILABLE
      4. OTS CLI runs, exit 0      -> VERIFIED
      5. OTS CLI runs, non-zero    -> FAILED
      6. OTS CLI invocation raises -> FAILED
    """
    path = Path(ots_path)
    if not path.exists():
        return TimestampStatus.FAILED, f"Missing OTS proof: {ots_path}"

    if _is_placeholder(path):
        return (
            TimestampStatus.PENDING,
            "File is a local placeholder awaiting stamping; not a proof",
        )

    if not is_available():
        return (
            TimestampStatus.UNAVAILABLE,
            "OpenTimestamps CLI unavailable; cannot verify",
        )

    try:
        result = subprocess.run(
            ["ots", "verify", str(path)],
            check=False,
            capture_output=True,
            text=True,
        )
    except Exception as exc:
        return TimestampStatus.FAILED, f"ots invocation failed: {exc}"

    if result.returncode == 0:
        return TimestampStatus.VERIFIED, (result.stdout or "").strip()
    return (
        TimestampStatus.FAILED,
        (result.stdout or result.stderr or "ots verify failed").strip(),
    )
