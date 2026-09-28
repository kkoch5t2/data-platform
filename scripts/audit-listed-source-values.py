#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.listed_companies.common import RAW
from collector.listed_companies.normalize_financials import (
    METRICS,
    accounting_standard,
    effective_unit_id,
    parse_number,
    read_fact_rows,
    select_metric,
    should_use_ordinary_revenue_topline,
)
from collector.listed_companies.presentation import recover_count_metric
from collector.listed_companies.salary import recover_average_salary
from collector.listed_companies.segments import extract_segments
from collector.listed_companies.ownership import extract_major_shareholders
from collector.listed_companies.source_corrections import CORRECTIONS

NORMALIZED = RAW / "normalized" / "financials.json"
BATCH_SIZE = 100


def audit_record(record: dict) -> tuple[int, list[str]]:
    checks = 0
    failures: list[str] = []
    doc_id = record.get("docID")
    csv_path = RAW / "csv" / f"{doc_id}.zip"
    xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
    if not csv_path.exists():
        return checks, failures

    rows = read_fact_rows(csv_path)
    standard = accounting_standard(rows)
    prefer_consolidated = bool(record.get("consolidatedPreferred"))
    preferred_metrics = {}
    preferred_sources = {}
    for metric, spec in METRICS.items():
        value, source = select_metric(rows, metric, spec, prefer_consolidated, standard)
        preferred_metrics[metric] = value
        if source:
            preferred_sources[metric] = source

    company = {"industry33": record.get("industry33")}
    if should_use_ordinary_revenue_topline(company, preferred_metrics, preferred_sources, prefer_consolidated):
        preferred_metrics["revenue"] = preferred_metrics["ordinaryRevenue"]
        preferred_sources["revenue"] = {**preferred_sources["ordinaryRevenue"], "toplineBasis": "ordinaryRevenue"}
        # The normalizer intentionally drops standalone operating income when the
        # consolidated group topline is ordinary revenue. Mirror that policy here
        # so source validation does not demand the discarded standalone fact.
        preferred_metrics["operatingIncome"] = None
        preferred_sources.pop("operatingIncome", None)

    for metric in METRICS:
        preferred_source = preferred_sources.get(metric)
        stored_source = record.get("metricSources", {}).get(metric)
        checks += 1
        preferred_key = (
            (preferred_source or {}).get("concept"),
            (preferred_source or {}).get("context"),
            ((preferred_source or {}).get("unitId") or (preferred_source or {}).get("unit") or "").upper(),
        )
        stored_key = (
            (stored_source or {}).get("concept"),
            (stored_source or {}).get("context"),
            ((stored_source or {}).get("unitId") or (stored_source or {}).get("unit") or "").upper(),
        )
        if preferred_key != stored_key:
            failures.append(
                f"{doc_id} {metric}: stored source {stored_key} is not current preferred source {preferred_key}"
            )

    checks += 1
    if extract_major_shareholders(rows, xbrl_path) != (record.get("majorShareholders") or []):
        failures.append(f"{doc_id}: major-shareholder extraction differs from exact source/presentation rows")
    if record.get("segments"):
        checks += 1
        if extract_segments(rows, xbrl_path) != record.get("segments"):
            failures.append(f"{doc_id}: segment extraction differs from exact source/XBRL contexts")

    for metric, source in record.get("metricSources", {}).items():
        expected = record.get("metrics", {}).get(metric)
        concept = source.get("concept")
        context = source.get("context")
        correction = CORRECTIONS.get((doc_id, metric))
        if not concept or not context:
            continue
        if expected is None and correction is None:
            continue
        source_unit = ((source.get("unitId") or source.get("unit") or "").strip()).upper()
        matching = [
            parse_number(row.get("value"))
            for row in rows
            if row.get("concept") == concept
            and row.get("context") == context
            and effective_unit_id(row) == source_unit
        ]
        matching = [value for value in matching if value is not None]
        if correction is not None:
            original = (source.get("validatedCorrection") or {}).get("originalValue")
            checks += 1
            if original not in matching:
                failures.append(f"{doc_id} {metric}: correction original {original} not found in exact source fact {matching[:4]}")
            checks += 1
            if expected != correction["value"]:
                failures.append(f"{doc_id} {metric}: correction value {expected} != registry {correction['value']}")
            continue
        if source.get("presentationRecovery"):
            if metric == "averageSalary":
                recovered, _ = recover_average_salary(xbrl_path)
            elif metric in {"employees", "sharesOutstanding"}:
                recovered, _ = recover_count_metric(xbrl_path, metric, source)
            else:
                recovered = None
            checks += 1
            if recovered != expected:
                failures.append(f"{doc_id} {metric}: presentation recovery {recovered} != normalized {expected}")
            continue
        checks += 1
        if expected not in matching:
            failures.append(
                f"{doc_id} {metric}: normalized {expected} not found in exact source fact "
                f"concept={concept} context={context} values={matching[:4]}"
            )
    return checks, failures


def audit_batch(batch: list[dict]) -> tuple[int, int, list[str]]:
    checks = 0
    failures: list[str] = []
    for record in batch:
        record_checks, record_failures = audit_record(record)
        checks += record_checks
        failures.extend(record_failures)
    return len(batch), checks, failures


def main() -> int:
    records = json.loads(NORMALIZED.read_text(encoding="utf-8")).get("records", [])
    batches = [records[i:i + BATCH_SIZE] for i in range(0, len(records), BATCH_SIZE)]
    workers = min(4, max(1, os.cpu_count() or 1))
    checks = 0
    failures: list[str] = []
    processed = 0
    next_report = 1000

    with ProcessPoolExecutor(max_workers=workers) as pool:
        for batch_size, batch_checks, batch_failures in pool.map(audit_batch, batches, chunksize=1):
            processed += batch_size
            checks += batch_checks
            failures.extend(batch_failures)
            if processed >= next_report or processed == len(records):
                print(
                    f"source-audit {processed}/{len(records)} checks={checks} "
                    f"failures={len(failures)} workers={workers}", flush=True,
                )
                while next_report <= processed:
                    next_report += 1000

    print(f"listed source audit: {len(records)} records, {checks} checks, {len(failures)} failures")
    for failure in failures[:100]:
        print("FAIL", failure)
    if len(failures) > 100:
        print(f"... and {len(failures) - 100} more")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
