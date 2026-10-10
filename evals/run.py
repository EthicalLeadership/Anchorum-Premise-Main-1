"""Golden-set evaluator for ANCHORUM gateways.

Metrics contract
================
Reported per declared document type:
    n                    - number of golden cases covering this type
    tp, fp, fn           - raw counts, kept for debugging
    precision, recall, f1
    field_completeness, field_precision
    untested             - True when n == 0; forces gate failure

Reported globally:
    coverage             - fraction of declared types with n > 0
    decision_accuracy    - None when decision_cases == 0, never 1.0
    extractor_mode       - "stub" or "real"
    micro, macro         - aggregate metrics; macro ignores untested types

Failure rules (any of these set pass=False):
    F1. Any declared type has n == 0 (untested)
    F2. Any declared type falls below its per-type or global threshold
    F3. Rules exist but no golden case exercised a decision
    F4. extractor_mode == "stub" without --allow-scaffold
    F5. Any undeclared prediction was emitted by the classifier
    F6. Any golden's expected.decision.route is not a declared route

Threshold semantics
===================
`evals.thresholds._global` is a floor applied to each per-type metric,
not to the macro average. A gateway with one 0.99 type and one 0.40 type
fails; it does not average its way to a pass.

Clock injection
===============
Every golden case must carry `evaluated_at` (epoch seconds, int, >= 0).
The harness passes it to PolicyRuntime.decide(now=...). No wall clock is
read. Re-running the same commit on the same goldens yields the same
numbers.
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Callable, Protocol

from dossier_pipeline.gateway import Gateway, DocumentSpec, load_gateway
from dossier_pipeline.policy_runtime import PolicyRuntime


class Classifier(Protocol):
    def __call__(self, case_input: dict, gateway: Gateway) -> str | None: ...


class Extractor(Protocol):
    def __call__(self, case_input: dict, doc_spec: DocumentSpec) -> dict[str, Any]: ...


_UNCLASSIFIED = "__unclassified__"


def run(
    gateway_name: str,
    *,
    classifier: Classifier | None = None,
    extractor: Extractor | None = None,
    allow_scaffold: bool = False,
) -> dict:
    """Run the golden set. Returns the report. Never raises on document input;
    raises SystemExit on malformed gateway or golden files (fail-loud at load)."""
    gw = load_gateway(gateway_name)
    extractor_mode = "real" if extractor is not None else "stub"
    classifier = classifier or _filename_classifier
    extractor = extractor or _golden_fields_extractor

    cases = _load_goldens(gw)
    if not cases:
        raise SystemExit(f"no golden cases in {gw.evals_dir}")

    runtime = PolicyRuntime(
        gw.policy_source,
        allowed_routes=gw.routes,
        policy_version=gw.policy_version,
    )

    declared_types = {d.id for d in gw.documents}
    counts: dict[str, dict[str, int]] = defaultdict(
        lambda: {"tp": 0, "fp": 0, "fn": 0}
    )
    completeness: dict[str, list[float]] = defaultdict(list)
    field_precision: dict[str, list[float]] = defaultdict(list)
    undeclared_predictions: list[dict] = []
    golden_route_errors: list[dict] = []
    decision_total = 0
    decision_correct = 0

    for case in cases:
        case_id = case["id"]
        expected_type = case["expected"]["document_type"]

        if "decision" in case["expected"]:
            r = case["expected"]["decision"].get("route")
            if r not in gw.routes:
                golden_route_errors.append(
                    {"case_id": case_id, "expected_route": r}
                )

        predicted_type = classifier(case["input"], gw)

        if predicted_type == expected_type:
            counts[expected_type]["tp"] += 1
        else:
            counts[expected_type]["fn"] += 1
            if predicted_type is None:
                pass
            elif predicted_type in declared_types:
                counts[predicted_type]["fp"] += 1
            else:
                counts[_UNCLASSIFIED]["fp"] += 1
                undeclared_predictions.append(
                    {
                        "case_id": case_id,
                        "expected": expected_type,
                        "predicted": predicted_type,
                    }
                )

        doc_spec = gw.document_by_id.get(expected_type)
        if doc_spec is None:
            continue
        extracted = extractor(case["input"], doc_spec)

        expected_present = set(case["expected"].get("fields_present", []))
        extracted_keys = set(extracted.keys())
        if expected_present:
            completeness[expected_type].append(
                len(expected_present & extracted_keys) / len(expected_present)
            )
        extra = extracted_keys - expected_present
        if extracted_keys:
            field_precision[expected_type].append(
                1.0 - len(extra) / len(extracted_keys)
            )

        if predicted_type == expected_type and "decision" in case["expected"]:
            decision = runtime.decide(extracted, now=int(case["evaluated_at"]))
            decision_total += 1
            if decision.route == case["expected"]["decision"]["route"]:
                decision_correct += 1

    return _build_report(
        gateway_name=gateway_name,
        gateway_version=gw.version,
        policy_version=runtime.policy_version,
        extractor_mode=extractor_mode,
        counts=dict(counts),
        completeness=dict(completeness),
        field_precision=dict(field_precision),
        decision_correct=decision_correct,
        decision_total=decision_total,
        thresholds=gw.thresholds,
        declared_types=declared_types,
        undeclared_predictions=undeclared_predictions,
        golden_route_errors=golden_route_errors,
        allow_scaffold=allow_scaffold,
        has_rules=runtime.rule_count() > 0,
    )


def _build_report(
    *,
    gateway_name: str,
    gateway_version: str,
    policy_version: str,
    extractor_mode: str,
    counts: dict,
    completeness: dict,
    field_precision: dict,
    decision_correct: int,
    decision_total: int,
    thresholds: dict,
    declared_types: set,
    undeclared_predictions: list,
    golden_route_errors: list,
    allow_scaffold: bool,
    has_rules: bool,
) -> dict:
    per_type: dict[str, dict] = {}
    tested_types = 0
    tp_sum = fp_sum = fn_sum = 0

    for t in sorted(declared_types):
        c = counts.get(t, {"tp": 0, "fp": 0, "fn": 0})
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        n = tp + fn
        if n > 0:
            tested_types += 1
        tp_sum += tp
        fp_sum += fp
        fn_sum += fn

        precision = tp / (tp + fp) if (tp + fp) else 1.0
        recall = tp / (tp + fn) if (tp + fn) else 1.0
        f1 = (
            2 * precision * recall / (precision + recall)
            if (precision + recall)
            else 0.0
        )
        fc = completeness.get(t, [])
        fpk = field_precision.get(t, [])

        per_type[t] = {
            "n": n,
            "tp": tp,
            "fp": fp,
            "fn": fn,
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "field_completeness": sum(fc) / len(fc) if fc else 0.0,
            "field_precision": sum(fpk) / len(fpk) if fpk else 0.0,
            "untested": n == 0,
        }

    u = counts.get(_UNCLASSIFIED, {"tp": 0, "fp": 0, "fn": 0})
    if u["fp"]:
        per_type[_UNCLASSIFIED] = {
            "n": 0,
            "tp": 0,
            "fp": u["fp"],
            "fn": 0,
            "precision": 0.0,
            "recall": 0.0,
            "f1": 0.0,
            "field_completeness": 0.0,
            "field_precision": 0.0,
            "untested": True,
        }
        fp_sum += u["fp"]

    micro_precision = tp_sum / (tp_sum + fp_sum) if (tp_sum + fp_sum) else 0.0
    micro_recall = tp_sum / (tp_sum + fn_sum) if (tp_sum + fn_sum) else 0.0
    micro_f1 = (
        2 * micro_precision * micro_recall / (micro_precision + micro_recall)
        if (micro_precision + micro_recall)
        else 0.0
    )

    macro = {
        m: (
            sum(v[m] for v in per_type.values() if not v["untested"])
            / max(tested_types, 1)
        )
        for m in (
            "precision",
            "recall",
            "f1",
            "field_completeness",
            "field_precision",
        )
    }

    coverage = tested_types / len(declared_types) if declared_types else 0.0
    decision_accuracy = (
        decision_correct / decision_total if decision_total else None
    )

    failures: list[dict] = []

    for t, m in per_type.items():
        if t != _UNCLASSIFIED and m["untested"]:
            failures.append(
                {
                    "scope": t,
                    "metric": "coverage",
                    "actual": 0,
                    "required": 1,
                    "reason": "declared type has no golden cases",
                }
            )

    global_floor = thresholds.get("_global", {})
    for t, m in per_type.items():
        if t == _UNCLASSIFIED:
            continue
        scoped = thresholds.get(t, {})
        for metric, floor in {**global_floor, **scoped}.items():
            actual = m.get(metric, 0.0)
            if actual < floor:
                failures.append(
                    {
                        "scope": t,
                        "metric": metric,
                        "actual": actual,
                        "required": floor,
                    }
                )

    if has_rules and decision_total == 0:
        failures.append(
            {
                "scope": "_global",
                "metric": "decision_cases",
                "actual": 0,
                "required": 1,
                "reason": "gateway declares rules but no golden exercised them",
            }
        )

    if extractor_mode == "stub" and not allow_scaffold:
        failures.append(
            {
                "scope": "_global",
                "metric": "extractor_mode",
                "actual": "stub",
                "required": "real",
                "reason": "stub extractor is not evidence of extraction quality; "
                "pass --allow-scaffold to override for development runs only",
            }
        )

    if undeclared_predictions:
        failures.append(
            {
                "scope": _UNCLASSIFIED,
                "metric": "undeclared_predictions",
                "actual": len(undeclared_predictions),
                "required": 0,
            }
        )

    if golden_route_errors:
        failures.append(
            {
                "scope": "_global",
                "metric": "golden_route_validity",
                "actual": len(golden_route_errors),
                "required": 0,
            }
        )

    return {
        "gateway": gateway_name,
        "gateway_version": gateway_version,
        "policy_version": policy_version,
        "extractor_mode": extractor_mode,
        "coverage": coverage,
        "decision_accuracy": decision_accuracy,
        "decision_cases": decision_total,
        "per_type": per_type,
        "macro": macro,
        "micro": {
            "precision": micro_precision,
            "recall": micro_recall,
            "f1": micro_f1,
        },
        "thresholds": thresholds,
        "undeclared_predictions": undeclared_predictions,
        "golden_route_errors": golden_route_errors,
        "failures": failures,
        "pass": not failures,
    }


_REQUIRED_CASE_KEYS = {"id", "input", "expected", "evaluated_at"}
_REQUIRED_EXPECTED_KEYS = {"document_type", "fields_present"}


def _load_goldens(gw: Gateway) -> list[dict]:
    """Load and validate every golden case. Recursive over evals_dir.

    Every failure names the file and case ID. A malformed golden is a
    hard stop, not a silent skip.
    """
    out: list[dict] = []
    seen_ids: set[str] = set()
    for p in sorted(gw.evals_dir.rglob("*.json")):
        try:
            case = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise SystemExit(f"{p}: invalid JSON - {exc}") from exc
        _validate_case(case, p, gw, seen_ids)
        out.append(case)
        seen_ids.add(case["id"])
    return out


def _validate_case(case: Any, path: Path, gw: Gateway, seen_ids: set) -> None:
    if not isinstance(case, dict):
        raise SystemExit(f"{path}: golden case must be a mapping")
    missing = _REQUIRED_CASE_KEYS - case.keys()
    if missing:
        raise SystemExit(f"{path}: case missing keys {sorted(missing)}")
    cid = case["id"]
    if cid in seen_ids:
        raise SystemExit(f"{path}: duplicate case id {cid!r}")
    if not isinstance(case["input"], dict):
        raise SystemExit(f"{path} ({cid}): input must be a mapping")
    if not isinstance(case["expected"], dict):
        raise SystemExit(f"{path} ({cid}): expected must be a mapping")
    missing_exp = _REQUIRED_EXPECTED_KEYS - case["expected"].keys()
    if missing_exp:
        raise SystemExit(
            f"{path} ({cid}): expected missing keys {sorted(missing_exp)}"
        )
    dt = case["expected"]["document_type"]
    if dt not in {d.id for d in gw.documents}:
        raise SystemExit(
            f"{path} ({cid}): expected.document_type {dt!r} not declared "
            f"in gateway documents"
        )
    if not isinstance(case["expected"].get("fields_present", []), list):
        raise SystemExit(f"{path} ({cid}): fields_present must be a list")
    ea = case["evaluated_at"]
    if not isinstance(ea, int) or isinstance(ea, bool) or ea < 0:
        raise SystemExit(
            f"{path} ({cid}): evaluated_at must be a non-negative int, got {ea!r}"
        )


def _filename_classifier(case_input: dict, gw: Gateway) -> str | None:
    import fnmatch

    name = case_input.get("source_filename", "")
    for doc in gw.documents:
        if fnmatch.fnmatchcase(name, doc.filename_glob):
            return doc.id
    return None


def _golden_fields_extractor(case_input: dict, doc_spec: DocumentSpec) -> dict:
    # Scaffold only. The report marks this mode as "stub"; the gate refuses
    # to pass unless --allow-scaffold is set.
    return case_input.get("fields", {})


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if len(args) != 1:
        raise SystemExit(
            "usage: python -m evals.run <gateway> [--allow-scaffold]"
        )
    result = run(args[0], allow_scaffold="--allow-scaffold" in flags)
    print(json.dumps(result, indent=2))
    sys.exit(0 if result["pass"] else 1)
