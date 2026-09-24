#!/usr/bin/env python3
import argparse, json, subprocess, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "collector" / "source_catalog.json"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", action="append", default=[])
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))["sources"]
    selected = args.source or [k for k, v in catalog.items() if v.get("enabled")]
    failures = []
    for key in selected:
        source = catalog.get(key)
        if not source:
            failures.append(key); print(f"unknown source: {key}", file=sys.stderr); continue
        cmd = source["command"]
        print(f"==> {key}: {' '.join(cmd)}", flush=True)
        if not args.dry_run:
            result = subprocess.run(cmd, cwd=ROOT)
            if result.returncode:
                failures.append(key)
    if failures:
        raise SystemExit(f"failed sources: {', '.join(failures)}")

if __name__ == "__main__":
    main()
