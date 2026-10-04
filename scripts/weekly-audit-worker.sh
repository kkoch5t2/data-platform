#!/usr/bin/env bash
# Runs only inside an isolated workspace owned by scheduled-refresh.py.
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
cd "$ROOT"
run_step() { echo "--- step: $1 ---"; shift; "$@"; }
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
E2E_BASE_URL="https://datlume.com" E2E_ONLY="/,/listed-companies/,/listed-companies/7203/,/listed-companies/compare/,/procurement/,/topics/" npm run e2e:deep
