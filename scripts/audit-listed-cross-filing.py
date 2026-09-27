#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.listed_companies.common import RAW
from collector.listed_companies.normalize_financials import (
    METRICS, effective_unit_id, local_concept, parse_number, read_fact_rows,
)

NORMALIZED = RAW / "normalized" / "financials.json"
FACTOR_LIMIT = 10.0
AUDIT_METRICS = set(METRICS) - {"averageSalary"}

# Both filings were checked at presentation level. These are later comparative
# revisions/reclassifications or a defect in the *later* comparative row, not an
# unresolved defect in the original-year value DATLUME publishes.
KNOWN_DIFFERENCES = {
    ("6800", "2018-03-31", "revenue", "S100G5PK"): (51919194000, 51919194000000),
    ("6800", "2018-03-31", "netIncome", "S100G5PK"): (2337571000, 2337571000000),
    ("6800", "2018-03-31", "operatingCashFlow", "S100G5PK"): (1980588000, 1980588000000),
    ("6800", "2018-03-31", "investingCashFlow", "S100G5PK"): (-2518806000, -2518806000000),
    ("6800", "2018-03-31", "financingCashFlow", "S100G5PK"): (-549945000, -549945000000),
    ("9622", "2018-12-31", "operatingCashFlow", "S100IAMO"): (2226721000, 2226721000000),
    ("9622", "2018-12-31", "investingCashFlow", "S100IAMO"): (-1381807000, -1381807000000),
    ("9622", "2018-12-31", "financingCashFlow", "S100IAMO"): (-1566818000, -1566818000000),
    ("2721", "2018-12-31", "netIncome", "S100ISIH"): (403000, -253589000),
    ("3692", "2024-03-31", "financingCashFlow", "S100W2IK"): (-50095000, -95000),
    ("3696", "2018-12-31", "ordinaryIncome", "S100I9YS"): (979071000, -2554000),
    ("4813", "2024-01-31", "ordinaryIncome", "S100W9LS"): (-12592000, -1924695000),
    ("4813", "2024-01-31", "profitBeforeTax", "S100W9LS"): (-4186000, -1949031000),
    ("5857", "2020-03-31", "financingCashFlow", "S100LJ0R"): (65165000000, 273000000),
    ("7363", "2024-12-31", "profitBeforeTax", "S100YNQ1"): (-343000, -43785000),
    ("7831", "2023-10-31", "netIncome", "S100V5M4"): (-227000000, 2000000),
    ("1447", "2022-03-31", "ordinaryIncome", "S100RSGH"): (15575000, 157244000),
    ("2170", "2020-12-31", "profitBeforeTax", "S100NRT2"): (58000000, 670000000),
    ("4558", "2018-03-31", "investingCashFlow", "S100G6US"): (210000, 7714000),
    ("4813", "2024-01-31", "operatingIncome", "S100W9LS"): (-105607000, -1977654000),
    ("6675", "2022-03-31", "operatingIncome", "S100R3Y6"): (107000000, 4000000),
    ("7422", "2024-12-20", "operatingIncome", "S100XRD8"): (6430000, 73682000),
}


def factor(a, b) -> float:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)) or a == 0 or b == 0:
        return 1.0
    return max(abs(float(a)), abs(float(b))) / min(abs(float(a)), abs(float(b)))


def nonconsolidated(context: str, consolidation: str) -> bool:
    return "NonConsolidatedMember" in context or "個別" in consolidation


def other_member(context: str) -> bool:
    return "member" in context.lower().replace("nonconsolidatedmember", "")


def prior_value(rows: list[dict], source: dict):
    wanted = local_concept(source.get("concept", ""))
    wanted_unit = ((source.get("unitId") or source.get("unit") or "").strip()).upper()
    wanted_noncon = nonconsolidated(source.get("context", ""), source.get("consolidation", ""))
    wanted_duration = "Duration" in source.get("context", "")
    candidates = []
    for row in rows:
        if local_concept(row.get("concept", "")) != wanted:
            continue
        context = row.get("context", "")
        if "Prior1Year" not in context and not (row.get("relativeYear") or "").startswith("前期"):
            continue
        if other_member(context):
            continue
        if nonconsolidated(context, row.get("consolidation", "")) != wanted_noncon:
            continue
        if ("Duration" in context) != wanted_duration:
            continue
        if effective_unit_id(row) != wanted_unit:
            continue
        value = parse_number(row.get("value", ""))
        if value is None:
            continue
        score = (20 if context.startswith("Prior1Year") else 0) + (10 if (row.get("relativeYear") or "").startswith("前期") else 0)
        candidates.append((score, value, row))
    if not candidates:
        return None
    _, value, row = max(candidates, key=lambda item: item[0])
    return value, row


def main() -> int:
    records = json.loads(NORMALIZED.read_text(encoding="utf-8")).get("records", [])
    by_company: dict[str, list[dict]] = defaultdict(list)
    for record in records:
        by_company[record["securityCode"]].append(record)
    for series in by_company.values():
        series.sort(key=lambda r: r.get("periodEnd") or "")

    # The outlier gate is deliberately 10x, but 10x alone is not an error:
    # real corporate events often move profits/cash flows by more than 10x.
    # Historical scale-error candidates are the stronger "round-trip" pattern:
    # the middle year differs >=10x from both neighbours while the neighbours
    # remain within 5x. Those candidates are checked against the following
    # filing's Prior1Year fact with the same concept/context/unit.
    candidate_pairs: list[tuple[str, dict, dict, list[str]]] = []
    transition_count = 0
    for code, series in by_company.items():
        for index in range(1, len(series) - 1):
            previous, current, following = series[index - 1:index + 2]
            try:
                gap_before = (date.fromisoformat(current["periodEnd"]) - date.fromisoformat(previous["periodEnd"])).days
                gap_after = (date.fromisoformat(following["periodEnd"]) - date.fromisoformat(current["periodEnd"])).days
            except (TypeError, ValueError):
                continue
            if not (250 <= gap_before <= 550 and 250 <= gap_after <= 550):
                continue
            metrics: list[str] = []
            for metric in AUDIT_METRICS:
                before_value = (previous.get("metrics") or {}).get(metric)
                value = (current.get("metrics") or {}).get(metric)
                next_value = (following.get("metrics") or {}).get(metric)
                if not all(isinstance(x, (int, float)) and x != 0 for x in (before_value, value, next_value)):
                    continue
                if (
                    factor(before_value, value) >= FACTOR_LIMIT
                    and factor(value, next_value) >= FACTOR_LIMIT
                    and factor(before_value, next_value) <= 5.0
                ):
                    metrics.append(metric)
            if metrics:
                transition_count += len(metrics)
                candidate_pairs.append((code, current, following, metrics))

    failures: list[str] = []
    checks = 0
    known = 0
    for pair_index, (code, current, following, metrics) in enumerate(candidate_pairs, 1):
        doc_id = following.get("docID")
        csv_path = RAW / "csv" / f"{doc_id}.zip"
        xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
        if csv_path.exists():
            rows = read_fact_rows(csv_path)
        elif xbrl_path.exists():
            from collector.listed_companies.xbrl_facts import read_xbrl_fact_rows
            rows = read_xbrl_fact_rows(xbrl_path)
        else:
            failures.append(f"{code} {following.get('periodEnd')}: comparison archive missing {doc_id}")
            continue
        for metric in metrics:
            value = (current.get("metrics") or {}).get(metric)
            source = (current.get("metricSources") or {}).get(metric)
            if not isinstance(value, (int, float)) or value == 0 or not source:
                continue
            prior = prior_value(rows, source)
            if prior is None:
                # A taxonomy/concept change is not evidence that the current value is wrong;
                # exact-source/unit/context checks are covered by the normalized/source audits.
                continue
            comparison, prior_row = prior
            if metric in {"employees", "sharesOutstanding"}:
                from collector.listed_companies.presentation import recover_count_metric
                xbrl_path = RAW / "xbrl" / f"{doc_id}.zip"
                recovered, _ = recover_count_metric(xbrl_path, metric, {
                    "concept": prior_row.get("concept", ""),
                    "context": prior_row.get("context", ""),
                })
                if recovered is not None:
                    comparison = recovered
            if not isinstance(comparison, (int, float)) or comparison == 0:
                continue
            checks += 1
            if factor(value, comparison) < FACTOR_LIMIT:
                continue
            key = (code, current.get("periodEnd"), metric, doc_id)
            allowed = KNOWN_DIFFERENCES.get(key)
            if allowed == (value, comparison):
                known += 1
                continue
            failures.append(
                f"{code} {current.get('periodEnd')} {metric}: current={value} "
                f"next-prior={comparison} following={doc_id} factor={factor(value, comparison):.1f}"
            )
        if pair_index % 500 == 0:
            print(
                f"cross-filing candidates {pair_index}/{len(candidate_pairs)} checks={checks} "
                f"known={known} failures={len(failures)}",
                flush=True,
            )

    print(
        f"listed cross-filing audit: {len(by_company)} companies, "
        f"{transition_count} 10x round-trip candidates, {len(candidate_pairs)} filing pairs, "
        f"{checks} prior-year comparisons, {known} known differences, {len(failures)} failures"
    )
    for failure in failures[:100]:
        print("FAIL", failure)
    if len(failures) > 100:
        print(f"... and {len(failures)-100} more")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
