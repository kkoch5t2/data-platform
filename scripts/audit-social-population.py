#!/usr/bin/env python3
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public/data/municipality-stats-2026.json"
DATA = ROOT / "public/data/municipality-social-indicators.json"
CATALOG = ROOT / "collector/metric_catalog.json"


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))
    data = json.loads(DATA.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    base_codes = {r["code"] for r in base["records"]}
    rows = data.get("records", [])
    codes = [r.get("code") for r in rows]
    errors = []
    if len(rows) != 1741 or len(set(codes)) != 1741 or set(codes) != base_codes:
        errors.append(f"municipality universe mismatch: rows={len(rows)} unique={len(set(codes))}")
    registered = {m["metricId"]: m["canonical"] for m in catalog["metrics"]}
    for metric in data.get("metrics", []):
        field, metric_id = metric["field"], metric["metricId"]
        actual = sum(r.get(field) is not None for r in rows)
        if actual != metric.get("coverageCount"):
            errors.append(f"{field}: coverage metadata {metric.get('coverageCount')} != actual {actual}")
        canonical = registered.get(metric_id)
        if not canonical or canonical.get("dataset") != DATA.name or canonical.get("field") != field:
            errors.append(f"{field}: canonical registry mismatch")
    fields = [m["field"] for m in data.get("metrics", [])]
    if len(fields) != len(set(fields)) or len(fields) != 5:
        errors.append(f"expected 5 unique metric fields, got {fields}")
    if errors:
        print("social population audit failed:\n- " + "\n- ".join(errors), file=sys.stderr)
        raise SystemExit(1)
    print(f"social population audit: {len(rows)} municipalities / {len(fields)} metrics / 0 failures")


if __name__ == "__main__":
    main()
