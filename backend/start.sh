#!/bin/bash
# Anchorum-prem Backend Startup Script

venv="/home/kark/anchorum-prem-main(1)/anchorum-prem-main/.venv"
backend_dir="/home/kark/anchorum-prem-main(1)/anchorum-prem-main/backend"

echo "=========================================="
echo "Starting Anchorum-prem Backend Server"
echo "=========================================="
echo ""

cd "$backend_dir"

# Activate virtual environment (optional, but recommended)
source "$venv/bin/activate"

# Start the server
echo "Starting uvicorn server on http://0.0.0.0:8000"
echo ""
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload

echo ""
echo "Server stopped."
