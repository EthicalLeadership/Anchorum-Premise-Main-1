#!/bin/bash
# Install and configure the Resident AI deterministic layer.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "[1/4] Activating virtual environment..."
if [ ! -d "../.venv" ]; then
    echo "Creating workspace venv..."
    python3 -m venv ../.venv
fi
source ../.venv/bin/activate

echo "[2/4] Installing Python dependencies..."
pip install -r requirements.txt

echo "[3/4] Checking Blackstar..."
if ! curl -sfk "https://127.0.0.1:8443/health/ready" >/dev/null 2>&1; then
    echo "WARNING: Blackstar is not responding at https://127.0.0.1:8443"
    echo "  Ensure the blackstar-dashboard service is running:"
    echo "    systemctl status blackstar-dashboard.service"
    echo "  Or start it manually before indexing."
fi

echo "[4/4] Writing prompt manifest..."
python3 - <<'PY'
import hashlib, json
from pathlib import Path
prompts_dir = Path('prompts/v1')
manifest = {'version': 'v1'}
for path in sorted(prompts_dir.glob('*.txt')):
    manifest[path.name] = hashlib.sha256(path.read_text(encoding='utf-8').encode('utf-8')).hexdigest()
(prompts_dir / 'manifest.json').write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding='utf-8')
print('manifest.json regenerated')
PY

echo ""
echo "Installation complete."
echo ""
echo "Next steps:"
echo "  1. Ensure Blackstar is running:  systemctl status blackstar-dashboard.service"
echo "  2. Export API key:              export BLACKSTAR_API_KEY=\$(cat /path/to/api_key.hex)"
echo "  3. Index documents:              python -m dossier_pipeline.resident_ai --index --no-repl"
echo "  4. Start interactive session:    python -m dossier_pipeline.resident_ai"
echo ""
