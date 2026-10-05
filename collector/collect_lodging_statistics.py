#!/usr/bin/env python3
"""Tourism Agency lodging nights and occupancy, monthly prefecture series."""
import hashlib
import json
import re
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urljoin
from xml.etree import ElementTree as ET
from zipfile import ZipFile

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
try:
    from collect_regional_trends import PREFECTURE_ORDER
except ModuleNotFoundError:
    from collector.collect_regional_trends import PREFECTURE_ORDER

ROOT = Path(__file__).resolve().parents[1]
PAGE = "https://www.mlit.go.jp/kankocho/tokei_hakusyo/shukuhakutokei.html"
OUT = ROOT / "public/data/lodging-statistics.json"
NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
HEADERS = {"User-Agent": "Mozilla/5.0 DATLUME public-data collector"}

class Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.href = None
        self.links = []
    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self.href = dict(attrs).get("href")
    def handle_data(self, value):
        if self.href and "推移表" in value:
            self.links.append(self.href)
    def handle_endtag(self, tag):
        if tag == "a":
            self.href = None

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=90) as response:
        return response.read()

def colnum(ref):
    value = 0
    for letter in re.match(r"[A-Z]+", ref).group():
        value = value * 26 + ord(letter) - 64
    return value

def sheet(zipfile, shared, index):
    root = ET.fromstring(zipfile.read(f"xl/worksheets/sheet{index}.xml"))
    rows = {}
    for row in root.iter(NS + "row"):
        result = {}
        for cell in row.findall(NS + "c"):
            value = cell.find(NS + "v")
            if value is None:
                continue
            result[colnum(cell.attrib["r"])] = shared[int(value.text)] if cell.get("t") == "s" else value.text
        rows[int(row.attrib["r"])] = result
    return rows

def value(row, column, integer=True):
    raw = row.get(column)
    if raw is None or raw in ("-", "…", "x"):
        return None
    number = float(raw)
    return int(number) if integer else round(number, 1)

def parse(raw):
    with ZipFile(__import__("io").BytesIO(raw)) as z:
        shared = ["".join(t.text or "" for t in item.iter(NS + "t")) for item in
                  ET.fromstring(z.read("xl/sharedStrings.xml")).findall(NS + "si")]
        old = {key: sheet(z, shared, index) for key, index in
               [("total", 11), ("japanese", 13), ("foreign", 15), ("occupancy", 17)]}
        current = {key: sheet(z, shared, index) for key, index in
                   [("total", 2), ("japanese", 3), ("foreign", 4), ("occupancy", 5)]}
    era = current["total"][3].get(2, "")
    match = re.search(r"令和(\d+)年", era)
    if not match:
        raise ValueError("Current year heading changed: " + era)
    current_year = 2018 + int(match.group(1))
    if current_year < 2026:
        raise ValueError("Unexpected current year")
    names = ["全国"] + PREFECTURE_ORDER
    months = []
    for year in range(2011, current_year):
        for month in range(1, 13):
            months.append(f"{year}-{month:02d}")
    months.extend(f"{current_year}-{month:02d}" for month in range(1, 13)
                  if current["total"][5].get(1 + month) is not None)
    if len(months) < 187:
        raise ValueError("Historical or latest monthly values missing")
    records = []
    for offset, name in enumerate(names):
        row = 5 + offset
        occrow = 5 + offset * 7
        for group in (old, current):
            label = group["total"][row].get(1, "")
            if offset and not label.startswith(f"{offset:02d}{name}"):
                raise ValueError(f"Prefecture row changed: {label}")
            if group["occupancy"][occrow].get(2, "").strip()[:1] != "計":
                raise ValueError("Occupancy total row changed")
        values = []
        for date in months:
            year, month = map(int, date.split("-"))
            group = old if year < current_year else current
            column = 1 + (year - 2011) * 12 + month if year < current_year else 1 + month
            occcolumn = column + 1
            total = value(group["total"][row], column)
            japanese = value(group["japanese"][row], column)
            foreign = value(group["foreign"][row], column)
            occupancy = value(group["occupancy"][occrow], occcolumn, False)
            if total is None or total < 0:
                raise ValueError(f"Missing total nights: {name} {date}")
            if japanese is not None and foreign is not None and abs(total - japanese - foreign) > 20:
                raise ValueError(f"Nights components inconsistent: {name} {date}")
            if occupancy is not None and not 0 <= occupancy <= 100:
                raise ValueError(f"Occupancy out of range: {name} {date}")
            values.append([total, japanese, foreign, occupancy])
        records.append({"prefecture": name, "values": values})
    if records[0]["values"][months.index("2025-12")][0] != 54986680:
        raise ValueError("2025 December national anchor changed")
    if records[0]["values"][-1][0] < 10000000:
        raise ValueError("Latest national total implausible")
    return months, records

def main():
    links = Links()
    links.feed(fetch(PAGE).decode("utf-8", "replace"))
    urls = list(dict.fromkeys(urljoin(PAGE, link) for link in links.links if link.endswith(".xlsx")))
    if len(urls) != 1:
        raise ValueError(f"Expected one trend workbook, got {urls}")
    raw = fetch(urls[0])
    months, records = parse(raw)
    raw_path = ROOT / "data/raw/tourism" / f"trend-{months[-1]}.xlsx"
    raw_path.parent.mkdir(parents=True, exist_ok=True)
    raw_path.write_bytes(raw)
    payload = {
        "schemaVersion": 1, "source": "観光庁 宿泊旅行統計調査（推移表）",
        "sourceUrl": PAGE, "workbookUrl": urls[0], "sha256": hashlib.sha256(raw).hexdigest(),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "unit": "人泊", "months": months, "prefectures": [r["prefecture"] for r in records],
        "records": records, "note": "2025年まで確報、最新年は月次速報・第2次速報を含む。月次推移表の掲載値。"
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"lodging-statistics: {len(records)} areas × {len(months)} months, latest {months[-1]} -> {OUT}")
    return {"records": len(records) * len(months), "areas": len(records), "latestMonth": months[-1]}

if __name__ == "__main__":
    with SourceRun("lodging_statistics", "観光庁 宿泊旅行統計調査") as run:
        run.set_metrics(**main())
