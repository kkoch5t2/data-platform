#!/usr/bin/env python3
"""Read DATLUME summary metrics without recursive directory traversal.

This helper is deliberately limited to two known, small JSON files so that
symlinked workspaces under data/ cannot create an infinite glob traversal.
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = {
    "listed": "public/data/listed-companies/summary.json",
    "registry": "public/data/company-registry/summary.json",
}
MAX_BYTES = 1_000_000
BASELINE = {
    "listed.companies": 3885,
    "listed.financialRecords": 33020,
    "listed.detailShards": 64,
    "registry.detailShards": 64,
}
ALERT_RATIO = 0.90


def main():
    result = {"checkedAt": datetime.now(timezone.utc).isoformat(), "metrics": {}, "alerts": []}
    for name, relpath in FILES.items():
        path = ROOT / relpath
        try:
            if path.is_symlink() or not path.is_file():
                raise ValueError("missing, non-file, or symlink")
            if path.stat().st_size > MAX_BYTES:
                raise ValueError(f"oversized JSON (over {MAX_BYTES} bytes)")
            with path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                raise ValueError("JSON root must be an object")
            selected = {k: v for k, v in data.items()
                        if k in ("dataset", "generatedAt", "sourceDate",
                                 "companies", "financialRecords", "detailShards")}
            result["metrics"][name] = selected
            for field, baseline in BASELINE.items():
                prefix, key = field.split(".", 1)
                if name != prefix:
                    continue
                value = data.get(key)
                if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                    result["alerts"].append(f"{field}: missing or invalid number")
                elif value < baseline * ALERT_RATIO:
                    result["alerts"].append(
                        f"{field}: {value} fell below 90% of baseline {baseline}")
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            result["alerts"].append(f"{name}: {type(exc).__name__}: {exc}")
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 1 if result["alerts"] else 0


if __name__ == "__main__":
    sys.exit(main())
