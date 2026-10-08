#!/usr/bin/env python3
from __future__ import annotations

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public" / "data"
errors: list[str] = []
checks = 0


def load(name: str):
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def check(condition: bool, message: str) -> None:
    global checks
    checks += 1
    if not condition:
        errors.append(message)


def prefectures(rows):
    return {r.get("prefecture") for r in rows}


CANONICAL_PREFS = prefectures(load("economy-prices.json")["records"])
check(len(CANONICAL_PREFS) == 47, "canonical prefecture set is not 47")

# Crime prefecture layer.
crime = load("crime-prefecture-2025.json")
check(crime.get("year") == 2025, "crime: year mismatch")
check(prefectures(crime.get("records", [])) == CANONICAL_PREFS, "crime: prefecture coverage mismatch")
for row in crime.get("records", []):
    label = f"crime {row.get('prefecture')}"
    check(row.get("count", 0) >= 0, f"{label}: negative count")
    check(row.get("population", 0) > 0, f"{label}: nonpositive population")
    if row.get("population"):
        expected = row["count"] / row["population"] * 1000
        check(abs(expected - row.get("ratePer1000", -999)) <= 0.011, f"{label}: rate mismatch")
    check(122 <= float(row.get("lon", 0)) <= 154 and 20 <= float(row.get("lat", 0)) <= 46, f"{label}: coordinate out of range")

# Traffic accident grid.
accidents = load("traffic-accidents-2024.json")
check(accidents.get("year") == 2024, "traffic accidents: year mismatch")
check(accidents.get("fields") == ["lon", "lat", "accidents", "deaths", "injuries"], "traffic accidents: schema mismatch")
check(len(accidents.get("records", [])) > 40000, "traffic accidents: unexpectedly few grid cells")
for row in accidents.get("records", []):
    check(len(row) == 5, "traffic accidents: row width mismatch")
    if len(row) != 5:
        continue
    lon, lat, count, deaths, injuries = row
    check(122 <= float(lon) <= 154 and 20 <= float(lat) <= 46, f"traffic accidents: coordinate out of range {row[:2]}")
    check(count >= 1 and deaths >= 0 and injuries >= 0, f"traffic accidents: invalid counts {row}")
    check(deaths + injuries >= count, f"traffic accidents: casualties below accident count {row}")

# Public facility point layers.
poi_specs = {
    "poi-hospitals-2020.json": (["lon", "lat", "name", "address", "beds"], 8000),
    "poi-schools-2023.json": (["lon", "lat", "name", "type", "address"], 27000),
    "poi-stations-2025.json": (["lon", "lat", "name", "line", "operator"], 9500),
}
for filename, (fields, minimum) in poi_specs.items():
    payload = load(filename)
    rows = payload.get("records", [])
    check(payload.get("fields") == fields, f"{filename}: field schema mismatch")
    check(len(rows) >= minimum, f"{filename}: unexpectedly few records {len(rows)}")
    seen = set()
    for row in rows:
        check(len(row) == len(fields), f"{filename}: row width mismatch")
        if len(row) != len(fields):
            continue
        check(122 <= float(row[0]) <= 154 and 20 <= float(row[1]) <= 46, f"{filename}: coordinate out of range {row[:2]}")
        check(all(isinstance(x, str) and x.strip() for x in row[2:-1]), f"{filename}: blank text field {row[:5]}")
        if filename == "poi-hospitals-2020.json":
            check(isinstance(row[4], (int, float)) and row[4] > 0, f"{filename}: invalid beds {row}")
        else:
            check(isinstance(row[-1], str) and row[-1].strip(), f"{filename}: blank final text field {row}")
        key = tuple(row)
        check(key not in seen, f"{filename}: exact duplicate row {row}")
        seen.add(key)

# Every municipality must be mappable after land-publication, land-survey and school fallbacks.
municipality = load("municipality-stats-2026.json")
for row in municipality.get("records", []):
    code = row.get("code")
    check(row.get("lon") is not None and row.get("lat") is not None, f"municipality {code}: missing coordinates")
    if row.get("lon") is not None and row.get("lat") is not None:
        check(122 <= float(row["lon"]) <= 154 and 20 <= float(row["lat"]) <= 46, f"municipality {code}: coordinate out of range")
    for key, value in row.items():
        if key not in {"elderlyRate", "foreignRate", "singleHouseholdRate"}:
            check(value is not None, f"municipality {code}: unexpected null {key}")
    check((row.get("population", 0) > 0) == (row.get("elderlyRate") is not None), f"municipality {code}: elderly rate nullability mismatch")
    check((row.get("population", 0) > 0) == (row.get("foreignRate") is not None), f"municipality {code}: foreign rate nullability mismatch")
    check((row.get("households", 0) > 0) == (row.get("singleHouseholdRate") is not None), f"municipality {code}: household rate nullability mismatch")

# Energy annual household table has one source-native gap: 2025 table 7-1 omits Otsu.
energy = load("energy.json")
annual_fields = [
    "annualUtilityWaterYen", "annualEnergyYen", "annualElectricityYen", "annualGasYen",
    "annualCityGasYen", "annualPropaneYen", "annualOtherHeatYen", "annualKeroseneYen", "annualWaterYen",
]
annual_missing = {
    row["prefecture"]: tuple(key for key in annual_fields if row.get(key) is None)
    for row in energy.get("records", []) if any(row.get(key) is None for key in annual_fields)
}
check(annual_missing == {"滋賀県": tuple(annual_fields)}, f"energy: unexpected annual source gaps {annual_missing}")
for row in energy.get("records", []):
    check(row.get("monthlyConsumptionYen") is not None, f"energy {row.get('prefecture')}: monthly consumption missing")
    check(row.get("monthlyUtilityWaterYen") is not None, f"energy {row.get('prefecture')}: monthly utility missing")

# Current employment/business/regional nested structures must be complete, not merely top-level 47-row shells.
employment = load("employment-economy-2026.json")
expected_age_bands = employment.get("ageBands", [])
for row in employment.get("records", []):
    age_rows = row.get("ageWages", [])
    check(len(age_rows) == 12, f"employment {row.get('prefecture')}: expected 12 age bands")
    check([x.get("ageBand") for x in age_rows] == expected_age_bands, f"employment {row.get('prefecture')}: age-band order/content mismatch")
    check(all(all(value is not None for value in x.values()) for x in age_rows), f"employment {row.get('prefecture')}: null age-wage field")
    trend = row.get("jobTrend", [])
    check(len(trend) == 12, f"employment {row.get('prefecture')}: expected 12 job-trend years")
    check(all(all(value is not None for value in x.values()) for x in trend), f"employment {row.get('prefecture')}: null job-trend field")

business_current = load("business-industry-2026.json")
for row in business_current.get("records", []):
    check(len(row.get("industries", [])) == 7, f"business {row.get('prefecture')}: expected 7 industries")
    check(all(all(value is not None for value in x.values()) for x in row.get("industries", [])), f"business {row.get('prefecture')}: null industry field")

regional_current = load("regional-trends-2026.json")
check(len(regional_current.get("records", [])) == 47 * len(regional_current.get("years", [])), "regional current: grid size mismatch")
for row in regional_current.get("records", []):
    check(all(value is not None for value in row.values()), f"regional {row.get('prefecture')} {row.get('year')}: null field")

# Wage history: full 47 x 25 grid and formula consistency.
wage = load("employment-wage-history.json")
check(wage.get("years") == list(range(2001, 2026)), "wage history: year coverage mismatch")
check(prefectures(wage.get("records", [])) == CANONICAL_PREFS, "wage history: prefecture coverage mismatch")
for row in wage.get("records", []):
    values = row.get("values", [])
    check([v[0] for v in values] == wage["years"], f"wage history {row.get('prefecture')}: year rows mismatch")
    for value in values:
        check(len(value) == 9 and all(x is not None for x in value), f"wage history {row.get('prefecture')}: missing/width mismatch {value}")
        if len(value) != 9 or any(x is None for x in value):
            continue
        year, monthly, scheduled, bonus, annual, age, tenure, hours, overtime = value
        check(abs(monthly * 12 + bonus - annual) <= 0.11, f"wage history {row.get('prefecture')} {year}: annual formula mismatch")
        check(0 < scheduled <= monthly < 1000, f"wage history {row.get('prefecture')} {year}: salary range mismatch")
        check(15 <= age <= 80 and 0 <= tenure <= 60, f"wage history {row.get('prefecture')} {year}: workforce range mismatch")
        check(0 < hours <= 250 and 0 <= overtime <= 100, f"wage history {row.get('prefecture')} {year}: hours range mismatch")

# Migration history: the official long-term series starts Okinawa at the 1972 reversion.
migration = load("regional-migration-history.json")
check(migration.get("years") == list(range(1954, 2026)), "migration history: year coverage mismatch")
check(prefectures(migration.get("records", [])) == CANONICAL_PREFS, "migration history: prefecture coverage mismatch")
expected_missing = {("沖縄県", year) for year in range(1954, 1973)}
actual_missing = set()
for row in migration.get("records", []):
    values = row.get("values", [])
    check([v[0] for v in values] == migration["years"], f"migration {row.get('prefecture')}: year rows mismatch")
    for value in values:
        check(len(value) == 4, f"migration {row.get('prefecture')}: row width mismatch {value}")
        if len(value) != 4:
            continue
        year, incoming, outgoing, net = value
        if incoming is None or outgoing is None or net is None:
            actual_missing.add((row["prefecture"], year))
            check(incoming is None and outgoing is None and net is None, f"migration {row.get('prefecture')} {year}: partial missing row")
            continue
        check(incoming >= 0 and outgoing >= 0, f"migration {row.get('prefecture')} {year}: negative movement")
        check(incoming - outgoing == net, f"migration {row.get('prefecture')} {year}: net mismatch")
check(actual_missing == expected_missing, f"migration history: unexpected missing cells {sorted(actual_missing ^ expected_missing)[:20]}")

# Business-industry history: two census snapshots with complete prefecture coverage.
business = load("business-industry-history.json")
check(business.get("years") == [2016, 2021], "business history: year coverage mismatch")
for snapshot in business.get("snapshots", []):
    rows = snapshot.get("records", [])
    check(prefectures(rows) == CANONICAL_PREFS, f"business history {snapshot.get('year')}: prefecture coverage mismatch")
    for row in rows:
        check(row.get("establishments", 0) > 0 and row.get("employees", 0) > 0, f"business history {snapshot.get('year')} {row.get('prefecture')}: invalid totals")
        for key, item in row.get("industries", {}).items():
            check(item.get("establishments", -1) >= 0 and item.get("employees", -1) >= 0, f"business history {snapshot.get('year')} {row.get('prefecture')} {key}: negative values")
            check(item.get("establishments", 0) <= row["establishments"], f"business history {snapshot.get('year')} {row.get('prefecture')} {key}: establishments exceed total")
            check(item.get("employees", 0) <= row["employees"], f"business history {snapshot.get('year')} {row.get('prefecture')} {key}: employees exceed total")

# Land-price history: national counts must equal prefecture sums for every source/year.
land_history = load("land-price-history.json")
check(land_history.get("years") == list(range(2020, 2027)), "land history: year coverage mismatch")
for series_name, series in land_history.get("series", {}).items():
    check([entry.get("year") for entry in series] == land_history["years"], f"land history {series_name}: year rows mismatch")
    for entry in series:
        rows = entry.get("prefectures", [])
        check(prefectures(rows) == CANONICAL_PREFS, f"land history {series_name} {entry.get('year')}: prefecture coverage mismatch")
        check(entry.get("count") == sum(row.get("count", 0) for row in rows), f"land history {series_name} {entry.get('year')}: count total mismatch")
        check(entry.get("medianPrice", 0) > 0 and entry.get("averagePrice", 0) > 0, f"land history {series_name} {entry.get('year')}: invalid national price")
        for row in rows:
            check(row.get("count", 0) > 0, f"land history {series_name} {entry.get('year')} {row.get('prefecture')}: zero count")
            check(row.get("medianPrice", 0) > 0 and row.get("averagePrice", 0) > 0, f"land history {series_name} {entry.get('year')} {row.get('prefecture')}: invalid price")

# Latest history aggregates must match the current point datasets exactly on count.
current_land = load("land-prices-2026.json")
current_survey = load("land-survey-2026.json")
latest_land = land_history["series"]["landPrice"][-1]
latest_survey = land_history["series"]["landSurvey"][-1]
check(latest_land.get("count") == len(current_land.get("records", [])), "land history: latest land-price count differs from current dataset")
check(latest_survey.get("count") == len(current_survey.get("records", [])), "land history: latest land-survey count differs from current dataset")

print(f"living/history audit: {checks} checks, {len(errors)} failures")
for error in errors[:100]:
    print("FAIL", error)
if len(errors) > 100:
    print(f"... and {len(errors) - 100} more")
raise SystemExit(1 if errors else 0)
