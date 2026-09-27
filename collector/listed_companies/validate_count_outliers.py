from __future__ import annotations

import json
from collections import defaultdict
from datetime import date, datetime, timezone

from .common import RAW, edinet_api_key, write_json
from .download_edinet_data import download_document
from .normalize_financials import choose_documents, load_master, normalize_document
from .presentation import recover_count_metric

FACTOR_LIMIT = 5.0
COUNT_METRICS = ("employees", "sharesOutstanding")


def factor(a, b) -> float:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return 1.0
    if a == 0 or b == 0:
        return 1.0
    return max(abs(float(a)), abs(float(b))) / min(abs(float(a)), abs(float(b)))


def latest_candidates(records: list[dict]) -> list[tuple[dict, str, int | float]]:
    by_code: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        if record.get("securityCode") and record.get("periodEnd"):
            by_code[record["securityCode"]].append(record)
    candidates: list[tuple[dict, str, int | float]] = []
    for series in by_code.values():
        series.sort(key=lambda r: r.get("periodEnd") or "")
        if len(series) < 2:
            continue
        previous, current = series[-2], series[-1]
        try:
            gap_days = (date.fromisoformat(current["periodEnd"]) - date.fromisoformat(previous["periodEnd"])).days
        except (TypeError, ValueError):
            continue
        if gap_days > 550:
            continue
        for metric in COUNT_METRICS:
            before = (previous.get("metrics") or {}).get(metric)
            value = (current.get("metrics") or {}).get(metric)
            if factor(before, value) >= FACTOR_LIMIT:
                candidates.append((current, metric, before))
    return candidates


def main() -> None:
    path = RAW / "normalized" / "financials.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    candidates = latest_candidates(records)
    docs = {d.get("docID"): d for d in choose_documents() if d.get("docID")}
    _, by_code = load_master()
    positions = {r.get("docID"): i for i, r in enumerate(records) if r.get("docID")}
    key = None
    verified = 0
    corrected: list[tuple[str, str, str, int | float, int | float]] = []
    unresolved: list[str] = []
    for record, metric, before in candidates:
        doc_id = record.get("docID")
        doc = docs.get(doc_id)
        company = by_code.get(str(record.get("securityCode") or ""))
        source = (record.get("metricSources") or {}).get(metric)
        if not doc_id or doc is None or company is None or not source:
            unresolved.append(f"{doc_id or '?'} {metric}: metadata/source missing")
            continue
        xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
        if not xbrl_path.exists():
            if str(doc.get("xbrlFlag")) != "1":
                unresolved.append(f"{doc_id} {metric}: XBRL unavailable")
                continue
            if key is None:
                key = edinet_api_key()
            try:
                download_document(doc_id, 1, xbrl_path, key)
            except Exception as exc:
                unresolved.append(f"{doc_id} {metric}: XBRL download failed: {type(exc).__name__}")
                continue
        recovered, _ = recover_count_metric(xbrl_path, metric, source)
        if recovered is None:
            unresolved.append(f"{doc_id} {metric}: presentation value could not be recovered")
            continue
        current = (record.get("metrics") or {}).get(metric)
        if current == recovered:
            verified += 1
            continue
        replacement = normalize_document(doc, company)
        if replacement is None:
            unresolved.append(f"{doc_id} {metric}: re-normalization failed")
            continue
        replacement_value = (replacement.get("metrics") or {}).get(metric)
        if replacement_value != recovered:
            unresolved.append(
                f"{doc_id} {metric}: presentation={recovered} re-normalized={replacement_value}"
            )
            continue
        records[positions[doc_id]] = replacement
        corrected.append((record["securityCode"], record.get("periodEnd") or "", metric, current, recovered))

    if unresolved:
        for message in unresolved:
            print("UNRESOLVED", message)
        raise SystemExit(f"count presentation validation unresolved={len(unresolved)}")

    records.sort(key=lambda r: (r["securityCode"], r.get("periodEnd") or ""))
    from .normalize_incremental import stats
    payload["generatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["records"] = records
    payload["stats"] = stats(records, payload.get("stats", {}).get("missingArchives", 0))
    write_json(path, payload)
    for code, period_end, metric, old, new in corrected:
        print(f"CORRECTED {code} {period_end} {metric}: {old} -> {new}")
    print(
        f"count candidates={len(candidates)} verified={verified} "
        f"corrected={len(corrected)} unresolved=0 threshold={FACTOR_LIMIT:.0f}x"
    )


if __name__ == "__main__":
    main()
