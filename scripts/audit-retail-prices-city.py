#!/usr/bin/env python3
"""Check continuity, unit provenance, coverage and a source-workbook anchor."""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "public/data/retail-prices-city-monthly.json"

def next_month(ym):
    y, m = map(int, ym.split("-"))
    return f"{y + (m == 12):04d}-{1 if m == 12 else m + 1:02d}"

def fail(message):
    raise ValueError(f"retail price audit failed: {message}")

def main():
    data = json.loads(PATH.read_text(encoding="utf-8"))
    months = data.get("months", [])
    cities = data.get("cities", [])
    items = data.get("items", [])
    values = data.get("values", {})
    if data.get("schemaVersion") != 2 or not months or months[0] != "2000-01":
        fail("expected historical schema and 2000-01 opening month")
    if len(months) < 320 or months != sorted(set(months)):
        fail(f"invalid month series: {len(months)}")
    for a, b in zip(months, months[1:]):
        if next_month(a) != b:
            fail(f"month gap: {a} -> {b}")
    if data.get("latestMonth") != months[-1]:
        fail("latestMonth does not match final month")
    if data.get("historicalMonthCount") != 296:  # 2000-01 through 2024-08
        fail("historical month count differs from source interval")
    codes = [str(c.get("code", "")) for c in cities]
    code_set = set(codes)
    if len(codes) < 80 or len(codes) != len(code_set):
        fail(f"invalid city codes: {len(codes)} / {len(code_set)}")
    if data.get("cityCount") != len(cities) or len(items) != 13:
        fail("cityCount or curated item count mismatch")
    conversion = data.get("unitConversions", {})
    incompatible = data.get("incompatibleHistoricalUnits", {})
    checked = 0
    idx = {month: i for i, month in enumerate(months)}
    for item in items:
        code = item["code"]
        series_by_city = values.get(code, {})
        monthly_coverage = [0] * len(months)
        for city, series in series_by_city.items():
            if city not in code_set or len(series) != len(months):
                fail(f"invalid city/series length: {code}/{city}")
            for i, value in enumerate(series):
                if value is None:
                    continue
                if not isinstance(value, (int, float)) or value < 0:
                    fail(f"invalid price {code}/{city}/{months[i]}={value}")
                monthly_coverage[i] += 1
                checked += 1
        if code == "1001" and min(monthly_coverage) < 40:
            fail(f"rice has a monthly food-table gap: {min(monthly_coverage)}")
        latest_count = monthly_coverage[-1]
        if latest_count != item.get("latestCoverage") or latest_count < 40:
            fail(f"latest coverage mismatch or too low for {code}: {latest_count}")
        if sum(n >= 40 for n in monthly_coverage) < 20:
            fail(f"too few historical months with comparable prices for {code}")
        for ym in conversion.get(code, {}):
            if ym not in idx or monthly_coverage[idx[ym]] < 40:
                fail(f"conversion metadata without prices: {code}/{ym}")
        for ym in incompatible.get(code, {}):
            if ym not in idx or monthly_coverage[idx[ym]]:
                fail(f"incompatible unit month has published prices: {code}/{ym}")

    # 2000-01 source workbook has Tokyo rice 5,922 yen / 10 kg;
    # published 5 kg equivalent must be 2,961 yen with provenance.
    if values["1001"]["13100"][0] != 2961:
        fail("2000-01 Tokyo rice workbook anchor / 5kg conversion")
    if "2000-01" not in conversion["1001"]:
        fail("missing 2000-01 rice conversion provenance")
    if "2000-01" not in incompatible["1341"] or values.get("1341", {}).get("13100", [None])[0] is not None:
        fail("2000 eggs 1kg must not be compared with a current 10-egg pack")
    print(f"retail prices city: OK / {len(months)} months / {len(cities)} cities / {len(items)} items / {checked} values")

if __name__ == "__main__":
    main()
