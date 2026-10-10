"""Orchestration toggle for the BlackStar environment.

This repository does not currently ship a blackstarctl binary. The
functions below are honest no-ops: they log what they would do and return
False to indicate that no orchestration was actually performed. Callers
that gate behavior on the return value get the correct semantics.

When a real blackstarctl lands, replace the bodies with subprocess calls
and keep the same return contract: True on success, False on not-attempted
or failed, and raise only for programmer errors (bad arguments).
"""
from __future__ import annotations

import shutil
import subprocess
import sys


BLACKSTARCTL = "blackstarctl"


def is_available() -> bool:
    """True if a blackstarctl binary is on PATH."""
    return shutil.which(BLACKSTARCTL) is not None


def enable_blackstar(*, quiet: bool = False) -> bool:
    """Attempt to enable BlackStar orchestration. Returns True if the
    environment was actually enabled, False if the tool is absent and the
    call was a no-op."""
    if not is_available():
        if not quiet:
            print(
                "orchestration: blackstarctl not found on PATH; "
                "no-op (baseline behavior)",
                file=sys.stderr,
            )
        return False

    try:
        result = subprocess.run(
            [BLACKSTARCTL, "enable"],
            check=False, capture_output=True, text=True,
        )
    except OSError as e:
        if not quiet:
            print(f"orchestration: enable failed: {e}", file=sys.stderr)
        return False

    if result.returncode != 0:
        if not quiet:
            print(
                f"orchestration: enable returned {result.returncode}: "
                f"{(result.stderr or result.stdout).strip()}",
                file=sys.stderr,
            )
        return False
    return True


def disable_blackstar(*, quiet: bool = False) -> bool:
    """Symmetric to enable_blackstar."""
    if not is_available():
        if not quiet:
            print(
                "orchestration: blackstarctl not found on PATH; "
                "no-op (already baseline)",
                file=sys.stderr,
            )
        return False
    try:
        result = subprocess.run(
            [BLACKSTARCTL, "disable"],
            check=False, capture_output=True, text=True,
        )
    except OSError as e:
        if not quiet:
            print(f"orchestration: disable failed: {e}", file=sys.stderr)
        return False
    return result.returncode == 0
