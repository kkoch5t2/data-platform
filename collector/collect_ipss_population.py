#!/usr/bin/env python3
"""IPSS 2023 municipality projections, official result tables 1 and 2_1–2_3."""
import hashlib
import json
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/ipss-shicyoson-2023"
OUT = ROOT / "public/data/municipality-population-projections.json"
BASE = "https://www.ipss.go.jp/pp-shicyoson/j/shicyoson23/2gaiyo_hyo/"
PAGE = BASE + "gaiyo.asp"
FILES = {"population": "kekkahyo1.xlsx", "under15": "kekkahyo2_1.xlsx",
         "workingAge": "kekkahyo2_2.xlsx", "elderly": "kekkahyo2_3.xlsx"}
YEARS = list(range(2020, 2051, 5))
NS = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

def download(name):
    RAW.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(BASE + name, headers={"User-Agent": "Mozilla/5.0 DATLUME/1.0"})
    with urllib.request.urlopen(request, timeout=90) as response:
        body = response.read()
    if len(body) < 100_000 or not zipfile.is_zipfile(__import__("io").BytesIO(body)):
        raise ValueError(f"Unexpected IPSS workbook: {name}")
    path = RAW / name
    path.write_bytes(body)
    return path, hashlib.sha256(body).hexdigest()

def rows(path):
    """Read the fixed official XLSX table with standard-library ZIP/XML."""
    with zipfile.ZipFile(path) as archive:
        strings = []
        if "xl/sharedStrings.xml" in archive.namelist():
            root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
            strings = ["".join(t.text or "" for t in item.findall(".//s:t", NS))
                       for item in root.findall("s:si", NS)]
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
        result = []
        for row in root.findall(".//s:sheetData/s:row", NS):
            cells = {}
            for cell in row.findall("s:c", NS):
                column = re.match(r"[A-Z]+", cell.attrib["r"]).group()
                value = cell.find("s:v", NS)
                text = value.text if value is not None else ""
                if cell.attrib.get("t") == "s" and text:
                    text = strings[int(text)]
                elif cell.attrib.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in cell.findall(".//s:t", NS))
                cells[column] = text
            result.append(cells)
        return result

def parse(path):
    table = rows(path)
    if table[3].get("A") != "コード" or "2020" not in table[4].get("E", "") or "2050" not in table[4].get("K", ""):
        raise ValueError(f"IPSS table schema changed: {path.name}")
    result = {}
    for row in table[5:]:
        raw_code = row.get("A", "")
        kind = row.get("B", "")
        if not raw_code.isdigit() or kind not in {"a", "0", "1", "2", "3", "9"}:
            continue
        code = raw_code.zfill(5)
        if code in result:
            raise ValueError(f"Duplicate IPSS code: {code}")
        values = []
        for col in "EFGHIJK":
            value = row.get(col, "")
            if not value.isdigit():
                raise ValueError(f"Missing population {path.name} {code} {col}: {value}")
            values.append(int(value))
        result[code] = {"code": code, "kind": kind, "prefecture": row.get("C", ""),
                        "municipality": row.get("D", ""), "values": values}
    if len(result) != 1951:  # 47 prefectures + 20 designated-city aggregates + 1,884 regions
        raise ValueError(f"IPSS coverage changed: {len(result)}")
    return result

def main():
    sha = {}
    tables = {}
    for metric, name in FILES.items():
        path, sha[name] = download(name)
        tables[metric] = parse(path)
    codes = set(tables["population"])
    if any(set(t) != codes for t in tables.values()):
        raise ValueError("IPSS age table coverage mismatch")
    base = json.loads((ROOT / "public/data/municipality-stats-2026.json").read_text())
    centroids = {r["code"]: r for r in base["records"]}
    records = []
    for code, row in tables["population"].items():
        for metric, table in tables.items():
            other = table[code]
            if (other["kind"], other["prefecture"], other["municipality"]) != (row["kind"], row["prefecture"], row["municipality"]):
                raise ValueError(f"IPSS table identity mismatch: {metric} {code}")
        by_year = [[tables[key][code]["values"][i] for key in FILES] for i in range(len(YEARS))]
        for year, (total, child, working, elderly) in zip(YEARS, by_year):
            if child + working + elderly > total or (year > 2020 and child + working + elderly != total):
                raise ValueError(f"IPSS age totals inconsistent: {code} {year}")
        record = {k: row[k] for k in ("code", "kind", "prefecture", "municipality")}
        if row["kind"] == "9":  # The workbook appends phonetic text to this label.
            record["municipality"] = "浜通り地域"
        record["values"] = by_year
        anchor = centroids.get(code)
        if anchor and anchor["prefecture"] == row["prefecture"] and anchor["municipality"] == row["municipality"]:
            record["lon"], record["lat"] = anchor["lon"], anchor["lat"]
        records.append(record)
    projected = [r for r in records if r["kind"] not in {"a", "1"}]
    if len(projected) != 1884 or sum(r["kind"] == "9" for r in projected) != 1:
        raise ValueError("IPSS regional composition changed")
    payload = {
        "schemaVersion": 1, "dataset": "IPSS-shicyoson-2023",
        "source": "国立社会保障・人口問題研究所「日本の地域別将来推計人口（令和5（2023）年推計）」",
        "sourceUrl": PAGE, "generatedAt": datetime.now(timezone.utc).isoformat(),
        "years": YEARS, "baseYear": 2020, "projectionYears": YEARS[1:],
        "metrics": list(FILES), "workbooksSha256": sha,
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"IPSS: {len(projected)} regions, {sum('lon' in r for r in projected)} geocoded, 47 prefectures -> {OUT}")
    return {"records": len(projected), "geocoded": sum("lon" in r for r in projected)}

if __name__ == "__main__":
    with SourceRun("ipss_population", "社人研 地域別将来推計人口（2023年推計）") as run:
        run.set_metrics(**main())
