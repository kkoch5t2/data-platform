#!/usr/bin/env python3
import json, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "public/data/housing-land-2023.json"
BASE = ROOT / "public/data/municipality-stats-2026.json"
CATALOG = ROOT / "collector/metric_catalog.json"
RATE_FIELDS = {
    "vacantHouseRate": ("vacantHouses", "totalHousing"),
    "otherVacancyRate": ("otherVacantHouses", "totalHousing"),
    "ownerOccupiedRate": ("ownerOccupiedHouses", "occupiedHousing"),
    "detachedRate": ("detachedHouses", "occupiedHousing"),
    "apartmentRate": ("apartmentHouses", "occupiedHousing"),
    "pre1981Share": ("pre1981Housing", "occupiedHousing"),
}


def expected_rate(row, numerator, denominator):
    a, b = row.get(numerator), row.get(denominator)
    return round(a / b * 100, 2) if a is not None and b else None


def main():
    data = json.loads(DATA.read_text(encoding="utf-8"))
    base = json.loads(BASE.read_text(encoding="utf-8"))
    catalog = json.loads(CATALOG.read_text(encoding="utf-8"))
    errors, checks = [], 0
    rows = data.get("records", [])
    codes = [r.get("code") for r in rows]
    base_codes = {r["code"] for r in base["records"]}
    if len(rows) != 1059 or len(set(codes)) != 1059:
        errors.append(f"expected 1059 unique municipality rows, got {len(rows)} / {len(set(codes))}")
    if not set(codes).issubset(base_codes):
        errors.append("housing municipality codes are not a subset of canonical municipality base")
    checks += len(rows) * 2

    national = data.get("national", {})
    expected_national = {
        "totalHousing": 65046700,
        "vacantHouses": 9001600,
        "otherVacantHouses": 3856000,
        "ownerOccupiedHouses": 33875500,
        "detachedHouses": 29319400,
        "apartmentHouses": 24968200,
    }
    for field, expected in expected_national.items():
        checks += 1
        if national.get(field) != expected:
            errors.append(f"national {field}: {national.get(field)} != {expected}")

    for row in rows:
        if not row.get("prefecture") or not row.get("municipality"):
            errors.append(f"missing municipality label: {row.get('code')}")
        for field, (num, den) in RATE_FIELDS.items():
            checks += 1
            actual, expected = row.get(field), expected_rate(row, num, den)
            if actual != expected:
                errors.append(f"{row.get('code')} {field}: {actual} != {expected}")
        for field in ("vacantHouseRate", "otherVacancyRate", "ownerOccupiedRate", "detachedRate", "apartmentRate", "pre1981Share"):
            checks += 1
            value = row.get(field)
            if value is not None and not (0 <= value <= 100):
                errors.append(f"{row.get('code')} {field} out of range: {value}")

    canonical = {m["canonical"]["field"]: m["canonical"] for m in catalog.get("metrics", []) if m.get("canonical", {}).get("dataset") == DATA.name}
    public_fields = [
        "totalHousing", "vacantHouses", "vacantHouseRate", "otherVacantHouses", "otherVacancyRate",
        "rentalVacantHouses", "forSaleVacantHouses", "secondaryHousing", "ownerOccupiedRate",
        "detachedRate", "apartmentRate", "averageFloorArea", "pre1981Share",
    ]
    for field in public_fields:
        checks += 1
        target = canonical.get(field)
        if not target or target.get("source") != "estat_housing_land_2023":
            errors.append(f"canonical registry mismatch: {field}")

    if data.get("surveyDate") != "2023-10-01" or data.get("municipalityCount") != 1059:
        errors.append("survey metadata mismatch")
    checks += 2
    if errors:
        print("housing-land audit failed:\n- " + "\n- ".join(errors[:50]), file=sys.stderr)
        raise SystemExit(1)
    print(f"housing-land 2023 audit: {checks} checks / {len(rows)} municipalities / 0 failures")


if __name__ == "__main__":
    main()
