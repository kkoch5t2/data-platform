#!/usr/bin/env python3
"""Optional YouTube Data API enrichment for Wikipedia trend topics."""
from __future__ import annotations

import json
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as dt_time, timedelta, timezone
from pathlib import Path

SEARCH_URL = "https://www.googleapis.com/youtube/v3/search"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
USER_AGENT = "DATLUME/1.0 (https://datlume.com/; public data dashboard)"
KEY_FILE = Path.home() / ".config/datlume/youtube_api_key"
VIDEO_ID_RE = re.compile(r"^[A-Za-z0-9_-]{11}$")
MIN_VIDEO_VIEWS = 10_000
SELECTION_VERSION = 4
AUTO_CHANNEL_RE = re.compile(r"(?:[-－–—]\s*Topic|[-－–—]\s*トピック)$", re.I)
AUTO_TITLE_RE = re.compile(r"(?:lyrics?\s*video|lyricsvideo|自動生成|auto.?generated)", re.I)
TRUSTED_CHANNEL_PATTERNS = ("公式", "official", "nhk", "tbs", "日テレ", "テレビ", "ann", "fnn", "jnn", "新聞", "スポーツ", "協会", "連盟", "リーグ", "クラブ")
LOW_QUALITY_PATTERNS = ("反応集", "知られざる", "衝撃", "暴露", "末路", "まさかの", "とんでもない", "徹底解説", "正式発表")


def _api_key() -> str | None:
    value = (os.environ.get("YOUTUBE_API_KEY") or "").strip()
    if value:
        return value
    if KEY_FILE.exists():
        value = KEY_FILE.read_text(encoding="utf-8").strip()
        return value or None
    return None


def _request_json(base: str, params: dict[str, str], *, retries: int = 2) -> dict:
    url = base + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=25) as response:
                return json.load(response)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt)
    raise RuntimeError(f"YouTube API request failed: {last}")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value or "").lower()
    return "".join(ch for ch in value if ch.isalnum())


def _query_title(article: str) -> str:
    core = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", article).strip()
    return core or article.strip()


def _quality_score(snippet: dict) -> int:
    title = unicodedata.normalize("NFKC", str(snippet.get("title") or "")).lower()
    channel = unicodedata.normalize("NFKC", str(snippet.get("channelTitle") or "")).lower()
    score = 3 if any(token in channel for token in TRUSTED_CHANNEL_PATTERNS) else 0
    score -= 2 * sum(1 for token in LOW_QUALITY_PATTERNS if token in title or token in channel)
    return score


def _thumbnail(video_id: str) -> str:
    # hqdefault is available much more consistently than maxresdefault/sddefault.
    # Do not persist optional high-resolution URLs that can return 404 for valid videos.
    return f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg"


def _search_topic(api_key: str, article: str, latest_day: date) -> list[dict]:
    query = _query_title(article)
    published_after = datetime.combine(
        latest_day - timedelta(days=6), dt_time.min, tzinfo=timezone.utc
    ).isoformat().replace("+00:00", "Z")
    payload = _request_json(SEARCH_URL, {
        "key": api_key,
        "part": "snippet",
        "type": "video",
        "q": query,
        "maxResults": "5",
        "order": "relevance",
        "regionCode": "JP",
        "relevanceLanguage": "ja",
        "safeSearch": "moderate",
        "videoEmbeddable": "true",
        "publishedAfter": published_after,
    })
    rows = []
    for item in payload.get("items") or []:
        video_id = str((item.get("id") or {}).get("videoId") or "")
        if VIDEO_ID_RE.fullmatch(video_id):
            rows.append({"videoId": video_id, "searchSnippet": item.get("snippet") or {}})
    return rows


def _video_details(api_key: str, video_ids: list[str]) -> dict[str, dict]:
    if not video_ids:
        return {}
    payload = _request_json(VIDEOS_URL, {
        "key": api_key,
        "part": "snippet,statistics,status",
        "id": ",".join(video_ids[:50]),
    })
    return {str(x.get("id")): x for x in payload.get("items") or [] if x.get("id")}


def collect_youtube_context(
    rising_rows: list[dict], latest_day: date, raw_dir: Path, *, refresh: bool = False, limit: int = 10
) -> dict:
    checked_rows = rising_rows[:max(0, limit)]
    base = {
        "source": "YouTube Data API v3",
        "checkedAt": None,
        "checkedCount": 0,
        "matchedCount": 0,
        "items": [],
        "failures": [],
        "selectionVersion": SELECTION_VERSION,
        "minViews": MIN_VIDEO_VIEWS,
    }
    api_key = _api_key()
    if not api_key:
        return {**base, "enabled": False, "status": "not_configured"}

    cache = raw_dir / "youtube" / f"{latest_day.isoformat()}.json"
    if cache.exists() and not refresh:
        cached = json.loads(cache.read_text(encoding="utf-8"))
        if cached.get("source") == "YouTube Data API v3" and cached.get("selectionVersion") == SELECTION_VERSION:
            changed = False
            for item in cached.get("items") or []:
                video_id = str(item.get("videoId") or "")
                if VIDEO_ID_RE.fullmatch(video_id):
                    thumbnail = _thumbnail(video_id)
                    if item.get("thumbnail") != thumbnail:
                        item["thumbnail"] = thumbnail
                        changed = True
            if changed:
                cache.write_text(json.dumps(cached, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            return cached

    base.update({"enabled": True, "status": "ok", "checkedCount": len(checked_rows)})
    candidates: dict[str, list[dict]] = {}
    for row in checked_rows:
        article = str(row.get("article") or "")
        try:
            candidates[article] = _search_topic(api_key, article, latest_day)
        except Exception as exc:
            base["failures"].append({"article": article, "error": type(exc).__name__})
            candidates[article] = []

    all_ids = []
    for rows in candidates.values():
        for row in rows:
            if row["videoId"] not in all_ids:
                all_ids.append(row["videoId"])
    try:
        details = _video_details(api_key, all_ids)
    except Exception as exc:
        base["failures"].append({"article": "*videos.list*", "error": type(exc).__name__})
        details = {}

    items = []
    used_video_ids = set()
    for topic_rank, row in enumerate(checked_rows, 1):
        article = str(row.get("article") or "")
        query_norm = _normalize(_query_title(article))
        eligible = []
        for candidate in candidates.get(article, []):
            if candidate["videoId"] in used_video_ids:
                continue
            video = details.get(candidate["videoId"]) or {}
            snippet = video.get("snippet") or candidate.get("searchSnippet") or {}
            status = video.get("status") or {}
            title = str(snippet.get("title") or "")
            if query_norm and query_norm not in _normalize(title):
                continue
            if status and not bool(status.get("embeddable", False)):
                continue
            stats = video.get("statistics") or {}
            try:
                views = int(stats.get("viewCount") or 0)
            except (TypeError, ValueError):
                views = 0
            if views < MIN_VIDEO_VIEWS:
                continue
            channel = str(snippet.get("channelTitle") or "").strip()
            description = str(snippet.get("description") or "")
            if AUTO_CHANNEL_RE.search(channel) or AUTO_TITLE_RE.search(title) or "Auto-generated by YouTube" in description or "YouTube によって自動生成" in description:
                continue
            # A single Roman-letter name often matches unrelated songs or generic captions.
            if re.fullmatch(r"[A-Za-z][A-Za-z0-9._-]*", _query_title(article)) and query_norm not in _normalize(channel):
                continue
            quality = _quality_score(snippet)
            if quality < 0:
                continue
            eligible.append((quality, views, candidate["videoId"], snippet))

        if not eligible:
            continue
        eligible.sort(key=lambda x: (-x[0], -x[1], x[2]))
        quality, views, video_id, snippet = eligible[0]
        used_video_ids.add(video_id)
        published_at = str(snippet.get("publishedAt") or "") or None
        items.append({
            "topic": article,
            "topicRank": topic_rank,
            "articleRank": row.get("rank"),
            "videoId": video_id,
            "url": f"https://www.youtube.com/watch?v={video_id}",
            "embedUrl": f"https://www.youtube-nocookie.com/embed/{video_id}",
            "title": str(snippet.get("title") or ""),
            "channelTitle": str(snippet.get("channelTitle") or ""),
            "publishedAt": published_at,
            "thumbnail": _thumbnail(video_id),
            "views": views,
            "embeddable": True,
            "matchedBy": "title",
        })

    base["checkedAt"] = datetime.now(timezone.utc).isoformat()
    base["matchedCount"] = len(items)
    base["items"] = items
    if base["failures"]:
        base["status"] = "partial" if items else "unavailable"
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(base, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return base
