#!/usr/bin/env bash
set -euo pipefail

PIPELINE_DIR="/home/kark/Dossier Intake Source/Dossier Intake Source/dossier_pipeline_v1.1"
PYTHON_BIN="/home/kark/Dossier Intake Source/.venv/bin/python"
LOG_DIR="$PIPELINE_DIR/output_proton/hourly_mail_audit"
LOG_FILE="$LOG_DIR/cron.log"

mkdir -p "$LOG_DIR"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python executable not found at $PYTHON_BIN"
  exit 1
fi

CRON_CMD="cd '$PIPELINE_DIR' && '$PYTHON_BIN' '$PIPELINE_DIR/scripts/hourly_mail_check.py' >> '$LOG_FILE' 2>&1"
CRON_LINE="0 * * * * $CRON_CMD"

TMP_CRON="$(mktemp)"
trap 'rm -f "$TMP_CRON"' EXIT

crontab -l 2>/dev/null | grep -v "hourly_mail_check.py" > "$TMP_CRON" || true
echo "$CRON_LINE" >> "$TMP_CRON"
crontab "$TMP_CRON"

echo "Installed hourly cron job:"
echo "$CRON_LINE"
