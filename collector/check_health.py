#!/usr/bin/env python3
import argparse, json, sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = json.loads((ROOT / "collector/source_catalog.json").read_text(encoding="utf-8"))["sources"]
STATUS_PATH = ROOT / "src/data/sources.json"

def parse_time(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00"))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", default=[])
    args = parser.parse_args()
    selected = args.source or [k for k, v in CATALOG.items() if v.get("enabled")]
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
        if finished and (now - parse_time(finished)).total_seconds() > cfg.get("maxAgeHours", 48) * 3600:
            errors.append(f"{key}: stale run status")
        records = (item.get("metrics") or {}).get("records", 0)
        if records < cfg.get("minRecords", 1):
            errors.append(f"{key}: records={records} below minimum")
    if errors:
        print("health check failed:\n- " + "\n- ".join(errors), file=sys.stderr); raise SystemExit(1)
    print(f"health check ok: {len(selected)} sources")

if __name__ == "__main__":
    main()
