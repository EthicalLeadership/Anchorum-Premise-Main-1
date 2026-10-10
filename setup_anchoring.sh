#!/bin/bash
set -euo pipefail

python3 -m pip install --quiet requests dnspython

mkdir -p output

echo "Anchoring setup complete."
echo "Set these environment variables before running anchor-now:"
echo "  CF_ZONE_ID"
echo "  CF_API_TOKEN"
echo "  DOSSIER_ID"
