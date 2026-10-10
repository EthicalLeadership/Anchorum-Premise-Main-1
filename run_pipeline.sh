#!/bin/bash
# Activate venv (if present) and run the pipeline CLI.
# Always executes from the directory containing this script so that
# "python -m dossier_pipeline.main" can resolve the package correctly.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d ".venv" ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate

python3 -m dossier_pipeline.main "$@"
