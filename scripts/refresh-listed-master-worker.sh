#!/usr/bin/env bash
# Selected inside the normal isolated daily transaction; all release gates still run.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
: "${DATLUME_MARKER_DIR:?Use scripts/daily-refresh.sh listed-master}"
npm run collect:listed-master
TODAY="$(date +%F)"
npm run collect:listed-documents -- --start "$TODAY" --end "$TODAY"
npm run collect:listed-bulk
npm run normalize:listed-incremental
npm run validate:listed-salary
npm run validate:listed-counts
npm run validate:listed-shareholders
npm run validate:listed-financials
npm run audit:listed-cross-filing
npm run build:listed-data
npm run build:company-registry
printf '%s\n' "$(date +%Y-%m)" > "$DATLUME_MARKER_DIR/last-listed-master-refresh"
