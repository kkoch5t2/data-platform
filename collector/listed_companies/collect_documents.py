from __future__ import annotations

import argparse
import json
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

from .common import EDINET_API_BASE, PUBLIC, RAW, edinet_api_key, write_json

ANNUAL_DOC_TYPES = {"120", "130"}
EVENT_DOC_TYPES = {"180", "190"}


def iter_days(start: date, end: date):
    day = start
    while day <= end:
        yield day
        day += timedelta(days=1)



def fetch_day(day: date, key: str) -> dict:
    params = urllib.parse.urlencode({"date": day.isoformat(), "type": 2, "Subscription-Key": key})
    url = f"{EDINET_API_BASE}/documents.json?{params}"
    request = urllib.request.Request(url, headers={"User-Agent": "DATLUME/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        payload = json.loads(response.read().decode("utf-8"))
    status = payload.get("metadata", {}).get("status")
    if status != "200" and status != 200:
        raise RuntimeError(f"EDINET metadata status={status} for {day}")
    return payload


def load_target_codes() -> set[str]:
    master_path = PUBLIC / "master.json"
    if not master_path.exists():
        return set()
    master = json.loads(master_path.read_text(encoding="utf-8"))
    return {item["edinetCode"] for item in master["records"] if item.get("edinetCode")}


def normalize_result(item: dict) -> dict:
    keys = (
        "docID", "edinetCode", "secCode", "JCN", "filerName", "fundCode",
        "ordinanceCode", "formCode", "docTypeCode", "periodStart", "periodEnd",
        "submitDateTime", "docDescription", "issuerEdinetCode", "subjectEdinetCode",
        "parentDocID", "opeDateTime", "withdrawalStatus", "docInfoEditStatus",
        "disclosureStatus", "xbrlFlag", "pdfFlag", "attachDocFlag", "englishDocFlag",
        "csvFlag", "legalStatus",
    )
    return {key: item.get(key) for key in keys}


def collect(start: date, end: date, sleep_seconds: float = 0.15) -> dict:
    key = edinet_api_key()
    targets = load_target_codes()
    annual: list[dict] = []
    events: list[dict] = []
    raw_dir = RAW / "documents"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for index, day in enumerate(iter_days(start, end), start=1):
        path = raw_dir / f"{day.isoformat()}.json"
        if path.exists():
            payload = json.loads(path.read_text(encoding="utf-8"))
        else:
            payload = fetch_day(day, key)
            write_json(path, payload)
            if sleep_seconds:
                time.sleep(sleep_seconds)
        for item in payload.get("results") or []:
            if targets and item.get("edinetCode") not in targets:
                continue
            doc = normalize_result(item)
            if doc.get("docTypeCode") in ANNUAL_DOC_TYPES:
                annual.append(doc)
            elif doc.get("docTypeCode") in EVENT_DOC_TYPES:
                events.append(doc)
        if index % 100 == 0:
            print(f"scanned {index} days / annual={len(annual)} events={len(events)}")
    return {"annual": annual, "events": events}


def parse_args():
    today = date.today()
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default=today.isoformat())
    parser.add_argument("--end", default=today.isoformat())
    parser.add_argument("--sleep", type=float, default=0.15)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    start = date.fromisoformat(args.start)
    end = date.fromisoformat(args.end)
    if end < start:
        raise SystemExit("--end must be on or after --start")
    result = collect(start, end, args.sleep)
    index_path = RAW / "documents-index.json"
    existing = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {}
    def merge_docs(old_docs, new_docs):
        merged = {doc.get("docID"): doc for doc in old_docs if doc.get("docID")}
        for doc in new_docs:
            if doc.get("docID"):
                merged[doc["docID"]] = doc
        return sorted(merged.values(), key=lambda d: (d.get("submitDateTime") or "", d.get("docID") or ""))
    ranges = existing.get("scanRanges", [])
    range_item = {"start": start.isoformat(), "end": end.isoformat()}
    if range_item not in ranges:
        ranges.append(range_item)
    payload = {
        "dataset": "listed-companies-edinet-documents",
        "scanRanges": ranges,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "annualReports": merge_docs(existing.get("annualReports", []), result["annual"]),
        "extraordinaryReports": merge_docs(existing.get("extraordinaryReports", []), result["events"]),
    }
    write_json(index_path, payload)
    print(
        f"annual={len(payload['annualReports'])} "
        f"extraordinary={len(payload['extraordinaryReports'])} "
        f"scanned={start.isoformat()}..{end.isoformat()}"
    )


if __name__ == "__main__":
    main()
