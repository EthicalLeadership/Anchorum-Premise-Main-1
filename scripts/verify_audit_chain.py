#!/usr/bin/env python3
"""Verify the integrity of a hash-chained audit log.

Walks the JSONL audit log and checks:
  * seq is 0, 1, 2, ... with no gaps
  * prev_hash of entry[i] equals entry_hash of entry[i-1]
  * record_hash equals sha256(canonical(record))
  * entry_hash equals sha256(canonical({seq, prev_hash, record_hash}))

Exit codes:
  0  chain intact
  1  chain broken
  2  usage error
"""
from __future__ import annotations
import argparse
import sys
from pathlib import Path


def _repo_on_path() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_repo_on_path()

from dossier_pipeline.registry.audit import AuditLog  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify_audit_chain")
    ap.add_argument("--audit", required=True)
    args = ap.parse_args(argv)

    path = Path(args.audit)
    if not path.exists():
        print(f"OK audit log empty (file absent: {path})")
        return 0

    log = AuditLog(path)
    try:
        errors = log.verify_chain()
    except Exception as e:
        print(f"FAIL parse: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    if errors:
        for seq, msg in errors:
            print(f"FAIL seq={seq}: {msg}", file=sys.stderr)
        return 1

    with path.open() as f:
        n = sum(1 for line in f if line.strip())
    print(f"OK {n} audit entries, chain intact")
    return 0


if __name__ == "__main__":
    sys.exit(main())
