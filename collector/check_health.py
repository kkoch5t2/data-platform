#!/usr/bin/env python3
import argparse, json, os, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "collector/source_catalog.json").read_text(encoding="utf-8"))["sources"]
STATUS_PATH = ROOT / "src/data/sources.json"

def parse_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("missing timestamp")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("timezone is required")
    return parsed.astimezone(timezone.utc)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--allow-stale-upstream", action="append", default=[],
                        help="source whose upstream probe failed; keep the last verified snapshot while other sources publish")
    args = parser.parse_args()
    selected = args.source or [k for k, v in CATALOG.items() if v.get("enabled")]
    allowed_stale = set(args.allow_stale_upstream)
    marker = os.environ.get('DATLUME_STALE_UPSTREAM_MARKER')
    if marker:
        allowed_stale.update(line.strip() for line in Path(marker).read_text().splitlines() if line.strip())
    eligible = {'jetro', 'jetro_local', 'sendai_procurement'}
    unknown = allowed_stale - (set(selected) & eligible)
    if unknown:
        parser.error(f"invalid stale upstream exception: {', '.join(sorted(unknown))}")
    status = json.loads(STATUS_PATH.read_text(encoding="utf-8")) if STATUS_PATH.exists() else {"sources": {}}
    errors = []
    now = datetime.now(timezone.utc)
    for key in selected:
        cfg = CATALOG.get(key)
        if not cfg:
            errors.append(f"{key}: unknown source"); continue
        item = status.get("sources", {}).get(key)
        if not item:
            errors.append(f"{key}: no run status"); continue
        if item.get("status") != "ok":
            errors.append(f"{key}: status={item.get('status')}")
        finished = item.get("finishedAt")
        try:
            completed_at = parse_time(finished)
            if completed_at > now + timedelta(minutes=10):
                errors.append(f"{key}: future run status")
            age_hours = (now - completed_at).total_seconds() / 3600
            if age_hours > cfg.get("maxAgeHours", 48):
                if key in allowed_stale and item.get("status") == "ok":
                    print(f"WARNING: {key}: upstream unavailable; using last verified snapshot {age_hours:.1f}h old (stale; no fixed expiry)")
                else:
                    errors.append(f"{key}: stale run status")
            if item.get("startedAt") and parse_time(item["startedAt"]) > completed_at:
                errors.append(f"{key}: startedAt is after finishedAt")
        except (ValueError, TypeError) as exc:
            errors.append(f"{key}: invalid finishedAt/startedAt ({exc})")
        records = (item.get("metrics") or {}).get("records", 0)
        if records < cfg.get("minRecords", 1):
            errors.append(f"{key}: records={records} below minimum")
    if errors:
        print("health check failed:\n- " + "\n- ".join(errors), file=sys.stderr); raise SystemExit(1)
    print(f"health check ok: {len(selected)} sources")

if __name__ == "__main__":
    main()
