from __future__ import annotations

import json
from datetime import datetime, timezone

from .common import RAW, write_json
from .normalize_financials import choose_documents, load_master, normalize_document


def stats(records: list[dict], missing: int = 0) -> dict:
    return {
        "records": len(records),
        "companies": len({r["securityCode"] for r in records}),
        "missingArchives": missing,
        "csvRecords": sum(1 for r in records if r.get("sourceFormat") == "edinet-csv"),
        "xbrlFallbackRecords": sum(1 for r in records if r.get("sourceFormat") == "xbrl"),
        "balanceSheetWarnings": sum(
            1 for r in records
            if any(w.get("type") == "balanceSheetEquation" for w in r.get("warnings", []))
        ),
    }


def main() -> None:
    output = RAW / "normalized" / "financials.json"
    existing = json.loads(output.read_text(encoding="utf-8")) if output.exists() else {"records": []}
    by_edinet, by_code = load_master()
    valid_codes = set(by_code)
    records = {
        (r.get("securityCode"), r.get("periodEnd")): r
        for r in existing.get("records", [])
        if r.get("securityCode") in valid_codes and r.get("periodEnd")
    }
    changed = 0
    missing = 0
    for doc in choose_documents():
        company = by_edinet.get(doc.get("edinetCode"))
        if not company:
            continue
        key = (company["securityCode"], doc.get("periodEnd"))
        old = records.get(key)
        if old and old.get("docID") == doc.get("docID"):
            continue
        record = normalize_document(doc, company)
        if record is None:
            missing += 1
            continue
        records[key] = record
        changed += 1

    ordered = sorted(records.values(), key=lambda r: (r["securityCode"], r.get("periodEnd") or ""))
    payload = {
        "dataset": "listed-companies-normalized-financials",
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "records": ordered,
        "stats": stats(ordered, missing),
    }
    write_json(output, payload)
    print(f"incremental changed={changed} {payload['stats']}")


if __name__ == "__main__":
    main()
