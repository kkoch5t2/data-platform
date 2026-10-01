#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
STATE_DIR="$ROOT/data/automation"
LOG_DIR="$STATE_DIR/logs"
LOCK="$STATE_DIR/wikipedia-topics-refresh.lock"
RELEASE_LOCK="$STATE_DIR/release.lock"
SCHEDULED_HOST_MARKER="$HOME/.config/datlume/allow-scheduled-refresh"
EXPECTED_SCHEDULED_HOST="kota-Intel"
MODE="${1:---scheduled}"
TODAY="$(date +%F)"
LOG="$LOG_DIR/wikipedia-topics-$TODAY.log"

mkdir -p "$STATE_DIR" "$LOG_DIR"
cd "$ROOT"

if [[ "$MODE" == "--scheduled" ]]; then
  if [[ "$(uname -s)" != "Linux" || "$(hostname)" != "$EXPECTED_SCHEDULED_HOST" || ! -f "$SCHEDULED_HOST_MARKER" ]] \
     || ! grep -qx "$EXPECTED_SCHEDULED_HOST" "$SCHEDULED_HOST_MARKER"; then
    echo "ERROR: scheduled Wikipedia topics refresh is authorized only on the production Ubuntu host" >&2
    exit 23
  fi
fi

exec 9>"$LOCK"
if ! flock -n 9; then exit 0; fi
exec > >(tee -a "$LOG") 2>&1

echo "=== Wikipedia topics refresh start $(date -Is) ==="
BASE="$(python3 scripts/scheduled-refresh-git.py check-start)"
echo "Scheduled refresh base: $BASE"

python3 collector/collect_wikipedia_topics.py --days 14
python3 scripts/scheduled-refresh-git.py prune-noops
python3 scripts/scheduled-refresh-git.py check-generated
npm run audit:wikipedia-topics

if [[ -z "$(git status --porcelain)" ]]; then
  echo "Wikipedia topics unchanged; nothing to deploy"
  exit 0
fi

exec 8>"$RELEASE_LOCK"
echo "Waiting for DATLUME release lock: $RELEASE_LOCK"
flock 8
export DATLUME_RELEASE_LOCK_HELD=1
npm run build
python3 scripts/scheduled-refresh-git.py commit-push --base "$BASE" --date "$TODAY"
bash ./deploy-datlume.sh
python3 scripts/scheduled-refresh-git.py check-clean
unset DATLUME_RELEASE_LOCK_HELD

echo "=== Wikipedia topics refresh complete $(date -Is) ==="
