#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "public/data/listed-companies"
NORMALIZED = ROOT / "data/raw/listed-companies/normalized/financials.json"
errors: list[str] = []
checks = 0


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


def percent_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def expected_metrics(record: dict, previous: dict | None) -> dict:
    metrics = dict(record.get("metrics") or {})
    prior = (previous or {}).get("metrics") or {}
    metrics["revenueGrowth"] = percent_change(metrics.get("revenue"), prior.get("revenue") if previous else None)
    metrics["profitGrowth"] = percent_change(metrics.get("netIncome"), prior.get("netIncome") if previous else None)
    employees = metrics.get("employees")
    metrics["profitPerEmployee"] = (
        metrics.get("netIncome") / employees
        if metrics.get("netIncome") is not None and employees not in (None, 0)
        else None
    )
    return metrics


normalized = load(NORMALIZED).get("records", [])
by_code: dict[str, list[dict]] = defaultdict(list)
for record in normalized:
    by_code[record["securityCode"]].append(record)
for series in by_code.values():
    series.sort(key=lambda r: r.get("periodEnd") or "")

public_by_code: dict[str, dict] = {}
for path in sorted((PUBLIC / "details").glob("*.json")):
    payload = load(path)
    check(payload.get("v") == 1, f"{path.name}: invalid detail version")
    for code, company_payload in (payload.get("c") or {}).items():
        check(code not in public_by_code, f"duplicate public detail {code}")
        public_by_code[code] = company_payload

master = load(PUBLIC / "master.json").get("records", [])
master_codes = {row["securityCode"] for row in master}
check(set(public_by_code) == master_codes, "public detail/master code set mismatch")
check(set(by_code).issubset(master_codes), "normalized data contains company outside master")
for code, company_payload in public_by_code.items():
    source_series = by_code.get(code, [])
    public_series = company_payload.get("financials") or []
    check(len(public_series) == len(source_series), f"{code}: public/normalized history length mismatch")
    previous = None
    for index, source in enumerate(source_series):
        if index >= len(public_series):
            break
        published = public_series[index]
        label = f"{code} {source.get('periodEnd')}"
        for field in ("docID", "periodEnd", "sourceFormat", "accountingStandard", "sectorModel"):
            check(published.get(field) == source.get(field), f"{label}: public {field} differs from normalized")
        expected = expected_metrics(source, previous)
        check(published.get("metrics") == expected, f"{label}: public metrics differ from normalized/derived values")
        previous = source

    latest = company_payload.get("latest")
    if not source_series:
        check(latest is None, f"{code}: latest exists without normalized financials")
        continue
    source_latest = source_series[-1]
    expected_latest = expected_metrics(source_latest, source_series[-2] if len(source_series) > 1 else None)
    check(latest is not None, f"{code}: latest missing")
    if latest is None:
        continue
    for field in ("docID", "periodStart", "periodEnd", "submitDateTime", "sourceFormat", "accountingStandard", "sectorModel"):
        check(latest.get(field) == source_latest.get(field), f"{code}: latest {field} differs from normalized")
    check(latest.get("metrics") == expected_latest, f"{code}: latest metrics differ from normalized/derived values")
    check(latest.get("segments") == (source_latest.get("segments") or []), f"{code}: latest segments differ from normalized")
    source_holders = [
        {key: holder.get(key) for key in ("rank", "name", "shares", "shareholdingRatio")}
        for holder in (source_latest.get("majorShareholders") or [])
    ]
    public_holders = [
        {key: holder.get(key) for key in ("rank", "name", "shares", "shareholdingRatio")}
        for holder in (latest.get("majorShareholders") or [])
    ]
    check(public_holders == source_holders, f"{code}: latest major shareholders differ from normalized")

index_rows = load(PUBLIC / "index.json").get("records", [])
index_by_code = {row["securityCode"]: row for row in index_rows}
check(set(index_by_code) == master_codes, "listed index/master code set mismatch")
index_metrics = (
    "revenue", "ordinaryRevenue", "insuranceRevenue", "operatingIncome", "ordinaryIncome",
    "profitBeforeTax", "operatingMargin", "netIncome", "roe", "equityRatio", "assets",
    "liabilities", "cash", "operatingCashFlow", "freeCashFlow", "averageSalary", "employees",
    "revenueGrowth",
)
for code, row in index_by_code.items():
    series = by_code.get(code, [])
    check(row.get("hasFinancials") == bool(series), f"{code}: index hasFinancials mismatch")
    if not series:
        continue
    expected = expected_metrics(series[-1], series[-2] if len(series) > 1 else None)
    check(row.get("latestPeriodEnd") == series[-1].get("periodEnd"), f"{code}: index latest period mismatch")
    for metric in index_metrics:
        if expected.get(metric) is None:
            check(metric not in row, f"{code}: index unexpectedly publishes null metric {metric}")
        else:
            check(row.get(metric) == expected.get(metric), f"{code}: index {metric} differs from normalized")
summary = load(PUBLIC / "summary.json")
check(summary.get("financialCompanies") == len(by_code), "listed summary financialCompanies differs from normalized")
check(summary.get("financialRecords") == len(normalized), "listed summary financialRecords differs from normalized")

print(f"listed public audit: {checks} checks, {len(errors)} failures")
for error in errors[:100]:
    print("FAIL", error)
if len(errors) > 100:
    print(f"... and {len(errors) - 100} more")
raise SystemExit(1 if errors else 0)
