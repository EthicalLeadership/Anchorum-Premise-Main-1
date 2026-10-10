#!/usr/bin/env bash
# apply_factory.sh — C5 drop: gateway factory with provenance, overwrite
# refusal, atomic writes, and non-executable stubs. Idempotent.
#
# What it writes (in this order, so partial runs fail safe):
#   factory/__init__.py
#   factory/provenance.py
#   factory/writer.py
#   factory/generate.py
#   factory/prompts/01_discovery.md
#   factory/examples/transportation_discovery.json
#   factory/README.md
#   (updates) gateways/_template/README.md with a "Factory" section

set -euo pipefail
REPO="${REPO:-/home/kark/anchorum-prem}"
[ -d "$REPO" ] || { echo "ERROR: $REPO not found"; exit 1; }
echo "==> Target: $REPO"; echo
mkdir -p "$REPO/factory/prompts" "$REPO/factory/examples"

# ============================================================================
cat > "$REPO/factory/__init__.py" <<'FILE_EOF'
"""ANCHORUM gateway factory.

Turns a vertical name + jurisdiction into a *draft* gateway. Drafts carry a
machine-readable provenance manifest (`.anchorum-factory.json`) that
records the model, prompt version, timestamp, and content hashes. The
writer refuses to overwrite files that a human has edited since
generation.
"""
FACTORY_VERSION = "0.1.0"
FILE_EOF
echo "  wrote factory/__init__.py"

# ============================================================================
cat > "$REPO/factory/provenance.py" <<'FILE_EOF'
"""Provenance manifest for factory-generated gateways.

Every gateway the factory writes carries `.anchorum-factory.json` at its
root. That file records, for each generated artifact:

  - sha256 hash of the file as the factory wrote it
  - generator version
  - model identifier
  - prompt version
  - generation timestamp (ISO 8601 UTC)

The manifest is what makes overwrite-refusal safe. `writer.write_gateway`
verifies each target file's current hash against the manifest before
rewriting; a mismatch means a human edited the file, and the factory
refuses unless `--force` is passed.

The manifest itself is not user-editable content. If it exists but does
not parse, the factory refuses to touch the gateway.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import FACTORY_VERSION

MANIFEST_NAME = ".anchorum-factory.json"


@dataclass(frozen=True)
class FileEntry:
    path: str          # relative to gateway root
    sha256: str


@dataclass(frozen=True)
class Manifest:
    generator_version: str
    model: str
    prompt_version: str
    generated_at: str      # ISO 8601 UTC
    files: tuple[FileEntry, ...]

    def to_json(self) -> dict:
        return {
            "generator_version": self.generator_version,
            "model": self.model,
            "prompt_version": self.prompt_version,
            "generated_at": self.generated_at,
            "files": [
                {"path": f.path, "sha256": f.sha256} for f in self.files
            ],
        }

    @classmethod
    def from_json(cls, data: dict) -> "Manifest":
        return cls(
            generator_version=data["generator_version"],
            model=data["model"],
            prompt_version=data["prompt_version"],
            generated_at=data["generated_at"],
            files=tuple(
                FileEntry(path=f["path"], sha256=f["sha256"])
                for f in data["files"]
            ),
        )


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_manifest(
    gateway_dir: Path,
    *,
    model: str,
    prompt_version: str,
    files: list[str],
) -> Manifest:
    """Build a manifest from files that have just been written."""
    entries = []
    for rel in files:
        p = gateway_dir / rel
        if p.is_file():
            entries.append(FileEntry(path=rel, sha256=sha256_of(p)))
    return Manifest(
        generator_version=FACTORY_VERSION,
        model=model,
        prompt_version=prompt_version,
        generated_at=now_iso(),
        files=tuple(entries),
    )


def read_manifest(gateway_dir: Path) -> Manifest | None:
    """Read the manifest if present. Raises on malformed manifest."""
    p = gateway_dir / MANIFEST_NAME
    if not p.is_file():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"{p}: manifest is malformed JSON ({exc}); refusing to touch "
            f"a gateway whose provenance cannot be read"
        ) from exc
    try:
        return Manifest.from_json(data)
    except (KeyError, TypeError) as exc:
        raise ValueError(
            f"{p}: manifest is missing required fields ({exc}); refusing "
            f"to touch a gateway whose provenance cannot be read"
        ) from exc


def write_manifest(gateway_dir: Path, manifest: Manifest) -> Path:
    p = gateway_dir / MANIFEST_NAME
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(
        json.dumps(manifest.to_json(), indent=2), encoding="utf-8"
    )
    tmp.replace(p)
    return p
FILE_EOF
echo "  wrote factory/provenance.py"

# ============================================================================
cat > "$REPO/factory/writer.py" <<'FILE_EOF'
"""Safe writer for factory-generated gateway files.

Three guarantees, in priority order:

1. Never destroy human edits. If the target file exists and its hash does
   not match what the manifest recorded, refuse. `--force` overrides.

2. Never write a file without provenance. After every successful write
   pass, the manifest is rewritten to reflect the new hashes.

3. Never leave a partially written file. All writes go through a temp
   file + os.replace (atomic on the same filesystem).
"""
from __future__ import annotations

import hashlib
from pathlib import Path

from .provenance import (
    MANIFEST_NAME,
    Manifest,
    build_manifest,
    read_manifest,
    sha256_of,
    write_manifest,
)


class OverwriteRefused(Exception):
    """Raised when a file has been edited since the factory wrote it, and
    the caller has not passed --force."""


class ForeignGateway(Exception):
    """Raised when a gateway directory exists but was not created by the
    factory (no manifest present), and --force was not passed."""


def _sha256_str(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def check_safe_to_write(gateway_dir: Path, *, force: bool) -> Manifest | None:
    """Decide whether the factory may write into `gateway_dir`.

    Returns the existing manifest (or None if the dir is new), or raises.
    """
    if not gateway_dir.exists():
        return None
    existing = read_manifest(gateway_dir)
    if existing is None:
        # Directory exists but no manifest. Either it's not a factory
        # gateway (template, hand-authored), or the manifest was deleted.
        # Either way, refuse unless explicitly overridden.
        if not force:
            raise ForeignGateway(
                f"{gateway_dir} exists but has no {MANIFEST_NAME}. It was "
                f"not created by the factory, or its provenance was "
                f"removed. Pass --force to overwrite."
            )
        return None
    return existing


def verify_no_edits(
    gateway_dir: Path, manifest: Manifest, *, force: bool
) -> list[str]:
    """Return a list of files whose current hash differs from the manifest.

    If any differ and force is False, raise OverwriteRefused.
    """
    edited: list[str] = []
    for entry in manifest.files:
        p = gateway_dir / entry.path
        if not p.is_file():
            continue  # deleted by human; allowed, will be regenerated
        if sha256_of(p) != entry.sha256:
            edited.append(entry.path)
    if edited and not force:
        raise OverwriteRefused(
            "the following files have been edited since the factory wrote "
            "them; refusing to overwrite:\n  "
            + "\n  ".join(edited)
            + "\n\nPass --force to overwrite anyway, or revert the edits."
        )
    return edited


def write_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(content, encoding="utf-8")
    tmp.replace(path)


def write_gateway(
    gateway_dir: Path,
    *,
    files: dict[str, str],
    model: str,
    prompt_version: str,
    force: bool,
) -> Manifest:
    """Write all files, then update the manifest.

    `files` maps relative paths to contents. Empty directories that need
    to exist (e.g. evals/golden/) are not part of `files`; create them
    separately.
    """
    existing = check_safe_to_write(gateway_dir, force=force)
    if existing is not None:
        verify_no_edits(gateway_dir, existing, force=force)

    gateway_dir.mkdir(parents=True, exist_ok=True)
    for rel, content in files.items():
        write_atomic(gateway_dir / rel, content)

    manifest = build_manifest(
        gateway_dir,
        model=model,
        prompt_version=prompt_version,
        files=list(files.keys()),
    )
    write_manifest(gateway_dir, manifest)
    return manifest
FILE_EOF
echo "  wrote factory/writer.py"

# ============================================================================
cat > "$REPO/factory/generate.py" <<'FILE_EOF'
"""Generate a draft gateway for a vertical.

Two modes:

  --from-json <path>   Read a discovery document produced elsewhere
                       (test fixture, or a prior LLM run captured to disk).
                       This is the deterministic path and the one to use
                       for testing.

  default              Call the configured LLM client to produce the
                       discovery document. The client is not bundled; the
                       operator wires it via ANCHORUM_FACTORY_LLM=module:callable.

Usage:
  python -m factory.generate --vertical transportation \
      --jurisdiction CA-QC --tier C --phi false \
      --from-json factory/examples/transportation_discovery.json

  # refuses to overwrite without --force:
  python -m factory.generate ... --force
"""
from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path

from . import FACTORY_VERSION
from .writer import OverwriteRefused, ForeignGateway, write_gateway


PROMPT_VERSION = "01_discovery/0.1.0"
DEFAULT_MODEL = "unspecified"


# --------------------------------------------------------------------- CLI

def _parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="factory.generate")
    p.add_argument("--vertical", required=True)
    p.add_argument("--jurisdiction", required=True)
    p.add_argument(
        "--tier",
        default="C",
        choices=["B", "C"],
        help="Factory never produces tier A. Manual promotion required.",
    )
    p.add_argument(
        "--phi",
        required=True,
        choices=["true", "false"],
        help="Explicit PHI handling flag. Never inferred. "
        "Required so the operator consciously decides.",
    )
    p.add_argument(
        "--from-json",
        dest="from_json",
        type=Path,
        default=None,
        help="Read discovery from a JSON file instead of calling an LLM.",
    )
    p.add_argument(
        "--gateways-dir",
        type=Path,
        default=None,
        help="Root for gateway output. Defaults to <repo>/gateways.",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite even if files have been edited since generation.",
    )
    return p.parse_args(argv)


def _base_gateways_dir() -> Path:
    import os
    env = os.environ.get("ANCHORUM_GATEWAYS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd() / "gateways"
    if cwd.is_dir():
        return cwd.resolve()
    return (Path(__file__).resolve().parent.parent / "gateways").resolve()


# ---------------------------------------------------------------- discovery

def load_discovery(args: argparse.Namespace) -> tuple[dict, str]:
    """Return (discovery_dict, model_identifier)."""
    if args.from_json:
        data = json.loads(args.from_json.read_text(encoding="utf-8"))
        return _validate_discovery(data), f"file://{args.from_json}"
    return _call_llm(args), _llm_identifier()


def _call_llm(args: argparse.Namespace) -> dict:
    import os
    target = os.environ.get("ANCHORUM_FACTORY_LLM")
    if not target:
        raise SystemExit(
            "no discovery source: pass --from-json <file> or set "
            "ANCHORUM_FACTORY_LLM=module:callable. The callable receives "
            "(vertical, jurisdiction, prompt_text) and returns a dict."
        )
    module_name, _, func_name = target.partition(":")
    if not module_name or not func_name:
        raise SystemExit(
            f"ANCHORUM_FACTORY_LLM={target!r} is not of the form "
            f"'module:callable'"
        )
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name)
    prompt_text = (Path(__file__).parent / "prompts" / "01_discovery.md").read_text()
    result = fn(args.vertical, args.jurisdiction, prompt_text)
    if not isinstance(result, dict):
        raise SystemExit("LLM callable did not return a dict")
    return _validate_discovery(result)


def _llm_identifier() -> str:
    import os
    return os.environ.get("ANCHORUM_FACTORY_LLM", DEFAULT_MODEL)


_REQUIRED_DISCOVERY_KEYS = {
    "documents", "actors", "regulations", "risk_patterns",
}


def _validate_discovery(data: dict) -> dict:
    if not isinstance(data, dict):
        raise SystemExit("discovery must be a mapping")
    missing = _REQUIRED_DISCOVERY_KEYS - data.keys()
    if missing:
        raise SystemExit(
            f"discovery missing keys: {sorted(missing)}"
        )
    for key in _REQUIRED_DISCOVERY_KEYS:
        if not isinstance(data[key], list):
            raise SystemExit(f"discovery.{key} must be a list")
    return data


# ------------------------------------------------------------- code generation

def render_gateway_yaml(
    args: argparse.Namespace, discovery: dict
) -> str:
    """Produce the gateway.yaml body.

    Design choices:
      - tier is fixed by CLI; factory never writes tier A.
      - phi_handling comes from CLI; never inferred from vertical name.
      - routes are derived from the discovery's declared routes.
      - retention_days_default is fixed at 2555 (7 years, conservative).
    """
    doc_entries: list[str] = []
    for d in discovery["documents"]:
        lines = [
            f"  - id: {d['id']}",
            f"    label: {json.dumps(d['label'])}",
            f"    match:",
            f"      filename_glob: {json.dumps(d['filename_glob'])}",
            f"      mime_types: {json.dumps(d.get('mime_types', ['*/*']))}",
            f"    required_fields:",
        ]
        for field in d["required_fields"]:
            lines.append(f"      - {field}")
        lines.append(f"    extractor: {d.get('extractor', 'pdf_text')}")
        lines.append(f"    retention_days: {int(d.get('retention_days', 2555))}")
        doc_entries.append("\n".join(lines))

    routes = discovery.get("routes") or ["QUARANTINE_REVIEW"]
    route_lines = "\n".join(f"  - {r}" for r in routes)

    return f"""# ANCHORUM-FACTORY-GENERATED
# generator: factory/{FACTORY_VERSION}
# prompt:    {PROMPT_VERSION}
# model:     {_llm_identifier()}
# This file will be refused for overwrite if edited by hand.
# Remove the "ANCHORUM-FACTORY-GENERATED" first line to opt out.

schema_version: "1.1"

identity:
  name: {args.vertical}
  version: "0.0.1-draft"
  jurisdiction: {args.jurisdiction}
  tier: {args.tier}
  description: >
    Draft gateway for {args.vertical} ({args.jurisdiction}).
    Generated by factory/{FACTORY_VERSION}. Requires domain-expert review
    before promotion to tier A.

routes:
{route_lines}

documents:
{chr(10).join(doc_entries)}

actors:
  path: actors.json
  required_roles: {json.dumps([a["id"] for a in discovery["actors"]])}

policy:
  path: policy.cel
  citations_path: regulations.json
  decision_log: true

risk:
  path: risk_patterns.json

evals:
  golden_dir: evals/golden/
  thresholds:
    _global:
      precision: 0.90
      recall: 0.85
      field_completeness: 0.95
      field_precision: 0.95

legal:
  privacy_jurisdictions: [{args.jurisdiction}]
  retention_days_default: 2555
  consent_required: false
  phi_handling: {args.phi}
"""


def render_policy_cel(discovery: dict) -> str:
    """Produce the policy.cel body.

    All rules are COMMENTED OUT. A fresh draft gateway loads (because a
    valid default block is present) but the default fires for every
    document, which fails every golden case until a human implements the
    real rules. This is intentional: a draft that silently passes is a
    draft that gets shipped.
    """
    lines: list[str] = [
        "// ANCHORUM-FACTORY-GENERATED",
        f"// generator: factory/{FACTORY_VERSION}",
        f"// prompt:    {PROMPT_VERSION}",
        f"// model:     {_llm_identifier()}",
        "",
        "// Every rule below is a commented-out skeleton. Uncomment, "
        "replace the `false` with the real condition, add the rule to the",
        "// golden set, and run evals. Do not ship a draft.",
        "",
    ]
    for i, r in enumerate(discovery["risk_patterns"], start=1):
        rid = r["id"]
        desc = r["description"]
        sev = r.get("severity", "info")
        lines.extend([
            f"// === rule: {rid} ===",
            f"// {desc}",
            "//",
            "// Replace `false` with the actual trigger condition, e.g.:",
            "//   'some_field' in fields && fields.some_field == \"value\"",
            "//",
            "// false",
            "//   ? {",
            f"//       \"route\": \"QUARANTINE_REVIEW\",",
            f"//       \"reason\": {json.dumps(desc)},",
            f"//       \"severity\": {json.dumps(sev)},",
            "//       \"citation\": \"UNVERIFIED\",",
            "//       \"fields_used\": []",
            "//     }",
            "//   : null",
            "// === end ===",
            "",
        ])

    lines.extend([
        "// === rule: default ===",
        "// MANDATORY. Do not delete. Fires when no rule matches.",
        "true",
        "  ? {",
        "      \"route\": \"QUARANTINE_REVIEW\",",
        "      \"reason\": \"Draft gateway: no rule matched\",",
        "      \"severity\": \"info\",",
        "      \"citation\": \"\",",
        "      \"fields_used\": []",
        "    }",
        "  : null",
        "// === end ===",
        "",
    ])
    return "\n".join(lines)


def render_actors_json(discovery: dict) -> str:
    out = {
        a["id"]: {
            "display": a.get("display", a["id"]),
            "patterns": a.get("patterns", []),
        }
        for a in discovery["actors"]
    }
    return json.dumps(out, indent=2) + "\n"


def render_regulations_json(discovery: dict) -> str:
    out = {}
    for r in discovery["regulations"]:
        out[r["id"]] = {
            "title": r.get("title", r["id"]),
            "status": r.get("status", "UNVERIFIED"),
            "url": r.get("url"),
        }
    return json.dumps(out, indent=2) + "\n"


def render_risk_patterns_json(discovery: dict) -> str:
    out = {
        r["id"]: {
            "description": r["description"],
            "severity": r.get("severity", "info"),
        }
        for r in discovery["risk_patterns"]
    }
    return json.dumps(out, indent=2) + "\n"


def render_review_queue_md(args: argparse.Namespace, discovery: dict) -> str:
    lines = [
        f"# {args.vertical} — review queue",
        "",
        f"Generated by factory/{FACTORY_VERSION} at {args.jurisdiction}.",
        "Tier: " + args.tier + ". PHI handling: " + args.phi + ".",
        "",
        "## Before this gateway can be promoted to tier A",
        "",
        "- [ ] Implement every rule in `policy.cel` (they are commented out).",
        "- [ ] Verify every citation in `regulations.json` (status field is "
        "`UNVERIFIED` until confirmed).",
        "- [ ] Add golden cases to `evals/golden/`. Every declared document "
        "type must be covered.",
        "- [ ] Run `python -m evals.run " + args.vertical + "` and reach "
        "`pass: true`.",
        "- [ ] Have a domain expert sign off on the schema, actors, "
        "policy, and risk patterns.",
        "- [ ] Confirm PHI handling: currently `" + args.phi + "`.",
        "",
        "## Per-item gaps reported by the generator",
        "",
    ]
    for d in discovery["documents"]:
        for g in d.get("gaps", []):
            lines.append(f"- document `{d['id']}`: {g}")
    for a in discovery["actors"]:
        for g in a.get("gaps", []):
            lines.append(f"- actor `{a['id']}`: {g}")
    for r in discovery["regulations"]:
        if r.get("status") == "UNVERIFIED":
            lines.append(f"- regulation `{r['id']}`: needs verification")
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------- entry

def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv if argv is not None else sys.argv[1:])
    gateways_dir = args.gateways_dir or _base_gateways_dir()
    gateway_dir = gateways_dir / args.vertical

    discovery, _ = load_discovery(args)
    # The model id used for the provenance header is whatever
    # _llm_identifier() returned at generation time.
    files = {
        "gateway.yaml": render_gateway_yaml(args, discovery),
        "policy.cel": render_policy_cel(discovery),
        "actors.json": render_actors_json(discovery),
        "regulations.json": render_regulations_json(discovery),
        "risk_patterns.json": render_risk_patterns_json(discovery),
        "REVIEW_QUEUE.md": render_review_queue_md(args, discovery),
    }
    try:
        manifest = write_gateway(
            gateway_dir,
            files=files,
            model=_llm_identifier(),
            prompt_version=PROMPT_VERSION,
            force=args.force,
        )
    except (OverwriteRefused, ForeignGateway) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    (gateway_dir / "evals" / "golden").mkdir(parents=True, exist_ok=True)

    print(f"wrote draft gateway: {gateway_dir}")
    print(f"  manifest: {len(manifest.files)} file(s)")
    print(f"  tier:     {args.tier}")
    print(f"  phi:      {args.phi}")
    print()
    print("Next:")
    print(f"  1. Implement rules in {gateway_dir}/policy.cel")
    print(f"  2. Add golden cases under {gateway_dir}/evals/golden/")
    print(f"  3. python -m evals.run {args.vertical} --allow-scaffold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
FILE_EOF
echo "  wrote factory/generate.py"

# ============================================================================
cat > "$REPO/factory/prompts/01_discovery.md" <<'FILE_EOF'
# Discovery prompt — v0.1.0

You are generating a **draft gateway** for the ANCHORUM Zero Trust platform.

## Inputs

- vertical: {{vertical}}
- jurisdiction: {{jurisdiction}}

## Your task

Produce a single JSON document describing what a gateway for this vertical
must contain. Return JSON only. No prose, no markdown fences, no commentary.

## Rules

1. **Be conservative.** A draft with three documents and an honest gap list
   is worth more than a draft with twenty documents and invented
   regulations.
2. **Never invent regulations.** If you are not certain a citation exists
   and applies, use the sentinel `"status": "UNVERIFIED"` and add it to the
   `gaps` list.
3. **Never infer PHI handling.** That is an operator decision, supplied
   outside this prompt.
4. **Every document, actor, and regulation may carry a `gaps` array.**
   Each entry names a specific thing a domain expert must verify. Empty is
   acceptable only when you are confident.
5. **`filename_glob`** uses fnmatch syntax. Prefer `*substring*` over
   `**/prefix*` because fnmatch does not implement recursive `**`.

## Output schema

```json
{
  "documents": [
    {
      "id": "snake_case_id",
      "label": "Human Label",
      "filename_glob": "*best_guess*",
      "mime_types": ["application/pdf"],
      "required_fields": ["field_one", "field_two"],
      "extractor": "pdf_text",
      "retention_days": 2555,
      "gaps": ["what a domain expert must verify"]
    }
  ],
  "actors": [
    {
      "id": "snake_case_role",
      "display": "Human Role",
      "patterns": ["keyword", "name@domain.example"],
      "gaps": []
    }
  ],
  "regulations": [
    {
      "id": "CITATION-ID",
      "title": "Full title of regulation",
      "status": "verified",
      "url": "https://... or null",
      "gaps": []
    }
  ],
  "risk_patterns": [
    {
      "id": "snake_case_id",
      "description": "What this pattern detects",
      "severity": "high",
      "gaps": []
    }
  ],
  "routes": ["QUARANTINE_REVIEW", "HOLD_FOR_REVIEW"]
}

FILE_EOF

echo
echo "==> apply_factory.sh complete"
