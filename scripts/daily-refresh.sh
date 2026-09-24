#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
STATE_DIR="$ROOT/data/automation"
BACKUP_DIR="$ROOT/data/backups"
LOG_DIR="$STATE_DIR/logs"
DB="$ROOT/data/public_it.db"
LOCK="$STATE_DIR/daily-refresh.lock"
LAST_SUCCESS="$STATE_DIR/last-success-date"
MODE="${1:-manual}"

mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$LOG_DIR"
cd "$ROOT"

if [[ "$MODE" == "--scheduled" ]]; then
  hour="$(date +%H)"
  if (( 10#$hour < 6 )); then exit 0; fi
fi

exec 9>"$LOCK"
if ! flock -n 9; then exit 0; fi

TODAY="$(date +%F)"
if [[ "$MODE" == "--scheduled" && -f "$LAST_SUCCESS" ]] && grep -qx "$TODAY" "$LAST_SUCCESS"; then
  exit 0
fi
LOG="$LOG_DIR/$(date +%F).log"
exec > >(tee -a "$LOG") 2>&1
find "$LOG_DIR" -type f -name '*.log' -mtime +30 -delete || true
find "$ROOT/data/raw" -type f -mtime +45 -delete 2>/dev/null || true
find "$ROOT/data/raw" -type d -empty -delete 2>/dev/null || true

echo "=== DATLUME refresh start $(date -Is) mode=$MODE ==="
FREE_KB="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
if (( FREE_KB < 10485760 )); then
  echo "ERROR: less than 10 GiB free; aborting"
  exit 20
fi

before_records="$(python3 - "$DB" <<'PY'
import sqlite3, sys
db=sys.argv[1]
try:
    c=sqlite3.connect(db).execute("select count(*) from procurements").fetchone()[0]
except Exception:
    c=0
print(c)
PY
)"

backup="$BACKUP_DIR/public_it-$(date +%F).db"
if [[ -s "$DB" ]]; then
  cp --reflink=auto "$DB" "$backup.tmp"
  mv "$backup.tmp" "$backup"
fi
find "$BACKUP_DIR" -type f -name 'public_it-*.db' -mtime +7 -delete || true
set +e
python3 collector/run_all.py --source jetro --source jetro_local
collect_rc=$?
set -e
if (( collect_rc != 0 )); then
  echo "ERROR: procurement collection failed rc=$collect_rc"
  [[ -s "$backup" ]] && cp "$backup" "$DB"
  exit "$collect_rc"
fi

if ! python3 collector/check_health.py --source jetro --source jetro_local; then
  echo "ERROR: procurement health check failed; restoring database"
  [[ -s "$backup" ]] && cp "$backup" "$DB"
  exit 21
fi

MONTH="$(date +%Y-%m)"
MONTH_MARKER="$STATE_DIR/last-monthly-refresh"
if [[ ! -f "$MONTH_MARKER" ]] || ! grep -qx "$MONTH" "$MONTH_MARKER"; then
  echo "Running monthly land/living refresh"
  python3 collector/collect_land_prices.py
  python3 collector/collect_living_layers.py
  python3 collector/check_health.py --source land_prices
  printf '%s\n' "$MONTH" > "$MONTH_MARKER"
fi

after_records="$(python3 - "$DB" <<'PY'
import sqlite3, sys
print(sqlite3.connect(sys.argv[1]).execute("select count(*) from procurements").fetchone()[0])
PY
)"
echo "Records: $before_records -> $after_records (delta=$((after_records-before_records)))"
npm run build
bash ./deploy-datlume.sh

python3 - "$ROOT/src/data/summary.json" "$STATE_DIR/history.jsonl" "$before_records" "$after_records" <<'PY'
import json, sys
from datetime import datetime, timezone
summary_path, history_path, before, after = sys.argv[1:]
summary=json.load(open(summary_path, encoding="utf-8"))
entry={
  "finishedAt": datetime.now(timezone.utc).isoformat(),
  "beforeRecords": int(before),
  "afterRecords": int(after),
  "deltaRecords": int(after)-int(before),
  "lastDate": summary.get("lastDate"),
  "awardRecords": summary.get("awardRecords"),
  "companies": summary.get("companies"),
}
with open(history_path, "a", encoding="utf-8") as f:
    f.write(json.dumps(entry, ensure_ascii=False, separators=(",",":"))+"\n")
PY

printf '%s\n' "$TODAY" > "$LAST_SUCCESS"
echo "=== DATLUME refresh success $(date -Is) ==="
