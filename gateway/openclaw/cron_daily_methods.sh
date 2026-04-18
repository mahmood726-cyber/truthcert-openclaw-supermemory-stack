#!/bin/bash
# Daily certification cron job example
#
# Add to crontab:
# 0 2 * * * /path/to/truthcert-openclaw-supermemory-stack/gateway/openclaw/cron_daily_methods.sh
#
# This script:
# 1. Activates the virtual environment
# 2. Runs certification on pending jobs
# 3. Generates reports
# 4. Cleans up old bundles

set -e

# Configuration
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
VENV_PATH="${PROJECT_ROOT}/.venv"
LOG_DIR="${PROJECT_ROOT}/logs"
INPUT_DIR="${PROJECT_ROOT}/jobs/pending"
OUTPUT_DIR="${PROJECT_ROOT}/bundles"
POLICY="silver"
RETENTION_DAYS=90

# Logging
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/daily_cert_$(date +%Y%m%d).log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" | tee -a "$LOG_FILE"
}

log "Starting daily certification job"

# Activate virtual environment
if [ -d "$VENV_PATH" ]; then
    source "$VENV_PATH/bin/activate"
    log "Activated virtual environment"
else
    log "WARNING: Virtual environment not found at $VENV_PATH"
fi

# Check service health
if ! curl -s http://localhost:8000/health > /dev/null; then
    log "TruthCert service not running, starting..."
    cd "$PROJECT_ROOT"
    nohup python -m certifier.main > "$LOG_DIR/truthcertd.log" 2>&1 &
    sleep 5
fi

# Process pending jobs
if [ -d "$INPUT_DIR" ]; then
    for job_dir in "$INPUT_DIR"/*; do
        if [ -d "$job_dir" ]; then
            job_name=$(basename "$job_dir")
            log "Processing job: $job_name"

            # Run certification
            python -c "
from gateway.openclaw.glue import run_daily_certification
import json
result = run_daily_certification('$job_dir', policy_id='$POLICY')
print(json.dumps(result, indent=2))
" 2>&1 | tee -a "$LOG_FILE"

            # Move to processed
            mkdir -p "${INPUT_DIR}/../processed"
            mv "$job_dir" "${INPUT_DIR}/../processed/${job_name}_$(date +%Y%m%d%H%M%S)"
            log "Moved $job_name to processed"
        fi
    done
else
    log "No pending jobs directory"
fi

# Generate daily report
log "Generating daily report"
python -c "
from pathlib import Path
from certifier.bundle import list_bundles
from datetime import datetime, timedelta, timezone

bundles = list_bundles(limit=100)
today = datetime.now(timezone.utc).date()

today_bundles = [b for b in bundles if b.get('created_at', '').startswith(str(today))]
pass_count = len([b for b in today_bundles if b.get('outcome') == 'PASS'])
reject_count = len([b for b in today_bundles if b.get('outcome') == 'REJECT'])

print(f'Daily Report - {today}')
print(f'Total bundles today: {len(today_bundles)}')
print(f'PASS: {pass_count}')
print(f'REJECT: {reject_count}')
" 2>&1 | tee -a "$LOG_FILE"

# Cleanup old bundles
log "Cleaning up bundles older than $RETENTION_DAYS days"
find "$OUTPUT_DIR" -name "bundle_*" -type d -mtime +$RETENTION_DAYS -exec rm -rf {} \; 2>/dev/null || true

# Compact memory
log "Compacting memory"
python -c "
from memory.commands import MemoryCommands
cmd = MemoryCommands()
result = cmd.compact(strategy='rolling', max_age_days=30)
print(f'Compacted: {result}')
" 2>&1 | tee -a "$LOG_FILE"

log "Daily certification job completed"
