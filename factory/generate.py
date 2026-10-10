"""Factory CLI.

    python -m factory.generate keys init [--factory-name NAME] [--home PATH]
    python -m factory.generate keys show
    python -m factory.generate write --vertical X --jurisdiction Y ...
    python -m factory.generate plan  --vertical X --jurisdiction Y ...
"""
from __future__ import annotations

import argparse
import importlib
import json
import os
import sys
from pathlib import Path

import yaml

from . import FACTORY_VERSION
from . import keys as keys_mod
from . import schema as schema_mod
from .writer import WriteRefused, commit_write, plan_write
from .lifecycle import LifecycleError


PROMPT_VERSION = "01_discovery/0.1.0"
PROMPT_PATH = Path(__file__).parent / "prompts" / "01_discovery.md"


# --------------------------------------------------------------------- keys

def cmd_keys_init(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser().resolve()
    if (home / "root_private.key").exists() and not args.force:
        print(f"refused: keys already exist at {home}; use --force to regenerate",
              file=sys.stderr)
        return 2
    km = keys_mod.init_keys(home, factory_name=args.factory_name)
    print(f"root public key:    {km.root_public_hex}")
    print(f"  fingerprint:      {km.root_public_hex and keys_mod.fingerprint(km.root_public_hex)}")
    print(f"factory public key: {km.factory_public_hex}")
    print(f"  fingerprint:      {keys_mod.fingerprint(km.factory_public_hex)}")
    print()
    print(f"Wrote key material to {home}")
    print("IMPORTANT: move root_private.key to offline storage.")
    print("           root_public.hex and factory_certificate.json may be committed.")
    return 0


def cmd_keys_show(args: argparse.Namespace) -> int:
    home = Path(args.home).expanduser().resolve()
    km = keys_mod.load_keys(home)
    ok, reason = keys_mod.verify_certificate(km.certificate, km.root_public_hex)
    print(f"home:               {home}")
    print(f"root public key:    {km.root_public_hex}")
    print(f"  fingerprint:      {keys_mod.fingerprint(km.root_public_hex)}")
    print(f"factory public key: {km.factory_public_hex}")
    print(f"  fingerprint:      {keys_mod.fingerprint(km.factory_public_hex)}")
    print(f"factory name:       {km.certificate.factory_name}")
    print(f"valid:              {km.certificate.valid_from} -> {km.certificate.valid_until}")
    print(f"certificate:        {'OK' if ok else 'INVALID: ' + reason}")
    return 0 if ok else 1


# ----------------------------------------------------------------- discovery

def load_discovery(args: argparse.Namespace) -> schema_mod.Discovery:
    if args.from_json:
        p = Path(args.from_json)
        raw = json.loads(p.read_text(encoding="utf-8"))
        source = schema_mod.Source(
            type="file", identifier=str(p.resolve()),
            prompt_version=PROMPT_VERSION,
        )
        return schema_mod.validate_discovery(raw, source)

    target = os.environ.get("ANCHORUM_FACTORY_LLM")
    if not target:
        raise SystemExit(
            "no discovery source: pass --from-json <file> or set "
            "ANCHORUM_FACTORY_LLM=module:callable"
        )
    module_name, _, func_name = target.partition(":")
    if not module_name or not func_name:
        raise SystemExit(f"ANCHORUM_FACTORY_LLM={target!r} must be 'module:callable'")
    mod = importlib.import_module(module_name)
    fn = getattr(mod, func_name)
    prompt_text = PROMPT_PATH.read_text(encoding="utf-8")
    raw = fn(args.vertical, args.jurisdiction, prompt_text)
    source = schema_mod.Source(
        type="llm", identifier=target, prompt_version=PROMPT_VERSION,
    )
    return schema_mod.validate_discovery(raw, source)


# ---------------------------------------------------------------- renderers

def render_gateway_yaml(args, discovery: schema_mod.Discovery, source) -> str:
    docs = []
    for d in discovery.documents:
        docs.append({
            "id": d.id,
            "label": d.label,
            "match": {"filename_glob": d.filename_glob, "mime_types": list(d.mime_types)},
            "required_fields": list(d.required_fields),
            "extractor": d.extractor,
            "retention_days": d.retention_days,
        })
    spec = {
        "schema_version": "1.1",
        "identity": {
            "name": args.vertical,
            "version": "0.0.1-draft",
            "jurisdiction": args.jurisdiction,
            "tier": args.tier,
            "description": f"Draft gateway for {args.vertical} ({args.jurisdiction}).",
        },
        "routes": list(discovery.routes),
        "documents": docs,
        "actors": {
            "path": "actors.json",
            "required_roles": [a.id for a in discovery.actors],
        },
        "policy": {"path": "policy.cel", "citations_path": "regulations.json",
                   "decision_log": True},
        "risk": {"path": "risk_patterns.json"},
        "evals": {
            "golden_dir": "evals/golden/",
            "thresholds": {
                "_global": {
                    "precision": 0.90, "recall": 0.85,
                    "field_completeness": 0.95, "field_precision": 0.95,
                }
            },
        },
        "legal": {
            "privacy_jurisdictions": [args.jurisdiction],
            "retention_days_default": args.retention_days,
            "consent_required": False,
            "phi_handling": args.phi == "true",
        },
    }
    header = (
        f"# ANCHORUM-FACTORY-GENERATED\n"
        f"# generator: factory/{FACTORY_VERSION}\n"
        f"# prompt:    {PROMPT_VERSION}\n"
        f"# source:    {source.type}:{source.identifier}\n"
    )
    return header + yaml.safe_dump(spec, sort_keys=False, allow_unicode=True)


def render_policy_cel(discovery: schema_mod.Discovery, source) -> str:
    lines = [
        f"// ANCHORUM-FACTORY-GENERATED",
        f"// generator: factory/{FACTORY_VERSION}",
        f"// prompt:    {PROMPT_VERSION}",
        f"// source:    {source.type}:{source.identifier}",
        "",
        "// Rules below are commented-out skeletons. Uncomment, replace",
        "// `false` with the real condition, add the rule to the golden set,",
        "// and run evals. Do not ship a draft.",
        "",
    ]
    for r in discovery.risk_patterns:
        lines += [
            f"// === rule: {r.id} ===",
            f"// {r.description}",
            "//",
            "// false",
            "//   ? {",
            f"//       \"route\": \"QUARANTINE_REVIEW\",",
            f"//       \"reason\": {json.dumps(r.description)},",
            f"//       \"severity\": {json.dumps(r.severity)},",
            f"//       \"citation\": \"UNVERIFIED\",",
            f"//       \"fields_used\": []",
            "//     }",
            "//   : null",
            "// === end ===",
            "",
        ]
    lines += [
        "// === rule: default ===",
        "// MANDATORY. Do not delete.",
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
    ]
    return "\n".join(lines)


def render_actors_json(discovery: schema_mod.Discovery) -> str:
    out = {
        a.id: {"display": a.display, "patterns": list(a.patterns)}
        for a in discovery.actors
    }
    return json.dumps(out, indent=2) + "\n"


def render_regulations_json(discovery: schema_mod.Discovery) -> str:
    out = {
        r.id: {"title": r.title, "status": r.status, "url": r.url}
        for r in discovery.regulations
    }
    return json.dumps(out, indent=2) + "\n"


def render_risk_patterns_json(discovery: schema_mod.Discovery) -> str:
    out = {
        r.id: {"description": r.description, "severity": r.severity}
        for r in discovery.risk_patterns
    }
    return json.dumps(out, indent=2) + "\n"


def render_review_queue_md(args, discovery, source) -> str:
    lines = [
        f"# {args.vertical} — review queue",
        "",
        f"Generated by factory/{FACTORY_VERSION}.",
        f"Source:  {source.type}:{source.identifier}",
        f"Tier:    {args.tier}",
        f"PHI:     {args.phi}",
        "",
        "## Before this gateway can be promoted to tier A",
        "",
        "- [ ] Implement every rule in `policy.cel` (they are commented out).",
        "- [ ] Verify every citation in `regulations.json`; change `status` to `verified`.",
        "- [ ] Add golden cases under `evals/golden/` — one per declared type minimum.",
        "- [ ] Run `python -m evals.run " + args.vertical + "` and reach `pass: true`.",
        "- [ ] Domain expert sign-off on schema, actors, policy, risk patterns.",
        f"- [ ] Confirm PHI handling: currently `{args.phi}`.",
        "",
        "## Gaps reported by the discovery source",
        "",
    ]
    for d in discovery.documents:
        for g in d.gaps:
            lines.append(f"- document `{d.id}`: {g}")
    for a in discovery.actors:
        for g in a.gaps:
            lines.append(f"- actor `{a.id}`: {g}")
    for r in discovery.regulations:
        if r.status == "UNVERIFIED":
            lines.append(f"- regulation `{r.id}`: needs verification")
        for g in r.gaps:
            lines.append(f"- regulation `{r.id}`: {g}")
    for r in discovery.risk_patterns:
        for g in r.gaps:
            lines.append(f"- risk `{r.id}`: {g}")
    return "\n".join(lines) + "\n"


# ------------------------------------------------------------------- cli

def _add_common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--vertical", required=True)
    p.add_argument("--jurisdiction", required=True)
    p.add_argument("--tier", default="C", choices=["B", "C"])
    p.add_argument("--phi", required=True, choices=["true", "false"])
    p.add_argument("--retention-days", type=int, required=True)
    p.add_argument("--from-json", type=Path, default=None)
    p.add_argument("--gateways-dir", type=Path, default=None)
    p.add_argument("--factory-home", type=Path, default=None)
    p.add_argument("--force", action="store_true")
    p.add_argument("--acknowledge", default=None)


def _base_gateways_dir(args) -> Path:
    if args.gateways_dir:
        return args.gateways_dir.resolve()
    env = os.environ.get("ANCHORUM_GATEWAYS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd = Path.cwd() / "gateways"
    if cwd.is_dir():
        return cwd.resolve()
    return (Path(__file__).resolve().parent.parent / "gateways").resolve()


def _base_factory_home(args) -> Path:
    if args.factory_home:
        return args.factory_home.expanduser().resolve()
    return keys_mod.default_home()


def _base_log_path(home: Path) -> Path:
    env = os.environ.get("ANCHORUM_FACTORY_LOG")
    if env:
        return Path(env).expanduser().resolve()
    return home / "generation_log.jsonl"


def build_files(args, discovery, source) -> dict[str, str]:
    return {
        "gateway.yaml": render_gateway_yaml(args, discovery, source),
        "policy.cel": render_policy_cel(discovery, source),
        "actors.json": render_actors_json(discovery),
        "regulations.json": render_regulations_json(discovery),
        "risk_patterns.json": render_risk_patterns_json(discovery),
        "REVIEW_QUEUE.md": render_review_queue_md(args, discovery, source),
    }


def cmd_write(args: argparse.Namespace) -> int:
    gateways_dir = _base_gateways_dir(args)
    factory_home = _base_factory_home(args)
    log_path = _base_log_path(factory_home)
    gateway_dir = gateways_dir / args.vertical

    discovery = load_discovery(args)
    files = build_files(args, discovery, discovery.source)
    import hashlib
    inputs_sha256 = hashlib.sha256(discovery.canonical_json().encode()).hexdigest()

    try:
        manifest = commit_write(
            gateway_dir,
            files,
            inputs_sha256=inputs_sha256,
            source=discovery.source,
            force=args.force,
            acknowledge=args.acknowledge,
            factory_home=factory_home,
            log_path=log_path,
        )
    except (WriteRefused, LifecycleError) as exc:
        print(f"REFUSED: {exc}", file=sys.stderr)
        return 2

    print(f"wrote draft gateway: {gateway_dir}")
    print(f"  generation_id: {manifest.generation_id}")
    print(f"  lifecycle:     {manifest.lifecycle}")
    print(f"  files:         {len(manifest.files)}")
    print(f"  signed:        {'yes' if manifest.signature else 'no (no keys found)'}")
    print(f"  log entry:     {log_path}")
    return 0


def cmd_plan(args: argparse.Namespace) -> int:
    gateways_dir = _base_gateways_dir(args)
    gateway_dir = gateways_dir / args.vertical
    discovery = load_discovery(args)
    files = build_files(args, discovery, discovery.source)
    plan = plan_write(gateway_dir, files, force=args.force)
    print(plan.summary())
    if plan.is_destructive:
        print()
        print(f"To proceed: --force --acknowledge={plan.acknowledgement()}")
    return 0


# -------------------------------------------------------------------- main

def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv[1:]
    parser = argparse.ArgumentParser(prog="factory.generate")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_keys = sub.add_parser("keys", help="key management")
    keys_sub = p_keys.add_subparsers(dest="keys_cmd", required=True)
    ki = keys_sub.add_parser("init")
    ki.add_argument("--factory-name", default="local-dev")
    ki.add_argument("--home", type=Path, default=str(keys_mod.default_home()))
    ki.add_argument("--force", action="store_true")
    ki.set_defaults(func=cmd_keys_init)
    ks = keys_sub.add_parser("show")
    ks.add_argument("--home", type=Path, default=str(keys_mod.default_home()))
    ks.set_defaults(func=cmd_keys_show)

    pw = sub.add_parser("write", help="write a gateway")
    _add_common(pw)
    pw.set_defaults(func=cmd_write)

    pp = sub.add_parser("plan", help="show what a write would do")
    _add_common(pp)
    pp.set_defaults(func=cmd_plan)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
