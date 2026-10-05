#!/usr/bin/env python3
"""Backfill official e-Stat monthly city retail prices from January 2000.

The older XLS layouts are different from current XLSX releases. Raw workbooks and
per-month parsed snapshots are kept outside the published site for review/resume.
"""
import argparse
import concurrent.futures
import hashlib
import html
import json
import re
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "collector"))
sys.path.insert(0, str(ROOT / "collector/vendor"))
import xlrd
import collect_retail_prices_city as current

RAW = ROOT / "data/raw/retail-prices-city-history"
NORMAL = ROOT / "data/normalized/retail-prices-city-history"
OUT = current.OUT
CODES = set(current.ITEM_BY_CODE)
FIRST_YEAR = 2000
LAST_YEAR = 2024  # Existing monthly collector owns 2024-09 onward.
HIST_END = "2024-08"

def request(url):
    for attempt in range(4):
        try:
            return current.fetch(url)
        except Exception:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)

def discover_year(year):
    found = {}
    for page in range(1, 10):
        body = current.year_page(year, page)
        blocks = re.findall(r'<article class="stat-resource_list-item[^"]*">.*?</article>', body, re.S)
        if not blocks:
            break
        for block in blocks:
            m = re.search(r'主要品目の都市別小売価格【(20\d{2})年(\d{1,2})月】', block)
            if not m or int(m.group(1)) != year:
                continue
            text = ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', block)).split())
            # Some item labels contain nested Japanese quotes (e.g. コシヒカリ),
            # so locate the two numeric codes, not the first closing quote.
            bounds = re.findall(r'「\s*(\d{4})', text)
            if len(bounds) < 2 or not any(int(bounds[0]) <= int(code) <= int(bounds[-1]) for code in CODES):
                continue
            sid = re.search(r'file-download\?statInfId=(\d+)(?:&|&amp;)fileKind=0', block)
            if not sid:
                continue
            ym = f'{year}-{int(m.group(2)):02d}'
            found.setdefault(ym, set()).add(sid.group(1))
    return {ym: sorted(ids) for ym, ids in found.items()}

def name_key(name):
    name = unicodedata.normalize("NFKC", str(name or ""))
    name = re.sub(r'\s+', '', name)
    name = re.sub(r'^\d+', '', name)
    name = name.replace("東京都区部", "東京区部")
    return name[:-1] if name.endswith("市") else name

def city_lookup():
    published = json.loads(OUT.read_text())
    by_key = {}
    for r in published["cities"]:
        by_key.setdefault(name_key(r["name"]), []).append(r)
    return {key: group[0] for key, group in by_key.items() if len(group) == 1}

def identify_city(raw, lookup):
    key = name_key(raw)
    if not key or key in {"都市", "Cities"}:
        return None
    if key in lookup:
        r = lookup[key]
        return r["code"], r["name"]
    # Do not assign a renamed or discontinued city to a present-day municipality.
    return "historical:" + key, key + ("（旧調査都市）" if key != "東京区部" else "")

def numeric(v):
    return current.number(v)

def unit_text(values):
    t = unicodedata.normalize("NFKC", ''.join(str(v or "") for v in values))
    for pat, unit in [
        (r'10\s*kg', "10kg"), (r'5\s*kg', "5kg"), (r'100\s*g', "100g"),
        (r'1\s*kg', "1kg"), (r'1000\s*m[lL]', "1000mL"),
        (r'10\s*個', "10個"), (r'1\s*皿', "1皿"), (r'3[.]3\s*m2', "3.3m2"),
        (r'20\s*m3', "20m3"), (r'1\s*[lL](?![a-zA-Z])', "1L"),
    ]:
        if re.search(pat, t, re.I):
            return unit
    return t[:80]

def parse_horizontal(sheet, lookup):
    values = {c: {} for c in CODES}
    units = {}
    cities = {}
    for row in range(sheet.nrows):
        selected = []
        for col in range(8, sheet.ncols):
            code = re.fullmatch(r'\((\d{4})\)', str(sheet.cell_value(row, col)).strip())
            if code and code.group(1) in CODES:
                selected.append((col, code.group(1)))
        if not selected:
            continue
        for col, code in selected:
            # Units are printed under the code/label, sometimes across several rows.
            units[code] = unit_text(sheet.cell_value(k, col) for k in range(row + 2, min(row + 8, sheet.nrows)))
            for i in range(row + 1, min(row + 115, sheet.nrows)):
                if str(sheet.cell_value(i, 0)).strip() not in {"001-1", "001-2", "001-3"}:
                    continue
                city = identify_city(sheet.cell_value(i, 7), lookup)
                if not city:
                    continue
                code_city, name = city
                cities[code_city] = name
                v = numeric(sheet.cell_value(i, col))
                if v is not None:
                    values[code][code_city] = v
    return cities, units, values

def parse_vertical(sheet, lookup):
    cities = {}
    columns = {}
    for col in range(11, sheet.ncols):
        city = identify_city(sheet.cell_value(10, col), lookup)
        if city:
            columns[col] = city
            cities[city[0]] = city[1]
    values = {c: {} for c in CODES}
    units = {}
    for row in range(15, sheet.nrows):
        raw = sheet.cell_value(row, 7)
        code = str(int(raw)) if isinstance(raw, (int, float)) and int(raw) == raw else str(raw).strip()
        if code not in CODES:
            continue
        units[code] = str(sheet.cell_value(row, 9)).strip()
        for col, (city_code, _) in columns.items():
            v = numeric(sheet.cell_value(row, col))
            if v is not None:
                values[code][city_code] = v
    return cities, units, values

def parse_xls(data, lookup):
    book = xlrd.open_workbook(file_contents=data, on_demand=True)
    merged_cities, merged_units = {}, {}
    merged_values = {c: {} for c in CODES}
    for sheet in book.sheets():
        if sheet.ncols < 30:
            cities, units, values = parse_horizontal(sheet, lookup)
        else:
            cities, units, values = parse_vertical(sheet, lookup)
        merged_cities.update(cities)
        merged_units.update(units)
        for code, mapping in values.items():
            merged_values[code].update(mapping)
    book.release_resources()
    return merged_cities, merged_units, merged_values

def fetch_month(ym, ids, lookup):
    path = NORMAL / (ym + ".json")
    if path.exists():
        return ym, json.loads(path.read_text())
    cities, units = {}, {}
    values = {c: {} for c in CODES}
    digests = {}
    for sid in ids:
        raw = RAW / (sid + ".xls")
        if not raw.exists():
            raw = RAW / (sid + ".xlsx")
        if not raw.exists():
            body = request(f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0')
            if body.startswith(b'\xd0\xcf\x11\xe0'):
                raw = RAW / (sid + ".xls")
            elif body.startswith(b'PK'):
                raw = RAW / (sid + ".xlsx")
            else:
                raise ValueError(f"Unexpected official workbook {ym} {sid}")
            raw.write_bytes(body)
        body = raw.read_bytes()
        digests[sid] = hashlib.sha256(body).hexdigest()
        if raw.suffix == ".xlsx":
            c, u, v = current.parse_book(body, ym)
        else:
            c, u, v = parse_xls(body, lookup)
        cities.update(c)
        for code, value in u.items():
            if code in units and units[code] != value:
                raise ValueError(f"Conflicting unit {ym} {code}: {units[code]} != {value}")
            units[code] = value
        for code, mapping in v.items():
            for city, price in mapping.items():
                if city in values[code] and values[code][city] != price:
                    raise ValueError(f"Conflicting price {ym} {sid} {code} {city}")
                values[code][city] = price
    result = {"month": ym, "ids": ids, "sha256": digests, "cities": cities,
              "units": units, "values": values}
    path.write_text(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return ym, result

def normalized_unit(raw):
    s = unicodedata.normalize("NFKC", str(raw or "")).lower().replace(" ", "").replace(",", "")
    for old, new in [("･", "・"), ("m2", "㎡"), ("m3", "㎥"), ("ml", "mL")]:
        s = s.replace(old, new)
    return s

def compatible(code, unit, target):
    src = normalized_unit(unit)
    dst = normalized_unit(target)
    if code == "1001" and "10kg" in src and "5kg" in dst:
        return 0.5, "10kg原値を5kg相当に換算"
    if code == "1001" and "5kg" in src and "5kg" in dst:
        return 1, None
    if code == "1341" and "10個" in dst and "1パック" in src and ("10個" in src or "10pieces" in src):
        return 1, None
    if src == dst:
        return 1, None
    # The early horizontal tables contain a compact unit under the item label.
    markers = {"1021": "1kg", "1201": "100g", "1211": "100g",
               "1303": "1000mL", "1401": "1kg", "2133": "1皿",
               "3001": "3.3㎡", "3800": "20㎥", "7301": "1l"}
    marker = normalized_unit(markers.get(code, ""))
    if marker and marker in src and marker in dst:
        return 1, None
    return None, None

def months_between(first, last):
    y, m = map(int, first.split("-"))
    while f"{y:04d}-{m:02d}" <= last:
        yield f"{y:04d}-{m:02d}"
        m += 1
        if m == 13:
            y, m = y + 1, 1

def assemble(months):
    old = json.loads(OUT.read_text())
    all_months = list(months_between("2000-01", old["latestMonth"]))
    assert len(all_months) > 300 and all_months[-1] == old["latestMonth"]
    lookups = {c["code"]: c["name"] for c in old["cities"]}
    snapshots = {ym: json.loads((NORMAL / (ym + ".json")).read_text()) for ym in months}
    for snap in snapshots.values():
        lookups.update(snap["cities"])
    codes = sorted(lookups, key=lambda c: (c.startswith("historical:"), lookups[c], c))
    units = {x["code"]: x["unit"] for x in old["items"]}
    values, conversion, unavailable = {}, {}, {}
    recent_index = {ym: i for i, ym in enumerate(old["months"])}
    for item in old["items"]:
        code = item["code"]
        values[code] = {}
        conversion[code] = {}
        unavailable[code] = {}
        for city in codes:
            series = []
            for ym in all_months:
                if ym in snapshots:
                    snap = snapshots[ym]
                    value = snap["values"][code].get(city)
                    unit = snap["units"].get(code)
                    factor, note = compatible(code, unit, units[code]) if value is not None else (None, None)
                    if factor is None and value is not None:
                        unavailable[code][ym] = unit
                        value = None
                    elif note and value is not None:
                        conversion[code][ym] = note
                        value = round(value * factor, 2)
                elif ym in recent_index:
                    value = old["values"].get(code, {}).get(city, [None] * len(old["months"]))[recent_index[ym]]
                else:
                    value = None
                series.append(value)
            if any(v is not None for v in series):
                values[code][city] = series
    old.update({"schemaVersion": 2, "months": all_months, "cities": [{"code": c, "name": lookups[c]} for c in codes],
                "cityCount": len(codes), "values": values, "unitConversions": conversion,
                "incompatibleHistoricalUnits": unavailable,
                "historicalSource": "e-Stat 小売物価統計調査（動向編）主要品目の都市別小売価格、月次XLS",
                "historicalSourceUrl": "https://www.stat.go.jp/data/kouri/doukou/3.htm"})
    old["historicalMonthCount"] = len(months)
    OUT.write_text(json.dumps(old, ensure_ascii=False, separators=(",", ":")))
    count = sum(v is not None for items in values.values() for series in items.values() for v in series)
    print(f"retail backfill: {len(all_months)} months / {len(codes)} cities / {count} usable prices -> {OUT}", flush=True)
    return old

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", default=f"{FIRST_YEAR}-{LAST_YEAR}")
    parser.add_argument("--download-only", action="store_true")
    args = parser.parse_args()
    first, last = (int(x) for x in args.years.split("-"))
    RAW.mkdir(parents=True, exist_ok=True)
    NORMAL.mkdir(parents=True, exist_ok=True)
    manifest_path = RAW / "manifest.json"
    manifest = json.loads(manifest_path.read_text()) if manifest_path.exists() else {}
    lookup = city_lookup()
    for year in range(first, last + 1):
        # Always reconcile discovery with cached snapshots. The January split
        # between e-Stat pages can leave one workbook out of a partial run.
        discovered = discover_year(year)
        manifest.update(discovered)
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2))
        missing = []
        for m in range(1, 13):
            ym = f"{year}-{m:02d}"
            if ym > HIST_END:
                continue
            path = NORMAL / f"{ym}.json"
            if path.exists() and json.loads(path.read_text())["ids"] != manifest.get(ym):
                path.unlink()
                print(f"{ym}: refreshed changed official file list", flush=True)
            if not path.exists():
                missing.append(ym)
        if not missing:
            continue
        if not all(ym in manifest for ym in missing):
            raise ValueError(f"Missing monthly files for {year}: {sorted(set(missing) - set(manifest))}")
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as pool:
            futures = [pool.submit(fetch_month, ym, manifest[ym], lookup) for ym in missing]
            for future in concurrent.futures.as_completed(futures):
                ym, snap = future.result()
                n = sum(len(x) for x in snap["values"].values())
                if n < 80:
                    raise ValueError(f"Insufficient historical data {ym}: {n}")
                print(f"{ym}: {n} values / {len(snap['ids'])} books", flush=True)
    if not args.download_only:
        months = list(months_between("2000-01", HIST_END))
        missing = [m for m in months if not (NORMAL / (m + ".json")).exists()]
        if missing:
            raise ValueError(f"Cannot assemble, missing {len(missing)} months, first={missing[:5]}")
        assemble(months)

if __name__ == "__main__":
    main()
