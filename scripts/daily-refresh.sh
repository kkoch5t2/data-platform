#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
STATE_DIR="$ROOT/data/automation"
BACKUP_DIR="$ROOT/data/backups"
LOG_DIR="$STATE_DIR/logs"
DB="$ROOT/data/public_it.db"
LOCK="$STATE_DIR/daily-refresh.lock"
LAST_SUCCESS="$STATE_DIR/last-success-date"
MODE="${1:-manual}"
RELEASE_LOCK="$STATE_DIR/release.lock"
SCHEDULED_HOST_MARKER="$HOME/.config/datlume/allow-scheduled-refresh"
EXPECTED_SCHEDULED_HOST="kota-Intel"

assert_release_tree_safe() {
  local bad
  bad="$({ git diff --name-only; git diff --cached --name-only; git ls-files --others --exclude-standard; } | sort -u | while IFS= read -r path; do
    [[ -z "$path" ]] && continue
    case "$path" in
      src/data/*.ts|src/data/sources.json|public/data/*.json|tmp/*) ;;
      *) printf '%s\n' "$path" ;;
    esac
  done)"
  if [[ -n "$bad" ]]; then
    echo "ERROR: scheduled refresh found non-generated working-tree changes:"
    printf '%s\n' "$bad"
    return 1
  fi
}

mkdir -p "$STATE_DIR" "$BACKUP_DIR" "$LOG_DIR"
cd "$ROOT"
TODAY="$(date +%F)"
LOG="$LOG_DIR/$TODAY.log"
FAILURE_LOG="$LOG_DIR/failures.log"
CURRENT_STEP="startup"

record_stop() {
  local rc="$1"
  local reason="$2"
  reason="${reason//$'\n'/ }"
  reason="${reason//$'\t'/ }"
  printf '%s\tstep=%s\trc=%s\treason=%s\tdaily_log=%s\n' \
    "$(date -Is)" "$CURRENT_STEP" "$rc" "$reason" "$LOG" >> "$FAILURE_LOG"
}

on_error() {
  local rc="$1" line="$2" command="$3"
  trap - ERR
  command="${command//$'\n'/ }"
  echo "ERROR: DATLUME refresh stopped: step=$CURRENT_STEP rc=$rc line=$line command=$command"
  record_stop "$rc" "line=$line command=$command"
  exit "$rc"
}

run_step() {
  CURRENT_STEP="$1"
  shift
  echo "--- step: $CURRENT_STEP ---"
  "$@"
}

if [[ "$MODE" == "--scheduled" ]]; then
  if [[ "$(uname -s)" != "Linux" || "$(hostname)" != "$EXPECTED_SCHEDULED_HOST" || ! -f "$SCHEDULED_HOST_MARKER" ]] \
     || ! grep -qx "$EXPECTED_SCHEDULED_HOST" "$SCHEDULED_HOST_MARKER"; then
    echo "ERROR: scheduled DATLUME refresh is authorized only on the production Ubuntu host" >&2
    exit 23
  fi
  hour="$(date +%H)"
  if (( 10#$hour < 6 )); then exit 0; fi
fi

exec 9>"$LOCK"
if ! flock -n 9; then exit 0; fi

if [[ "$MODE" == "--scheduled" ]] && ! assert_release_tree_safe; then
  CURRENT_STEP="pre-refresh-release-tree-safety"
  record_stop 22 "non-generated working-tree changes detected before refresh"
  exit 22
fi

if [[ "$MODE" == "--scheduled" && -f "$LAST_SUCCESS" ]] && grep -qx "$TODAY" "$LAST_SUCCESS"; then
  exit 0
fi
exec > >(tee -a "$LOG") 2>&1
trap 'on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
find "$LOG_DIR" -type f -name '*.log' -mtime +30 -delete || true
# EDINET annual-report Raw is the long-term source of truth and must not be aged out.
find "$ROOT/data/raw" -path "$ROOT/data/raw/listed-companies" -prune -o -type f -mtime +45 -delete 2>/dev/null || true
find "$ROOT/data/raw" -path "$ROOT/data/raw/listed-companies" -prune -o -type d -empty -delete 2>/dev/null || true

echo "=== DATLUME refresh start $(date -Is) mode=$MODE ==="
FREE_KB="$(df -Pk "$ROOT" | awk 'NR==2 {print $4}')"
if (( FREE_KB < 10485760 )); then
  CURRENT_STEP="disk-space-check"
  echo "ERROR: less than 10 GiB free; aborting"
  record_stop 20 "less than 10 GiB free"
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

CATCHUP_FROM="$TODAY"
if [[ -s "$LAST_SUCCESS" ]]; then
  candidate="$(head -n1 "$LAST_SUCCESS" | tr -d '\r\n')"
  if [[ "$candidate" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] && \
     [[ "$candidate" < "$TODAY" || "$candidate" == "$TODAY" ]]; then
    CATCHUP_FROM="$candidate"
  fi
else
  CATCHUP_FROM="$(date -d '2 days ago' +%F)"
fi
echo "Procurement catch-up window: $CATCHUP_FROM -> $TODAY"

fiscal_year="$(date +%Y)"
if (( 10#$(date +%m) < 4 )); then fiscal_year="$((10#$fiscal_year-1))"; fi
previous_fiscal_year="$((10#$fiscal_year-1))"

CURRENT_STEP="procurement-collection"
trap - ERR
set +e
python3 collector/collect_geps_awards.py --years "$previous_fiscal_year,$fiscal_year" --no-export
collect_rc=$?
if (( collect_rc == 0 )); then
  python3 collector/collect_jetro.py --pages 20 --detail-limit 0 \
    --backfill-from "$CATCHUP_FROM" --backfill-to "$TODAY" --backfill-all-notices-monthly
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_jetro_local.py --pages 20
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_yokohama_procurement.py --years "$(date +%Y)"
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_sapporo_procurement.py --years "$fiscal_year"
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_kobe_procurement.py --years "$(date +%Y)" --workers 4
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_fukuoka_procurement.py --years "$(date +%Y)" --workers 4
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_chiba_procurement.py --years "$fiscal_year"
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_kyoto_procurement.py --years "$(date +%Y)"
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_kawasaki_procurement.py --years "$(date +%Y)" --workers 6
  collect_rc=$?
fi
if (( collect_rc == 0 )); then
  python3 collector/collect_sendai_procurement.py --years "$fiscal_year" --workers 6
  collect_rc=$?
fi
set -e
trap 'on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR
if (( collect_rc != 0 )); then
  echo "ERROR: procurement collection failed rc=$collect_rc"
  [[ -s "$backup" ]] && cp "$backup" "$DB"
  record_stop "$collect_rc" "procurement collector returned a non-zero status; database restored from backup when available"
  exit "$collect_rc"
fi

CURRENT_STEP="procurement-health-check"
if ! python3 collector/check_health.py --source geps_awards --source jetro --source jetro_local --source yokohama_procurement --source sapporo_procurement --source kobe_procurement --source fukuoka_procurement --source chiba_procurement --source kyoto_procurement --source kawasaki_procurement --source sendai_procurement; then
  echo "ERROR: procurement health check failed; restoring database"
  [[ -s "$backup" ]] && cp "$backup" "$DB"
  record_stop 21 "procurement health check failed; database restored from backup when available"
  exit 21
fi

MONTH="$(date +%Y-%m)"
LISTED_MASTER_MARKER="$STATE_DIR/last-listed-master-refresh"
if [[ ! -f "$LISTED_MASTER_MARKER" ]] || ! grep -qx "$MONTH" "$LISTED_MASTER_MARKER"; then
  echo "Refreshing JPX / EDINET listed-company master"
  npm run collect:listed-master
  printf '%s\n' "$MONTH" > "$LISTED_MASTER_MARKER"
fi

echo "Listed-company EDINET catch-up window: $CATCHUP_FROM -> $TODAY"
run_step "listed-documents" npm run collect:listed-documents -- --start "$CATCHUP_FROM" --end "$TODAY"
run_step "listed-download" npm run collect:listed-bulk
run_step "listed-normalize" npm run normalize:listed-incremental
run_step "listed-salary-validation" npm run validate:listed-salary
run_step "listed-count-5x-validation" npm run validate:listed-counts
run_step "listed-shareholder-validation" npm run validate:listed-shareholders
# Heavy read-only audits run on the Windows production-data mirror, not on the production collector host.
run_step "listed-public-data-build" npm run build:listed-data

MONTH="$(date +%Y-%m)"
MONTH_MARKER="$STATE_DIR/last-monthly-refresh"
if [[ ! -f "$MONTH_MARKER" ]] || ! grep -qx "$MONTH" "$MONTH_MARKER"; then
  echo "Running monthly land/living/regional/employment/business-industry/economy-prices/energy refresh"
  python3 collector/collect_land_prices.py
  python3 collector/collect_living_layers.py
  python3 collector/collect_regional_trends.py
  python3 collector/collect_regional_migration_history.py
  python3 collector/collect_employment_economy.py
  python3 collector/collect_employment_wage_history.py
  python3 collector/collect_business_industry.py
  python3 collector/collect_business_industry_history.py
  python3 collector/collect_economy_prices.py
  python3 collector/collect_economy_prices_history.py
  python3 collector/collect_energy.py
  python3 collector/collect_energy_consumption_history.py
  python3 collector/check_health.py --source land_prices --source regional_trends --source regional_migration --source employment_economy --source employment_wage_history --source business_industry --source business_industry_history --source economy_prices --source economy_prices_history --source energy --source energy_consumption_history
  printf '%s\n' "$MONTH" > "$MONTH_MARKER"
fi

after_records="$(python3 - "$DB" <<'PY'
import sqlite3, sys
print(sqlite3.connect(sys.argv[1]).execute("select count(*) from procurements").fetchone()[0])
PY
)"
echo "Records: $before_records -> $after_records (delta=$((after_records-before_records)))"
if python3 scripts/cloudflare_web_analytics.py --days 7 --save public/data/site-analytics.json; then
  echo "Cloudflare Web Analytics snapshot updated"
else
  echo "WARNING: analytics refresh failed; continuing with the last saved snapshot"
fi
# Full published-data audits run on the Windows production-data mirror.
CURRENT_STEP="pre-deploy-release-tree-safety"
if [[ "$MODE" == "--scheduled" ]] && ! assert_release_tree_safe; then
  echo "ERROR: refusing scheduled deploy because source-code changes appeared during collection"
  record_stop 23 "non-generated source-code changes appeared during collection"
  exit 23
fi
exec 8>"$RELEASE_LOCK"
echo "Waiting for DATLUME release lock: $RELEASE_LOCK"
flock 8
export DATLUME_RELEASE_LOCK_HELD=1
run_step "astro-build" npm run build
run_step "cloudflare-deploy" bash ./deploy-datlume.sh
unset DATLUME_RELEASE_LOCK_HELD

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
