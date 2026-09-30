#!/usr/bin/env python3
import argparse
import json
import sys
from pathlib import Path

CORE_FIELDS = {
    "records": (0.01, 500),
    "awardRecords": (0.01, 100),
    "awardEligibleRecords": (0.01, 100),
}
SOURCE_FIELDS = [
    "gepsRecords", "jetroRecords", "yokohamaRecords", "sapporoRecords",
    "kobeRecords", "fukuokaRecords", "chibaRecords", "kyotoRecords",
    "kawasakiRecords", "sendaiRecords",
]

def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))

def regressed(previous, current, ratio, absolute):
    if previous <= 0:
        return False
    drop = previous - current
    return drop > absolute and current < previous * (1 - ratio)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--previous", required=True)
    ap.add_argument("--current", required=True)
    args = ap.parse_args()
    prev, cur = load(args.previous), load(args.current)
    failures = []
    for field, (ratio, absolute) in CORE_FIELDS.items():
        p, c = int(prev.get(field) or 0), int(cur.get(field) or 0)
        if regressed(p, c, ratio, absolute):
            failures.append(f"{field}: {p} -> {c}")
    for field in SOURCE_FIELDS:
        p, c = int(prev.get(field) or 0), int(cur.get(field) or 0)
        if regressed(p, c, 0.02, 50):
            failures.append(f"{field}: {p} -> {c}")
    if prev.get("lastDate") and cur.get("lastDate") and cur["lastDate"] < prev["lastDate"]:
        failures.append(f"lastDate: {prev['lastDate']} -> {cur['lastDate']}")
    if failures:
        print("procurement regression detected:")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("procurement regression check ok")
    return 0

if __name__ == "__main__":
    sys.exit(main())
