#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import date

ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "public" / "data" / "retail-prices-city-monthly.json"


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
    if len(months) < 12 or months != sorted(set(months)):
        fail(f"invalid month series: {len(months)}")
    for a, b in zip(months, months[1:]):
        if next_month(a) != b:
            fail(f"month gap: {a} -> {b}")
    if data.get("latestMonth") != months[-1]:
        fail("latestMonth does not match final month")
    codes = [str(c.get("code", "")) for c in cities]
    if len(codes) < 80 or len(codes) != len(set(codes)):
        fail(f"invalid city codes: {len(codes)} / {len(set(codes))}")
    if data.get("cityCount") != len(cities):
        fail("cityCount mismatch")
    if len(items) < 10:
        fail(f"too few curated items: {len(items)}")

    checked = 0
    for item in items:
        code = item["code"]
        series_by_city = values.get(code, {})
        latest_count = 0
        monthly_coverage = [0] * len(months)
        for city, series in series_by_city.items():
            if city not in set(codes):
                fail(f"unknown city {city} in item {code}")
            if len(series) != len(months):
                fail(f"series length mismatch: {code}/{city}")
            for i, value in enumerate(series):
                if value is None:
                    continue
                if not isinstance(value, (int, float)) or value < 0:
                    fail(f"invalid price {code}/{city}/{months[i]}={value}")
                monthly_coverage[i] += 1
                checked += 1
            if series[-1] is not None:
                latest_count += 1
        if latest_count != item.get("latestCoverage"):
            fail(f"latest coverage mismatch for {code}: {latest_count}")
        if latest_count < 40:
            fail(f"latest coverage too low for {code}: {latest_count}")
        if min(monthly_coverage) < 40:
            fail(f"historical coverage too low for {code}: {min(monthly_coverage)}")

    print(
        f"retail prices city: OK / {len(months)} months / "
        f"{len(cities)} cities / {len(items)} items / {checked} values"
    )


if __name__ == "__main__":
    main()
