#!/usr/bin/env python3
"""Verify a v3 trust anchor from disk as a fresh process.

Reads an anchor JSON file and a set of pinned root public keys, and
confirms that:
  * the anchor parses as schema v3
  * its signatures verify against the supplied root pubkeys
  * it is not expired
  * (if a predecessor is supplied) it is a valid transition from that
    predecessor

Does not import the governance flow or the store. Only the primitive
trust module.

Exit codes:
  0  anchor is valid
  1  anchor is invalid (reason printed to stderr)
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

from dossier_pipeline.registry.trust import (  # noqa: E402
    TrustError,
    load_anchor,
    parse_root_pubkeys_env,
    root_pubkeys_from_file,
    verify_anchor,
)


def _load_pubkeys(path_str: str | None) -> dict:
    if path_str:
        return root_pubkeys_from_file(Path(path_str))
    env = parse_root_pubkeys_env()
    if env:
        return env
    raise TrustError(
        "no root pubkeys supplied (--roots or ANCHORUM_ROOT_PUBKEYS)"
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify_anchor")
    ap.add_argument("--anchor", required=True, help="path to anchor JSON")
    ap.add_argument("--roots", default=None,
                    help="path to roots file (name:hex per line)")
    ap.add_argument("--predecessor", default=None,
                    help="path to predecessor anchor (for rotation/revocation)")
    args = ap.parse_args(argv)

    try:
        anchor = load_anchor(Path(args.anchor))
    except Exception as e:
        print(f"FAIL load anchor: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    try:
        pubkeys = _load_pubkeys(args.roots)
    except Exception as e:
        print(f"FAIL load root pubkeys: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    predecessor = None
    if args.predecessor:
        try:
            predecessor = load_anchor(Path(args.predecessor))
        except Exception as e:
            print(f"FAIL load predecessor: {type(e).__name__}: {e}", file=sys.stderr)
            return 1

    try:
        verify_anchor(anchor, pubkeys, predecessor=predecessor)
    except TrustError as e:
        print(f"FAIL anchor: {e}", file=sys.stderr)
        return 1

    print(
        f"OK anchor_seq={anchor.anchor_seq} "
        f"root_ids={sorted(anchor.root_ids)} "
        f"threshold={anchor.threshold} "
        f"signers={len(anchor.signers)} "
        f"issued_at={anchor.issued_at} "
        f"expires_at={anchor.expires_at}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
