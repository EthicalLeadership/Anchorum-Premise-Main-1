"""
Dossier DOSSIER-PIPELINE Anchoring CLI

Commands:
  - anchor-now
  - verify-anchors
  - dns-check
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .anchor import (AnchorFileTampered, anchor_now, anchor_path_for,
                     build_control_anchor, verify_anchor_file,
                     write_anchor_file)
from .anchor_dnssec import get_credentials_from_env, resolve_public_anchor_name
from .control import ControlPlane


def _load_control_plane(dossier_id: str, output_dir: str) -> ControlPlane:
    db_path = Path(output_dir) / f"{dossier_id}_chain.db"
    return ControlPlane(str(db_path))


def cmd_anchor_now(args) -> int:
    control = _load_control_plane(args.dossier_id, args.output_dir)
    try:
        result = anchor_now(control, output_dir=args.output_dir)
        print("Anchor result: SUCCESS")
        print(f"  Merkle root: {result.merkle_root}")
        print(f"  Tail hash: {result.tail_hash}")
        print(f"  OpenTimestamps: {result.ots_status}")
        if result.dns_record_name:
            print(f"  DNSSEC: {result.dns_record_name}")
        else:
            print(f"  DNSSEC: {result.dns_status}")
        print(f"  Anchor file: {result.message}")
        return 0
    finally:
        control.close()


def cmd_verify_anchors(args) -> int:
    """Verify the on-disk anchor file without rewriting it.

    Rebuilds the expected anchor from the current control plane, loads the
    existing anchor file from disk, verifies its self-hash, and cross-checks
    the four identity fields (dossier_id, tail_hash, merkle_root, record_count).
    Exit 1 on missing, tampered, malformed, or stale.
    """
    try:
        control = _load_control_plane(args.dossier_id, args.output_dir)
    except Exception as e:
        print(f"Verify anchors: CONTROL_PLANE_ERROR  {type(e).__name__}: {e}",
              file=sys.stderr)
        return 1
    try:
        expected = build_control_anchor(control)
    finally:
        control.close()

    anchor_path = anchor_path_for(expected["dossier_id"], args.output_dir)

    try:
        loaded = verify_anchor_file(str(anchor_path))
    except FileNotFoundError as e:
        print(f"Verify anchors: MISSING  {e}", file=sys.stderr)
        return 1
    except AnchorFileTampered as e:
        print(f"Verify anchors: TAMPERED  {e}", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"Verify anchors: MALFORMED  {e}", file=sys.stderr)
        return 1

    mismatches = []
    for field in ("dossier_id", "tail_hash", "merkle_root", "record_count"):
        if loaded.get(field) != expected.get(field):
            mismatches.append(
                f"{field}: disk={loaded.get(field)!r} db={expected.get(field)!r}"
            )

    if mismatches:
        print("Verify anchors: STALE", file=sys.stderr)
        for m in mismatches:
            print(f"  {m}", file=sys.stderr)
        return 1

    print("Verify anchors: SUCCESS")
    print(f"  Dossier ID: {loaded.get('dossier_id')}")
    print(f"  Tail hash: {loaded.get('tail_hash')}")
    print(f"  Merkle root: {loaded.get('merkle_root')}")
    print(f"  Record count: {loaded.get('record_count')}")
    print(f"  Anchor hash: {loaded.get('anchor_hash')}")
    return 0


def cmd_dns_check(args) -> int:
    creds = get_credentials_from_env()
    if not creds.get("zone_id") or not creds.get("api_token"):
        print("DNS check: MISSING_CREDENTIALS")
        return 1
    record_name = resolve_public_anchor_name(args.dossier_id)
    print("DNS check: READY")
    print(f"  Zone ID: {creds['zone_id']}")
    print(f"  Record: {record_name}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Dossier DOSSIER-PIPELINE anchoring CLI")
    parser.add_argument("--dossier-id", default="DOSSIER-PIPELINE")
    parser.add_argument("--output-dir", default="./output")

    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("anchor-now", help="Create anchor artifacts and publish public anchors")
    sub.add_parser("verify-anchors", help="Rebuild and verify local anchor artifacts")
    sub.add_parser("dns-check", help="Check Cloudflare anchoring credentials and record name")

    args = parser.parse_args(argv)

    if args.command == "anchor-now":
        return cmd_anchor_now(args)
    if args.command == "verify-anchors":
        return cmd_verify_anchors(args)
    if args.command == "dns-check":
        return cmd_dns_check(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
