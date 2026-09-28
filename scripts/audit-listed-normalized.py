#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from collector.listed_companies.common import RAW
from collector.listed_companies.normalize_financials import FINANCIAL_INDUSTRIES, MONETARY_METRICS
from collector.listed_companies.presentation import recover_count_metric
from collector.listed_companies.source_corrections import CORRECTIONS

NORMALIZED = RAW / "normalized" / "financials.json"
CORE_CONSOLIDATED = {
    "revenue", "operatingIncome", "ordinaryIncome", "profitBeforeTax", "netIncome",
    "assets", "liabilities", "equity", "parentEquity", "cash",
    "operatingCashFlow", "investingCashFlow", "financingCashFlow", "employees",
}
STABLE_METRICS = (
    "revenue", "assets", "liabilities", "equity", "parentEquity", "cash",
    "employees", "averageSalary", "sharesOutstanding",
)
ROUND_TRIP_FACTOR_LIMIT = 10.0
COUNT_FACTOR_LIMIT = 5.0
COUNT_METRICS = {"employees", "sharesOutstanding"}

# Reviewed against exact EDINET concept/context/unit and surrounding statements.
# Values are pinned so a future source correction or a changed extraction fails loudly.
KNOWN_ROUND_TRIPS = {
    ("2338", "2024-02-29", "liabilities"): (72044000, 1131821000, 86988000),
    ("2338", "2024-02-29", "equity"): (396657000, 18109000, 237499000),
    ("2338", "2025-02-28", "liabilities"): (1131821000, 86988000, 3046595000),
    ("2404", "2017-08-31", "equity"): (1612010000, 16989000, 376837000),
    ("3370", "2022-03-31", "equity"): (44621000, 2555000, 83799000),
    ("3557", "2021-02-28", "equity"): (1640652000, 33737000, 376367000),
    ("3777", "2020-12-31", "equity"): (3297183000, 109143000, 1517608000),
    ("4179", "2024-03-31", "equity"): (153500000, 4036000, 168714000),
    ("4586", "2018-12-31", "revenue"): (198212000, 8397000, 169860000),
    ("4591", "2019-03-31", "liabilities"): (99748000, 1086016000, 88788000),
    ("4594", "2024-03-31", "revenue"): (5280000, 72000, 1133000),
    ("4594", "2025-03-31", "revenue"): (72000, 1133000, 84000),
    ("4599", "2022-07-31", "revenue"): (1400000000, 22976000, 2350000000),
    ("7063", "2024-06-30", "cash"): (1196856000, 115844000, 1728198000),
    ("8894", "2024-10-31", "equity"): (1291716000, 19054862000, 1511518000),
    ("9722", "2020-12-31", "equity"): (26438000000, 1347000000, 28833000000),
    ("9973", "2019-12-31", "equity"): (-1057901000, 9203000, 306384000),
}

KNOWN_LATEST_10X = {
    ('1491', '2026-03-31', 'sharesOutstanding'): (289747000, 14487000),
    ('175A', '2025-12-31', 'equity'): (410176000, 3183000),
    ('184A', '2026-04-30', 'cash'): (29956000, 459872000),
    ('2146', '2026-03-31', 'sharesOutstanding'): (39860383, 601193745),
    ('2334', '2026-03-31', 'assets'): (1046576000, 11001112000),
    ('2334', '2026-03-31', 'equity'): (310524000, 3498517000),
    ('2334', '2026-03-31', 'liabilities'): (736051000, 7502595000),
    ('2334', '2026-03-31', 'sharesOutstanding'): (2648992, 41023920),
    ('2338', '2026-02-28', 'liabilities'): (86988000, 3046595000),
    ('2345', '2025-10-31', 'assets'): (86538161000, 533389000),
    ('2345', '2025-10-31', 'employees'): (80, 7),
    ('2345', '2025-10-31', 'liabilities'): (85106288000, 105545000),
    ('2345', '2025-10-31', 'revenue'): (1613430000, 26550000),
    ('3070', '2026-01-31', 'assets'): (628999000, 6645786000),
    ('3070', '2026-01-31', 'equity'): (205796000, 4931231000),
    ('3175', '2026-03-31', 'equity'): (-50726000, 1124852000),
    ('3185', '2026-03-31', 'equity'): (417207000, 19988000),
    ('3185', '2026-03-31', 'parentEquity'): (417207000, 19988000),
    ('3189', '2025-08-31', 'assets'): (822859000, 18320042000),
    ('3350', '2025-12-31', 'assets'): (30325812000, 505286000000),
    ('3350', '2025-12-31', 'equity'): (16965842000, 458592000000),
    ('3350', '2025-12-31', 'sharesOutstanding'): (36268334, 1142274340),
    ('3697', '2025-08-31', 'sharesOutstanding'): (17833378, 267500670),
    ('3750', '2026-03-31', 'equity'): (630536000, 22025000),
    ('3777', '2025-12-31', 'revenue'): (17237007000, 1371110000),
    ('3798', '2026-03-31', 'sharesOutstanding'): (6228800, 63853000),
    ('3810', '2026-05-31', 'cash'): (212000000, 3634000000),
    ('3810', '2026-05-31', 'equity'): (546000000, 6530000000),
    ('3905', '2026-03-31', 'revenue'): (2942635000, 33605038000),
    ('3976', '2025-12-31', 'equity'): (-52542000, 986294000),
    ('3997', '2025-12-31', 'sharesOutstanding'): (3445800, 39042000),
    ('4594', '2026-03-31', 'revenue'): (1133000, 84000),
    ('4784', '2025-12-31', 'sharesOutstanding'): (16757200, 274698528),
    ('4896', '2025-12-31', 'liabilities'): (94760000, 1673785000),
    ('6177', '2025-12-31', 'cash'): (70832000, 735756000),
    ('6177', '2025-12-31', 'equity'): (70871000, 918851000),
    ('6574', '2026-03-31', 'sharesOutstanding'): (4334960, 509156000),
    ('6634', '2025-11-30', 'assets'): (5941035000, 134712580000),
    ('6634', '2025-11-30', 'liabilities'): (1609763000, 131684283000),
    ('7063', '2025-06-30', 'cash'): (115844000, 1728198000),
    ('7111', '2026-03-31', 'sharesOutstanding'): (109596485, 7306432),
    ('7273', '2026-03-31', 'sharesOutstanding'): (1744400, 29385000),
    ('7422', '2025-12-20', 'sharesOutstanding'): (512070, 5120700),
    ('8303', '2026-03-31', 'sharesOutstanding'): (48, 895500000),
    ('8729', '2026-03-31', 'sharesOutstanding'): (435100000, 6770358000),
    ('8746', '2026-03-31', 'liabilities'): (1640152000, 23582000000),
    ('8894', '2025-10-31', 'equity'): (19054862000, 1511518000),
    ('9238', '2026-02-28', 'equity'): (581816000, 39510000),
    ('9417', '2025-06-30', 'liabilities'): (1878637000, 21904680000),
    ('9444', '2026-05-08', 'revenue'): (17795149000, 340951000),
}


def factor(a, b) -> float:
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return 1.0
    if a == 0 or b == 0:
        return 1.0
    return max(abs(float(a)), abs(float(b))) / min(abs(float(a)), abs(float(b)))


def ratio(numerator, denominator):
    if numerator is None or denominator in (None, 0):
        return None
    return numerator / denominator * 100


def same_number(a, b, tolerance=1e-9) -> bool:
    if a is None or b is None:
        return a is b
    scale = max(1.0, abs(float(a)), abs(float(b)))
    return abs(float(a) - float(b)) <= scale * tolerance


def main() -> int:
    payload = json.loads(NORMALIZED.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    index = json.loads((RAW / "documents-index.json").read_text(encoding="utf-8"))
    doc_meta = {d["docID"]: d for d in index.get("annualReports", []) if d.get("docID")}
    failures: list[str] = []
    outlier_warnings: list[str] = []
    checks = 0

    def check(condition: bool, message: str) -> None:
        nonlocal checks
        checks += 1
        if not condition:
            failures.append(message)

    by_company: dict[str, list[dict]] = defaultdict(list)
    seen = set()
    for record in records:
        key = (record.get("securityCode"), record.get("periodEnd"))
        check(key not in seen, f"duplicate normalized period: {key}")
        seen.add(key)
        by_company[record["securityCode"]].append(record)
        meta = doc_meta.get(record.get("docID"), {})
        check(str(meta.get("ordinanceCode") or "") == "010", f"non-corporate EDINET filing selected: {record.get('docID')} {key}")
        standard = (record.get("accountingStandard") or "").strip().strip('"').upper()
        for metric, source in record.get("metricSources", {}).items():
            if metric in MONETARY_METRICS and record.get("metrics", {}).get(metric) is not None:
                unit_id = ((source.get("unitId") or source.get("unit") or "").strip()).upper()
                check(unit_id == "JPY" or (source.get("unit") or "").strip() == "円", f"{key} {metric}: non-JPY monetary fact selected ({unit_id or source.get('unit')})")
        if record.get("consolidatedPreferred") and standard in {"IFRS", "US GAAP"}:
            for metric, source in record.get("metricSources", {}).items():
                if metric not in CORE_CONSOLIDATED:
                    continue
                context = source.get("context") or ""
                check(
                    "NonConsolidatedMember" not in context,
                    f"{key} {standard} {metric}: standalone fact selected ({context})",
                )
        employees = record.get("metrics", {}).get("employees")
        if employees is not None:
            check(0 < employees < 2_000_000, f"{key}: implausible employees={employees}")
            employee_source = record.get("metricSources", {}).get("employees") or {}
            employee_unit = (employee_source.get("unitId") or employee_source.get("unit") or "").upper()
            check(employee_unit not in {"円", "JPY", "USD", "EUR", "GBP", "CNY", "HKD", "SGD"}, f"{key}: employees selected from currency unit {employee_unit}")
        shares = record.get("metrics", {}).get("sharesOutstanding")
        if shares is not None:
            check(shares > 0, f"{key}: nonpositive sharesOutstanding={shares}")
            share_source = record.get("metricSources", {}).get("sharesOutstanding") or {}
            share_unit = (share_source.get("unitId") or share_source.get("unit") or "").upper()
            check(share_unit not in {"円", "JPY", "USD", "EUR", "GBP", "CNY", "HKD", "SGD"}, f"{key}: shares selected from currency unit {share_unit}")
        metrics = record.get("metrics", {})

        # A consolidated group must not silently keep a standalone revenue fact
        # when the same filing exposes a much larger consolidated ordinary-revenue
        # topline. This is the failure mode that previously understated Japan Post.
        revenue_source = record.get("metricSources", {}).get("revenue") or {}
        ordinary_revenue_source = record.get("metricSources", {}).get("ordinaryRevenue") or {}
        ordinary_income_source = record.get("metricSources", {}).get("ordinaryIncome") or {}
        revenue_nonconsolidated = (
            "個別" in (revenue_source.get("consolidation") or "")
            or "NonConsolidatedMember" in (revenue_source.get("context") or "")
        )
        ordinary_revenue_nonconsolidated = (
            "個別" in (ordinary_revenue_source.get("consolidation") or "")
            or "NonConsolidatedMember" in (ordinary_revenue_source.get("context") or "")
        )
        ordinary_income_nonconsolidated = (
            "個別" in (ordinary_income_source.get("consolidation") or "")
            or "NonConsolidatedMember" in (ordinary_income_source.get("context") or "")
        )
        revenue_value = metrics.get("revenue")
        ordinary_revenue_value = metrics.get("ordinaryRevenue")
        ordinary_income_value = metrics.get("ordinaryIncome")
        ordinary_revenue_concept = (ordinary_revenue_source.get("concept") or "").rsplit(":", 1)[-1]
        unhandled_ordinary_topline = (
            bool(record.get("consolidatedPreferred"))
            and record.get("industry33") not in FINANCIAL_INDUSTRIES
            and revenue_nonconsolidated
            and revenue_value not in (None, 0)
            and ordinary_revenue_value is not None
            and ordinary_income_value is not None
            and not ordinary_revenue_nonconsolidated
            and not ordinary_income_nonconsolidated
            and ordinary_revenue_concept == "OrdinaryIncomeSummaryOfBusinessResults"
            and abs(ordinary_revenue_value) >= abs(revenue_value) * 1.5
        )
        check(not unhandled_ordinary_topline, f"{key}: consolidated ordinary-revenue topline left behind standalone revenue")

        ordinary_topline_warning = any(w.get("type") == "ordinaryRevenueTopline" for w in record.get("warnings", []))
        if ordinary_topline_warning:
            check(record.get("toplineBasis") == "ordinaryRevenue", f"{key}: ordinaryRevenueTopline basis missing")
            check(record.get("sectorModel") == "financial", f"{key}: ordinaryRevenueTopline must use financial sector model")
            check(metrics.get("operatingIncome") is None, f"{key}: ordinaryRevenueTopline retained standalone operating income")
            check(same_number(metrics.get("revenue"), metrics.get("ordinaryRevenue")), f"{key}: ordinaryRevenueTopline revenue mismatch")
            check(revenue_source.get("toplineBasis") == "ordinaryRevenue", f"{key}: ordinaryRevenueTopline source basis missing")

        salary = metrics.get("averageSalary")
        if salary is not None:
            check(100_000 <= salary <= 100_000_000, f"{key}: implausible averageSalary={salary}")
        age = metrics.get("averageAge")
        if age is not None:
            check(15 <= age <= 100, f"{key}: implausible averageAge={age}")
        tenure = metrics.get("averageTenure")
        if tenure is not None:
            check(0 <= tenure <= 80, f"{key}: implausible averageTenure={tenure}")
        for metric, value in metrics.items():
            if isinstance(value, (int, float)):
                check(math.isfinite(float(value)), f"{key}: non-finite metric {metric}={value}")
        expected_fcf = None
        if metrics.get("operatingCashFlow") is not None and metrics.get("investingCashFlow") is not None:
            expected_fcf = metrics["operatingCashFlow"] + metrics["investingCashFlow"]
        check(same_number(metrics.get("freeCashFlow"), expected_fcf), f"{key}: freeCashFlow formula mismatch")
        financial = record.get("sectorModel") == "financial"
        expected_operating_margin = None if financial else ratio(metrics.get("operatingIncome"), metrics.get("revenue"))
        expected_net_margin = None if financial else ratio(metrics.get("netIncome"), metrics.get("revenue"))
        expected_debt_ratio = None if financial else ratio(metrics.get("liabilities"), metrics.get("equity"))
        check(same_number(metrics.get("operatingMargin"), expected_operating_margin), f"{key}: operatingMargin formula mismatch")
        check(same_number(metrics.get("netMargin"), expected_net_margin), f"{key}: netMargin formula mismatch")
        check(same_number(metrics.get("roa"), ratio(metrics.get("netIncome"), metrics.get("assets"))), f"{key}: roa formula mismatch")
        check(same_number(metrics.get("debtRatio"), expected_debt_ratio), f"{key}: debtRatio formula mismatch")
        reported_equity_ratio = metrics.get("reportedEquityRatio")
        expected_equity_ratio = reported_equity_ratio * 100 if reported_equity_ratio is not None and abs(reported_equity_ratio) <= 2 else reported_equity_ratio
        if expected_equity_ratio is None:
            expected_equity_ratio = ratio(metrics.get("parentEquity") or metrics.get("equity"), metrics.get("assets"))
        check(same_number(metrics.get("equityRatio"), expected_equity_ratio), f"{key}: equityRatio formula mismatch")
        reported_roe = metrics.get("reportedRoe")
        if reported_roe is not None:
            expected_roe = reported_roe * 100 if abs(reported_roe) <= 2 else reported_roe
            check(same_number(metrics.get("roe"), expected_roe), f"{key}: reported roe conversion mismatch")
        elif metrics.get("roe") is not None:
            check(same_number(metrics.get("roe"), ratio(metrics.get("netIncome"), metrics.get("parentEquity") or metrics.get("equity"))), f"{key}: fallback roe formula mismatch")

        segments = record.get("segments") or []
        segment_members = set()
        for segment in segments:
            member = segment.get("member")
            check(bool(member) and member not in segment_members, f"{key}: duplicate/blank segment member {member}")
            segment_members.add(member)
            check(bool((segment.get("name") or "").strip()), f"{key} {member}: blank segment name")
            check(segment.get("revenueBasis") in {"external", "segment-total"}, f"{key} {member}: invalid revenue basis")
            revenue = segment.get("revenue")
            profit = segment.get("operatingProfit")
            margin = segment.get("operatingMargin")
            check(isinstance(revenue, (int, float)) and revenue > 0, f"{key} {member}: invalid segment revenue {revenue}")
            if isinstance(revenue, (int, float)) and revenue and isinstance(profit, (int, float)) and margin is not None:
                check(abs(profit / revenue * 100 - margin) <= 1e-6, f"{key} {member}: segment margin mismatch")
            for field in ("revenueYoY", "profitYoY", "operatingMargin"):
                value = segment.get(field)
                check(value is None or (isinstance(value, (int, float)) and math.isfinite(float(value))), f"{key} {member}: invalid {field}")

        holders = record.get("majorShareholders") or []
        ranks = [holder.get("rank") for holder in holders]
        check(ranks == sorted(set(ranks)), f"{key}: shareholder ranks duplicate/out of order")
        for holder in holders:
            rank = holder.get("rank")
            check(bool((holder.get("name") or "").strip()), f"{key} shareholder {rank}: blank name")
            holding_ratio = holder.get("shareholdingRatio")
            check(isinstance(holding_ratio, (int, float)) and 0 <= holding_ratio <= 100, f"{key} shareholder {rank}: invalid ratio {holding_ratio}")
            shares = holder.get("shares")
            check(isinstance(shares, (int, float)) and shares >= 0, f"{key} shareholder {rank}: invalid/missing shares {shares}")

        xbrl = RAW / "xbrl" / f"{record.get('docID')}.zip"
        if xbrl.exists():
            for metric in ("employees", "sharesOutstanding"):
                source = record.get("metricSources", {}).get(metric)
                if not source:
                    continue
                recovered, _ = recover_count_metric(xbrl, metric, source)
                if recovered is not None:
                    check(
                        recovered == record.get("metrics", {}).get(metric) or (record.get("docID"), metric) in CORRECTIONS,
                        f"{key} {metric}: presentation unit says {recovered}, normalized={record.get('metrics', {}).get(metric)}",
                    )

    for (doc_id, metric), correction in CORRECTIONS.items():
        matches = [r for r in records if r.get("docID") == doc_id]
        check(len(matches) == 1, f"validated correction source missing/duplicate: {doc_id} {metric}")
        check(correction.get("evidenceDocID") in doc_meta, f"validated correction evidence document missing: {doc_id} {metric} -> {correction.get('evidenceDocID')}")
        check(bool((correction.get("reason") or "").strip()), f"validated correction reason missing: {doc_id} {metric}")
        if matches:
            value = matches[0].get("metrics", {}).get(metric)
            check(value == correction["value"], f"validated correction not applied: {doc_id} {metric}={value}")

    # Catch one-year scale spikes/drops. A legitimate corporate event generally persists;
    # the classic extraction/source-unit failures jump and then return near the old scale.
    for code, series in by_company.items():
        series.sort(key=lambda r: r.get("periodEnd") or "")
        for index in range(1, len(series) - 1):
            previous, current, following = series[index - 1:index + 2]
            for metric in STABLE_METRICS:
                if current.get("sectorModel") == "financial" and metric == "revenue":
                    continue
                a = previous.get("metrics", {}).get(metric)
                b = current.get("metrics", {}).get(metric)
                c = following.get("metrics", {}).get(metric)
                before_factor = factor(a, b)
                after_factor = factor(b, c)
                neighbour_factor = factor(a, c)
                if (
                    before_factor >= ROUND_TRIP_FACTOR_LIMIT
                    and after_factor >= ROUND_TRIP_FACTOR_LIMIT
                    and neighbour_factor <= 5
                ):
                    key = (code, current.get("periodEnd"), metric)
                    candidate = (a, b, c)
                    checks += 1
                    if KNOWN_ROUND_TRIPS.get(key) == candidate:
                        continue
                    failures.append(
                        f"{code} {current.get('periodEnd')} {metric}: unreviewed one-year 10x round-trip "
                        f"{a} -> {b} -> {c}; factors={before_factor:.1f}x/{after_factor:.1f}x "
                        f"neighbours={neighbour_factor:.1f}x threshold={ROUND_TRIP_FACTOR_LIMIT:.1f}x"
                    )

    # Latest count metrics are more sensitive to unit/context defects. Any >=5x
    # change must be backed by the filing presentation itself; the daily validator
    # downloads the XBRL archive for these candidates before this audit runs.
    from datetime import date
    for code, series in by_company.items():
        series.sort(key=lambda r: r.get("periodEnd") or "")
        if len(series) < 2:
            continue
        previous, current = series[-2], series[-1]
        try:
            gap_days = (date.fromisoformat(current["periodEnd"]) - date.fromisoformat(previous["periodEnd"])).days
        except (TypeError, ValueError):
            gap_days = 99999
        if gap_days > 550:
            continue
        for metric in COUNT_METRICS:
            before = previous.get("metrics", {}).get(metric)
            value = current.get("metrics", {}).get(metric)
            if factor(before, value) < COUNT_FACTOR_LIMIT:
                continue
            checks += 1
            source = current.get("metricSources", {}).get(metric)
            xbrl = RAW / "xbrl" / f"{current.get('docID')}.zip"
            if not source or not xbrl.exists():
                failures.append(
                    f"{code} {current.get('periodEnd')} {metric}: >=5x latest change lacks source/XBRL verification"
                )
                continue
            recovered, _ = recover_count_metric(xbrl, metric, source)
            if recovered is None:
                failures.append(
                    f"{code} {current.get('periodEnd')} {metric}: >=5x latest presentation value unavailable"
                )
                continue
            if recovered != value and (current.get("docID"), metric) not in CORRECTIONS:
                failures.append(
                    f"{code} {current.get('periodEnd')} {metric}: >=5x latest presentation={recovered} normalized={value}"
                )

    # Latest-year non-count values have no following filing yet. Treat any >=10x
    # change as review-required. Current reviewed source-exact pairs are pinned;
    # any new pair fails the release audit until manually verified.
    for code, series in by_company.items():
        series.sort(key=lambda r: r.get("periodEnd") or "")
        if len(series) < 2:
            continue
        previous, current = series[-2], series[-1]
        try:
            gap_days = (date.fromisoformat(current["periodEnd"]) - date.fromisoformat(previous["periodEnd"])).days
        except (TypeError, ValueError):
            gap_days = 99999
        if gap_days > 550:
            continue
        for metric in STABLE_METRICS:
            if metric in COUNT_METRICS:
                continue
            if current.get("sectorModel") == "financial" and metric == "revenue":
                continue
            a = previous.get("metrics", {}).get(metric)
            b = current.get("metrics", {}).get(metric)
            if factor(a, b) < ROUND_TRIP_FACTOR_LIMIT:
                continue
            key = (code, current.get("periodEnd"), metric)
            candidate = (a, b)
            checks += 1
            if KNOWN_LATEST_10X.get(key) == candidate:
                continue
            failures.append(
                f"{code} {current.get('periodEnd')} {metric}: unreviewed latest >=10x change "
                f"{a} -> {b}; factor={factor(a,b):.1f}x threshold={ROUND_TRIP_FACTOR_LIMIT:.1f}x"
            )

    print(
        f"listed normalized audit: {checks} checks, {len(failures)} failures, "
        f"{len(KNOWN_ROUND_TRIPS)} reviewed 10x round-trips, "
        f"{sum(1 for key in KNOWN_LATEST_10X if key[2] not in COUNT_METRICS)} reviewed latest non-count 10x changes"
    )
    for warning in outlier_warnings[:100]:
        print("WARN", warning)
    if len(outlier_warnings) > 100:
        print(f"... and {len(outlier_warnings) - 100} more warnings")
    for failure in failures[:100]:
        print("FAIL", failure)
    if len(failures) > 100:
        print(f"... and {len(failures) - 100} more failures")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
