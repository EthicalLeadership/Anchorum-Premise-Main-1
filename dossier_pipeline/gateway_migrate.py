"""Migrate a gateway directory from schema_version 1.0 to 1.1.

Reads gateway.yaml, applies the deterministic transformation, writes the
result. Backs up the original to gateway.yaml.bak. Refuses if the file
already declares 1.1.

Transformations applied:
    schema_version: "1.0" -> "1.1"
    routes: added if absent, default ["QUARANTINE_REVIEW", "HOLD_UNCLASSIFIED"]
    evals.thresholds: flat map -> {_global: <flat>}
    legal: missing keys filled with conservative defaults; phi_handling=False
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

import yaml


_DEFAULT_ROUTES = ["QUARANTINE_REVIEW", "HOLD_UNCLASSIFIED"]


def migrate(gateway_dir: Path) -> bool:
    spec_path = gateway_dir / "gateway.yaml"
    if not spec_path.is_file():
        raise SystemExit(f"not found: {spec_path}")

    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    if not isinstance(spec, dict):
        raise SystemExit(f"{spec_path}: top level must be a mapping")

    if spec.get("schema_version") == "1.1":
        print(f"{spec_path}: already 1.1, no change")
        return False

    shutil.copy2(spec_path, spec_path.with_suffix(".yaml.bak"))

    spec["schema_version"] = "1.1"

    if "routes" not in spec:
        spec["routes"] = list(_DEFAULT_ROUTES)

    evals = spec.setdefault("evals", {})
    thresholds = evals.get("thresholds", {})
    if thresholds and "_global" not in thresholds:
        evals["thresholds"] = {"_global": thresholds}

    legal = spec.setdefault("legal", {})
    jurisdiction = spec.get("identity", {}).get("jurisdiction", "UNKNOWN")
    legal.setdefault("privacy_jurisdictions", [jurisdiction])
    legal.setdefault("retention_days_default", 2555)
    legal.setdefault("consent_required", False)
    legal.setdefault("phi_handling", False)

    spec_path.write_text(
        yaml.safe_dump(spec, sort_keys=False), encoding="utf-8"
    )
    print(f"{spec_path}: migrated to 1.1 (backup at {spec_path}.bak)")
    return True


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(
            "usage: python -m dossier_pipeline.gateway_migrate <gateway-dir>"
        )
    migrate(Path(sys.argv[1]))
