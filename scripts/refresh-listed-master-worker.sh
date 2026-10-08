#!/usr/bin/env bash
# Selected inside the normal isolated daily transaction; all release gates still run.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
: "${DATLUME_MARKER_DIR:?Use scripts/daily-refresh.sh listed-master}"
npm run collect:listed-master
npm run validate:listed-financials
npm run audit:listed-cross-filing
npm run build:listed-data
npm run build:company-registry
printf '%s\n' "$(date +%Y-%m)" > "$DATLUME_MARKER_DIR/last-listed-master-refresh"
