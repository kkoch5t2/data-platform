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
  "$@" || {
    local rc=$?
    case "$CURRENT_STEP" in
      *-health|*-audit|*-validation) touch "$STATE_DIR/retry-unsafe" ;;
    esac
    return "$rc"
  }
  case "$CURRENT_STEP" in
    procurement-*|listed-master|listed-public-data-build)
      rm -f "$STEP_DIR/company-registry-build" ;;
  esac
  printf '%s\n' "$TODAY" > "$STEP_DIR/$CURRENT_STEP.tmp"
  mv "$STEP_DIR/$CURRENT_STEP.tmp" "$STEP_DIR/$CURRENT_STEP"
}
FAILED_STEPS=()
try_step() {
  local source="$1"
  if run_step "$@"; then
    return 0
  fi
  FAILED_STEPS+=("$source")
  echo "WARNING: source step failed: $source; continuing independent sources"
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
echo "Procurement catch-up window: $CATCHUP_FROM -> $TODAY"

fiscal_year="$(date +%Y)"
if (( 10#$(date +%m) < 4 )); then fiscal_year="$((10#$fiscal_year-1))"; fi
previous_fiscal_year="$((10#$fiscal_year-1))"

CURRENT_STEP="procurement-collection"
stale_upstream_args=()
stale_upstream_sources=()
record_upstream_failure() {
  local source="$1"
  if [[ -n "${DATLUME_UPSTREAM_FAILURE_LOG:-}" ]]; then
    python3 scripts/log-upstream-failure.py --source "$source" --log "$DATLUME_UPSTREAM_FAILURE_LOG"
  fi
}
procurement_failures_before=${#FAILED_STEPS[@]}
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
  stale_upstream_args+=(--allow-stale-upstream jetro)
  stale_upstream_sources+=(jetro)
fi
if [[ -f "$STEP_DIR/procurement-jetro-local" ]]; then
  echo "--- already collected: procurement-jetro-local ---"
elif python3 collector/collect_jetro_local.py --probe; then
  try_step "procurement-jetro-local" python3 collector/collect_jetro_local.py --pages 20
else
  echo "WARNING: JETRO local API unavailable; preserving the last verified local snapshot"
  record_upstream_failure jetro_local
  stale_upstream_args+=(--allow-stale-upstream jetro_local)
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
  stale_upstream_args+=(--allow-stale-upstream sendai_procurement)
  stale_upstream_sources+=(sendai_procurement)
fi
printf '%s\n' "${stale_upstream_sources[@]}" > "$STATE_DIR/stale-upstream-sources.txt"
if (( ${#FAILED_STEPS[@]} == procurement_failures_before )); then
  CURRENT_STEP="procurement-health-check"
  if ! python3 collector/check_health.py --source geps_awards --source jetro --source jetro_local --source yokohama_procurement --source sapporo_procurement --source kobe_procurement --source fukuoka_procurement --source chiba_procurement --source kyoto_procurement --source kawasaki_procurement --source sendai_procurement "${stale_upstream_args[@]}"; then
    echo "ERROR: procurement health check failed; restoring database"
    touch "$STATE_DIR/retry-unsafe"
    exit 21
  fi
  CURRENT_STEP="procurement-regression-check"
  if [[ -s "$PREV_SUMMARY" ]] && ! python3 scripts/check-procurement-regression.py --previous "$PREV_SUMMARY" --current "$ROOT/src/data/summary.json"; then
    echo "ERROR: procurement coverage regressed; restoring database and previous summary"
    touch "$STATE_DIR/retry-unsafe"
    exit 24
  fi
else
  echo "WARNING: procurement health check deferred until all procurement sources succeed"
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
  run_step "listed-salary-validation" npm run validate:listed-salary
  run_step "listed-count-5x-validation" npm run validate:listed-counts
  run_step "listed-shareholder-validation" npm run validate:listed-shareholders
else
  echo "WARNING: listed validation and builds deferred until their source pipeline succeeds"
fi
shokuba_failures_before=${#FAILED_STEPS[@]}
try_step "shokuba-workplace" npm run collect:shokuba
if (( ${#FAILED_STEPS[@]} == shokuba_failures_before )); then
  run_step "shokuba-health" python3 collector/check_health.py --source shokuba
fi
GBIZ_MARKER="$STATE_DIR/last-gbiz-activity-refresh"
MONTH="$(date +%Y-%m)"
if [[ ! -f "$GBIZ_MARKER" ]] || ! grep -qx "$MONTH" "$GBIZ_MARKER"; then
  gbiz_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-gbiz-subsidy" npm run collect:gbiz-subsidy
  try_step "monthly-gbiz-patent" npm run collect:gbiz-patent
  if (( ${#FAILED_STEPS[@]} == gbiz_failures_before )); then
    run_step "monthly-gbiz-health" python3 collector/check_health.py --source gbiz_subsidy --source gbiz_patent
    printf '%s\n' "$MONTH" > "$GBIZ_MARKER"
  fi
fi
# Build derived datasets only after their input sources have completed.
if (( ${#FAILED_STEPS[@]} == listed_failures_before )); then
  run_step "listed-public-data-build" npm run build:listed-data
fi
if (( ${#FAILED_STEPS[@]} == 0 )); then
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
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    run_step "monthly-core-health" python3 collector/check_health.py --source land_prices --source regional_trends --source regional_migration --source employment_economy --source employment_wage_history --source business_industry --source business_industry_history --source economy_prices --source economy_prices_history --source energy --source energy_consumption_history
    printf '%s\n' "$MONTH" > "$MONTH_MARKER"
  fi
fi

# Independently refresh this newly added source even when the regional monthly marker already passed.
LODGING_MARKER="$STATE_DIR/last-lodging-statistics-refresh"
if [[ ! -f "$LODGING_MARKER" ]] || ! grep -qx "$MONTH" "$LODGING_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-lodging-statistics" npm run collect:lodging-statistics
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    run_step "monthly-lodging-health" python3 collector/check_health.py --source lodging_statistics
    printf '%s\n' "$MONTH" > "$LODGING_MARKER"
  fi
fi

# Station observations use a separate marker so an existing monthly run does not skip them.
TRANSPORT_MARKER="$STATE_DIR/last-public-transport-refresh"
if [[ ! -f "$TRANSPORT_MARKER" ]] || ! grep -qx "$MONTH" "$TRANSPORT_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-public-transport" npm run collect:public-transport
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    run_step "monthly-public-transport-audit" npm run audit:public-transport
    run_step "monthly-public-transport-health" python3 collector/check_health.py --source public_transport
    printf '%s\n' "$MONTH" > "$TRANSPORT_MARKER"
  fi
fi

JMA_MARKER="$STATE_DIR/last-jma-weather-refresh"
if [[ ! -f "$JMA_MARKER" ]] || ! grep -qx "$MONTH" "$JMA_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-jma-weather" npm run collect:jma-weather
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    run_step "monthly-jma-weather-audit" npm run audit:jma-weather
    run_step "monthly-jma-weather-health" python3 collector/check_health.py --source jma_weather
    printf '%s\n' "$MONTH" > "$JMA_MARKER"
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
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    run_step "monthly-secondary-health" python3 collector/check_health.py --source housing_land_2023 --source social_population --source retail_prices_city
    printf '%s\n' "$MONTH" > "$SECONDARY_MONTH_MARKER"
  fi
fi

# Independent marker also runs a newly added projection source in an already refreshed month.
IPSS_MARKER="$STATE_DIR/last-ipss-population-refresh"
if [[ ! -f "$IPSS_MARKER" ]] || ! grep -qx "$MONTH" "$IPSS_MARKER"; then
  group_failures_before=${#FAILED_STEPS[@]}
  try_step "monthly-ipss-population" python3 collector/collect_ipss_population.py
  if (( ${#FAILED_STEPS[@]} == group_failures_before )); then
    run_step "monthly-ipss-health" python3 collector/check_health.py --source ipss_population
    printf '%s\n' "$MONTH" > "$IPSS_MARKER"
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
    run_step "weekly-reinfolib-health" python3 collector/check_health.py --source reinfolib_transactions
    printf '%s\n' "$REINFOLIB_WEEK" > "$REINFOLIB_MARKER"
  fi
fi

try_step "reinfolib-history-if-new" python3 collector/backfill_reinfolib_history.py --if-new

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
if (( ${#FAILED_STEPS[@]} > 0 )); then
  printf 'ERROR: source collection incomplete; retry only: %s\n' "${FAILED_STEPS[*]}"
  exit 25
fi
echo "Daily collection and public-data generation complete"
