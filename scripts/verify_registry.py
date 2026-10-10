#!/usr/bin/env python3
"""Verify every entry in a registry file against a v3 anchor.

For every entry:
  * signer must be listed in the anchor
  * signer must not be revoked
  * entry signature must verify against the anchor-listed pubkey
  * snapshot_hash(entry.config_snapshot) must equal entry.config_hash

Does not use RegistryStore; verifies entries directly against the anchor.

Exit codes:
  0  all entries valid
  1  at least one entry failed
  2  usage error
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path


def _repo_on_path() -> None:
    root = Path(__file__).resolve().parent.parent
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))


_repo_on_path()

from dossier_pipeline.registry.entry import (  # noqa: E402
    RegistryEntry,
    snapshot_hash,
    verify_entry,
)
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
    raise TrustError("no root pubkeys supplied (--roots or ANCHORUM_ROOT_PUBKEYS)")


def _check_entry(entry: RegistryEntry, anchor) -> list[str]:
    if not anchor.contains(entry.signer_id):
        return [f"signer {entry.signer_id!r} not in anchor"]
    revoked_at = anchor.revoked_at(entry.signer_id)
    if revoked_at is not None:
        return [f"signer {entry.signer_id!r} revoked at {revoked_at}"]
    pub = anchor.authorized_pubkey(entry.signer_id)
    if pub is None:
        return [f"signer {entry.signer_id!r} pubkey could not be parsed"]
    errs: list[str] = []
    if not verify_entry(entry, pub):
        errs.append("signature invalid against anchor")
    if snapshot_hash(entry.config_snapshot) != entry.config_hash:
        errs.append(
            f"snapshot hash mismatch: expected {entry.config_hash}, "
            f"got {snapshot_hash(entry.config_snapshot)}"
        )
    return errs


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="verify_registry")
    ap.add_argument("--anchor", required=True)
    ap.add_argument("--roots", default=None)
    ap.add_argument("--predecessor", default=None)
    ap.add_argument("--registry", required=True)
    args = ap.parse_args(argv)

    try:
        anchor = load_anchor(Path(args.anchor))
        pubkeys = _load_pubkeys(args.roots)
        predecessor = (
            load_anchor(Path(args.predecessor)) if args.predecessor else None
        )
        verify_anchor(anchor, pubkeys, predecessor=predecessor)
    except Exception as e:
        print(f"FAIL anchor: {type(e).__name__}: {e}", file=sys.stderr)
        return 1

    path = Path(args.registry)
    if not path.exists():
        print(f"OK registry empty (file absent: {path})")
        return 0

    total = 0
    failed = 0
    with path.open() as f:
        for lineno, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            total += 1
            try:
                entry = RegistryEntry(**json.loads(line))
            except Exception as e:
                print(
                    f"FAIL line {lineno}: parse: {type(e).__name__}: {e}",
                    file=sys.stderr,
                )
                failed += 1
                continue
            errs = _check_entry(entry, anchor)
            if errs:
                failed += 1
                for err in errs:
                    print(
                        f"FAIL line {lineno} "
                        f"({entry.config_hash[:12]}…): {err}",
                        file=sys.stderr,
                    )

    if failed == 0:
        print(
            f"OK {total} entries verified against anchor_seq={anchor.anchor_seq}"
        )
        return 0
    print(f"FAILED {failed}/{total} entries", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
