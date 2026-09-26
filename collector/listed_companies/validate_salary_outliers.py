from __future__ import annotations

import json
import statistics
from collections import defaultdict
from datetime import datetime, timezone

from .common import RAW, edinet_api_key, write_json
from .download_edinet_data import download_document
from .normalize_financials import choose_documents, load_master, normalize_document
from .salary import recover_average_salary

LOW = 1_000_000
HIGH = 20_000_000
RATIO = 3.0


def candidate_doc_ids(records: list[dict]) -> set[str]:
    by_code: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        salary = (record.get("metrics") or {}).get("averageSalary")
        if salary is not None:
            by_code[str(record.get("securityCode") or "")].append(record)
    candidates: set[str] = set()
    for company_records in by_code.values():
        ordered = sorted(company_records, key=lambda r: r.get("periodEnd") or "")
        salaries = [(r.get("metrics") or {}).get("averageSalary") for r in ordered]
        median = statistics.median(salaries) if salaries else None
        for record, salary in zip(ordered, salaries):
            if salary < LOW or salary > HIGH:
                candidates.add(record["docID"])
            elif median and (salary / median >= RATIO or salary / median <= 1 / RATIO):
                candidates.add(record["docID"])
        for before, after in zip(ordered, ordered[1:]):
            a = (before.get("metrics") or {}).get("averageSalary")
            b = (after.get("metrics") or {}).get("averageSalary")
            if a and b and (b / a >= RATIO or b / a <= 1 / RATIO):
                candidates.add(before["docID"])
                candidates.add(after["docID"])
    return candidates


def compute_stats(records: list[dict], missing: int = 0) -> dict:
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
    path = RAW / "normalized" / "financials.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    candidates = candidate_doc_ids(records)
    docs = {d.get("docID"): d for d in choose_documents() if d.get("docID")}
    _, by_code = load_master()
    positions = {r.get("docID"): i for i, r in enumerate(records) if r.get("docID")}
    key = None
    corrected: list[tuple[str, str, int | float, int | float]] = []
    verified = 0
    unresolved: list[str] = []

    for doc_id in sorted(candidates):
        pos = positions.get(doc_id)
        doc = docs.get(doc_id)
        if pos is None or doc is None:
            unresolved.append(f"{doc_id}: normalized/document metadata missing")
            continue
        record = records[pos]
        xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
        if not xbrl_path.exists():
            if str(doc.get("xbrlFlag")) != "1":
                unresolved.append(f"{doc_id}: XBRL unavailable")
                continue
            if key is None:
                key = edinet_api_key()
            try:
                download_document(doc_id, 1, xbrl_path, key)
            except Exception as exc:
                unresolved.append(f"{doc_id}: XBRL download failed: {type(exc).__name__}")
                continue
        recovered, recovery_source = recover_average_salary(xbrl_path)
        if recovered is None:
            unresolved.append(f"{doc_id}: presentation salary could not be recovered")
            continue
        company = by_code.get(str(record.get("securityCode") or ""))
        if not company:
            unresolved.append(f"{doc_id}: company mapping missing")
            continue
        replacement = normalize_document(doc, company)
        if replacement is None:
            unresolved.append(f"{doc_id}: re-normalization failed")
            continue
        current = (record.get("metrics") or {}).get("averageSalary")
        new_value = (replacement.get("metrics") or {}).get("averageSalary")
        if new_value != recovered:
            unresolved.append(f"{doc_id}: recovered/re-normalized salary mismatch")
            continue
        if current != new_value:
            corrected.append((record["securityCode"], record.get("periodEnd") or "", current, new_value))
        else:
            verified += 1
        records[pos] = replacement

    if unresolved:
        for message in unresolved:
            print("UNRESOLVED", message)
        raise SystemExit(f"salary presentation validation unresolved={len(unresolved)}")

    records.sort(key=lambda r: (r["securityCode"], r.get("periodEnd") or ""))
    payload["generatedAt"] = datetime.now(timezone.utc).isoformat()
    payload["records"] = records
    payload["stats"] = compute_stats(records, payload.get("stats", {}).get("missingArchives", 0))
    write_json(path, payload)
    for code, period_end, old, new in corrected:
        print(f"CORRECTED {code} {period_end}: {old} -> {new}")
    print(f"salary candidates={len(candidates)} verified={verified} corrected={len(corrected)} unresolved=0")


if __name__ == "__main__":
    main()
