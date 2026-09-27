from __future__ import annotations

import json
import re
from collections import defaultdict
from datetime import datetime, timezone

from .common import RAW, edinet_api_key, write_json
from .download_edinet_data import download_document
from .normalize_financials import choose_documents, load_master, normalize_document, parse_number, read_fact_rows

RANK_RE = re.compile(r"CurrentYearInstant_No(\d+)MajorShareholdersMember$")
OWNERSHIP_CONCEPTS = {"NameMajorShareholders", "NumberOfSharesHeld", "ShareholdingRatio"}


def _rank_facts(rows: list[dict]) -> dict[int, set[str]]:
    facts: dict[int, set[str]] = defaultdict(set)
    for row in rows:
        match = RANK_RE.search(row.get("context") or "")
        if not match:
            continue
        concept = (row.get("concept") or "").rsplit(":", 1)[-1]
        if concept not in OWNERSHIP_CONCEPTS:
            continue
        if concept == "ShareholdingRatio" and parse_number(row.get("value") or "") is None:
            continue
        facts[int(match.group(1))].add(concept)
    return facts


def _incomplete_ratio_ranks(rows: list[dict]) -> list[int]:
    facts = _rank_facts(rows)
    return sorted(
        rank for rank, concepts in facts.items()
        if "ShareholdingRatio" in concepts
        and ({"NameMajorShareholders", "NumberOfSharesHeld"} - concepts)
    )


def _latest_by_code(records: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for record in records:
        code = record.get("securityCode")
        if not code:
            continue
        current = latest.get(code)
        if current is None or (record.get("periodEnd") or "") > (current.get("periodEnd") or ""):
            latest[code] = record
    return latest


def main() -> None:
    path = RAW / "normalized" / "financials.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    latest = _latest_by_code(records)
    docs = {d.get("docID"): d for d in choose_documents() if d.get("docID")}
    _, by_code = load_master()
    positions = {r.get("docID"): i for i, r in enumerate(records) if r.get("docID")}
    candidates: list[tuple[dict, list[int]]] = []

    for record in latest.values():
        doc_id = record.get("docID")
        csv_path = RAW / "csv" / f"{doc_id}.zip"
        if not doc_id or not csv_path.exists():
            continue
        ranks = _incomplete_ratio_ranks(read_fact_rows(csv_path))
        if ranks:
            candidates.append((record, ranks))

    key = None
    repaired = 0
    unresolved: list[str] = []
    for record, ranks in candidates:
        doc_id = record["docID"]
        doc = docs.get(doc_id)
        company = by_code.get(record.get("securityCode"))
        if doc is None or company is None:
            unresolved.append(f"{doc_id}: metadata/company mapping missing")
            continue
        xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
        if not xbrl_path.exists():
            if str(doc.get("xbrlFlag")) != "1":
                unresolved.append(f"{doc_id}: XBRL unavailable for incomplete shareholder ranks {ranks}")
                continue
            if key is None:
                key = edinet_api_key()
            try:
                download_document(doc_id, 1, xbrl_path, key)
            except Exception as exc:
                unresolved.append(f"{doc_id}: XBRL download failed: {type(exc).__name__}")
                continue
        replacement = normalize_document(doc, company)
        if replacement is None:
            unresolved.append(f"{doc_id}: re-normalization failed")
            continue
        holders = {h.get("rank"): h for h in replacement.get("majorShareholders", [])}
        missing = [
            rank for rank in ranks
            if rank not in holders or not holders[rank].get("name") or holders[rank].get("shares") is None
        ]
        if missing:
            unresolved.append(f"{doc_id}: presentation recovery unresolved ranks {missing}")
            continue
        records[positions[doc_id]] = replacement
        repaired += 1

    if unresolved:
        for message in unresolved:
            print("UNRESOLVED", message)
        raise SystemExit(f"shareholder presentation validation unresolved={len(unresolved)}")

    records.sort(key=lambda r: (r["securityCode"], r.get("periodEnd") or ""))
    from .normalize_incremental import stats
    payload["generatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["records"] = records
    payload["stats"] = stats(records, payload.get("stats", {}).get("missingArchives", 0))
    write_json(path, payload)
    print(
        f"shareholder candidates={len(candidates)} repaired={repaired} unresolved=0"
    )


if __name__ == "__main__":
    main()
