#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PATH="$HOME/.nvm/versions/node/v22.23.2/bin:$PATH"
STATE_DIR="$ROOT/data/automation"
LOG_DIR="$STATE_DIR/logs"
LOCK="$STATE_DIR/wikipedia-topics-refresh.lock"
RELEASE_LOCK="$STATE_DIR/release.lock"
UPDATE_LOCK="$STATE_DIR/update.lock"
SCHEDULED_HOST_MARKER="$HOME/.config/datlume/allow-scheduled-refresh"
EXPECTED_SCHEDULED_HOST="kota-Intel"
MODE="${1:---scheduled}"
TODAY="$(TZ=Asia/Tokyo date +%F)"
SUCCESS="$STATE_DIR/last-wikipedia-success-date"
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
exec 7>"$UPDATE_LOCK"
if ! flock -n 7; then exit 0; fi
if [[ "$MODE" == "--scheduled" && -f "$SUCCESS" ]] && grep -qx "$TODAY" "$SUCCESS"; then exit 0; fi
exec > >(tee -a "$LOG") 2>&1

CURRENT_STEP="startup"
on_error() {
  local rc="$1" line="$2"
  trap - ERR
  printf '%s\tstep=%s\trc=%s\tline=%s\tlog=%s\n' "$(date -Is)" "$CURRENT_STEP" "$rc" "$line" "$LOG" >> "$STATE_DIR/wikipedia-failures.log"
  echo "ERROR: Wikipedia topics refresh stopped at $CURRENT_STEP (rc=$rc line=$line)"
  exit "$rc"
}
trap 'on_error "$?" "$LINENO"' ERR
echo "=== Wikipedia topics refresh start $(date -Is) ==="
BASE="$(python3 scripts/scheduled-refresh-git.py check-start)"
echo "Scheduled refresh base: $BASE"

CURRENT_STEP="collector"
python3 collector/collect_wikipedia_topics.py --days 14
python3 scripts/scheduled-refresh-git.py prune-noops
python3 scripts/scheduled-refresh-git.py check-generated
npm run audit:wikipedia-topics

if [[ -z "$(git status --porcelain)" ]]; then
  printf "%s\n" "$TODAY" > "$SUCCESS"
  echo "Wikipedia topics unchanged; collection and audit succeeded"
  exit 0
fi

exec 8>"$RELEASE_LOCK"
echo "Waiting for DATLUME release lock: $RELEASE_LOCK"
flock 8
CURRENT_STEP="build-and-deploy"
export DATLUME_RELEASE_LOCK_HELD=1
npm run build
npm run audit:html
python3 scripts/scheduled-refresh-git.py commit-push --base "$BASE" --date "$TODAY"
bash ./deploy-datlume.sh
python3 scripts/scheduled-refresh-git.py check-clean
unset DATLUME_RELEASE_LOCK_HELD

printf "%s\n" "$TODAY" > "$SUCCESS"
echo "=== Wikipedia topics refresh complete $(date -Is) ==="
