#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "data/raw/listed-companies/normalized/financials.json"
METRICS = (
    "revenue", "operatingIncome", "ordinaryIncome", "netIncome",
    "assets", "liabilities", "equity", "cash",
    "operatingCashFlow", "investingCashFlow", "financingCashFlow",
    "employees", "averageSalary", "averageAge", "averageTenure",
    "roe", "equityRatio",
)


def pct(value: int, total: int) -> float:
    return round(value / total * 100, 2) if total else 0.0


def main() -> int:
    if not SOURCE.exists():
        print("listed coverage: normalized data missing")
        return 2
    payload = json.loads(SOURCE.read_text(encoding="utf-8"))
    records = payload.get("records", [])
    total = len(records)
    companies = {r.get("securityCode") for r in records if r.get("securityCode")}
    source_formats = Counter(r.get("sourceFormat") or "unknown" for r in records)
    standards = Counter(r.get("accountingStandard") or "unknown" for r in records)
    by_year = Counter((r.get("periodEnd") or "")[:4] or "unknown" for r in records)
    metric_counts = {
        metric: sum(1 for r in records if r.get("metrics", {}).get(metric) is not None)
        for metric in METRICS
    }
    company_years: dict[str, int] = defaultdict(int)
    for record in records:
        if record.get("securityCode"):
            company_years[record["securityCode"]] += 1
    report = {
        "records": total,
        "companies": len(companies),
        "sourceFormats": dict(source_formats),
        "accountingStandards": dict(standards),
        "recordsByYear": dict(sorted(by_year.items())),
        "metricCoverage": {
            metric: {"count": count, "pct": pct(count, total)}
            for metric, count in metric_counts.items()
        },
        "companiesWith10Years": sum(1 for years in company_years.values() if years >= 10),
        "maxYears": max(company_years.values(), default=0),
    }
    out = SOURCE.parent / "coverage-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(
        f"listed coverage: records={total} companies={len(companies)} "
        f"10y={report['companiesWith10Years']} maxYears={report['maxYears']}"
    )
    print("source formats", dict(source_formats))
    for metric, info in report["metricCoverage"].items():
        print(f"{metric}: {info['count']}/{total} ({info['pct']}%)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
