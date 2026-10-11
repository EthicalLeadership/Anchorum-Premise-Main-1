#!/usr/bin/env bash
# Run every gate this project enforces, in the order CI runs them.
#
# Usage: scripts/check.sh
#
# The integrity gate runs first and is dependency-free, so a corrupt tree is
# reported before anything expensive starts.
set -euo pipefail

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

echo "== integrity gate self-test =="
python3 scripts/check_integrity.py --selftest

echo "== integrity gate (all tracked source) =="
python3 scripts/check_integrity.py --all

echo "== python tests =="
python3 -m pytest -q -p no:cacheprovider

echo "== interface type-check =="
(cd interface && npx tsc --noEmit)

echo "== interface tests =="
(cd interface && npx vitest run)

echo "== interface production build =="
(cd interface && npm run build)

echo
echo "all gates passed"
