#!/usr/bin/env python3
"""Generate a CycloneDX SBOM from requirements.lock, and detect environment drift.

The SBOM describes the packages *this project declares*, at the versions it
pins, so the document is a statement about what ships rather than about whatever
happened to be installed on the machine that generated it.

Running it also checks the live environment against the lock. A package that is
missing, or present at a different version, is reported and the command exits
non-zero. That turns "is this the verified environment?" into something CI
answers rather than something a README asserts.

Audit finding F-06 asked for an SBOM; it also recorded that the environment was
not reproducible. This addresses both from one source of truth.

Usage:
    python scripts/generate_sbom.py                 # write docs/security/SBOM.cdx.json
    python scripts/generate_sbom.py --check         # verify the environment, write nothing
    python scripts/generate_sbom.py --output -      # write to stdout
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from importlib import metadata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK_PATH = ROOT / "requirements.lock"
DEFAULT_OUTPUT = ROOT / "docs" / "security" / "SBOM.cdx.json"

PROJECT_NAME = "dossier-pipeline-v1-1"
SPEC_VERSION = "1.5"
_CANONICAL = re.compile(r"[-_.]+")
_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)\s*==\s*(?P<version>\S+)\s*$")


def _canonical(name: str) -> str:
    return _CANONICAL.sub("-", name).strip().lower()


def _installed_versions() -> dict[str, str]:
    installed: dict[str, str] = {}
    for distribution in metadata.distributions():
        name = distribution.metadata["Name"]
        if name:
            installed[_canonical(name)] = distribution.version
    return installed


def _timestamp() -> str:
    """Reproducible timestamp.

    A generated artifact that changes on every run produces a diff every time it
    is regenerated, which trains reviewers to ignore it. Honouring
    SOURCE_DATE_EPOCH (the standard reproducible-builds convention) makes the
    document stable when the inputs are stable.
    """
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None and epoch.strip().isdigit():
        moment = datetime.fromtimestamp(int(epoch), tz=timezone.utc)
    else:
        moment = datetime.now(timezone.utc)
    return moment.isoformat()


def _read_lock() -> list[tuple[str, str]]:
    if not LOCK_PATH.exists():
        raise SystemExit(f"FAIL no lockfile at {LOCK_PATH}")
    pins: list[tuple[str, str]] = []
    for line in LOCK_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _PIN.match(line)
        if match is None:
            raise SystemExit(
                f"FAIL {LOCK_PATH.name} line is not a pin: {line!r}. "
                "Every line must be 'name==version'."
            )
        pins.append((match.group("name"), match.group("version")))
    if not pins:
        raise SystemExit(f"FAIL {LOCK_PATH.name} contains no pins")
    return sorted(pins, key=lambda pin: _canonical(pin[0]))


def _find_drift(pins: list[tuple[str, str]], installed: dict[str, str]) -> list[str]:
    problems: list[str] = []
    for name, version in pins:
        found = installed.get(_canonical(name))
        if found is None:
            problems.append(f"{name}=={version}: not installed")
        elif found != version:
            problems.append(f"{name}: locked {version}, installed {found}")
    return problems


def _build_sbom(pins: list[tuple[str, str]]) -> dict:
    components = [
        {
            "type": "library",
            "bom-ref": f"pkg:pypi/{_canonical(name)}@{version}",
            "name": name,
            "version": version,
            "purl": f"pkg:pypi/{_canonical(name)}@{version}",
        }
        for name, version in pins
    ]
    return {
        "bomFormat": "CycloneDX",
        "specVersion": SPEC_VERSION,
        "version": 1,
        "metadata": {
            "timestamp": _timestamp(),
            "tools": [
                {
                    "vendor": "anchorum",
                    "name": Path(__file__).name,
                    "version": "1.0.0",
                }
            ],
            "component": {
                "type": "application",
                "bom-ref": f"pkg:pypi/{PROJECT_NAME}",
                "name": PROJECT_NAME,
            },
        },
        "components": components,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        default=str(DEFAULT_OUTPUT),
        help="destination path, or '-' for stdout",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="verify the installed environment against the lock and write nothing",
    )
    args = parser.parse_args(argv)

    pins = _read_lock()
    drift = _find_drift(pins, _installed_versions())

    if args.check:
        if drift:
            for problem in drift:
                print(f"FAIL lock drift: {problem}", file=sys.stderr)
            return 1
        print(f"OK environment matches {LOCK_PATH.name} ({len(pins)} packages)")
        return 0

    document = json.dumps(_build_sbom(pins), indent=2, sort_keys=True) + "\n"
    if args.output == "-":
        sys.stdout.write(document)
    else:
        destination = Path(args.output)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document, encoding="utf-8")
        try:
            shown = destination.relative_to(ROOT)
        except ValueError:
            # --output may legitimately point outside the repository.
            shown = destination
        print(f"OK wrote {shown} ({len(pins)} components)")

    if drift:
        for problem in drift:
            print(f"WARN lock drift: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
