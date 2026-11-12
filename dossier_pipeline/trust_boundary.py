"""
Dossier DOSSIER-PIPELINE Trust Boundary Contract

Defines the schema-level roles for fields that may appear in governed output.
The goal is to make export eligibility deterministic instead of relying only on
string-based leakage heuristics.
"""

from __future__ import annotations

import os as _os
from dataclasses import dataclass
from typing import Final, Iterable

try:
    from .config import load_config
except ImportError:  # pragma: no cover - fallback for direct execution / tests
    def load_config():
        return {}

BOUNDARY_CONTRACT_VERSION: Final[str] = "1.0.0"


@dataclass(frozen=True)
class BoundaryFieldRole:
    field_name: str
    role: str


@dataclass(frozen=True)
class TrustBoundaryContract:
    version: str
    internal_only_fields: tuple[str, ...]
    exportable_fields: tuple[str, ...]
    regulated_fields: tuple[str, ...]

    def is_internal_only(self, field_name: str) -> bool:
        return field_name in self.internal_only_fields

    def is_exportable(self, field_name: str) -> bool:
        return field_name in self.exportable_fields

    def is_regulated(self, field_name: str) -> bool:
        return field_name in self.regulated_fields

    def get_role(self, field_name: str) -> str:
        if self.is_internal_only(field_name):
            return "internal_only"
        if self.is_regulated(field_name):
            return "regulated"
        if self.is_exportable(field_name):
            return "exportable"
        return "unknown"


DEFAULT_CONTRACT = TrustBoundaryContract(
    version=BOUNDARY_CONTRACT_VERSION,
    internal_only_fields=(
        "decision_reasoning",
        "decision_trace",
        "payload_hash",
        "previous_hash",
        "control_hash",
        "trace",
        # W3 §7.6: analysis and extracted text never enter a pipeline payload
        # today, but `validate_export_fields` is a denylist — anything not named
        # here passes through `_public_payload` and into `export_json` /
        # `export_markdown_summary`. Naming them here guarantees that if they
        # are ever added for convenience, they export redacted rather than in
        # the clear. The two hashes are digests, not inert: F-18 found a hash
        # being published as if it were metadata, and a digest lets a reader
        # confirm a guessed document against the record.
        "extract_text",
        "extract_error",
        "analysis_json",
        "extract_text_path",
        "extract_sha256",
        "analysis_rules_hash",
        "analysis_config_hash",
    ),
    exportable_fields=(
        "dossier_id",
        "message_key",
        "message_id",
        "subject",
        "sender",
        "recipient",
        "date",
        "actor",
        "labels",
        "confidence",
        "route",
        "policy",
        "record_hash",
        "raw_sha256",
        "body_preview",
        "received_count",
        "received_first_ts",
        "received_last_ts",
        "received_chain_fingerprint_b64",
        # The record's account of what was received, and which envelope fields
        # were invented rather than observed. `synthesised_fields` in particular
        # is the honesty signal: it must travel with the record, not be stripped
        # from it. Document text and its digest do NOT belong here - if they are
        # ever put in a payload they must be named in `internal_only_fields`.
        "source_sha256",
        "source_bytes",
        "source_filename",
        "source_media_type",
        "transport",
        "synthesised_fields",
        "classification_scope_warning",
    ),
    regulated_fields=(
        "original_message_id",
        "ingest_time",
        "missing_fields",
        "human_review",
        "quarantine",
    ),
)


def normalize_field_name(field_name: str) -> str:
    return field_name.strip().lower()


def get_contract() -> TrustBoundaryContract:
    return DEFAULT_CONTRACT


def classify_field(field_name: str) -> BoundaryFieldRole:
    normalized = normalize_field_name(field_name)
    return BoundaryFieldRole(field_name=normalized, role=get_contract().get_role(normalized))


def allowed_export_fields() -> tuple[str, ...]:
    return get_contract().exportable_fields


def regulated_export_fields() -> tuple[str, ...]:
    return get_contract().regulated_fields


def internal_only_fields() -> tuple[str, ...]:
    return get_contract().internal_only_fields


def validate_export_fields(field_names: Iterable[str]) -> tuple[str, ...]:
    contract = get_contract()
    rejected: list[str] = []
    for field_name in field_names:
        normalized = normalize_field_name(field_name)
        if contract.is_internal_only(normalized):
            rejected.append(normalized)
    return tuple(rejected)


def _config() -> dict:
    cfg = load_config()
    cfg.setdefault("dossier_id", "INTERFACE")
    # §7.7 / F-11 residual: a CWD-relative default means two processes started
    # from two directories write pipeline state to two places. `ANCHORUM_OUTPUT_DIR`
    # lets a deployment pin one absolute root regardless of CWD. Unset in local
    # dev and in tests, so nothing changes there — `_pipeline_config` still
    # resolves whatever value ends up here.
    cfg.setdefault(
        "output_dir",
        _os.environ.get("ANCHORUM_OUTPUT_DIR") or "./output",
    )
    cfg.setdefault("email", "interface@localhost")
    return cfg
