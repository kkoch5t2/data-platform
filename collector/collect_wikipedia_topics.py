#!/usr/bin/env python3
"""Collect Japanese Wikipedia pageview trends for DATLUME."""
from __future__ import annotations

import argparse
import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_PATH = ROOT / "public/data/wikipedia-topics.json"
RAW_DIR = ROOT / "data/raw/wikipedia-topics"
BASE = "https://wikimedia.org/api/rest_v1/metrics/pageviews/top/ja.wikipedia/all-access"
USER_AGENT = "DATLUME/1.0 (https://datlume.com/; public data dashboard)"
EXCLUDED_EXACT = {"メインページ"}
EXCLUDED_PREFIXES = (
    "特別:", "Wikipedia:", "ファイル:", "カテゴリ:", "Help:", "Portal:",
    "テンプレート:", "利用者:", "利用者‐会話:", "MediaWiki:", "プロジェクト:",
)


def request_json(url: str, *, retries: int = 3) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                return json.load(response)
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise
            last = exc
        except (urllib.error.URLError, TimeoutError) as exc:
            last = exc
        if attempt + 1 < retries:
            time.sleep(1.2 * (attempt + 1))
    raise RuntimeError(f"Wikimedia request failed: {url}: {last}")


def api_url(day: date) -> str:
    return f"{BASE}/{day.year:04d}/{day.month:02d}/{day.day:02d}"


def raw_path(day: date) -> Path:
    return RAW_DIR / f"{day.isoformat()}.json"


def load_day(day: date, *, refresh: bool) -> list[dict]:
    path = raw_path(day)
    if path.exists() and not refresh:
        payload = json.loads(path.read_text(encoding="utf-8"))
    else:
        payload = request_json(api_url(day))
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    items = payload.get("items") or []
    if not items or not items[0].get("articles"):
        raise ValueError(f"No articles in Wikimedia response for {day}")
    return items[0]["articles"]


def clean_title(raw: str) -> str:
    return urllib.parse.unquote(raw).replace("_", " ").strip()


def is_content_title(title: str) -> bool:
    if not title or title in EXCLUDED_EXACT:
        return False
    return not any(title.startswith(prefix) for prefix in EXCLUDED_PREFIXES)


def normalize_articles(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        title = clean_title(str(row.get("article") or ""))
        if not is_content_title(title):
            continue
        views = int(row.get("views") or 0)
        if views <= 0:
            continue
        out.append({"article": title, "views": views})
    out.sort(key=lambda x: (-x["views"], x["article"]))
    for idx, row in enumerate(out, 1):
        row["rank"] = idx
    return out


def pct_change(current: float, previous: float | None) -> float | None:
    if previous is None or previous <= 0:
        return None
    return round((current - previous) / previous * 100, 1)


def wikipedia_url(title: str) -> str:
    encoded = urllib.parse.quote(title.replace(" ", "_"), safe="()'!~*-._")
    return "https://ja.wikipedia.org/wiki/" + encoded


def collect(window_days: int, *, refresh: bool) -> dict:
    if window_days < 7:
        raise ValueError("window_days must be at least 7")
    utc_today = datetime.now(timezone.utc).date()
    latest_day = None
    latest_rows = None
    for lag in range(1, 7):
        candidate = utc_today - timedelta(days=lag)
        try:
            latest_rows = normalize_articles(load_day(candidate, refresh=refresh))
            latest_day = candidate
            break
        except urllib.error.HTTPError as exc:
            if exc.code != 404:
                raise
    if latest_day is None or latest_rows is None:
        raise RuntimeError("No recent Japanese Wikipedia top-pageview data is available")

    by_day = {latest_day.isoformat(): latest_rows}
    for offset in range(1, window_days):
        day = latest_day - timedelta(days=offset)
        by_day[day.isoformat()] = normalize_articles(load_day(day, refresh=refresh))

    ordered_dates = sorted(by_day)
    maps = {d: {row["article"]: row for row in rows} for d, rows in by_day.items()}
    latest_key = latest_day.isoformat()
    previous_key = (latest_day - timedelta(days=1)).isoformat()
    previous_map = maps.get(previous_key, {})
    latest_map = maps[latest_key]
    baseline_keys = [d for d in ordered_dates if d < latest_key][-7:]

    top = []
    for row in latest_rows[:100]:
        title = row["article"]
        prev = previous_map.get(title)
        baseline_views = [maps[d][title]["views"] for d in baseline_keys if title in maps[d]]
        average7 = round(sum(baseline_views) / len(baseline_views)) if baseline_views else None
        days_top100 = sum(1 for d in ordered_dates[-7:] if title in maps[d] and maps[d][title]["rank"] <= 100)
        history = [{"date": d, "views": maps[d].get(title, {}).get("views")} for d in ordered_dates[-7:]]
        top.append({
            "rank": row["rank"],
            "article": title,
            "views": row["views"],
            "previousRank": prev.get("rank") if prev else None,
            "rankChange": (prev["rank"] - row["rank"]) if prev else None,
            "previousViews": prev.get("views") if prev else None,
            "viewChangePct": pct_change(row["views"], prev.get("views") if prev else None),
            "average7": average7,
            "vsAverage7Pct": pct_change(row["views"], average7),
            "daysInTop100": days_top100,
            "isNew": prev is None or prev.get("rank", 9999) > 100,
            "url": wikipedia_url(title),
            "history": history,
        })

    rising_candidates = [x for x in top if x["previousViews"] and x["previousViews"] >= 3000]
    rising_candidates.sort(
        key=lambda x: (x["viewChangePct"] if x["viewChangePct"] is not None else -math.inf, x["views"]),
        reverse=True,
    )
    rising = rising_candidates[:20]

    weekly_totals = defaultdict(lambda: {"totalViews": 0, "daysObserved": 0, "bestRank": None})
    for d in ordered_dates[-7:]:
        for row in by_day[d]:
            rec = weekly_totals[row["article"]]
            rec["totalViews"] += row["views"]
            rec["daysObserved"] += 1
            rec["bestRank"] = row["rank"] if rec["bestRank"] is None else min(rec["bestRank"], row["rank"])

    weekly = []
    for title, rec in weekly_totals.items():
        latest = latest_map.get(title)
        weekly.append({
            "article": title,
            **rec,
            "latestRank": latest.get("rank") if latest else None,
            "url": wikipedia_url(title),
        })
    weekly.sort(key=lambda x: (-x["totalViews"], x["article"]))
    weekly = weekly[:30]

    daily = []
    for d in ordered_dates:
        rows = by_day[d]
        top100 = rows[:100]
        daily.append({
            "date": d,
            "top100Views": sum(x["views"] for x in top100),
            "leader": rows[0]["article"] if rows else None,
            "leaderViews": rows[0]["views"] if rows else None,
        })

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "project": "ja.wikipedia",
        "latestDate": latest_key,
        "window": {"from": ordered_dates[0], "to": latest_key, "days": len(ordered_dates)},
        "source": {
            "name": "Wikimedia Analytics API - Pageviews",
            "access": "all-access",
            "endpoint": "metrics/pageviews/top/ja.wikipedia/all-access/{year}/{month}/{day}",
            "note": "Japanese Wikipedia pageview rankings; not a measure of all web searches or public opinion in Japan.",
        },
        "filters": {"excludedExact": sorted(EXCLUDED_EXACT), "excludedPrefixes": list(EXCLUDED_PREFIXES)},
        "summary": {
            "latestArticles": len(latest_rows),
            "latestTop100Views": sum(x["views"] for x in latest_rows[:100]),
            "newEntriesTop20": sum(1 for x in top[:20] if x["isNew"]),
            "risingCount": len(rising),
        },
        "top": top,
        "rising": rising,
        "weekly": weekly,
        "daily": daily,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=14, help="Number of daily rankings to collect (min 7)")
    parser.add_argument("--refresh", action="store_true", help="Refetch cached raw dates")
    parser.add_argument("--output", default=str(PUBLIC_PATH))
    args = parser.parse_args()
    with SourceRun("wikipedia_topics", "Wikimedia Analytics API 日本語版Wikipedia Pageviews") as run:
        payload = collect(args.days, refresh=args.refresh)
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        run.set_metrics(records=len(payload["top"]), sourceArticles=payload["summary"]["latestArticles"], windowDays=payload["window"]["days"], latestDate=payload["latestDate"])
        print(f"Wikipedia topics: latest={payload['latestDate']} top={len(payload['top'])} rising={len(payload['rising'])} weekly={len(payload['weekly'])}")
        print(f"Wrote {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
