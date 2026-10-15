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
                program = self._env.program(ast, functions={"parse_ts": _fn_parse_ts})
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
    return celpy.Environment(
        annotations={"parse_ts": celtypes.FunctionType},
    )


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


def _fn_parse_ts(value: celtypes.StringType) -> celtypes.IntType:
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
