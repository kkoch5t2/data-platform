#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
STAMP="$(date '+%Y%m%d-%H%M%S')"
LOG_DIR="$ROOT/tmp/classifier-logs"
LOG="$LOG_DIR/$STAMP.log"
STATE="$LOG_DIR/latest-state.txt"
mkdir -p "$LOG_DIR"
exec > >(tee -a "$LOG") 2>&1

CURRENT_STEP="bootstrap"
step() {
  CURRENT_STEP="$1"
  printf '\n[%s] START step=%s\n' "$(date '+%F %T')" "$CURRENT_STEP"
  printf 'RUNNING step=%s started=%s log=%s\n' "$CURRENT_STEP" "$(date -Is)" "$LOG" > "$STATE"
}
finish_step() {
  printf '[%s] DONE step=%s\n' "$(date '+%F %T')" "$CURRENT_STEP"
}
trap 'code=$?; printf "[%s] FAILED step=%s exit_code=%s line=%s command=%q\n" "$(date "+%F %T")" "$CURRENT_STEP" "$code" "$LINENO" "$BASH_COMMAND"; printf "FAILED step=%s exit_code=%s line=%s log=%s\n" "$CURRENT_STEP" "$code" "$LINENO" "$LOG" > "$STATE"; exit "$code"' ERR
cd "$ROOT"
echo "classifier_validation_log=$LOG"
echo "git_head=$(git rev-parse --short HEAD)"
echo "git_origin=$(git rev-parse --short origin/main 2>/dev/null || echo unknown)"

step regression_tests
python3 -m unittest collector.test_market_classifier
finish_step

step backup_before_reclassify
cp --reflink=auto data/public_it.db tmp/classifier-before.db
python3 - <<'PY'
import sqlite3
p='tmp/classifier-before.db'
c=sqlite3.connect(p)
print('backup_records=', c.execute('select count(*) from procurements').fetchone()[0])
print('backup_categories=', c.execute('select count(distinct category) from procurements').fetchone()[0])
PY
finish_step

step reclassify_and_export
python3 - <<'PY'
import sqlite3
from collector import collect_jetro as c
conn=sqlite3.connect(c.DB_PATH)
c.init_db(conn)
changed=c.reclassify_existing(conn)
summary=c.export_json(conn)
print('reclassified_existing=', changed)
print('summary_records=', summary.get('records'))
print('summary_itRecords=', summary.get('itRecords'))
PY
finish_step
step integrity_audit
python3 scripts/audit-data-integrity.py
finish_step

step generate_review_samples
python3 scripts/generate-market-review-samples.py
finish_step

printf 'SUCCESS completed=%s log=%s\n' "$(date -Is)" "$LOG" > "$STATE"
printf '[%s] SUCCESS all_validation_steps_completed log=%s\n' "$(date '+%F %T')" "$LOG"
