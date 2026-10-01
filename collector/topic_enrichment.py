#!/usr/bin/env python3
"""Metadata classification and news-context enrichment for Wikipedia topics."""
from __future__ import annotations

import hashlib
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from datetime import date, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path

USER_AGENT = "DATLUME/1.0 (https://datlume.com/; public data dashboard)"
MEDIAWIKI_API = "https://ja.wikipedia.org/w/api.php"
WIKIDATA_API = "https://www.wikidata.org/w/api.php"
GOOGLE_NEWS_RSS = "https://news.google.com/rss/search"
ENRICHMENT_VERSION = 4

CATEGORY_DEFS = [
    ("sports", "スポーツ", "⚽", ["スポーツ選手", "野球選手", "サッカー選手", "バレーボール選手", "バスケットボール選手", "テニス選手", "卓球選手", "ゴルファー", "力士", "プロレスラー", "競泳選手", "陸上競技選手", "選手権", "リーグ", "オリンピック", "パラリンピック", "baseball player", "footballer", "volleyball player", "basketball player", "tennis player", "athlete", "sports league"]),
    ("incident", "事件・事故", "🚨", ["殺人事件", "殺害事件", "傷害事件", "強盗事件", "刑事事件", "テロ事件", "事故", "災害", "地震", "火災", "爆発事故", "襲撃事件", "失踪事件", "誘拐事件", "事件", "murder", "crime", "incident", "disaster", "earthquake", "accident"]),
    ("politics", "政治", "🏛️", ["政治家", "国会議員", "衆議院議員", "参議院議員", "内閣総理大臣", "総理大臣", "大臣", "知事", "市長", "政党", "選挙", "政治", "politician", "prime minister", "minister", "governor", "political party", "election"]),
    ("games", "ゲーム", "🎮", ["コンピュータゲーム", "ビデオゲーム", "ゲームソフト", "ゲームシリーズ", "ゲーム作品", "ゲーム会社", "任天堂", "PlayStation", "Xbox", "ソーシャルゲーム", "アーケードゲーム", "video game", "game series", "game developer"]),
    ("anime_manga", "アニメ・漫画", "🌸", ["テレビアニメ", "アニメ映画", "アニメ作品", "漫画作品", "漫画家", "漫画", "アニメ", "声優", "ライトノベル", "manga", "anime", "voice actor", "light novel"]),
    ("music", "音楽", "🎵", ["音楽グループ", "歌手", "シンガーソングライター", "ミュージシャン", "バンド", "アイドル", "楽曲", "シングル", "アルバム", "作曲家", "音楽家", "singer", "musician", "music group", "band", "song", "album", "composer"]),
    ("film_tv", "映画・ドラマ", "🎬", ["映画作品", "日本の映画", "テレビドラマ", "ドラマ", "テレビ番組", "映画監督", "脚本家", "film", "television series", "television program", "film director", "screenwriter"]),
    ("entertainment", "芸能", "🎭", ["俳優", "女優", "男優", "タレント", "お笑い芸人", "コメディアン", "モデル", "芸能人", "ニュースキャスター", "キャスター", "アナウンサー", "YouTuber", "actor", "actress", "entertainer", "comedian", "television personality", "announcer"]),
    ("business", "経済・企業", "💴", ["企業", "会社", "株式会社", "経済", "金融", "株式", "投資", "銀行", "実業家", "起業家", "company", "corporation", "business", "economy", "finance", "bank", "entrepreneur", "businessperson"]),
    ("science_tech", "科学・テクノロジー", "🔬", ["科学者", "研究者", "技術者", "人工知能", "コンピュータ", "ソフトウェア", "宇宙", "天文学", "物理学", "化学", "technology", "scientist", "researcher", "artificial intelligence", "computer", "software", "astronomy"]),
    ("international", "国際", "🌏", ["国際関係", "外交", "戦争", "紛争", "条約", "軍事", "国際機関", "国家", "主権国家", "foreign relations", "war", "armed conflict", "treaty", "international organization", "country", "sovereign state"]),
    ("nature", "自然・地理", "🗺️", ["日本の山", "山岳", "火山", "山地", "山脈", "日本の河川", "日本の湖", "日本の島", "自然地理", "mountain", "volcano", "river", "lake", "island"]),
    ("history_culture", "歴史・文化", "📚", ["歴史", "作家", "小説家", "小説", "文学", "詩人", "美術", "芸術", "文化", "宗教", "神話", "武将", "大名", "戦国時代", "江戸時代", "歴史上の人物", "writer", "novelist", "novel", "literature", "poet", "history", "culture", "religion"]),
]
CATEGORY_INFO = {key: {"key": key, "label": label, "emoji": emoji} for key, label, emoji, _ in CATEGORY_DEFS}
CATEGORY_INFO["people"] = {"key": "people", "label": "人物", "emoji": "👤"}
CATEGORY_INFO["other"] = {"key": "other", "label": "その他", "emoji": "📌"}

TREND_INFO = {
    "new": {"key": "new", "label": "新着", "emoji": "🆕"},
    "spike": {"key": "spike", "label": "突発急上昇", "emoji": "⚡"},
    "rising": {"key": "rising", "label": "急上昇", "emoji": "🔥"},
    "gradual": {"key": "gradual", "label": "じわ伸び", "emoji": "📈"},
    "evergreen": {"key": "evergreen", "label": "定番人気", "emoji": "👑"},
    "steady": {"key": "steady", "label": "通常", "emoji": "➖"},
}


def _request(url: str, *, retries: int = 3, timeout: int = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json,application/xml,text/xml,*/*"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read()
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as exc:
            last = exc
            if isinstance(exc, urllib.error.HTTPError) and exc.code in {400, 401, 403, 404}:
                break
            if attempt + 1 < retries:
                time.sleep(1.0 + attempt * 1.5)
    raise RuntimeError(f"request failed: {url}: {last}")


def _json_request(base: str, params: dict) -> dict:
    url = base + "?" + urllib.parse.urlencode(params)
    return json.loads(_request(url).decode("utf-8"))


def _chunks(values: list[str], size: int) -> list[list[str]]:
    return [values[i:i + size] for i in range(0, len(values), size)]


def fetch_mediawiki_metadata(titles: list[str]) -> dict[str, dict]:
    result: dict[str, dict] = {}
    for batch in _chunks(titles, 20):
        params = {
            "action": "query", "format": "json", "formatversion": "2", "redirects": "1",
            "prop": "categories|pageprops|extracts", "cllimit": "max", "exintro": "1", "explaintext": "1",
            "titles": "|".join(batch),
        }
        pages_by_title: dict[str, dict] = {}
        aliases: dict[str, str] = {}
        while True:
            payload = _json_request(MEDIAWIKI_API, params)
            query = payload.get("query") or {}
            for item in query.get("normalized") or []:
                aliases[item.get("from", "")] = item.get("to", "")
            for item in query.get("redirects") or []:
                aliases[item.get("from", "")] = item.get("to", "")
            for page in query.get("pages") or []:
                title = str(page.get("title") or "")
                rec = pages_by_title.setdefault(title, {"title": title, "categories": [], "extract": "", "wikibaseItem": None})
                rec["extract"] = str(page.get("extract") or rec["extract"] or "")[:1800]
                rec["wikibaseItem"] = (page.get("pageprops") or {}).get("wikibase_item") or rec["wikibaseItem"]
                seen = set(rec["categories"])
                for cat in page.get("categories") or []:
                    label = str(cat.get("title") or "").removeprefix("Category:").strip()
                    if label and label not in seen:
                        rec["categories"].append(label); seen.add(label)
            cont = payload.get("continue")
            if not cont:
                break
            params = {**params, **cont}
        for original in batch:
            resolved = original
            for _ in range(5):
                nxt = aliases.get(resolved)
                if not nxt or nxt == resolved:
                    break
                resolved = nxt
            result[original] = pages_by_title.get(resolved) or pages_by_title.get(original) or {"title": resolved, "categories": [], "extract": "", "wikibaseItem": None}
    return result


def _claim_entity_ids(entity: dict, prop: str) -> list[str]:
    out = []
    for claim in (entity.get("claims") or {}).get(prop) or []:
        value = (((claim.get("mainsnak") or {}).get("datavalue") or {}).get("value"))
        if isinstance(value, dict) and value.get("id"):
            out.append(str(value["id"]))
    return out


def _localized(block: dict, lang: str) -> str:
    return str((block.get(lang) or {}).get("value") or "")


def fetch_wikidata_metadata(qids: list[str]) -> dict[str, dict]:
    entities: dict[str, dict] = {}
    for batch in _chunks(sorted(set(qids)), 25):
        payload = _json_request(WIKIDATA_API, {
            "action": "wbgetentities", "format": "json", "ids": "|".join(batch),
            "props": "labels|descriptions|aliases|claims", "languages": "ja|en", "languagefallback": "1",
        })
        entities.update(payload.get("entities") or {})
    referenced: set[str] = set()
    signal_props = ("P31", "P106", "P136", "P641")
    for entity in entities.values():
        for prop in signal_props:
            referenced.update(_claim_entity_ids(entity, prop))
    labels: dict[str, str] = {}
    for batch in _chunks(sorted(referenced), 50):
        payload = _json_request(WIKIDATA_API, {
            "action": "wbgetentities", "format": "json", "ids": "|".join(batch),
            "props": "labels|descriptions", "languages": "ja|en", "languagefallback": "1",
        })
        for qid, entity in (payload.get("entities") or {}).items():
            ja = _localized(entity.get("labels") or {}, "ja")
            en = _localized(entity.get("labels") or {}, "en")
            labels[qid] = " / ".join(x for x in (ja, en) if x)
    out: dict[str, dict] = {}
    for qid, entity in entities.items():
        aliases_ja = [str(x.get("value") or "") for x in (entity.get("aliases") or {}).get("ja") or []][:8]
        aliases_en = [str(x.get("value") or "") for x in (entity.get("aliases") or {}).get("en") or []][:8]
        claim_ids = {prop: _claim_entity_ids(entity, prop) for prop in signal_props}
        out[qid] = {
            "id": qid,
            "labelJa": _localized(entity.get("labels") or {}, "ja"),
            "labelEn": _localized(entity.get("labels") or {}, "en"),
            "descriptionJa": _localized(entity.get("descriptions") or {}, "ja"),
            "descriptionEn": _localized(entity.get("descriptions") or {}, "en"),
            "aliasesJa": [x for x in aliases_ja if x], "aliasesEn": [x for x in aliases_en if x],
            "claimIds": claim_ids,
            "signalLabels": [labels[x] for prop in signal_props for x in claim_ids[prop] if labels.get(x)],
        }
    return out


def classify_topic(title: str, page: dict, wd: dict | None) -> dict:
    categories = [str(x) for x in page.get("categories") or []]
    category_text = " ".join(categories).lower()
    structured_parts = []
    if wd:
        structured_parts = [wd.get("descriptionJa", ""), wd.get("descriptionEn", ""), *wd.get("signalLabels", [])]
    structured_text = " ".join(str(x) for x in structured_parts if x).lower()
    title_text = title.lower()
    extract_text = str(page.get("extract") or "").lower()
    scores: dict[str, float] = defaultdict(float)
    evidence: dict[str, list[str]] = defaultdict(list)
    for key, _, _, keywords in CATEGORY_DEFS:
        for keyword in keywords:
            needle = keyword.lower()
            hit = False
            if needle in category_text:
                scores[key] += 4.0; hit = True
            if needle in structured_text:
                scores[key] += 3.0; hit = True
            if needle in title_text:
                scores[key] += 2.5; hit = True
            if needle in extract_text:
                scores[key] += 0.8; hit = True
            if hit and len(evidence[key]) < 4:
                evidence[key].append(keyword)
    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    if ranked and ranked[0][1] >= 2.5:
        key, top_score = ranked[0]
        second = ranked[1][1] if len(ranked) > 1 else 0.0
        confidence = min(0.98, 0.58 + min(top_score, 18) / 45 + min(max(top_score - second, 0), 10) / 30)
    else:
        is_human = bool(wd and "Q5" in (wd.get("claimIds") or {}).get("P31", []))
        key, top_score, second = ("people", 2.0, 0.0) if is_human else ("other", 0.0, 0.0)
        confidence = 0.62 if is_human else 0.42
    info = CATEGORY_INFO[key]
    return {**info, "confidence": round(confidence, 2), "evidence": evidence.get(key, [])[:3]}


def classify_trend(row: dict) -> dict:
    change = row.get("viewChangePct")
    versus = row.get("vsAverage7Pct")
    days = int(row.get("daysInTop100") or 0)
    if row.get("isNew"):
        key = "new"
    elif change is not None and change >= 180:
        key = "spike"
    elif (change is not None and change >= 55) or (versus is not None and versus >= 140):
        key = "rising"
    elif (change is not None and change >= 15) and (versus is None or versus >= 15):
        key = "gradual"
    elif days >= 6 and (change is None or abs(change) < 45):
        key = "evergreen"
    else:
        key = "steady"
    return TREND_INFO[key]


def _news_query_term(title: str) -> str:
    base = re.sub(r"\s*[（(][^）)]*[）)]\s*$", "", title).strip()
    return base or title


def _clean_headline(title: str, source: str) -> str:
    suffix = f" - {source}" if source else ""
    return title[:-len(suffix)].strip() if suffix and title.endswith(suffix) else title.strip()


def fetch_google_news(title: str, target_day: date) -> dict:
    term = _news_query_term(title)
    start = target_day - timedelta(days=1)
    end_exclusive = target_day + timedelta(days=2)
    query = f'"{term}" after:{start.isoformat()} before:{end_exclusive.isoformat()}'
    url = GOOGLE_NEWS_RSS + "?" + urllib.parse.urlencode({"q": query, "hl": "ja", "gl": "JP", "ceid": "JP:ja"})
    raw = _request(url, retries=2, timeout=25)
    root = ET.fromstring(raw)
    items = []
    seen = set()
    for item in root.findall("./channel/item"):
        source = (item.findtext("source") or "").strip()
        raw_title = (item.findtext("title") or "").strip()
        headline = _clean_headline(raw_title, source)
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        key = re.sub(r"\s+", "", headline).lower()
        if not headline or key in seen:
            continue
        seen.add(key)
        try:
            published = parsedate_to_datetime(pub).isoformat() if pub else None
        except Exception:
            published = None
        direct = re.sub(r"\W+", "", term).lower() in re.sub(r"\W+", "", headline).lower()
        items.append({"title": headline, "source": source or "Google News", "publishedAt": published, "url": link, "directMention": direct})
    related_count = len(items)
    direct_count = sum(1 for item in items if item["directMention"])
    items.sort(key=lambda item: (not item["directMention"]))
    shown = items[:3]
    if shown:
        clipped = shown[0]["title"]
        if len(clipped) > 72:
            clipped = clipped[:71] + "…"
        summary = f"「{clipped}」など、急上昇日の前後に関連報道を{related_count}件確認。"
        confidence = "high" if direct_count >= 3 else "medium" if direct_count >= 1 or related_count >= 3 else "low"
        status = "candidate"
    else:
        summary = "急上昇日の前後で明確な関連報道を確認できず、背景は特定できません。"
        confidence = "none"
        status = "unconfirmed"
    return {
        "query": term, "status": status, "confidence": confidence, "summary": summary,
        "relatedCount": related_count, "directMentionCount": direct_count, "items": shown,
        "note": "同時期のニュース検索結果を背景候補として表示しており、閲覧増加との因果関係を断定しません。",
    }


def enrich_topics(titles: list[str], news_titles: list[str], target_day: date, raw_dir: Path, *, refresh: bool = False) -> dict:
    unique_titles = list(dict.fromkeys(titles))
    unique_news = list(dict.fromkeys(news_titles))
    input_hash = hashlib.sha256(json.dumps({"titles": sorted(unique_titles), "news": sorted(unique_news)}, ensure_ascii=False).encode()).hexdigest()[:16]
    cache_path = raw_dir / "enrichment" / f"{target_day.isoformat()}.json"
    if cache_path.exists() and not refresh:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if cached.get("version") == ENRICHMENT_VERSION and cached.get("inputHash") == input_hash:
                return cached
        except Exception:
            pass

    pages = fetch_mediawiki_metadata(unique_titles)
    qids = [x.get("wikibaseItem") for x in pages.values() if x.get("wikibaseItem")]
    wikidata = fetch_wikidata_metadata([str(x) for x in qids]) if qids else {}
    topics = {}
    for title in unique_titles:
        page = pages.get(title) or {"categories": [], "extract": "", "wikibaseItem": None}
        wd = wikidata.get(str(page.get("wikibaseItem") or ""))
        topics[title] = {
            "category": classify_topic(title, page, wd),
            "metadata": {
                "resolvedTitle": page.get("title") or title,
                "wikidataId": page.get("wikibaseItem"),
                "description": (wd or {}).get("descriptionJa") or (wd or {}).get("descriptionEn") or "",
            },
        }

    news_failures = []
    for title in unique_news:
        try:
            topics.setdefault(title, {})["reason"] = fetch_google_news(title, target_day)
        except Exception as exc:
            news_failures.append({"article": title, "error": str(exc)[:180]})
            topics.setdefault(title, {})["reason"] = {
                "query": _news_query_term(title), "status": "unavailable", "confidence": "none",
                "summary": "ニュース検索を取得できなかったため、背景候補は表示していません。",
                "relatedCount": 0, "items": [],
                "note": "ニュース連携は補助情報であり、取得失敗時もWikipediaランキング自体は更新します。",
            }
        time.sleep(0.08)

    payload = {
        "version": ENRICHMENT_VERSION, "inputHash": input_hash, "date": target_day.isoformat(),
        "topics": topics,
        "sources": {
            "classification": ["MediaWiki Action API categories/extracts", "Wikidata labels/descriptions/claims"],
            "newsContext": "Google News RSS search (Japan/Japanese edition)",
        },
        "newsFailures": news_failures,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    return payload
