#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.5/bin:$PATH"
exec python3 "$ROOT/scripts/scheduled-refresh.py" daily "${1:-manual}"
