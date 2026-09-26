from __future__ import annotations

import json
import shutil
from collections import defaultdict
from datetime import datetime, timezone

from .common import PUBLIC, RAW, write_json
from .collect_master import normalize_name


DETAIL_SHARDS = 64

def detail_bucket(code: str) -> str:
    value = 0
    for ch in code:
        value = (value * 31 + ord(ch)) % DETAIL_SHARDS
    return f"{value:02x}"

RANKING_METRICS = (
    "revenue", "operatingIncome", "netIncome", "operatingMargin", "cash",
    "roe", "equityRatio", "revenueGrowth", "averageSalary", "profitPerEmployee",
)


def load_json(path, default):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def percent_change(current, previous):
    if current is None or previous in (None, 0):
        return None
    return (current - previous) / abs(previous) * 100


def enrich_series(series: list[dict]) -> list[dict]:
    ordered = sorted(series, key=lambda x: x.get("periodEnd") or "")
    previous = None
    for record in ordered:
        metrics = record["metrics"]
        metrics["revenueGrowth"] = percent_change(
            metrics.get("revenue"), previous["metrics"].get("revenue") if previous else None
        )
        metrics["profitGrowth"] = percent_change(
            metrics.get("netIncome"), previous["metrics"].get("netIncome") if previous else None
        )
        employees = metrics.get("employees")
        metrics["profitPerEmployee"] = (
            metrics.get("netIncome") / employees
            if metrics.get("netIncome") is not None and employees not in (None, 0)
            else None
        )
        previous = record
    return ordered




def compact_history_record(record: dict) -> dict:
    return {
        "docID": record.get("docID"),
        "periodEnd": record.get("periodEnd"),
        "sourceFormat": record.get("sourceFormat"),
        "accountingStandard": record.get("accountingStandard"),
        "sectorModel": record.get("sectorModel"),
        "metrics": record.get("metrics", {}),
    }


def compact_latest_record(record: dict | None) -> dict | None:
    if not record:
        return None
    return {
        "docID": record.get("docID"),
        "periodStart": record.get("periodStart"),
        "periodEnd": record.get("periodEnd"),
        "submitDateTime": record.get("submitDateTime"),
        "sourceFormat": record.get("sourceFormat"),
        "accountingStandard": record.get("accountingStandard"),
        "sectorModel": record.get("sectorModel"),
        "metrics": record.get("metrics", {}),
        "segments": record.get("segments", []),
        "majorShareholders": record.get("majorShareholders", []),
    }

def main() -> None:
    master = load_json(PUBLIC / "master.json", {"records": [], "counts": {}})
    financials = load_json(RAW / "normalized" / "financials.json", {"records": []})
    name_lookup: dict[str, list[dict]] = defaultdict(list)
    for item in master.get("records", []):
        key = normalize_name(item.get("name", ""))
        if key:
            name_lookup[key].append(item)
    by_company: dict[str, list[dict]] = defaultdict(list)
    for record in financials.get("records", []):
        by_company[record["securityCode"]].append(record)
    legacy_company_dir = PUBLIC / "companies"
    if legacy_company_dir.exists():
        shutil.rmtree(legacy_company_dir)
    detail_dir = PUBLIC / "details"
    if detail_dir.exists():
        shutil.rmtree(detail_dir)
    detail_dir.mkdir(parents=True, exist_ok=True)
    detail_shards: dict[str, dict[str, dict]] = defaultdict(dict)
    index_records = []
    latest_rows = []
    for company in master.get("records", []):
        code = company["securityCode"]
        series = enrich_series(by_company.get(code, []))
        for record in series:
            for holder in record.get("majorShareholders", []):
                matches = name_lookup.get(normalize_name(holder.get("name", "")), [])
                if len(matches) == 1 and matches[0].get("securityCode") != code:
                    holder["listedSecurityCode"] = matches[0]["securityCode"]
                    holder["listedCompanyName"] = matches[0]["name"]
        latest = series[-1] if series else None
        payload = {
            "company": company,
            "financials": [compact_history_record(record) for record in series],
            "latest": compact_latest_record(latest),
            "coverage": {
                "years": len(series),
                "firstPeriodEnd": series[0].get("periodEnd") if series else None,
                "lastPeriodEnd": series[-1].get("periodEnd") if series else None,
            },
        }
        detail_shards[detail_bucket(code)][code] = payload
        latest_metrics = (latest or {}).get("metrics", {})
        compact = {
            "securityCode": code,
            "name": company["name"],
            "market": company["market"],
            "industry33": company.get("industry33"),
            "hasFinancials": bool(series),
        }
        if latest:
            compact["latestPeriodEnd"] = latest.get("periodEnd")
            for metric in (
                "revenue", "ordinaryRevenue", "insuranceRevenue",
                "operatingIncome", "ordinaryIncome", "profitBeforeTax", "operatingMargin",
                "netIncome", "roe", "equityRatio", "assets", "liabilities", "cash",
                "operatingCashFlow", "freeCashFlow", "averageSalary", "employees", "revenueGrowth",
            ):
                value = latest_metrics.get(metric)
                if value is not None:
                    compact[metric] = value
        index_records.append(compact)
        if latest:
            latest_rows.append({"company": company, "record": latest})
    for bucket in (f"{i:02x}" for i in range(DETAIL_SHARDS)):
        write_json(detail_dir / f"{bucket}.json", {"v": 1, "c": detail_shards.get(bucket, {})})

    rankings = {}
    for metric in RANKING_METRICS:
        rows = []
        for item in latest_rows:
            value = item["record"]["metrics"].get(metric)
            if value is None:
                continue
            company = item["company"]
            if company.get("industry33") in {"銀行業", "保険業", "証券、商品先物取引業", "その他金融業"}:
                if metric in {"revenue", "operatingIncome", "operatingMargin"}:
                    continue
            rows.append({
                "securityCode": company["securityCode"],
                "name": company["name"],
                "market": company["market"],
                "industry33": company.get("industry33"),
                "periodEnd": item["record"].get("periodEnd"),
                "value": value,
            })
        rankings[metric] = sorted(rows, key=lambda x: x["value"], reverse=True)[:100]

    generated_at = datetime.now(timezone.utc).isoformat()
    write_json(PUBLIC / "index.json", {
        "dataset": "listed-companies-index",
        "generatedAt": generated_at,
        "sourceDate": master.get("sourceDate"),
        "records": index_records,
    })
    write_json(PUBLIC / "rankings.json", {
        "dataset": "listed-companies-rankings",
        "generatedAt": generated_at,
        "rankings": rankings,
    })
    write_json(PUBLIC / "summary.json", {
        "dataset": "listed-companies-summary",
        "generatedAt": generated_at,
        "sourceDate": master.get("sourceDate"),
        "companies": len(index_records),
        "financialCompanies": sum(1 for x in index_records if x["hasFinancials"]),
        "financialRecords": sum(len(x) for x in by_company.values()),
        "markets": master.get("counts", {}).get("byMarket", {}),
        "detailShards": DETAIL_SHARDS,
    })
    print({
        "companies": len(index_records),
        "financialCompanies": sum(1 for x in index_records if x["hasFinancials"]),
        "financialRecords": sum(len(x) for x in by_company.values()),
        "detailShards": DETAIL_SHARDS,
    })


if __name__ == "__main__":
    main()
