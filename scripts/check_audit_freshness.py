#!/usr/bin/env python3
"""Verify that each audit document's tree stamp is still fresh."""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

STAMP_PATTERNS = [
    re.compile(r"\*\*Tree stamp:\*\*\s*`?([0-9a-f]{7,40})`?"),
    re.compile(r"Findings reflect commit\s+`([0-9a-f]{7,40})`"),
]
AUDIT_DIR = Path("docs/audit")


def git(*args: str) -> str:
    return subprocess.check_output(
        ["git", *args], text=True, stderr=subprocess.DEVNULL
    ).strip()


def find_stamp(text: str) -> str | None:
    for pat in STAMP_PATTERNS:
        m = pat.search(text)
        if m:
            return m.group(1)
    return None


def find_audits() -> list[tuple[Path, str]]:
    out: list[tuple[Path, str]] = []
    if not AUDIT_DIR.is_dir():
        return out
    for md in sorted(AUDIT_DIR.glob("*.md")):
        stamp = find_stamp(md.read_text(encoding="utf-8"))
        if stamp:
            out.append((md, stamp))
    return out


def changed_paths(stamp: str, exclude: Path) -> list[str]:
    rel = exclude.as_posix()
    try:
        out = git("diff", "--name-only", f"{stamp}..HEAD", "--", f":(exclude){rel}")
    except subprocess.CalledProcessError:
        return ["<stamp not in history>"]
    return [p for p in out.splitlines() if p]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="exit 1 on stale (default: warn only, exit 0)")
    args = ap.parse_args()

    audits = find_audits()
    if not audits:
        print("check_audit_freshness: no audit documents with a tree stamp")
        return 0

    stale = False
    for doc, stamp in audits:
        paths = changed_paths(stamp, doc)
        if not paths:
            print(f"OK    {doc.as_posix()}  stamp={stamp}")
            continue
        stale = True
        head = git("rev-parse", "--short", "HEAD")
        print(f"STALE {doc.as_posix()}")
        print(f"        stamp: {stamp}")
        print(f"        HEAD:  {head}")
        print("        changed paths since stamp (excluding this audit):")
        for p in paths[:20]:
            print(f"          {p}")
        if len(paths) > 20:
            print(f"          ... and {len(paths) - 20} more")
        print()
        print("        To resolve:")
        print("          1. re-run the checks the audit cites and update the")
        print("             stamp in the audit header, or")
        print("          2. verify none of these paths invalidate a finding")
        print("             and amend the header with a note explaining why.")

    return 1 if (stale and args.strict) else 0


if __name__ == "__main__":
    sys.exit(main())
