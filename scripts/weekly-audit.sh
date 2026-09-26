#!/usr/bin/env bash
set -euo pipefail

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
exec > >(tee -a "$LOG") 2>&1
find "$LOG_DIR" -type f -name '*.log' -mtime +90 -delete || true

echo "=== DATLUME weekly audit start $(date -Is) ==="
bad="$({ git diff --name-only; git diff --cached --name-only; } | sort -u | while IFS= read -r path; do
  [[ -z "$path" ]] && continue
  case "$path" in
    src/data/*.ts|src/data/sources.json|public/data/*.json) ;;
    scripts/weekly-audit.sh|scripts/audit-data-integrity.py) ;;
    *) printf '%s\n' "$path" ;;
  esac
done)"
if [[ -n "$bad" ]]; then
  echo "ERROR: non-generated tracked changes exist; refusing weekly audit"
  printf '%s\n' "$bad"
  exit 30
fi

npm run audit:data
npm run audit:listed-xbrl
npm run build
npm run audit:html

export E2E_BASE_URL="https://datlume.com"
export E2E_ONLY="/,/listed-companies/,/listed-companies/7203/,/listed-companies/compare/,/procurement/,/procurement/companies/co_f96b284bc087/"
npm run e2e:deep
unset E2E_BASE_URL E2E_ONLY

echo "=== DATLUME weekly audit success $(date -Is) ==="
