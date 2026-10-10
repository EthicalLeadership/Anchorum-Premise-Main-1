"""Strict validation of discovery documents.

Every value from the discovery source (LLM or file) is untrusted. This
module converts raw JSON into typed dataclasses. Anything that doesn't
conform is rejected before any file is written.

Identifiers are pattern-checked; lists have min/max; enums are enforced;
strings that will be emitted into YAML/JSON must not contain characters
that break those formats.
"""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from typing import Any

_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_FIELD_RE = _ID_RE
_CITATION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-]{0,127}$")
_ROUTE_RE = re.compile(r"^[A-Z][A-Z0-9_]{0,63}$")

MAX_LIST_ITEMS = 500
MAX_STRING_LEN = 500

VALID_SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
VALID_CITATION_STATUSES = frozenset({"verified", "UNVERIFIED", "deprecated"})
VALID_EXTRACTORS = frozenset({"pdf_text", "pdf_form", "ocr", "csv", "json"})


class SchemaError(ValueError):
    pass


@dataclass(frozen=True)
class DocumentSpec:
    id: str
    label: str
    filename_glob: str
    mime_types: tuple[str, ...]
    required_fields: tuple[str, ...]
    extractor: str
    retention_days: int
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class ActorSpec:
    id: str
    display: str
    patterns: tuple[str, ...]
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class RegulationSpec:
    id: str
    title: str
    status: str
    url: str | None
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class RiskSpec:
    id: str
    description: str
    severity: str
    gaps: tuple[str, ...]


@dataclass(frozen=True)
class Source:
    type: str
    identifier: str
    prompt_version: str


@dataclass(frozen=True)
class Discovery:
    documents: tuple[DocumentSpec, ...]
    actors: tuple[ActorSpec, ...]
    regulations: tuple[RegulationSpec, ...]
    risk_patterns: tuple[RiskSpec, ...]
    routes: tuple[str, ...]
    source: Source

    def canonical_json(self) -> str:
        """Deterministic serialization for hashing; excludes source."""
        return json.dumps(
            {
                "documents": [asdict(d) for d in self.documents],
                "actors": [asdict(a) for a in self.actors],
                "regulations": [asdict(r) for r in self.regulations],
                "risk_patterns": [asdict(r) for r in self.risk_patterns],
                "routes": list(self.routes),
            },
            sort_keys=True, separators=(",", ":"),
        )


# ------------------------------------------------------------------ helpers

def _req_str(obj: dict, key: str, where: str, *, allow_empty: bool = False) -> str:
    v = obj.get(key)
    if not isinstance(v, str):
        raise SchemaError(f"{where}: {key!r} must be a string, got {type(v).__name__}")
    if not allow_empty and not v.strip():
        raise SchemaError(f"{where}: {key!r} must be non-empty")
    if len(v) > MAX_STRING_LEN:
        raise SchemaError(f"{where}: {key!r} exceeds {MAX_STRING_LEN} chars")
    return v


def _req_id(obj: dict, key: str, where: str, *, pattern: re.Pattern = _ID_RE) -> str:
    v = _req_str(obj, key, where)
    if not pattern.match(v):
        raise SchemaError(f"{where}: {key!r}={v!r} must match {pattern.pattern}")
    return v


def _req_list_str(
    obj: dict, key: str, where: str, *,
    min_items: int = 0, max_items: int = MAX_LIST_ITEMS,
    item_pattern: re.Pattern | None = None,
) -> tuple[str, ...]:
    v = obj.get(key, [])
    if not isinstance(v, list):
        raise SchemaError(f"{where}: {key!r} must be a list")
    if len(v) < min_items:
        raise SchemaError(f"{where}: {key!r} needs >= {min_items} items")
    if len(v) > max_items:
        raise SchemaError(f"{where}: {key!r} exceeds {max_items} items")
    out: list[str] = []
    for i, item in enumerate(v):
        if not isinstance(item, str):
            raise SchemaError(f"{where}.{key}[{i}]: must be a string")
        if not item.strip():
            raise SchemaError(f"{where}.{key}[{i}]: must be non-empty")
        if len(item) > MAX_STRING_LEN:
            raise SchemaError(f"{where}.{key}[{i}]: exceeds {MAX_STRING_LEN} chars")
        if item_pattern and not item_pattern.match(item):
            raise SchemaError(
                f"{where}.{key}[{i}]={item!r} must match {item_pattern.pattern}"
            )
        out.append(item)
    return tuple(out)


# ---------------------------------------------------------------- top level

def validate_discovery(raw: Any, source: Source) -> Discovery:
    if not isinstance(raw, dict):
        raise SchemaError("discovery: top level must be a mapping")
    for key in ("documents", "actors", "regulations", "risk_patterns"):
        if key not in raw:
            raise SchemaError(f"discovery: missing key {key!r}")
        if not isinstance(raw[key], list) or not raw[key]:
            raise SchemaError(f"discovery: {key!r} must be a non-empty list")

    documents = tuple(_validate_document(d, i) for i, d in enumerate(raw["documents"]))
    actors = tuple(_validate_actor(a, i) for i, a in enumerate(raw["actors"]))
    regulations = tuple(_validate_regulation(r, i) for i, r in enumerate(raw["regulations"]))
    risks = tuple(_validate_risk(r, i) for i, r in enumerate(raw["risk_patterns"]))

    routes_raw = raw.get("routes", ["QUARANTINE_REVIEW"])
    routes = _req_list_str(
        {"routes": routes_raw}, "routes", "discovery",
        min_items=1, max_items=50, item_pattern=_ROUTE_RE,
    )

    _check_unique("documents", [d.id for d in documents])
    _check_unique("actors", [a.id for a in actors])
    _check_unique("regulations", [r.id for r in regulations])
    _check_unique("risk_patterns", [r.id for r in risks])

    return Discovery(
        documents=documents, actors=actors, regulations=regulations,
        risk_patterns=risks, routes=routes, source=source,
    )


def _check_unique(what: str, ids: list[str]) -> None:
    seen: set[str] = set()
    for i in ids:
        if i in seen:
            raise SchemaError(f"discovery.{what}: duplicate id {i!r}")
        seen.add(i)


def _validate_document(d: Any, i: int) -> DocumentSpec:
    where = f"documents[{i}]"
    if not isinstance(d, dict):
        raise SchemaError(f"{where}: must be a mapping")
    doc_id = _req_id(d, "id", where)
    label = _req_str(d, "label", where)
    glob = _req_str(d, "filename_glob", where)
    if "/../" in glob or glob.startswith("/"):
        raise SchemaError(f"{where}.filename_glob: must not be absolute or traverse")
    mimes = _req_list_str(d, "mime_types", where, min_items=1)
    fields = _req_list_str(d, "required_fields", where, min_items=1, item_pattern=_FIELD_RE)
    extractor = _req_str(d, "extractor", where)
    if extractor not in VALID_EXTRACTORS:
        raise SchemaError(f"{where}.extractor={extractor!r} not in {sorted(VALID_EXTRACTORS)}")
    retention = d.get("retention_days")
    if not isinstance(retention, int) or isinstance(retention, bool):
        raise SchemaError(f"{where}.retention_days must be an int")
    if not 1 <= retention <= 36500:
        raise SchemaError(f"{where}.retention_days must be 1..36500")
    gaps = _req_list_str(d, "gaps", where, min_items=0)
    return DocumentSpec(
        id=doc_id, label=label, filename_glob=glob, mime_types=mimes,
        required_fields=fields, extractor=extractor,
        retention_days=retention, gaps=gaps,
    )


def _validate_actor(a: Any, i: int) -> ActorSpec:
    where = f"actors[{i}]"
    if not isinstance(a, dict):
        raise SchemaError(f"{where}: must be a mapping")
    return ActorSpec(
        id=_req_id(a, "id", where),
        display=_req_str(a, "display", where),
        patterns=_req_list_str(a, "patterns", where, min_items=1),
        gaps=_req_list_str(a, "gaps", where, min_items=0),
    )


def _validate_regulation(r: Any, i: int) -> RegulationSpec:
    where = f"regulations[{i}]"
    if not isinstance(r, dict):
        raise SchemaError(f"{where}: must be a mapping")
    rid = _req_id(r, "id", where, pattern=_CITATION_RE)
    status = _req_str(r, "status", where)
    if status not in VALID_CITATION_STATUSES:
        raise SchemaError(f"{where}.status={status!r} not in {sorted(VALID_CITATION_STATUSES)}")
    url = r.get("url")
    if url is not None and not isinstance(url, str):
        raise SchemaError(f"{where}.url must be a string or null")
    return RegulationSpec(
        id=rid, title=_req_str(r, "title", where), status=status, url=url,
        gaps=_req_list_str(r, "gaps", where, min_items=0),
    )


def _validate_risk(r: Any, i: int) -> RiskSpec:
    where = f"risk_patterns[{i}]"
    if not isinstance(r, dict):
        raise SchemaError(f"{where}: must be a mapping")
    sev = _req_str(r, "severity", where)
    if sev not in VALID_SEVERITIES:
        raise SchemaError(f"{where}.severity={sev!r} not in {sorted(VALID_SEVERITIES)}")
    return RiskSpec(
        id=_req_id(r, "id", where),
        description=_req_str(r, "description", where),
        severity=sev,
        gaps=_req_list_str(r, "gaps", where, min_items=0),
    )
