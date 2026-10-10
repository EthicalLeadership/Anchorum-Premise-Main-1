#!/usr/bin/env bash
# Run the audit harness against the baseline environment.
set -euo pipefail
cd "$(dirname "$0")/../.."
source .venv/bin/activate 2>/dev/null || true
python3 -m harness.audit_run \
    --env baseline \
    --duration 12 \
    --sample-interval 1.0 \
    --workloads cpu_burn \
    --outdir harness/runs \
    "$@"
