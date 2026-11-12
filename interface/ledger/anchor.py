"""OpenTimestamps anchoring for LedgerSnapshot canonical bytes.

Phase 3: no schema, no migration. A snapshot is written to disk as .alp,
stamped by the `ots` CLI, and the resulting .ots proof is the artifact an
independent party can verify against Bitcoin.

Install the CLI outside this project:
    pipx install opentimestamps-client
or:
    python3 -m venv ~/.venv-ots && ~/.venv-ots/bin/pip install opentimestamps-client
Do not `apt install ots`; the package is often unrelated.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

DEFAULT_TIMEOUT_SECONDS = 60.0

_SUCCESS_RE = re.compile(
    r"Success!\s+Bitcoin block\s+(\d+)\s+attests",
    re.IGNORECASE,
)
_AS_OF_RE = re.compile(
    r"as of\s+(\d{4}-\d{2}-\d{2}(?:[ T]\d{2}:\d{2}:\d{2})?)",
    re.IGNORECASE,
)
_PENDING_MARKERS = (
    "pending confirmation",
    "not yet confirmed",
    "pending attestation",
)


class AnchorUnavailable(RuntimeError):
    """The `ots` CLI is not installed or not on PATH."""


class AnchorError(RuntimeError):
    """`ots` ran but did not produce the expected artifact or proof."""


@dataclass(frozen=True)
class AnchorResult:
    snapshot_path: Path
    ots_path: Path
    stdout: str
    stderr: str


@dataclass(frozen=True)
class VerifyResult:
    status: str  # "confirmed" | "pending" | "failed"
    bitcoin_block: Optional[int]
    attested_at: Optional[str]
    ots_path: Path
    stdout: str
    stderr: str


def resolve_ots_binary() -> str:
    binary = shutil.which("ots")
    if not binary:
        raise AnchorUnavailable(
            "OpenTimestamps client 'ots' not found on PATH. "
            "Install with: pipx install opentimestamps-client"
        )
    return binary


def stamp_bytes(
    data: bytes,
    out_dir: Path,
    filename: str = "snapshot.alp",
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> AnchorResult:
    """Write *data* to out_dir/filename and stamp it with `ots stamp`.

    `ots stamp` creates <file>.ots next to the input. The .alp file is kept
    because `ots verify` recomputes its hash; removing it breaks verification.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = out_dir / filename
    snapshot_path.write_bytes(data)
    ots_path = Path(str(snapshot_path) + ".ots")

    binary = resolve_ots_binary()
    cmd = [binary, "stamp", str(snapshot_path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnchorError(f"ots stamp timed out after {timeout}s") from exc

    if proc.returncode != 0:
        raise AnchorError(
            f"ots stamp failed (rc={proc.returncode}): {proc.stderr.strip()}"
        )
    if not ots_path.exists():
        raise AnchorError(
            f"ots stamp returned success but {ots_path} does not exist"
        )
    return AnchorResult(
        snapshot_path=snapshot_path,
        ots_path=ots_path,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )


def verify(
    ots_path: Path,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> VerifyResult:
    """Run `ots verify` and classify the proof.

    `ots verify` needs the original file next to the .ots (it strips the
    suffix automatically). A pending proof is not a failure: it means the
    calendar has not yet been mined into a Bitcoin block.
    """
    ots_path = Path(ots_path)
    if not ots_path.exists():
        raise AnchorError(f"proof file does not exist: {ots_path}")

    if ots_path.suffix != ".ots":
        raise AnchorError(f"expected a .ots file, got: {ots_path}")

    original = Path(str(ots_path)[: -len(".ots")])
    if not original.exists():
        raise AnchorError(
            f"original file missing next to proof: {original}. "
            "`ots verify` needs both files."
        )

    binary = resolve_ots_binary()
    cmd = [binary, "verify", str(ots_path)]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        raise AnchorError(f"ots verify timed out after {timeout}s") from exc

    combined = f"{proc.stdout}\n{proc.stderr}"

    match = _SUCCESS_RE.search(combined)
    if match:
        as_of = _AS_OF_RE.search(combined)
        return VerifyResult(
            status="confirmed",
            bitcoin_block=int(match.group(1)),
            attested_at=as_of.group(1) if as_of else None,
            ots_path=ots_path,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    lower = combined.lower()
    if any(marker in lower for marker in _PENDING_MARKERS):
        return VerifyResult(
            status="pending",
            bitcoin_block=None,
            attested_at=None,
            ots_path=ots_path,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )

    return VerifyResult(
        status="failed",
        bitcoin_block=None,
        attested_at=None,
        ots_path=ots_path,
        stdout=proc.stdout,
        stderr=proc.stderr,
    )
