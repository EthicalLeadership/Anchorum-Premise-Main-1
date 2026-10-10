"""
dossier_enforcement.cli
~~~~~~~~~~~~~~~~~~~~~~~~
Minimal command-line entry point for the enforcement package.
"""

from __future__ import annotations

import argparse
from typing import Sequence


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dossier-inspect")
    subparsers = parser.add_subparsers(dest="command")

    list_controls = subparsers.add_parser(
        "list-controls",
        help="List enforcement controls",
    )
    list_controls.set_defaults(command="list-controls")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
