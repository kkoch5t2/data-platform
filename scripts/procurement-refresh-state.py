#!/usr/bin/env python3
"""Snapshot and restore only procurement collector outputs; retain failure evidence."""
import argparse
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATTERNS = (
    "src/data/sources.json", "src/data/companies.json", "src/data/organizations.json",
    "src/data/summary.json", "src/data/procurements-*.json",
    "public/data/dashboard.json", "public/data/dashboard-meta.json",
    "public/data/dashboard-*.json", "public/data/company-details/*.json",
)

def outputs(root):
    return {p.relative_to(root).as_posix(): p for pattern in PATTERNS
            for p in root.glob(pattern) if p.is_file()}

def copy(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["cp", "--reflink=auto", "--preserve=mode,timestamps", "--",
                    str(source), str(target)], check=True)

def snapshot(root, destination):
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True)
    files = outputs(root)
    for rel, source in files.items():
        copy(source, destination / rel)
    (destination / "manifest.json").write_text(json.dumps(sorted(files)), encoding="utf-8")
    print(f"Procurement snapshot saved: {len(files)} files")

def restore(root, destination):
    entries = json.loads((destination / "manifest.json").read_text(encoding="utf-8"))
    # Validate the complete manifest before modifying any output.
    for rel in entries:
        path = Path(rel)
        if path.is_absolute() or ".." in path.parts or not (destination / path).is_file():
            raise ValueError(f"Invalid procurement snapshot entry: {rel}")
    failure = root / "src/data/sources.json"
    if failure.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        copy(failure, root / "data/automation/logs" / f"procurement-failure-sources-{stamp}.json")
    for rel, path in outputs(root).items():
        if rel not in entries:
            path.unlink()
    for rel in entries:
        copy(destination / rel, root / rel)
    print(f"Procurement outputs restored: {len(entries)} files; failure status retained in logs")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["snapshot", "restore"])
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    {"snapshot": snapshot, "restore": restore}[args.action](ROOT, args.destination)
