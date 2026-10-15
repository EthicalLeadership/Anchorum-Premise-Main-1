#!/bin/bash
# run_frontend.sh - Launch Anchorum Prem Frontend Development Server

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d "node_modules" ]; then
    echo "📦 Installing dependencies..."
    npm install
fi

PORT="${ANCHORUM_PORT:-3000}"

echo "🚀 Starting Anchorum Prem Frontend Development Server"
echo "   📍 Directory: $(pwd)"
echo "   🔌 Port: $PORT"
echo "   🌐 URL: http://localhost:$PORT"
echo ""

npm run dev -- --host 0.0.0.0 --port "$PORT"
