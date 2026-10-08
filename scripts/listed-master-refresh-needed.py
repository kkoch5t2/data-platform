#!/usr/bin/env python3
"""Retry monthly JPX acquisition until the previous month's edition is obtained."""
import argparse
from datetime import date, datetime, timedelta
import json
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]


def needs_refresh(source_date, marker, today):
    month = today.strftime("%Y-%m")
    expected_month = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    if marker != month:
        return True
    try:
        published = date.fromisoformat(source_date)
    except (TypeError, ValueError):
        return True
    return published > today or published.strftime("%Y-%m") < expected_month


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--marker", type=Path, required=True)
    parser.add_argument("--master", type=Path, default=ROOT / "public/data/listed-companies/master.json")
    args = parser.parse_args()
    try:
        source_date = json.loads(args.master.read_text())["sourceDate"]
    except (OSError, ValueError, KeyError, TypeError):
        source_date = None
    try:
        marker = args.marker.read_text().strip()
    except OSError:
        marker = None
    today = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    needed = needs_refresh(source_date, marker, today)
    expected = (today.replace(day=1) - timedelta(days=1)).strftime("%Y-%m")
    print(f"JPX master: sourceDate={source_date}, expectedMonth>={expected}, refresh={needed}")
    raise SystemExit(0 if needed else 1)


if __name__ == "__main__":
    main()
