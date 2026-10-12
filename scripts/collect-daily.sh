#!/usr/bin/env bash
# Collection only. scheduled-refresh.py owns isolation, rollback and publication.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="${DATLUME_MARKER_DIR:?collector must run inside the refresh transaction}"
DB="$ROOT/data/public_it.db"
LAST_SUCCESS="$STATE_DIR/last-success-date"
PREV_SUMMARY="$STATE_DIR/pre-refresh-summary.json"
TODAY="$(TZ=Asia/Tokyo date +%F)"
CURRENT_STEP="startup"
mkdir -p "$STATE_DIR"
cd "$ROOT"
STEP_DIR="$STATE_DIR/completed-steps"
mkdir -p "$STEP_DIR"
run_step() {
  CURRENT_STEP="$1"; shift
  if [[ -f "$STEP_DIR/$CURRENT_STEP" ]]; then
    echo "--- already collected: $CURRENT_STEP ---"
    return 0
  fi
  echo "--- step: $CURRENT_STEP ---"
  "$@" || return $?
  case "$CURRENT_STEP" in
    procurement-*-health) ;;
    procurement-*) rm -f "$STEP_DIR/$CURRENT_STEP-health" "$STEP_DIR/company-registry-build" ;;
    listed-normalize)
      rm -f "$STEP_DIR/listed-salary-validation" "$STEP_DIR/listed-count-5x-validation" \
        "$STEP_DIR/listed-shareholder-validation" "$STEP_DIR/listed-public-data-build" \
        "$STEP_DIR/company-registry-build" ;;
    listed-master|listed-public-data-build) rm -f "$STEP_DIR/company-registry-build" ;;
    monthly-lodging-statistics) rm -f "$STEP_DIR/monthly-lodging-health" ;;
    monthly-ipss-population) rm -f "$STEP_DIR/monthly-ipss-health" ;;
    shokuba-workplace) rm -f "$STEP_DIR/shokuba-health" ;;
    weekly-reinfolib-transactions) rm -f "$STEP_DIR/weekly-reinfolib-health" ;;
    monthly-public-transport) rm -f "$STEP_DIR/monthly-public-transport-audit" "$STEP_DIR/monthly-public-transport-health" ;;
    monthly-jma-weather) rm -f "$STEP_DIR/monthly-jma-weather-audit" "$STEP_DIR/monthly-jma-weather-health" ;;
    monthly-*) rm -f "$STEP_DIR/$CURRENT_STEP-health" ;;
  esac
  printf '%s\n' "$TODAY" > "$STEP_DIR/$CURRENT_STEP.tmp"
  mv "$STEP_DIR/$CURRENT_STEP.tmp" "$STEP_DIR/$CURRENT_STEP"
}
FAILED_STEPS=()
UNRESTORED_STEPS=()
fallback_step() {
  local source="$1" reason="$2" result key
  rm -f "$STEP_DIR/$source" "$STEP_DIR/$source-health" "$STEP_DIR/company-registry-build"
  case "$source" in
    listed-*)
      rm -f "$STEP_DIR"/listed-* "$STEP_DIR/company-registry-build"
      if [[ -f "$STATE_DIR/../../../../last-listed-master-refresh" ]]; then
        cp "$STATE_DIR/../../../../last-listed-master-refresh" "$STATE_DIR/last-listed-master-refresh"
      else
        rm -f "$STATE_DIR/last-listed-master-refresh"
      fi ;;
  esac
  FAILED_STEPS+=("$source")
  if result="$(python3 scripts/restore-failed-source.py "$source" --backup "${DATLUME_BASELINE_DB:-$STATE_DIR/../../../../transactions/daily/public_it.db}" 2>&1)"; then
    key="${result##*$'\n'}"
    echo "$result"
    stale_upstream_sources+=("$key")
    record_upstream_failure "$key" source-fallback
    echo "WARNING: $reason; restored previous snapshot for $source"
  else
    echo "$result" >&2
    UNRESTORED_STEPS+=("$source")
    record_upstream_failure "$source" source-fallback-unavailable
    echo "ERROR: $source has no safe source-level fallback; publication blocked" >&2
  fi
}
try_step() {
  local source="$1"
  if run_step "$@"; then return 0; fi
  fallback_step "$source" "collection failed"
}
verify_step() {
  local source="$1" check="$2"
  shift 2
  if run_step "$check" "$@"; then return 0; fi
  rm -f "$STEP_DIR/$check"
  fallback_step "$source" "validation failed"
}
verify_catalog_health() {
  local source="$1" check="$2" key="$3" stale
  local extra=()
  for stale in "${stale_upstream_sources[@]}"; do
    if [[ "$stale" == "$key" ]]; then extra=(--allow-stale-upstream "$key"); break; fi
  done
  verify_step "$source" "$check" python3 collector/check_health.py --source "$key" "${extra[@]}"
}
trap 'echo "Collection failed: step=$CURRENT_STEP line=$LINENO rc=$?"' ERR
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

if [[ ! -s "$PREV_SUMMARY" && -s "$ROOT/src/data/summary.json" ]]; then
  cp "$ROOT/src/data/summary.json" "$PREV_SUMMARY"
fi

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
STALE_SINCE="$STATE_DIR/source-stale-since.json"
if [[ -s "$STALE_SINCE" ]]; then
  stale_oldest="$(python3 - "$STALE_SINCE" <<'PY_STALE'
import json,sys
dates=json.load(open(sys.argv[1])).values()
print(min(dates, default=''))
PY_STALE
)"
  if [[ -n "$stale_oldest" && "$stale_oldest" < "$CATCHUP_FROM" ]]; then
    CATCHUP_FROM="$stale_oldest"
  fi
fi
echo "Procurement catch-up window: $CATCHUP_FROM -> $TODAY"

fiscal_year="$(date +%Y)"
if (( 10#$(date +%m) < 4 )); then fiscal_year="$((10#$fiscal_year-1))"; fi
previous_fiscal_year="$((10#$fiscal_year-1))"

CURRENT_STEP="procurement-collection"
stale_upstream_sources=()
record_upstream_failure() {
  local source="$1" event="${2:-upstream-probe-failed}"
  if [[ -n "${DATLUME_UPSTREAM_FAILURE_LOG:-}" ]]; then
    python3 scripts/log-upstream-failure.py --source "$source" --event "$event" --log "$DATLUME_UPSTREAM_FAILURE_LOG"
  fi
}
try_step "procurement-geps-awards" python3 collector/collect_geps_awards.py --years "$previous_fiscal_year,$fiscal_year" --no-export
# A failed upstream probe leaves the verified snapshot unchanged.
if [[ -f "$STEP_DIR/procurement-jetro" ]]; then
  echo "--- already collected: procurement-jetro ---"
elif python3 collector/collect_jetro.py --probe; then
  try_step "procurement-jetro" python3 collector/collect_jetro.py --pages 20 --detail-limit 0 \
    --backfill-from "$CATCHUP_FROM" --backfill-to "$TODAY" --backfill-all-notices-monthly
else
  echo "WARNING: JETRO national API unavailable; preserving the last verified national snapshot"
  record_upstream_failure jetro
  stale_upstream_sources+=(jetro)
fi
if [[ -f "$STEP_DIR/procurement-jetro-local" ]]; then
  echo "--- already collected: procurement-jetro-local ---"
elif python3 collector/collect_jetro_local.py --probe; then
  try_step "procurement-jetro-local" python3 collector/collect_jetro_local.py --pages 20
else
  echo "WARNING: JETRO local API unavailable; preserving the last verified local snapshot"
  record_upstream_failure jetro_local
  stale_upstream_sources+=(jetro_local)
fi
try_step "procurement-yokohama" python3 collector/collect_yokohama_procurement.py --years "$(date +%Y)"
try_step "procurement-sapporo" python3 collector/collect_sapporo_procurement.py --years "$fiscal_year"
try_step "procurement-kobe" python3 collector/collect_kobe_procurement.py --years "$(date +%Y)" --workers 4
try_step "procurement-fukuoka" python3 collector/collect_fukuoka_procurement.py --years "$(date +%Y)" --workers 4
try_step "procurement-chiba" python3 collector/collect_chiba_procurement.py --years "$fiscal_year"
try_step "procurement-kyoto" python3 collector/collect_kyoto_procurement.py --years "$(date +%Y)"
try_step "procurement-kawasaki" python3 collector/collect_kawasaki_procurement.py --years "$(date +%Y)" --workers 6
# Sendai's public EPI endpoint occasionally accepts no TCP connections. Keep the
# last verified rows and timestamp when its probe fails.
if [[ -f "$STEP_DIR/procurement-sendai" ]]; then
  echo "--- already collected: procurement-sendai ---"
elif python3 collector/collect_sendai_procurement.py --probe; then
  try_step "procurement-sendai" python3 collector/collect_sendai_procurement.py --years "$fiscal_year" --workers 6
else
  echo "WARNING: Sendai EPI is unavailable; preserving the last verified Sendai snapshot"
  record_upstream_failure sendai_procurement
  stale_upstream_sources+=(sendai_procurement)
fi
# Inspect each source separately so an unhealthy source alone loses its checkpoint.
  while read -r source key; do
    verify_catalog_health "$source" "$source-health" "$key"
  done <<'SOURCES'
procurement-geps-awards geps_awards
procurement-jetro jetro
procurement-jetro-local jetro_local
procurement-yokohama yokohama_procurement
procurement-sapporo sapporo_procurement
procurement-kobe kobe_procurement
procurement-fukuoka fukuoka_procurement
procurement-chiba chiba_procurement
procurement-kyoto kyoto_procurement
procurement-kawasaki kawasaki_procurement
procurement-sendai sendai_procurement
SOURCES
  if (( ${#UNRESTORED_STEPS[@]} == 0 )); then
    CURRENT_STEP="procurement-regression-check"
    if [[ -s "$PREV_SUMMARY" ]]; then
      regression_report="$STATE_DIR/procurement-regression.txt"
      if ! python3 scripts/check-procurement-regression.py --previous "$PREV_SUMMARY" --current "$ROOT/src/data/summary.json" > "$regression_report" 2>&1; then
        cat "$regression_report"
        mapped=0
        while read -r field; do
          source=""
          case "$field" in
            gepsRecords) source=procurement-geps-awards ;;
            jetroRecords) source=procurement-jetro ;;
            yokohamaRecords) source=procurement-yokohama ;;
            sapporoRecords) source=procurement-sapporo ;;
            kobeRecords) source=procurement-kobe ;;
            fukuokaRecords) source=procurement-fukuoka ;;
            chibaRecords) source=procurement-chiba ;;
            kyotoRecords) source=procurement-kyoto ;;
            kawasakiRecords) source=procurement-kawasaki ;;
            sendaiRecords) source=procurement-sendai ;;
          esac
          if [[ -n "$source" ]]; then
            fallback_step "$source" "procurement regression"
            mapped=1
          fi
        done < <(sed -n 's/^[[:space:]]*-[[:space:]]*\([^:]*\):.*/\1/p' "$regression_report")
        if (( mapped == 0 )); then
          echo "ERROR: aggregate procurement regression has no identifiable source; checkpoints retained for diagnosis"
          exit 24
        fi
        if ! python3 scripts/check-procurement-regression.py --previous "$PREV_SUMMARY" --current "$ROOT/src/data/summary.json" > "$regression_report" 2>&1; then
          cat "$regression_report"
          echo "ERROR: procurement regression remains after source fallback; publication blocked" >&2
          exit 24
        fi
      fi
    fi
  fi

MONTH="$(date +%Y-%m)"
LISTED_MASTER_MARKER="$STATE_DIR/last-listed-master-refresh"
listed_failures_before=${#FAILED_STEPS[@]}
if python3 scripts/listed-master-refresh-needed.py --marker "$LISTED_MASTER_MARKER"; then
  echo "Refreshing JPX / EDINET listed-company master"
  try_step "listed-master" npm run collect:listed-master
  if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
    printf '%s\n' "$MONTH" > "$LISTED_MASTER_MARKER"
  fi
fi

echo "Listed-company EDINET catch-up window: $CATCHUP_FROM -> $TODAY"
if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  try_step "listed-documents" npm run collect:listed-documents -- --start "$CATCHUP_FROM" --end "$TODAY"
fi
if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  try_step "listed-download" npm run collect:listed-bulk
fi
if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  try_step "listed-normalize" npm run normalize:listed-incremental
fi
if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  verify_step "listed-normalize" "listed-salary-validation" npm run validate:listed-salary
  if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  verify_step "listed-normalize" "listed-count-5x-validation" npm run validate:listed-counts
  fi
  if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  verify_step "listed-normalize" "listed-shareholder-validation" npm run validate:listed-shareholders
  fi
else
  echo "WARNING: listed validation and builds deferred until their source pipeline succeeds"
fi
shokuba_failures_before=${#FAILED_STEPS[@]}
try_step "shokuba-workplace" npm run collect:shokuba
if (( ${#FAILED_STEPS[@]} == shokuba_failures_before )); then
  verify_step "shokuba-workplace" "shokuba-health" python3 collector/check_health.py --source shokuba
fi
GBIZ_MARKER="$STATE_DIR/last-gbiz-activity-refresh"
MONTH="$(date +%Y-%m)"
if [[ ! -f "$GBIZ_MARKER" ]] || ! grep -qx "$MONTH" "$GBIZ_MARKER"; then
  gbiz_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-gbiz-subsidy" npm run collect:gbiz-subsidy
  try_step "monthly-gbiz-patent" npm run collect:gbiz-patent
  verify_step "monthly-gbiz-subsidy" "monthly-gbiz-subsidy-health" python3 collector/check_health.py --source gbiz_subsidy
    verify_step "monthly-gbiz-patent" "monthly-gbiz-patent-health" python3 collector/check_health.py --source gbiz_patent
  if (( ${#FAILED_STEPS[@]} == gbiz_failures_before )); then
    printf '%s\n' "$MONTH" > "$GBIZ_MARKER"
  fi
fi
# Build derived datasets only after their input sources have completed.
if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  run_step "listed-public-data-build" npm run build:listed-data
fi
if (( ${#UNRESTORED_STEPS[@]} == 0 )); then
  run_step "company-registry-build" npm run build:company-registry
fi

MONTH="$(date +%Y-%m)"
MONTH_MARKER="$STATE_DIR/last-monthly-refresh"
if [[ ! -f "$MONTH_MARKER" ]] || ! grep -qx "$MONTH" "$MONTH_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  echo "Running monthly land/living/regional/employment/business-industry/economy-prices/energy refresh"
  try_step "monthly-land-prices" python3 collector/collect_land_prices.py
  try_step "monthly-living-layers" python3 collector/collect_living_layers.py
  try_step "monthly-regional-trends" python3 collector/collect_regional_trends.py
  try_step "monthly-regional-migration" python3 collector/collect_regional_migration_history.py
  try_step "monthly-employment-economy" python3 collector/collect_employment_economy.py
  try_step "monthly-employment-wage" python3 collector/collect_employment_wage_history.py
  try_step "monthly-business-industry" python3 collector/collect_business_industry.py
  try_step "monthly-business-history" python3 collector/collect_business_industry_history.py
  try_step "monthly-economy-prices" python3 collector/collect_economy_prices.py
  try_step "monthly-economy-history" python3 collector/collect_economy_prices_history.py
  try_step "monthly-energy" python3 collector/collect_energy.py
  try_step "monthly-energy-history" python3 collector/collect_energy_consumption_history.py
  while read -r source key; do
      verify_catalog_health "$source" "$source-health" "$key"
    done <<'SOURCES'
monthly-land-prices land_prices
monthly-regional-trends regional_trends
monthly-regional-migration regional_migration
monthly-employment-economy employment_economy
monthly-employment-wage employment_wage_history
monthly-business-industry business_industry
monthly-business-history business_industry_history
monthly-economy-prices economy_prices
monthly-economy-history economy_prices_history
monthly-energy energy
monthly-energy-history energy_consumption_history
SOURCES
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    printf '%s\n' "$MONTH" > "$MONTH_MARKER"
  fi
fi

# Independently refresh this newly added source even when the regional monthly marker already passed.
LODGING_MARKER="$STATE_DIR/last-lodging-statistics-refresh"
if [[ ! -f "$LODGING_MARKER" ]] || ! grep -qx "$MONTH" "$LODGING_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-lodging-statistics" npm run collect:lodging-statistics
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    verify_step "monthly-lodging-statistics" "monthly-lodging-health" python3 collector/check_health.py --source lodging_statistics
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      printf '%s\n' "$MONTH" > "$LODGING_MARKER"
    fi
  fi
fi

# Station observations use a separate marker so an existing monthly run does not skip them.
TRANSPORT_MARKER="$STATE_DIR/last-public-transport-refresh"
if [[ ! -f "$TRANSPORT_MARKER" ]] || ! grep -qx "$MONTH" "$TRANSPORT_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-public-transport" npm run collect:public-transport
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    verify_step "monthly-public-transport" "monthly-public-transport-audit" npm run audit:public-transport
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      verify_step "monthly-public-transport" "monthly-public-transport-health" python3 collector/check_health.py --source public_transport
    fi
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      printf '%s\n' "$MONTH" > "$TRANSPORT_MARKER"
    fi
  fi
fi

JMA_MARKER="$STATE_DIR/last-jma-weather-refresh"
if [[ ! -f "$JMA_MARKER" ]] || ! grep -qx "$MONTH" "$JMA_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-jma-weather" npm run collect:jma-weather
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    verify_step "monthly-jma-weather" "monthly-jma-weather-audit" npm run audit:jma-weather
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      verify_step "monthly-jma-weather" "monthly-jma-weather-health" python3 collector/check_health.py --source jma_weather
    fi
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      printf '%s\n' "$MONTH" > "$JMA_MARKER"
    fi
  fi
fi

# This marker is separate so a month already refreshed before this source list changed
# still runs the newly covered collectors once on the next scheduled attempt.
SECONDARY_MONTH_MARKER="$STATE_DIR/last-monthly-secondary-refresh"
if [[ ! -f "$SECONDARY_MONTH_MARKER" ]] || ! grep -qx "$MONTH" "$SECONDARY_MONTH_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-housing-land" python3 collector/collect_housing_land_2023.py
  try_step "monthly-social-population" python3 collector/collect_social_population.py
  try_step "monthly-retail-prices-city" python3 collector/collect_retail_prices_city.py
  verify_step "monthly-housing-land" "monthly-housing-land-health" python3 collector/check_health.py --source housing_land_2023
    verify_step "monthly-social-population" "monthly-social-population-health" python3 collector/check_health.py --source social_population
    verify_step "monthly-retail-prices-city" "monthly-retail-prices-city-health" python3 collector/check_health.py --source retail_prices_city
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    printf '%s\n' "$MONTH" > "$SECONDARY_MONTH_MARKER"
  fi
fi

# Independent marker also runs a newly added projection source in an already refreshed month.
IPSS_MARKER="$STATE_DIR/last-ipss-population-refresh"
if [[ ! -f "$IPSS_MARKER" ]] || ! grep -qx "$MONTH" "$IPSS_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-ipss-population" python3 collector/collect_ipss_population.py
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    verify_step "monthly-ipss-population" "monthly-ipss-health" python3 collector/check_health.py --source ipss_population
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      printf '%s\n' "$MONTH" > "$IPSS_MARKER"
    fi
  fi
fi

REINFOLIB_WEEK="$(date +%G-W%V)"
REINFOLIB_MARKER="$STATE_DIR/last-reinfolib-check"
if [[ ! -f "$REINFOLIB_MARKER" ]] || ! grep -qx "$REINFOLIB_WEEK" "$REINFOLIB_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  echo "Checking MLIT Reinfolib for a newly published transaction quarter"
  try_step "weekly-reinfolib-transactions" python3 collector/collect_reinfolib_transactions.py --if-new
  try_step "weekly-reinfolib-history" python3 collector/backfill_reinfolib_history.py --refresh-recent
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    verify_step "weekly-reinfolib-transactions" "weekly-reinfolib-health" python3 collector/check_health.py --source reinfolib_transactions
    if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
      printf '%s\n' "$REINFOLIB_WEEK" > "$REINFOLIB_MARKER"
    fi
  fi
fi

# Both history steps write the same shards; do not overwrite a restored snapshot.
if [[ " ${FAILED_STEPS[*]} " != *" weekly-reinfolib-history "* ]]; then
  try_step "reinfolib-history-if-new" python3 collector/backfill_reinfolib_history.py --if-new
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
printf '%s\n' "${stale_upstream_sources[@]}" > "$STATE_DIR/stale-upstream-sources.txt"
python3 - "$STALE_SINCE" "$TODAY" "$STEP_DIR" "$STATE_DIR/stale-upstream-sources.txt" <<'PY_STALE'
import json,sys
from pathlib import Path
path,today,steps,stale=Path(sys.argv[1]),sys.argv[2],Path(sys.argv[3]),Path(sys.argv[4])
prior=json.loads(path.read_text()) if path.exists() else {}
failed=set(stale.read_text().splitlines())
keys={'procurement-geps-awards':'geps_awards','procurement-jetro':'jetro',
'procurement-jetro-local':'jetro_local','procurement-yokohama':'yokohama_procurement',
'procurement-sapporo':'sapporo_procurement','procurement-kobe':'kobe_procurement',
'procurement-fukuoka':'fukuoka_procurement','procurement-chiba':'chiba_procurement',
'procurement-kyoto':'kyoto_procurement','procurement-kawasaki':'kawasaki_procurement',
'procurement-sendai':'sendai_procurement'}
for step,key in keys.items():
    if (steps/step).exists() and key not in failed:
        prior.pop(key,None)
for key in failed:
    if key in keys.values():
        prior.setdefault(key,today)
temp=path.with_suffix('.tmp')
temp.write_text(json.dumps(prior,sort_keys=True)+'\n')
temp.replace(path)
PY_STALE
if (( ${#UNRESTORED_STEPS[@]} > 0 )); then
  printf 'ERROR: source fallback unavailable; publication blocked for: %s\n' "${UNRESTORED_STEPS[*]}"
  exit 25
fi
if (( ${#FAILED_STEPS[@]} > 0 )); then
  printf 'WARNING: published prior snapshots for: %s\n' "${FAILED_STEPS[*]}"
fi
echo "Daily collection and public-data generation complete"
