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

## CEL map key syntax

celpy 0.5.0 requires map literal keys to be quoted strings:
  `? { "route": "X", "severity": "info" } : null`

Bare identifier keys (`{ route: "X" }`) parse but crash at evaluation with
an opaque `unhashable type: CELEvalError` message. Always quote map keys.

