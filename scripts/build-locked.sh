#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$ROOT/data/automation"
LOCK="$STATE_DIR/release.lock"
mkdir -p "$STATE_DIR"
cd "$ROOT"
run_build() {
  npx astro build
  node scripts/run-python.cjs scripts/generate-sitemap.py
}
if [[ "${DATLUME_RELEASE_LOCK_HELD:-0}" == "1" ]]; then
  run_build
  exit 0
fi
exec 8>"$LOCK"
echo "Waiting for DATLUME release lock: $LOCK"
flock 8
run_build
