from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from .common import RAW

GBIZ_FINANCE_DB = RAW / "gbiz-finance.sqlite"
REVENUE_FIELDS = (
    ("netSales", "売上高"),
    ("operatingRevenue1", "営業収益"),
    ("operatingRevenue2", "営業収入"),
    ("grossOperatingRevenue", "営業総収入"),
    ("ordinaryRevenue", "経常収益"),
    ("netPremiums", "正味収入保険料"),
)
METRIC_FIELDS = (
    "netSales", "operatingRevenue1", "operatingRevenue2", "grossOperatingRevenue",
    "ordinaryRevenue", "netPremiums", "ordinaryIncomeLoss", "netIncomeLoss",
    "capitalStock", "netAssets", "totalAssets", "employees",
)


def ratio(numerator: int | None, denominator: int | None) -> float | None:
    if numerator is None or denominator in (None, 0):
        return None
    return round(numerator / denominator * 100, 2)
def primary_revenue(record: dict) -> tuple[int | None, str | None, str | None]:
    for field, label in REVENUE_FIELDS:
        value = record.get(field)
        if value is not None:
            return value, label, field
    return None, None, None


def normalize_record(row: sqlite3.Row) -> dict:
    record = {
        "periodOrder": int(row["period_order"]),
        "fiscalYear": row["fiscal_year"],
        "accountingStandard": row["accounting_standard"],
    }
    for field in METRIC_FIELDS:
        record[field] = row[field]
        record[f"{field}Unit"] = row[f"{field}_unit"]
    record["shareholders"] = json.loads(row["shareholders_json"] or "[]")
    revenue, label, field = primary_revenue(record)
    record["primaryRevenue"] = revenue
    record["primaryRevenueLabel"] = label
    record["primaryRevenueUnit"] = record.get(f"{field}Unit") if field else None
    return record


def analyze_periods(periods: list[dict]) -> dict:
    if not periods:
        return {}
    latest = periods[0]
    previous = periods[1] if len(periods) > 1 else None
    revenue_growth = None
    if previous and latest.get("primaryRevenue") is not None and (previous.get("primaryRevenue") or 0) > 0:
        revenue_growth = round((latest["primaryRevenue"] / previous["primaryRevenue"] - 1) * 100, 2)
    return {
        "primaryRevenue": latest.get("primaryRevenue"),
        "primaryRevenueLabel": latest.get("primaryRevenueLabel"),
        "primaryRevenueUnit": latest.get("primaryRevenueUnit"),
        "ordinaryIncomeLoss": latest.get("ordinaryIncomeLoss"),
        "netIncomeLoss": latest.get("netIncomeLoss"),
        "netIncomeLossUnit": latest.get("netIncomeLossUnit"),
        "capitalStock": latest.get("capitalStock"),
        "netAssets": latest.get("netAssets"),
        "netAssetsUnit": latest.get("netAssetsUnit"),
        "totalAssets": latest.get("totalAssets"),
        "totalAssetsUnit": latest.get("totalAssetsUnit"),
        "employees": latest.get("employees"),
        "revenueGrowthPct": revenue_growth,
        "netMarginPct": ratio(latest.get("netIncomeLoss"), latest.get("primaryRevenue")),
        "equityRatioPct": ratio(latest.get("netAssets"), latest.get("totalAssets")),
        "roaEndAssetsPct": ratio(latest.get("netIncomeLoss"), latest.get("totalAssets")),
    }
def load_finance_map() -> tuple[dict[str, dict], dict[str, str]]:
    if not GBIZ_FINANCE_DB.exists():
        return {}, {}
    conn = sqlite3.connect(GBIZ_FINANCE_DB)
    conn.row_factory = sqlite3.Row
    metadata = dict(conn.execute("SELECT key,value FROM metadata"))
    result: dict[str, dict] = {}
    current_number = None
    periods: list[dict] = []

    def flush() -> None:
        nonlocal current_number, periods
        if current_number is None:
            return
        result[current_number] = {
            "source": "gBizINFO",
            "sourceDate": metadata.get("sourceDate") or None,
            "sourceUrl": metadata.get("sourceUrl") or None,
            "sourceFile": metadata.get("sourceFile") or None,
            "snapshotStatus": "legacy" if "20251204" in (metadata.get("sourceFile") or "") else "current",
            "periods": periods,
            "analysis": analyze_periods(periods),
        }

    for row in conn.execute("SELECT * FROM finance_records ORDER BY corporate_number, period_order"):
        number = row["corporate_number"]
        if current_number is not None and number != current_number:
            flush()
            periods = []
        current_number = number
        periods.append(normalize_record(row))
    flush()
    conn.close()
    return result, metadata
