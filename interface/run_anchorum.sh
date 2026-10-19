#!/bin/bash
# Launch Anchorum backend + frontend together.
# Backend:  uvicorn on 127.0.0.1:8011
# Frontend: Vite dev on 0.0.0.0:5173 (matches backend CORS default)

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

pkill -f 'uvicorn interface.server' 2>/dev/null || true
pkill -f 'vite.*--port 5173' 2>/dev/null || true
sleep 1

source "$REPO_ROOT/.venv/bin/activate"

export ANCHORUM_LOCAL_API_MODE=1
export ANCHORUM_DATABASE_URL="sqlite:///$REPO_ROOT/dev_data/api.db"
export ANCHORUM_EVIDENCE_DIRECTORY="$REPO_ROOT/dev_data/evidence"

cd "$REPO_ROOT"
python3 -m uvicorn interface.server:app --host 127.0.0.1 --port 8011 --log-level info &
BACKEND_PID=$!

for i in $(seq 1 20); do
  if curl -sS http://127.0.0.1:8011/health >/dev/null 2>&1; then break; fi
  sleep 0.5
done

trap 'kill $BACKEND_PID 2>/dev/null || true' EXIT

cd "$SCRIPT_DIR"
npm run dev -- --host 0.0.0.0 --port 5173
