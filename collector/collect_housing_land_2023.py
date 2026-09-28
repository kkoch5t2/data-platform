#!/usr/bin/env python3
import io, json, math, re, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.canonical_metrics import assert_can_publish
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.canonical_metrics import assert_can_publish
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "public/data/municipality-stats-2026.json"
OUT = ROOT / "public/data/housing-land-2023.json"
RAW = ROOT / "data/raw/housing-land-2023"
RAW.mkdir(parents=True, exist_ok=True)
SOURCE_ID = "estat_housing_land_2023"
SOURCE_PAGE = "https://www.e-stat.go.jp/stat-search/files?cycle=0&tclass=000001207743"
UA = {"User-Agent": "Mozilla/5.0 DATLUME/1.0 (+https://datlume.com/)"}
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
TABLES = {
    "housing": {"number": "1-2", "statInfId": "000040209842"},
    "ownership_age": {"number": "5-3", "statInfId": "000040209851"},
    "housing_form": {"number": "10-4", "statInfId": "000040209867"},
}
METRICS = {
    "totalHousing": "municipality.housing.total_housing",
    "vacantHouses": "municipality.housing.vacant_houses",
    "vacantHouseRate": "municipality.housing.vacant_house_rate",
    "otherVacantHouses": "municipality.housing.other_vacant_houses",
    "otherVacancyRate": "municipality.housing.other_vacant_house_rate",
    "rentalVacantHouses": "municipality.housing.rental_vacant_houses",
    "forSaleVacantHouses": "municipality.housing.for_sale_vacant_houses",
    "secondaryHousing": "municipality.housing.secondary_housing",
    "ownerOccupiedRate": "municipality.housing.owner_occupied_rate",
    "detachedRate": "municipality.housing.detached_house_rate",
    "apartmentRate": "municipality.housing.apartment_rate",
    "averageFloorArea": "municipality.housing.average_floor_area",
    "pre1981Share": "municipality.housing.pre_1981_share",
}


def fetch_table(info):
    url = f"https://www.e-stat.go.jp/stat-search/file-download?fileKind=0&statInfId={info['statInfId']}"
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=120) as response:
        raw = response.read()
    path = RAW / f"table-{info['number']}-{info['statInfId']}.xlsx"
    path.write_bytes(raw)
    return url, raw


def xlsx_rows(raw):
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            root = ET.fromstring(z.read("xl/sharedStrings.xml"))
            shared = ["".join(t.text or "" for t in item.iter(NS + "t")) for item in root]
        sheet = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
    rows = []
    for row in sheet.findall(".//" + NS + "sheetData/" + NS + "row"):
        values = {}
        for cell in row.findall(NS + "c"):
            match = re.match(r"[A-Z]+", cell.get("r", ""))
            if not match:
                continue
            value = cell.find(NS + "v")
            text = "" if value is None else (value.text or "")
            if cell.get("t") == "s" and text:
                text = shared[int(text)]
            values[match.group()] = text
        rows.append(values)
    return rows


def number(value):
    text = str(value or "").replace(",", "").strip()
    if not text or text in {"-", "…", "...", "X", "x"}:
        return None
    try:
        value = float(text)
    except ValueError:
        return None
    if not math.isfinite(value):
        return None
    return int(value) if value.is_integer() else value


def pct(value, total):
    return round(value / total * 100, 2) if value is not None and total else None


def region_code(row):
    token = str(row.get("B") or "").split("_", 1)[0]
    return token if re.fullmatch(r"\d{5}", token) else None


def indexed(rows, predicate=lambda row: True):
    out = {}
    for row in rows:
        code = region_code(row)
        if code and predicate(row):
            out[code] = row
    return out


def core_values(code, row1, age_rows, form_rows):
    total = number(row1.get("C")); occupied = number(row1.get("D")); vacant = number(row1.get("I"))
    if not total or occupied is None or vacant is None:
        raise ValueError(f"missing housing totals: {code}")
    age_total = age_rows.get("00_総数")
    old_a = age_rows.get("01_1970年以前")
    old_b = age_rows.get("02_1971～1980年")
    form_total = form_rows.get("0_総数")
    detached = form_rows.get("1_一戸建")
    apartment = form_rows.get("3_共同住宅")
    if not all((age_total, old_a, old_b, form_total, detached, apartment)):
        raise ValueError(f"missing ownership/form rows: {code}")
    owner = number(age_total.get("E"))
    pre1981 = (number(old_a.get("D")) or 0) + (number(old_b.get("D")) or 0)
    detached_count = number(detached.get("F")); apartment_count = number(apartment.get("F"))
    return {
        "totalHousing": total,
        "occupiedHousing": occupied,
        "vacantHouses": vacant,
        "vacantHouseRate": pct(vacant, total),
        "otherVacantHouses": number(row1.get("J")),
        "otherVacancyRate": pct(number(row1.get("J")), total),
        "rentalVacantHouses": number(row1.get("K")),
        "forSaleVacantHouses": number(row1.get("L")),
        "secondaryHousing": number(row1.get("M")),
        "ownerOccupiedHouses": owner,
        "ownerOccupiedRate": pct(owner, occupied),
        "detachedHouses": detached_count,
        "detachedRate": pct(detached_count, occupied),
        "apartmentHouses": apartment_count,
        "apartmentRate": pct(apartment_count, occupied),
        "averageFloorArea": number(form_total.get("K")),
        "pre1981Housing": pre1981,
        "pre1981Share": pct(pre1981, occupied),
    }


def main():
    base = json.loads(BASE.read_text(encoding="utf-8"))
    base_by_code = {row["code"]: row for row in base["records"]}
    if len(base_by_code) != 1741:
        raise ValueError(f"expected 1741 municipality base codes, got {len(base_by_code)}")
    downloaded, parsed = {}, {}
    for key, info in TABLES.items():
        url, raw = fetch_table(info)
        rows = xlsx_rows(raw)
        if not rows or "令和５年住宅・土地統計調査" not in rows[0].get("A", ""):
            raise ValueError(f"unexpected workbook: {key}")
        downloaded[key] = url
        parsed[key] = rows

    housing = indexed(parsed["housing"])
    age_by_code = {}
    for row in parsed["ownership_age"]:
        code = region_code(row)
        if code:
            age_by_code.setdefault(code, {})[row.get("C")] = row
    form_by_code = {}
    for row in parsed["housing_form"]:
        code = region_code(row)
        if code and row.get("C") == "0_総数" and row.get("D") == "0_総数":
            form_by_code.setdefault(code, {})[row.get("E")] = row

    eligible = sorted(set(base_by_code) & set(housing) & set(age_by_code) & set(form_by_code))
    if len(eligible) != 1059:
        raise ValueError(f"expected 1059 published municipalities, got {len(eligible)}")
    records = []
    for code in eligible:
        base_row = base_by_code[code]
        values = core_values(code, housing[code], age_by_code[code], form_by_code[code])
        records.append({
            "code": code,
            "prefecture": base_row["prefecture"],
            "municipality": base_row["municipality"],
            "lon": base_row.get("lon"),
            "lat": base_row.get("lat"),
            **values,
        })

    national = core_values("00000", housing["00000"], age_by_code["00000"], form_by_code["00000"])
    for field, metric_id in METRICS.items():
        assert_can_publish(metric_id, SOURCE_ID, OUT.name, field)
    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "総務省統計局 令和5年住宅・土地統計調査 住宅及び世帯に関する基本集計",
        "sourceUrl": SOURCE_PAGE,
        "surveyDate": "2023-10-01",
        "publishedDate": "2024-09-25",
        "coverageNote": "市、区及び人口1万5千人以上の町村など、原表で結果が公表される自治体を収録。DATLUMEの1,741市区町村正本との一致コードは1,059自治体。",
        "tables": [{"key": key, "table": info["number"], "statInfId": info["statInfId"], "downloadUrl": downloaded[key]} for key, info in TABLES.items()],
        "municipalityCount": len(records),
        "national": national,
        "records": records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(
        "housing-land 2023:", len(records), "municipalities /",
        f"national housing {national['totalHousing']:,} /",
        f"vacancy {national['vacantHouseRate']:.2f}% /",
        f"owner {national['ownerOccupiedRate']:.2f}%"
    )
    return {
        "records": len(records),
        "municipalities": len(records),
        "year": 2023,
        "nationalHousing": national["totalHousing"],
        "nationalVacancyRate": national["vacantHouseRate"],
    }


if __name__ == "__main__":
    with SourceRun("housing_land_2023", "総務省統計局 令和5年住宅・土地統計調査（確報）") as run:
        run.set_metrics(**main())
