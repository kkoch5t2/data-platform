#!/usr/bin/env python3
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "public/data/wikipedia-topics.json"


def fail(message: str) -> None:
    raise SystemExit(f"FAIL wikipedia-topics: {message}")


def main() -> int:
    if not PATH.exists():
        fail(f"missing {PATH}")
    data = json.loads(PATH.read_text(encoding="utf-8"))
    if data.get("schemaVersion") != 1:
        fail("schemaVersion must be 1")
    if data.get("project") != "ja.wikipedia":
        fail("project must be ja.wikipedia")
    latest = data.get("latestDate")
    if not latest:
        fail("latestDate missing")
    latest_date = datetime.strptime(latest, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    age_hours = (datetime.now(timezone.utc) - latest_date).total_seconds() / 3600
    if age_hours < 0 or age_hours > 120:
        fail(f"latestDate stale or future: {latest} age_hours={age_hours:.1f}")

    top = data.get("top") or []
    if len(top) != 100:
        fail(f"top must have 100 rows, got {len(top)}")
    titles = [str(x.get("article") or "") for x in top]
    if len(set(titles)) != len(titles):
        fail("duplicate article in top")
    if any(not title for title in titles):
        fail("blank article title")
    for expected_rank, row in enumerate(top, 1):
        if row.get("rank") != expected_rank:
            fail(f"rank sequence broken at {expected_rank}: {row.get('rank')}")
        if not isinstance(row.get("views"), int) or row["views"] <= 0:
            fail(f"invalid views for {row.get('article')}")
        if not str(row.get("url") or "").startswith("https://ja.wikipedia.org/wiki/"):
            fail(f"invalid article URL for {row.get('article')}")
        history = row.get("history") or []
        if len(history) != 7:
            fail(f"history must have 7 points for {row.get('article')}")
    if any(top[i]["views"] < top[i + 1]["views"] for i in range(len(top) - 1)):
        fail("top ranking is not sorted by views descending")

    excluded_exact = set((data.get("filters") or {}).get("excludedExact") or [])
    excluded_prefixes = tuple((data.get("filters") or {}).get("excludedPrefixes") or [])
    for title in titles:
        if title in excluded_exact or title.startswith(excluded_prefixes):
            fail(f"excluded title leaked into top: {title}")

    rising = data.get("rising") or []
    top_titles = set(titles)
    if not rising or len(rising) > 20:
        fail(f"rising size invalid: {len(rising)}")
    for row in rising:
        if row.get("article") not in top_titles:
            fail(f"rising article not present in top: {row.get('article')}")
        if row.get("previousViews") is None or row.get("previousViews") < 3000:
            fail(f"rising threshold broken: {row.get('article')}")
        if row.get("viewChangePct") is None:
            fail(f"rising change missing: {row.get('article')}")

    weekly = data.get("weekly") or []
    if not weekly or len(weekly) > 30:
        fail(f"weekly size invalid: {len(weekly)}")
    if any((row.get("totalViews") or 0) <= 0 for row in weekly):
        fail("weekly contains non-positive totalViews")
    if any(weekly[i]["totalViews"] < weekly[i + 1]["totalViews"] for i in range(len(weekly) - 1)):
        fail("weekly ranking is not sorted by totalViews descending")

    daily = data.get("daily") or []
    if len(daily) < 7 or len(daily) > 31:
        fail(f"daily size invalid: {len(daily)}")
    dates = [x.get("date") for x in daily]
    if dates != sorted(dates) or len(set(dates)) != len(dates):
        fail("daily dates must be unique and ascending")
    if dates[-1] != latest:
        fail(f"daily latest {dates[-1]} != latestDate {latest}")
    if any((x.get("top100Views") or 0) <= 0 for x in daily):
        fail("daily contains non-positive top100Views")

    summary = data.get("summary") or {}
    expected_total = sum(x["views"] for x in top)
    if summary.get("latestTop100Views") != expected_total:
        fail("summary latestTop100Views mismatch")

    print(f"Wikipedia topics audit: top={len(top)} rising={len(rising)} weekly={len(weekly)} daily={len(daily)} latest={latest} OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
