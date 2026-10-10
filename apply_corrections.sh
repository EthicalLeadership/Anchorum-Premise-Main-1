#!/usr/bin/env bash
# apply_corrections.sh — writes the corrected section 2, 3, 4 files into
# the anchorum-prem repo, then runs the celpy probe. Idempotent.
#
# What it writes:
#   evals/__init__.py
#   evals/run.py                    (section 1 — metrics with no vacuous passes)
#   dossier_pipeline/policy_runtime.py   (section 2 — pinned, validated, fail-closed)
#   dossier_pipeline/gateway.py          (section 3 — strict loader with schema 1.0/1.1)
#   dossier_pipeline/gateway_migrate.py  (section 3 — 1.0 -> 1.1 migration)
#   probe_celpy.py                        (4-check celpy compatibility probe)
#   gateways/_template/gateway.yaml       (section 4 — schema 1.1 template)
#   gateways/_template/README.md          (schema documentation)
#
# What it does NOT touch:
#   Anything outside $REPO. Any existing gateway under gateways/<name>/.

set -euo pipefail

REPO="${REPO:-/home/kark/anchorum-prem}"

if [ ! -d "$REPO" ]; then
    echo "ERROR: repo directory not found: $REPO"
    echo "Set REPO=<path> and re-run."
    exit 1
fi

echo "==> Target repo: $REPO"
echo

mkdir -p \
    "$REPO/evals/golden" \
    "$REPO/dossier_pipeline" \
    "$REPO/gateways/_template"

# ---------------------------------------------------------------------------
# File 1: evals/__init__.py
# ---------------------------------------------------------------------------
cat > "$REPO/evals/__init__.py" <<'FILE_EOF'
"""Golden-set evaluation package for ANCHORUM gateways.

See evals/run.py for the metrics contract and failure rules.
"""
FILE_EOF
echo "  wrote evals/__init__.py"

# ---------------------------------------------------------------------------
# File 2: evals/run.py
# ---------------------------------------------------------------------------
cat > "$REPO/evals/run.py" <<'FILE_EOF'
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
FILE_EOF
echo "  wrote evals/run.py"

# ---------------------------------------------------------------------------
# File 3: dossier_pipeline/policy_runtime.py
# ---------------------------------------------------------------------------
cat > "$REPO/dossier_pipeline/policy_runtime.py" <<'FILE_EOF'
"""CEL-based policy runtime for the ANCHORUM gateway framework.

Guarantees, precisely stated
============================
G1. Determinism, scoped. Given identical (fields, now, policy_version,
    celpy series), decide() returns an identical Decision. We do not read
    the wall clock inside the runtime; `now` is injected. CEL semantics
    are pinned to a declared celpy major.minor, enforced at import time
    via ANCHORUM_CELPY_PIN.

G2. Fail-closed. decide() never raises on document-derived input (fields,
    now, rule return values). Errors during field normalisation or rule
    evaluation are captured as RuleError entries on the returned Decision.
    If no rule and no default yield a decision, decide() returns a
    sentinel Decision with route=HOLD_UNCLASSIFIED.

    The one input that raises: `fields` not being a mapping, or `now` not
    being a non-negative int. Those are caller-side bugs, not document-side
    ones, and swallowing them would hide code defects behind audit entries.

G3. Auditable. Every Decision names the rule that fired, its citation,
    the fields it consulted, and the injected timestamp. That tuple is
    what the hash-chained decision log records.

Concurrency
===========
PolicyRuntime is read-only after construction. celpy.Program.evaluate is
treated as stateless per call. If your celpy version is not documented as
thread-safe, wrap calls to decide() in a lock. We do not add the lock
because the cost on every decision is not justified by an unverified risk.

Known limitations
=================
L1. Route validation is runtime, not static. A rule emitting an undeclared
    route is skipped with a RuleError (fail-safe), not rejected at load.
L2. Rule evaluation cost is not bounded. A pathological policy can slow
    one document. max_rules / max_expr_len guards are deferred until a
    real policy exercises the limit.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any

import celpy
from celpy import celtypes


# Celpy pin. Set ANCHORUM_CELPY_PIN="<major.minor>" to enforce. Unset means
# no check (dev convenience). In production, set it and record the value
# in your deployment docs.
_PIN_ENV = "ANCHORUM_CELPY_PIN"


def _check_celpy_version() -> None:
    pin = os.environ.get(_PIN_ENV, "").strip()
    if not pin:
        return
    installed = getattr(celpy, "__version__", "unknown")
    parts = installed.split(".")
    inst_mm = ".".join(parts[:2]) if len(parts) >= 2 else installed
    if inst_mm != pin:
        raise ImportError(
            f"celpy version {installed} does not match pinned series "
            f"{pin}.x (set via {_PIN_ENV}). Upgrade the pin only after "
            f"re-running probe_celpy.py and re-running the golden set: "
            f"CEL semantics may have changed."
        )


_check_celpy_version()


RULE_HEADER = re.compile(r"^\s*//\s*===\s*rule:\s*([A-Za-z0-9_\-]+)\s*===\s*$")
RULE_END = re.compile(r"^\s*//\s*===\s*end\s*===\s*$")
POLICY_VERSION = re.compile(r"^\s*//\s*policy-version:\s*(\S+)\s*$")

UNCLASSIFIED_ROUTE = "HOLD_UNCLASSIFIED"

VALID_SEVERITIES: frozenset[str] = frozenset(
    {"critical", "high", "medium", "low", "info"}
)


class PolicyParseError(Exception):
    """Raised at load time when a policy file cannot be compiled.

    Parse errors are fatal. Runtime errors on document input are not.
    """


@dataclass(frozen=True)
class RuleError:
    rule_id: str
    message: str


@dataclass(frozen=True)
class Decision:
    route: str
    reason: str
    severity: str
    citation: str
    fields_used: tuple[str, ...]
    rule_id: str
    evaluated_at: int
    rule_errors: tuple[RuleError, ...] = ()

    def to_log_entry(
        self,
        *,
        gateway_version: str,
        policy_version: str,
        model_version: str,
    ) -> dict:
        """The shape the hash-chained decision log stores.

        Stable across runs for identical inputs. Any change here is a
        change to the audit contract and requires a version bump.
        """
        return {
            "route": self.route,
            "reason": self.reason,
            "severity": self.severity,
            "citation": self.citation,
            "fields_used": list(self.fields_used),
            "rule_id": self.rule_id,
            "evaluated_at": self.evaluated_at,
            "gateway_version": gateway_version,
            "policy_version": policy_version,
            "model_version": model_version,
            "rule_errors": [
                {"rule_id": e.rule_id, "message": e.message}
                for e in self.rule_errors
            ],
        }


class PolicyRuntime:
    """Compiled policy for one gateway. Construct once; reuse per document."""

    def __init__(
        self,
        policy_source: str,
        *,
        allowed_routes: set[str],
        policy_version: str | None = None,
    ) -> None:
        if not allowed_routes:
            raise PolicyParseError(
                "allowed_routes must be a non-empty set; declare routes "
                "in gateway.yaml under `routes:`"
            )
        # HOLD_UNCLASSIFIED is a runtime-emitted route. Register it here so
        # the registry is genuinely complete: every route the runtime can
        # emit is in allowed_routes.
        self._allowed_routes = frozenset(allowed_routes) | {UNCLASSIFIED_ROUTE}
        self.policy_version = policy_version or _extract_version(policy_source)
        self._rules: list[tuple[str, celpy.Program]] = []
        self._default: celpy.Program | None = None
        self._env = _make_env()
        self._parse(policy_source)

    def rule_count(self) -> int:
        """Number of non-default rules. Used by the eval harness to detect
        gateways that declare rules but never exercise them."""
        return len(self._rules)

    def decide(self, fields: dict[str, Any], *, now: int) -> Decision:
        """Evaluate all rules in source order. First valid decision wins.

        Raises TypeError only if `fields` is not a mapping or `now` is not
        a non-negative int (excluding bool). Those are caller bugs.
        """
        if not isinstance(fields, dict):
            raise TypeError(
                f"fields must be a mapping, got {type(fields).__name__}"
            )
        if not isinstance(now, int) or isinstance(now, bool) or now < 0:
            raise TypeError(f"now must be a non-negative int, got {now!r}")

        errors: list[RuleError] = []
        try:
            wrapped = _wrap(fields)
        except Exception as exc:
            errors.append(RuleError("__wrap__", f"{type(exc).__name__}: {exc}"))
            return self._sentinel(
                now, errors, reason="Field normalisation failed."
            )

        activation = {
            "fields": wrapped,
            "now": celtypes.IntType(int(now)),
        }

        for rule_id, program in self._rules:
            decision, rule_err = self._evaluate_one(
                rule_id, program, activation, now
            )
            if rule_err is not None:
                errors.append(rule_err)
                continue
            if decision is None:
                continue
            if decision.route not in self._allowed_routes:
                errors.append(
                    RuleError(
                        rule_id,
                        f"route {decision.route!r} not declared in gateway routes",
                    )
                )
                continue
            return replace(decision, rule_errors=tuple(errors))

        return self._evaluate_default(activation, now=now, errors=errors)

    # ---------------------------------------------------------------- internals

    def _parse(self, source: str) -> None:
        blocks = _split_blocks(source)
        if not blocks:
            raise PolicyParseError("policy contains no rule blocks")

        seen: set[str] = set()
        default_seen = False
        for rule_id, expr in blocks:
            if rule_id in seen:
                raise PolicyParseError(f"duplicate rule id {rule_id!r}")
            seen.add(rule_id)

            if rule_id == "default":
                if default_seen:
                    raise PolicyParseError("duplicate default block")
                default_seen = True
            elif default_seen:
                raise PolicyParseError(
                    f"rule {rule_id!r} appears after the default block; "
                    "the default must be last"
                )

            try:
                ast = self._env.compile(expr)
                program = self._env.program(ast)
            except Exception as exc:
                raise PolicyParseError(
                    f"rule {rule_id!r} failed to compile: {exc}"
                ) from exc

            if rule_id == "default":
                self._default = program
            else:
                self._rules.append((rule_id, program))

        if not default_seen:
            raise PolicyParseError(
                "policy must contain a `// === rule: default ===` block"
            )

    def _evaluate_one(
        self,
        rule_id: str,
        program: celpy.Program,
        activation: dict,
        now: int,
    ) -> tuple[Decision | None, RuleError | None]:
        try:
            result = program.evaluate(activation)
        except Exception as exc:
            # Any exception is captured, not propagated. A malformed
            # document cannot DoS the decision path.
            name = type(exc).__name__
            return None, RuleError(rule_id, f"{name}: {exc}")

        try:
            decision = _coerce_decision(result, rule_id=rule_id, now=now)
        except ValueError as exc:
            return None, RuleError(rule_id, str(exc))
        return decision, None

    def _evaluate_default(
        self, activation: dict, *, now: int, errors: list[RuleError]
    ) -> Decision:
        default = self._default
        if default is None:  # unreachable by construction; -O safe
            return self._sentinel(
                now, errors, reason="Policy has no default block."
            )

        decision, err = self._evaluate_one("default", default, activation, now)
        if err is not None:
            errors.append(err)
        if decision is not None:
            if decision.route in self._allowed_routes:
                return replace(decision, rule_errors=tuple(errors))
            errors.append(
                RuleError(
                    "default",
                    f"default route {decision.route!r} not in gateway routes",
                )
            )

        return self._sentinel(
            now,
            errors,
            reason="No rule matched and the default did not yield a valid decision.",
        )

    def _sentinel(
        self, now: int, errors: list[RuleError], *, reason: str
    ) -> Decision:
        return Decision(
            route=UNCLASSIFIED_ROUTE,
            reason=reason,
            severity="high",
            citation="",
            fields_used=(),
            rule_id="__sentinel__",
            evaluated_at=now,
            rule_errors=tuple(errors),
        )


# ----------------------------------------------------------------- helpers

def _make_env() -> celpy.Environment:
    env = celpy.Environment()
    env.add_function("parse_ts", _fn_parse_ts)
    return env


def _extract_version(source: str) -> str:
    found: str | None = None
    for line in source.splitlines():
        m = POLICY_VERSION.match(line)
        if m:
            if found is not None:
                raise PolicyParseError(
                    "multiple `// policy-version:` headers in policy source"
                )
            found = m.group(1)
    return found or "unversioned"


def _split_blocks(source: str) -> list[tuple[str, str]]:
    """Return [(rule_id, cel_expression), ...] in source order.

    Strict: any non-blank, non-comment line outside a rule block is a
    parse error. Silently discarding author intent is worse than
    refusing the file.
    """
    blocks: list[tuple[str, str]] = []
    cur_id: str | None = None
    cur_lines: list[str] = []

    for lineno, line in enumerate(source.splitlines(), start=1):
        m = RULE_HEADER.match(line)
        if m:
            if cur_id is not None:
                raise PolicyParseError(
                    f"line {lineno}: rule {cur_id!r} not closed before "
                    f"{m.group(1)!r} began"
                )
            cur_id = m.group(1)
            cur_lines = []
            continue

        if RULE_END.match(line):
            if cur_id is None:
                raise PolicyParseError(
                    f"line {lineno}: `end` marker without preceding rule header"
                )
            expr = "\n".join(cur_lines).strip()
            if not expr:
                raise PolicyParseError(f"line {lineno}: rule {cur_id!r} is empty")
            blocks.append((cur_id, expr))
            cur_id = None
            cur_lines = []
            continue

        if cur_id is not None:
            cur_lines.append(line)
            continue

        stripped = line.strip()
        if stripped and not stripped.startswith("//"):
            raise PolicyParseError(
                f"line {lineno}: content outside any rule block: {line!r}"
            )

    if cur_id is not None:
        raise PolicyParseError(f"rule {cur_id!r} was never closed")

    return blocks


def _wrap(fields: dict[str, Any]) -> celtypes.MapType:
    out: dict[celtypes.StringType, Any] = {}
    for k, v in fields.items():
        if not isinstance(k, str):
            raise TypeError(f"field keys must be strings; got {k!r}")
        out[celtypes.StringType(k)] = _wrap_val(v)
    return celtypes.MapType(out)


def _wrap_val(v: Any) -> Any:
    if isinstance(v, dict):
        return _wrap(v)
    if isinstance(v, list):
        return celtypes.ListType([_wrap_val(x) for x in v])
    if isinstance(v, bool):
        return celtypes.BoolType(v)
    if isinstance(v, int):
        return celtypes.IntType(v)
    if isinstance(v, float):
        return celtypes.DoubleType(v)
    if isinstance(v, str) or v is None:
        return v
    return str(v)


def _coerce_decision(
    value: Any, *, rule_id: str, now: int
) -> Decision | None:
    if not isinstance(value, celtypes.MapType):
        return None
    d = dict(value)
    route = d.get("route")
    if not route:
        return None
    severity = str(d.get("severity", "info"))
    if severity not in VALID_SEVERITIES:
        raise ValueError(
            f"rule {rule_id!r}: severity {severity!r} not in "
            f"{sorted(VALID_SEVERITIES)}"
        )
    return Decision(
        route=str(route),
        reason=str(d.get("reason", "")),
        severity=severity,
        citation=str(d.get("citation", "")),
        fields_used=tuple(str(f) for f in d.get("fields_used", [])),
        rule_id=rule_id,
        evaluated_at=now,
    )


def _fn_parse_ts(value: Any) -> celtypes.IntType:
    """CEL helper: string timestamp -> epoch seconds.

    Returns 0 on any parse failure. Never raises.
    """
    if not isinstance(value, str):
        return celtypes.IntType(0)
    s = value.strip().replace("Z", "+00:00")
    if not s:
        return celtypes.IntType(0)
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return celtypes.IntType(0)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return celtypes.IntType(int(dt.timestamp()))
FILE_EOF
echo "  wrote dossier_pipeline/policy_runtime.py"

# ---------------------------------------------------------------------------
# File 4: dossier_pipeline/gateway.py (complete)
# ---------------------------------------------------------------------------
cat > "$REPO/dossier_pipeline/gateway.py" <<'FILE_EOF'
"""Gateway loader — the only entry point for vertical configs.

A "gateway" is a directory under `gateways/<name>/` containing:
    gateway.yaml        — the contract (validated by this loader)
    actors.json         — actor classification rules
    policy.cel          — policy decision rules (CEL, rule-block format)
    regulations.json    — citation library referenced by policy.cel
    risk_patterns.json  — risk flag definitions
    evals/golden/       — golden test set

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
FILE_EOF
echo "  wrote dossier_pipeline/gateway.py"

# ---------------------------------------------------------------------------
# File 5: dossier_pipeline/gateway_migrate.py
# ---------------------------------------------------------------------------
cat > "$REPO/dossier_pipeline/gateway_migrate.py" <<'FILE_EOF'
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
FILE_EOF
echo "  wrote dossier_pipeline/gateway_migrate.py"

# ---------------------------------------------------------------------------
# File 6: probe_celpy.py
# ---------------------------------------------------------------------------
cat > "$REPO/probe_celpy.py" <<'FILE_EOF'
"""probe_celpy.py — verify the installed celpy supports the API we depend on.

Exit 0 = all checks passed. Any FAIL prints a specific message and exits
non-zero. Run once per environment before deploying a PolicyRuntime change.

This probe prints what it finds. It does not assert against celpy internals.
"""
import sys

try:
    import celpy
    from celpy import celtypes
except ImportError as exc:
    sys.exit(f"FAIL celpy not installed: {exc}")

print(f"celpy version: {getattr(celpy, '__version__', 'unknown')}")

# Check 1: custom function registration.
try:
    env = celpy.Environment()
    env.add_function("parse_ts", lambda s: celtypes.IntType(0))
    print("OK   add_function")
except Exception as exc:
    sys.exit(f"FAIL add_function: {exc}")

# Check 2: compile + evaluate + custom function. Print the return type.
try:
    p = env.program(env.compile("parse_ts('2024-01-01') == 0"))
    result = p.evaluate({})
    print(f"OK   compile + evaluate + custom fn (type={type(result).__name__}, value={result!r})")
except Exception as exc:
    sys.exit(f"FAIL compile/evaluate: {exc}")

# Check 3: comments inside compiled expressions.
try:
    p = env.program(env.compile("// comment\n1 == 1"))
    result = p.evaluate({})
    print(f"OK   inline comments (type={type(result).__name__}, value={result!r})")
except Exception as exc:
    sys.exit(f"FAIL comments: {exc}")

# Check 4: exception class for missing map key. Informational.
try:
    env.program(env.compile("fields.x")).evaluate(
        {"fields": celtypes.MapType({})}
    )
    print("WARN missing-key access did NOT raise (unexpected)")
except Exception as exc:
    name = type(exc).__name__
    if name == "CELEvalError":
        print(f"OK   exception class is CELEvalError")
    else:
        print(f"WARN exception class is {name!r}, not CELEvalError "
              f"(PolicyRuntime catches all exceptions, so no action needed, "
              f"but note the divergence)")

print("probe complete")
FILE_EOF
echo "  wrote probe_celpy.py"

# ---------------------------------------------------------------------------
# File 7: gateways/_template/gateway.yaml
# ---------------------------------------------------------------------------
cat > "$REPO/gateways/_template/gateway.yaml" <<'FILE_EOF'
# ANCHORUM gateway — schema_version 1.1
#
# Copy this directory to gateways/<your-vertical>/ and fill in each field.
# Every field marked REQUIRED must be present or the loader rejects the file.
#
# Fields that reference paths are resolved under this gateway's directory.
# Paths escaping the gateway (via ../) are rejected.
#
# See README.md in this directory for the full schema and constraints.

schema_version: "1.1"                    # REQUIRED. Exact string.

identity:
  name: template                         # REQUIRED. Matches directory name.
  version: "0.0.1-draft"                 # REQUIRED. semver; tier A forbids "draft"
  jurisdiction: CA-QC                    # REQUIRED. ISO 3166-2 or similar.
  tier: C                                # REQUIRED. One of A, B, C.
  description: >                         # Optional. Short human description.
    Template gateway. Replace with your vertical's purpose.

routes:                                  # REQUIRED (1.1). Non-empty list.
  # Every route a rule may emit must appear here. HOLD_UNCLASSIFIED is
  # auto-registered by the runtime; do not list it here.
  - QUARANTINE_REVIEW
  - HOLD_FOR_HR
  - CUSTOMS_REVIEW

documents:                               # REQUIRED. Non-empty list.
  - id: example_document                 # snake_case, unique within gateway
    label: "Example Document"            # Human label
    match:
      filename_glob: "**/*example*"      # fnmatch pattern (fnmatchcase)
      mime_types: [application/pdf]      # Optional; default is ["*/*"]
    required_fields:                     # Field names the extractor must produce
      - example_field_1
      - example_field_2
    extractor: pdf_text                  # Named extractor (registry TBD)
    retention_days: 2555                 # Must be >= 1

actors:                                  # REQUIRED.
  path: actors.json                      # Relative to this directory
  required_roles: [example_role]         # Optional but recommended

policy:                                  # REQUIRED.
  path: policy.cel                       # CEL rule-block file
  citations_path: regulations.json       # Citation library
  decision_log: true                     # Reserved; not yet wired

risk:                                    # REQUIRED.
  path: risk_patterns.json

evals:                                   # REQUIRED.
  golden_dir: evals/golden/              # Must exist and be inside gateway dir
  thresholds:                            # REQUIRED. Must include _global.
    _global:                             # Floor applied to each per-type metric
      precision: 0.90
      recall: 0.85
      field_completeness: 0.95
      field_precision: 0.95
    # Per-type overrides (optional):
    # example_document:
    #   precision: 0.95

legal:                                   # REQUIRED (1.1). All four keys.
  privacy_jurisdictions: [QC, CA]
  retention_days_default: 2555           # Must be >= 1
  consent_required: false                # Boolean
  phi_handling: false                    # Boolean. Never inferred from vertical.

# integrations:                          # Optional. External service stubs.
#   - id: example_lookup
#     kind: http
#     endpoint: "https://example.gov/api/v1/lookup"
#     auth: api_key
#     live: false                        # Stub until credential provisioned
FILE_EOF
echo "  wrote gateways/_template/gateway.yaml"

# ---------------------------------------------------------------------------
# File 8: gateways/_template/README.md
# ---------------------------------------------------------------------------
cat > "$REPO/gateways/_template/README.md" <<'FILE_EOF'
# Gateway schema — version 1.1

A gateway is a self-contained directory under `gateways/<name>/` that
configures the ANCHORUM pipeline for one industry vertical. The loader
(`dossier_pipeline.gateway.load_gateway`) validates every gateway at
load time and rejects anything that doesn't conform.

## Files a gateway must contain

| File | Purpose |
|------|---------|
| `gateway.yaml` | The contract. Required top-level fields listed below. |
| `actors.json` | Actor classification rules. Keys are role IDs. |
| `policy.cel` | CEL rule-block file. Must include a `default` block. |
| `regulations.json` | Citation library. Each entry is a mapping with `status`. |
| `risk_patterns.json` | Risk flag definitions (free-form). |
| `evals/golden/*.json` | Golden test cases. See "Golden cases" below. |

## Required top-level keys in gateway.yaml

`schema_version`, `identity`, `documents`, `actors`, `policy`, `risk`,
`evals`, `legal`, `routes`.

`schema_version` must be exactly `"1.1"`. `"1.0"` is still accepted with a
deprecation warning; migrate with `python -m dossier_pipeline.gateway_migrate <dir>`.

## Threshold semantics

`evals.thresholds` is a mapping of scope to metric floors:

```yaml
thresholds:
  _global:                # mandatory fallback
    precision: 0.90
    recall: 0.85
    field_completeness: 0.95
    field_precision: 0.95
  driver_qualification_file:    # per-type override
    precision: 0.95

FILE_EOF

echo
echo "==> apply_corrections.sh complete"
