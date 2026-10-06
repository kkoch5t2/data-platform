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
run_step() { CURRENT_STEP="$1"; shift; echo "--- step: $CURRENT_STEP ---"; "$@"; }
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

if [[ -s "$ROOT/src/data/summary.json" ]]; then
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
trap 'echo "Collection failed: step=$CURRENT_STEP line=$LINENO rc=$?"' ERR
if (( collect_rc != 0 )); then
  echo "ERROR: procurement collection failed rc=$collect_rc"
  exit "$collect_rc"
fi

CURRENT_STEP="procurement-health-check"
if ! python3 collector/check_health.py --source geps_awards --source jetro --source jetro_local --source yokohama_procurement --source sapporo_procurement --source kobe_procurement --source fukuoka_procurement --source chiba_procurement --source kyoto_procurement --source kawasaki_procurement --source sendai_procurement; then
  echo "ERROR: procurement health check failed; restoring database"
  exit 21
fi

CURRENT_STEP="procurement-regression-check"
if [[ -s "$PREV_SUMMARY" ]] && ! python3 scripts/check-procurement-regression.py --previous "$PREV_SUMMARY" --current "$ROOT/src/data/summary.json"; then
  echo "ERROR: procurement coverage regressed; restoring database and previous summary"
  exit 24
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
run_step "shokuba-workplace" npm run collect:shokuba
run_step "shokuba-health" python3 collector/check_health.py --source shokuba
GBIZ_MARKER="$STATE_DIR/last-gbiz-activity-refresh"
MONTH="$(date +%Y-%m)"
if [[ ! -f "$GBIZ_MARKER" ]] || ! grep -qx "$MONTH" "$GBIZ_MARKER" ]; then
  run_step "monthly-gbiz-subsidy" npm run collect:gbiz-subsidy
  run_step "monthly-gbiz-patent" npm run collect:gbiz-patent
  run_step "monthly-gbiz-health" python3 collector/check_health.py --source gbiz_subsidy --source gbiz_patent
  printf '%s\n' "$MONTH" > "$GBIZ_MARKER"
fi
# Build the public listed-company snapshot before reconciling the company registry.
run_step "listed-public-data-build" npm run build:listed-data
# Procurement and listed-master updates both affect unlisted-company identity and award summaries.
run_step "company-registry-build" npm run build:company-registry

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

# Independently refresh this newly added source even when the regional monthly marker already passed.
LODGING_MARKER="$STATE_DIR/last-lodging-statistics-refresh"
if [[ ! -f "$LODGING_MARKER" ]] || ! grep -qx "$MONTH" "$LODGING_MARKER"; then
  run_step "monthly-lodging-statistics" npm run collect:lodging-statistics
  run_step "monthly-lodging-health" python3 collector/check_health.py --source lodging_statistics
  printf '%s\n' "$MONTH" > "$LODGING_MARKER"
fi

# Station observations use a separate marker so an existing monthly run does not skip them.
JMA_MARKER="$STATE_DIR/last-jma-weather-refresh"
if [[ ! -f "$JMA_MARKER" ]] || ! grep -qx "$MONTH" "$JMA_MARKER"; then
  run_step "monthly-jma-weather" npm run collect:jma-weather
  run_step "monthly-jma-weather-audit" npm run audit:jma-weather
  run_step "monthly-jma-weather-health" python3 collector/check_health.py --source jma_weather
  printf '%s\n' "$MONTH" > "$JMA_MARKER"
fi

# This marker is separate so a month already refreshed before this source list changed
# still runs the newly covered collectors once on the next scheduled attempt.
SECONDARY_MONTH_MARKER="$STATE_DIR/last-monthly-secondary-refresh"
if [[ ! -f "$SECONDARY_MONTH_MARKER" ]] || ! grep -qx "$MONTH" "$SECONDARY_MONTH_MARKER"; then
  run_step "monthly-housing-land" python3 collector/collect_housing_land_2023.py
  run_step "monthly-social-population" python3 collector/collect_social_population.py
  run_step "monthly-retail-prices-city" python3 collector/collect_retail_prices_city.py
  run_step "monthly-secondary-health" python3 collector/check_health.py --source housing_land_2023 --source social_population --source retail_prices_city
  printf '%s\n' "$MONTH" > "$SECONDARY_MONTH_MARKER"
fi

# Independent marker also runs a newly added projection source in an already refreshed month.
IPSS_MARKER="$STATE_DIR/last-ipss-population-refresh"
if [[ ! -f "$IPSS_MARKER" ]] || ! grep -qx "$MONTH" "$IPSS_MARKER"; then
  run_step "monthly-ipss-population" python3 collector/collect_ipss_population.py
  run_step "monthly-ipss-health" python3 collector/check_health.py --source ipss_population
  printf '%s\n' "$MONTH" > "$IPSS_MARKER"
fi

REINFOLIB_WEEK="$(date +%G-W%V)"
REINFOLIB_MARKER="$STATE_DIR/last-reinfolib-check"
if [[ ! -f "$REINFOLIB_MARKER" ]] || ! grep -qx "$REINFOLIB_WEEK" "$REINFOLIB_MARKER"; then
  echo "Checking MLIT Reinfolib for a newly published transaction quarter"
  python3 collector/collect_reinfolib_transactions.py --if-new
  python3 collector/check_health.py --source reinfolib_transactions
  printf '%s\n' "$REINFOLIB_WEEK" > "$REINFOLIB_MARKER"
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
echo "Daily collection and public-data generation complete"
