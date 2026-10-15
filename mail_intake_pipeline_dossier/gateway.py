"""Gateway loader the only entry point for vertical configs.

A "gateway" is a directory under `gateways/<name>/` containing:
    gateway.yaml        the contract (validated by this loader)
    actors.json         actor classification rules
    policy.cel          policy decision rules (CEL, rule-block format)
    regulations.json    citation library referenced by policy.cel
    risk_patterns.json  risk flag definitions
    evals/golden/       golden test set

Schema versions
===============
1.0  Legacy. Loaded with a deprecation warning. Support will be removed
     in a future minor release. Migrate with `python -m
     dossier_pipeline.gateway_migrate <dir>`.

1.1  Current. Requires `routes:`, uses nested `evals.thresholds` under a
     mandatory `_global` scope, requires explicit `legal` keys with
     boolean `phi_handling`, and rejects duplicate YAML keys.
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


logger = logging.getLogger(__name__)


CURRENT_SCHEMA_VERSION = "1.1"
SUPPORTED_SCHEMA_VERSIONS = frozenset({"1.0", "1.1"})

_VALID_METRICS = frozenset(
    {"precision", "recall", "f1", "field_completeness", "field_precision"}
)
_VALID_TIERS = {"A", "B", "C"}
_VALID_CITATION_STATUSES = {"verified", "UNVERIFIED", "deprecated"}
_MIN_RETENTION_DAYS = 1

_LEGAL_REQUIRED_KEYS = {
    "privacy_jurisdictions",
    "retention_days_default",
    "consent_required",
    "phi_handling",
}

_REQUIRED_TOP_KEYS = {
    "schema_version",
    "identity",
    "documents",
    "actors",
    "policy",
    "risk",
    "evals",
    "legal",
}
_REQUIRED_IDENTITY_KEYS = {"name", "version", "jurisdiction", "tier"}


class GatewayError(Exception):
    """Raised on any gateway validation failure."""


@dataclass(frozen=True)
class DocumentSpec:
    id: str
    label: str
    filename_glob: str
    mime_types: tuple[str, ...]
    required_fields: tuple[str, ...]
    extractor: str
    retention_days: int


@dataclass(frozen=True)
class Gateway:
    name: str
    version: str
    jurisdiction: str
    tier: str
    description: str
    schema_version: str
    routes: frozenset[str]
    documents: tuple[DocumentSpec, ...]
    actors: dict[str, Any]
    policy_source: str
    policy_version: str
    citations: dict[str, Any]
    risk_patterns: dict[str, Any]
    evals_dir: Path
    thresholds: dict[str, dict[str, float]]
    legal: dict[str, Any]
    integrations: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def document_by_id(self) -> dict[str, DocumentSpec]:
        return {d.id: d for d in self.documents}


def load_gateway(
    name: str,
    *,
    base_path: Path | str | None = None,
) -> Gateway:
    """Load and validate a gateway by name.

    Raises GatewayError on any validation failure. Callers should treat
    this as a hard stop.
    """
    root = Path(base_path) if base_path else _base_gateways_dir()
    gw_dir = root / name
    if not gw_dir.is_dir():
        raise GatewayError(f"gateway directory not found: {gw_dir}")

    spec_path = gw_dir / "gateway.yaml"
    if not spec_path.is_file():
        raise GatewayError(f"missing gateway.yaml in {gw_dir}")

    spec = _load_yaml_strict(spec_path)
    if not isinstance(spec, dict):
        raise GatewayError(f"{spec_path}: top level must be a mapping")

    declared = spec.get("schema_version")
    if declared not in SUPPORTED_SCHEMA_VERSIONS:
        raise GatewayError(
            f"{spec_path}: schema_version {declared!r} not supported; "
            f"this loader accepts {sorted(SUPPORTED_SCHEMA_VERSIONS)}. "
            f"Run `python -m dossier_pipeline.gateway_migrate {gw_dir}` "
            f"to upgrade."
        )
    if declared == "1.0":
        logger.warning(
            "%s: gateway declares schema_version 1.0; support is "
            "deprecated. Run `python -m dossier_pipeline.gateway_migrate %s`.",
            spec_path,
            gw_dir,
        )

    _validate_top(spec, spec_path)
    tier = _validate_tier(spec["identity"]["tier"], spec_path)

    # Routes: required for 1.1, optional for 1.0 with a safe default.
    if declared == "1.1":
        routes = _validate_routes(spec.get("routes"), spec_path)
    else:
        routes = frozenset({"QUARANTINE_REVIEW", "HOLD_UNCLASSIFIED"})

    legal = _validate_legal(spec.get("legal"), spec_path, schema_version=declared)

    docs = _load_documents(spec, spec_path)
    for d, raw_d in zip(docs, spec["documents"]):
        _validate_retention(raw_d["retention_days"], d.id, spec_path)
    _detect_glob_overlaps(tuple(docs), spec_path)

    actors_path = _assert_contained(
        gw_dir / spec["actors"]["path"], gw_dir, spec_path
    )
    citations_path = _assert_contained(
        gw_dir / spec["policy"]["citations_path"], gw_dir, spec_path
    )
    risk_path = _assert_contained(
        gw_dir / spec["risk"]["path"], gw_dir, spec_path
    )
    policy_path = _assert_contained(
        gw_dir / spec["policy"]["path"], gw_dir, spec_path
    )
    evals_dir = _assert_contained(
        gw_dir / spec["evals"]["golden_dir"], gw_dir, spec_path
    )
    if not evals_dir.is_dir():
        raise GatewayError(f"{spec_path}: evals golden dir missing: {evals_dir}")

    actors = _load_json(actors_path, spec_path, "actors")
    citations = _validate_citations(
        _load_json(citations_path, spec_path, "citations"), spec_path
    )
    risk = _load_json(risk_path, spec_path, "risk_patterns")

    if not policy_path.is_file():
        raise GatewayError(f"{spec_path}: policy file missing: {policy_path}")
    policy_source = policy_path.read_text(encoding="utf-8")
    policy_version = _read_policy_version(policy_source) or "unversioned"

    thresholds = _validate_thresholds(
        spec["evals"]["thresholds"], spec_path, schema_version=declared
    )

    _validate_actor_roles(actors, spec["actors"].get("required_roles", []), spec_path)

    # Tier A gating: drafts and non-verified citations rejected.
    version = spec["identity"]["version"]
    if tier == "A":
        if "draft" in version.lower():
            raise GatewayError(
                f"{spec_path}: tier A gateway cannot declare a draft version "
                f"({version!r})"
            )
        for cid, cit in citations.items():
            if cit["status"] != "verified":
                raise GatewayError(
                    f"{spec_path}: tier A gateway requires all citations "
                    f"'verified'; {cid!r} is {cit['status']!r}"
                )

    return Gateway(
        name=spec["identity"]["name"],
        version=version,
        jurisdiction=spec["identity"]["jurisdiction"],
        tier=tier,
        description=str(spec["identity"].get("description", "")).strip(),
        schema_version=declared,
        routes=routes,
        documents=tuple(docs),
        actors=actors,
        policy_source=policy_source,
        policy_version=policy_version,
        citations=citations,
        risk_patterns=risk,
        evals_dir=evals_dir,
        thresholds=thresholds,
        legal=legal,
        integrations=tuple(spec.get("integrations", [])),
    )


# ----------------------------------------------------------------- helpers

def _base_gateways_dir() -> Path:
    """Resolve the gateways/ directory. Never derived from __file__.

    Order: ANCHORUM_GATEWAYS_DIR env, then ./gateways in cwd, then the
    repo layout as an editable-install fallback.
    """
    env = os.environ.get("ANCHORUM_GATEWAYS_DIR")
    if env:
        return Path(env).expanduser().resolve()
    cwd_candidate = Path.cwd() / "gateways"
    if cwd_candidate.is_dir():
        return cwd_candidate.resolve()
    return (Path(__file__).resolve().parent.parent / "gateways").resolve()


def _load_yaml_strict(path: Path) -> Any:
    """Parse YAML, rejecting duplicate mapping keys.

    `yaml.safe_load` silently keeps the last value. For a config file
    where a key appearing twice is a compliance event, that's the wrong
    failure mode.
    """
    text = path.read_text(encoding="utf-8")
    try:
        node = yaml.compose(text)
    except yaml.YAMLError as exc:
        raise GatewayError(f"{path}: invalid YAML - {exc}") from exc
    if node is not None:
        # yaml.compose cannot produce cycles from text; recursion is
        # bounded by the document.
        _reject_duplicate_keys(node, path)
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise GatewayError(f"{path}: invalid YAML - {exc}") from exc


def _reject_duplicate_keys(node: Any, path: Path) -> None:
    if isinstance(node, yaml.MappingNode):
        seen: set[Any] = set()
        for key_node, value_node in node.value:
            key = key_node.value
            if key in seen:
                raise GatewayError(f"{path}: duplicate key {key!r}")
            seen.add(key)
            _reject_duplicate_keys(value_node, path)
    elif isinstance(node, yaml.SequenceNode):
        for child in node.value:
            _reject_duplicate_keys(child, path)


def _validate_top(spec: dict, path: Path) -> None:
    missing = _REQUIRED_TOP_KEYS - spec.keys()
    if missing:
        raise GatewayError(f"{path}: missing top-level keys: {sorted(missing)}")
    ident = spec.get("identity")
    if not isinstance(ident, dict):
        raise GatewayError(f"{path}: identity must be a mapping")
    missing_ident = _REQUIRED_IDENTITY_KEYS - ident.keys()
    if missing_ident:
        raise GatewayError(
            f"{path}: identity missing keys: {sorted(missing_ident)}"
        )


def _validate_tier(tier: Any, path: Path) -> str:
    if tier not in _VALID_TIERS:
        raise GatewayError(
            f"{path}: tier {tier!r} invalid; must be one of {sorted(_VALID_TIERS)}"
        )
    return tier


def _validate_routes(raw: Any, path: Path) -> frozenset[str]:
    if not isinstance(raw, list) or not raw:
        raise GatewayError(f"{path}: `routes` must be a non-empty list")
    for r in raw:
        if not isinstance(r, str) or not r:
            raise GatewayError(
                f"{path}: route entries must be non-empty strings"
            )
    return frozenset(raw)


def _validate_legal(
    raw: Any, path: Path, *, schema_version: str
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise GatewayError(f"{path}: `legal` must be a mapping")
    if schema_version == "1.1":
        missing = _LEGAL_REQUIRED_KEYS - raw.keys()
        if missing:
            raise GatewayError(f"{path}: `legal` missing keys {sorted(missing)}")
    if not isinstance(raw.get("privacy_jurisdictions"), list):
        raise GatewayError(
            f"{path}: legal.privacy_jurisdictions must be a list"
        )
    if not isinstance(raw.get("phi_handling"), bool):
        raise GatewayError(
            f"{path}: legal.phi_handling must be an explicit boolean, "
            "never inferred from the vertical name"
        )
    if not isinstance(raw.get("consent_required"), bool):
        raise GatewayError(
            f"{path}: legal.consent_required must be a boolean"
        )
    try:
        n = int(raw["retention_days_default"])
    except (TypeError, ValueError, KeyError):
        raise GatewayError(f"{path}: legal.retention_days_default not an int")
    if n < _MIN_RETENTION_DAYS:
        raise GatewayError(
            f"{path}: legal.retention_days_default below minimum"
        )
    return dict(raw)


def _validate_thresholds(
    raw: Any, path: Path, *, schema_version: str
) -> dict[str, dict[str, float]]:
    if not isinstance(raw, dict) or not raw:
        raise GatewayError(
            f"{path}: evals.thresholds must be a non-empty mapping"
        )
    # 1.0 shape: flat mapping of metric -> float. Promote to nested.
    if schema_version == "1.0" or "_global" not in raw:
        promoted = {"_global": raw}
    else:
        promoted = raw
    out: dict[str, dict[str, float]] = {}
    for scope, metrics in promoted.items():
        if not isinstance(metrics, dict) or not metrics:
            raise GatewayError(
                f"{path}: threshold scope {scope!r} must be a non-empty mapping"
            )
        unknown = set(metrics) - _VALID_METRICS
        if unknown:
            raise GatewayError(
                f"{path}: threshold scope {scope!r} has unknown metrics "
                f"{sorted(unknown)}; valid metrics are {sorted(_VALID_METRICS)}"
            )
        parsed: dict[str, float] = {}
        for k, v in metrics.items():
            try:
                f = float(v)
            except (TypeError, ValueError):
                raise GatewayError(
                    f"{path}: threshold {scope}.{k} is not numeric: {v!r}"
                )
            if not 0.0 <= f <= 1.0:
                raise GatewayError(
                    f"{path}: threshold {scope}.{k}={f} outside [0, 1]"
                )
            parsed[k] = f
        out[scope] = parsed
    return out


def _validate_citations(raw: Any, path: Path) -> dict[str, dict]:
    if not isinstance(raw, dict):
        raise GatewayError(
            f"{path}: regulations.json top level must be an object"
        )
    for cid, val in raw.items():
        if not isinstance(val, dict):
            raise GatewayError(
                f"{path}: citation {cid!r} must be a mapping, got "
                f"{type(val).__name__}"
            )
        if "status" not in val:
            raise GatewayError(f"{path}: citation {cid!r} missing `status`")
        if val["status"] not in _VALID_CITATION_STATUSES:
            raise GatewayError(
                f"{path}: citation {cid!r} status {val['status']!r} invalid; "
                f"valid: {sorted(_VALID_CITATION_STATUSES)}"
            )
    return raw


def _validate_retention(days: Any, doc_id: str, path: Path) -> int:
    try:
        n = int(days)
    except (TypeError, ValueError):
        raise GatewayError(
            f"{path}: documents[{doc_id}].retention_days not an int: {days!r}"
        )
    if n < _MIN_RETENTION_DAYS:
        raise GatewayError(
            f"{path}: documents[{doc_id}].retention_days={n} below "
            f"minimum {_MIN_RETENTION_DAYS}"
        )
    return n


def _assert_contained(child: Path, parent: Path, spec_path: Path) -> Path:
    resolved = child.resolve()
    parent_resolved = parent.resolve()
    try:
        resolved.relative_to(parent_resolved)
    except ValueError:
        raise GatewayError(
            f"{spec_path}: path {child!r} resolves outside the gateway "
            f"directory ({parent_resolved})"
        )
    return resolved


def _detect_glob_overlaps(docs: tuple[DocumentSpec, ...], path: Path) -> None:
    """Heuristic overlap detection for filename_globs.

    Full glob-overlap detection is undecidable in general. This catches
    the common case (one glob is a prefix of another after stripping
    trailing `*`). Character classes (`[...]`, `?`) are not analyzed;
    that's a documented limitation.
    """
    for i, a in enumerate(docs):
        for b in docs[i + 1 :]:
            ga = a.filename_glob.rstrip("*").rstrip("/")
            gb = b.filename_glob.rstrip("*").rstrip("/")
            if ga and gb and (ga.startswith(gb) or gb.startswith(ga)):
                raise GatewayError(
                    f"{path}: documents {a.id!r} and {b.id!r} have "
                    f"overlapping filename_globs ({a.filename_glob!r}, "
                    f"{b.filename_glob!r}); classification would be "
                    f"order-dependent"
                )


def _load_documents(spec: dict, path: Path) -> list[DocumentSpec]:
    raw = spec.get("documents")
    if not isinstance(raw, list) or not raw:
        raise GatewayError(f"{path}: documents must be a non-empty list")
    seen: set[str] = set()
    out: list[DocumentSpec] = []
    for i, d in enumerate(raw):
        if not isinstance(d, dict):
            raise GatewayError(f"{path}: documents[{i}] must be a mapping")
        for key in (
            "id",
            "label",
            "match",
            "required_fields",
            "extractor",
            "retention_days",
        ):
            if key not in d:
                raise GatewayError(
                    f"{path}: documents[{i}] missing key {key!r}"
                )
        if d["id"] in seen:
            raise GatewayError(f"{path}: duplicate document id {d['id']!r}")
        seen.add(d["id"])
        match = d["match"]
        if not isinstance(match, dict) or "filename_glob" not in match:
            raise GatewayError(
                f"{path}: documents[{i}].match missing filename_glob"
            )
        out.append(
            DocumentSpec(
                id=d["id"],
                label=d["label"],
                filename_glob=match["filename_glob"],
                mime_types=tuple(match.get("mime_types", ["*/*"])),
                required_fields=tuple(d["required_fields"]),
                extractor=d["extractor"],
                retention_days=int(d["retention_days"]),
            )
        )
    return out


def _load_json(path: Path, spec_path: Path, kind: str) -> dict[str, Any]:
    if not path.is_file():
        raise GatewayError(f"{spec_path}: {kind} file missing: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise GatewayError(f"{path}: invalid JSON - {exc}") from exc
    if not isinstance(data, dict):
        raise GatewayError(f"{path}: top level must be an object")
    return data


def _validate_actor_roles(
    actors: dict[str, Any], required: list[str], path: Path
) -> None:
    if not required:
        return
    present = set(actors.keys())
    missing = set(required) - present
    if missing:
        raise GatewayError(
            f"{path}: actors.json missing required roles: {sorted(missing)}"
        )


def _read_policy_version(source: str) -> str | None:
    import re

    pat = re.compile(r"^\s*//\s*policy-version:\s*(\S+)\s*$")
    found: str | None = None
    for line in source.splitlines():
        m = pat.match(line)
        if m:
            if found is not None:
                raise GatewayError(
                    "policy source has multiple `// policy-version:` headers"
                )
            found = m.group(1)
    return found
