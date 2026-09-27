#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
STATE_DIR="$ROOT/data/automation"
LOG_DIR="$STATE_DIR/weekly-audit-logs"
LOCK="$STATE_DIR/weekly-audit.lock"
mkdir -p "$LOG_DIR"
cd "$ROOT"

exec 9>"$LOCK"
if ! flock -n 9; then exit 0; fi
LOG="$LOG_DIR/$(date +%F).log"
FAILURE_LOG="$LOG_DIR/failures.log"
CURRENT_STEP="startup"
exec > >(tee -a "$LOG") 2>&1
find "$LOG_DIR" -type f -name '*.log' -mtime +90 -delete || true

record_stop() {
  local rc="$1" reason="$2"
  reason="${reason//$'\n'/ }"
  reason="${reason//$'\t'/ }"
  printf '%s\tstep=%s\trc=%s\treason=%s\tweekly_log=%s\n' \
    "$(date -Is)" "$CURRENT_STEP" "$rc" "$reason" "$LOG" >> "$FAILURE_LOG"
}

on_error() {
  local rc="$1" line="$2" command="$3"
  trap - ERR
  command="${command//$'\n'/ }"
  echo "ERROR: DATLUME weekly audit stopped: step=$CURRENT_STEP rc=$rc line=$line command=$command"
  record_stop "$rc" "line=$line command=$command"
  exit "$rc"
}

run_step() {
  CURRENT_STEP="$1"
  shift
  echo "--- step: $CURRENT_STEP ---"
  "$@"
}
trap 'on_error "$?" "$LINENO" "$BASH_COMMAND"' ERR

echo "=== DATLUME weekly audit start $(date -Is) ==="
bad="$({ git diff --name-only; git diff --cached --name-only; } | sort -u | while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  case "$path" in
    src/data/*.ts|src/data/sources.json|public/data/*.json) ;;
    *) printf '%s\n' "$path" ;;
  esac
done)"
if [[ -n "$bad" ]]; then
  CURRENT_STEP="release-tree-safety"
  echo "ERROR: non-generated tracked changes exist; refusing weekly audit"
  printf '%s\n' "$bad"
  record_stop 30 "non-generated tracked changes exist"
  exit 30
fi

run_step "listed-salary-validation" npm run validate:listed-salary
run_step "listed-count-5x-validation" npm run validate:listed-counts
run_step "listed-shareholder-validation" npm run validate:listed-shareholders
run_step "listed-financial-validation" npm run validate:listed-financials
run_step "listed-public-data-build" npm run build:listed-data
run_step "full-published-data-audit" npm run audit:data
run_step "listed-cross-filing-10x-validation" npm run audit:listed-cross-filing
run_step "listed-source-audit" npm run audit:listed-source
run_step "listed-xbrl-audit" npm run audit:listed-xbrl
run_step "astro-build" npm run build
run_step "html-audit" npm run audit:html

export E2E_BASE_URL="https://datlume.com"
export E2E_ONLY="/,/listed-companies/,/listed-companies/7203/,/listed-companies/compare/,/procurement/,/procurement/companies/co_f96b284bc087/"
run_step "production-e2e" npm run e2e:deep
unset E2E_BASE_URL E2E_ONLY

echo "=== DATLUME weekly audit success $(date -Is) ==="
