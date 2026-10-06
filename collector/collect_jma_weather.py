#!/usr/bin/env python3
"""JMA station observations: monthly history and recent daily temperature/rainfall."""
import csv
import hashlib
import io
import json
import os
import re
import time
import urllib.parse
import urllib.request
import zipfile
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
try:
    from collect_regional_trends import PREFECTURE_ORDER
except ModuleNotFoundError:
    from collector.collect_regional_trends import PREFECTURE_ORDER

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://www.data.jma.go.jp/risk/obsdl/"
MASTER = "https://www.jma.go.jp/jma/kishou/know/amedas/ame_master.zip"
OUT = ROOT / "public/data/weather"
RAW = ROOT / "data/raw/weather"
HEADERS = {"User-Agent": "DATLUME public-data collector (https://datlume.com/about-data/)"}
HOKKAIDO = set("宗谷 上川 留萌 石狩 空知 後志 ｵﾎｰﾂｸ 根室 釧路 十勝 胆振 日高 渡島 檜山".split())
PREF_BY_STEM = {p.removesuffix("都").removesuffix("道").removesuffix("府").removesuffix("県"): p for p in PREFECTURE_ORDER}
MUNICIPAL = json.loads((ROOT / "public/data/municipality-stats-2026.json").read_text())["records"]

def fetch(url, form=None, timeout=120):
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    request = urllib.request.Request(url, data=data, headers=HEADERS)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return response.read()
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt * 3)

def clean_name(name):
    return re.sub(r"（.*?）|\(.*?\)|\s+", "", name)

def coord_from_title(title, direction):
    m = re.search(direction + r"：(\d+)度([\d.]+)分", title)
    return round(int(m.group(1)) + float(m.group(2))/60, 5) if m else None

def station_index():
    RAW.mkdir(parents=True, exist_ok=True)
    raw = fetch(MASTER)
    (RAW / "ame_master.zip").write_bytes(raw)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        master = list(csv.DictReader(io.StringIO(archive.read(archive.namelist()[0]).decode("cp932"))))
        master_file = archive.namelist()[0]
    by_name = defaultdict(list)
    for row in master:
        try:
            lat = int(row["緯度(度)"]) + float(row["緯度(分)"])/60
            lon = int(row["経度(度)"]) + float(row["経度(分)"])/60
        except ValueError:
            continue
        by_name[clean_name(row["観測所名"])].append((row, lat, lon))
    pref_lists = defaultdict(list)
    for row in MUNICIPAL:
        pref_lists[row["prefecture"]].append(row)
    for rows in pref_lists.values():
        rows.sort(key=lambda r: -len(r["municipality"]))
    codes = sorted({r["観測所番号"][:2] for r in master})
    stations = {}
    for code in codes:
        payload = json.loads(fetch(BASE + "top/station", {"pd": code, "format": "json"}))
        for m in payload["markers"]:
            if m.get("kind") != "station" or not m.get("small") or m.get("ended"):
                continue
            sid = m["stid"]
            if sid in stations:
                continue
            lat = coord_from_title(m["title"], "北緯")
            lon = coord_from_title(m["title"], "東経")
            if lat is None or lon is None:
                raise ValueError("Station coordinate missing: " + sid)
            candidates = by_name[clean_name(m["stname"])]
            close = [(r, abs(y-lat)+abs(x-lon)) for r,y,x in candidates
                     if abs(y-lat) < .1 and abs(x-lon) < .1]
            close.sort(key=lambda item: item[1])
            row = close[0][0] if close else None
            area = row["都府県振興局"] if row else None
            pref = "北海道" if area in HOKKAIDO else PREF_BY_STEM.get(area)
            if pref is None and code == "91":
                pref = "沖縄県"
            if pref is None:
                # Region code is shared by stations even when names have changed.
                existing = [s["prefecture"] for s in stations.values() if s["regionCode"] == code]
                pref = existing[0] if existing else None
            if pref is None:
                raise ValueError(f"Unknown prefecture for {sid} {m['stname']} {code}")
            address = row["所在地"] if row else None
            locality = address.removeprefix(pref).removeprefix("八丈島").replace("梼原町", "檮原町") if address else ""
            matches = [r for r in pref_lists[pref] if
                       (locality.startswith(r["municipality"]) or
                        re.match(r"^.{1,12}郡" + re.escape(r["municipality"]), locality))]
            city = matches[0] if matches else None
            stations[sid] = {
                "id": sid, "name": m["stname"], "regionCode": code,
                "prefecture": pref, "municipality": city["municipality"] if city else None,
                "municipalityCode": city["code"] if city else None,
                "address": address, "lat": lat, "lon": lon,
            }
        time.sleep(.12)
    if len(stations) < 1200:
        raise ValueError(f"Station coverage regressed: {len(stations)}")
    return list(stations.values()), master_file, hashlib.sha256(raw).hexdigest()

def request_table(batch, period, begin, end):
    form = {
        "stationNumList": json.dumps([s["id"] for s in batch]),
        "aggrgPeriod": "5" if period == "monthly" else "1",
        "elementNumList": json.dumps([["201",""], ["101",""]]),
        "interAnnualType": "1",
        "ymdList": json.dumps([str(begin.year),str(end.year),str(begin.month),str(end.month),
                               str(begin.day),str(end.day)]),
        "option": json.dumps({"list":["obs"],"nyear":0}),
        "downloadFlag":"true", "rmkFlag":"1", "disconnectFlag":"1",
        "youbiFlag":"0", "fukenFlag":"0", "kijiFlag":"0", "csvFlag":"1",
        "jikantaiFlag":"0", "jikantaiList":"[]", "ymdLiteral":"1",
    }
    return fetch(BASE + "show/table", form)

def parse_table(raw, batch, period, expected_dates):
    rows = list(csv.reader(io.StringIO(raw.decode("cp932"))))
    if len(rows) < 6 or rows[3][0] not in ("年月", "年月日"):
        raise ValueError(f"JMA table header changed: {period} {rows[:5]}")
    header, label, sub = rows[2:5]
    groups = []
    for i in range(1, len(header)):
        if i == 1 or header[i] != header[i-1]:
            groups.append((i, header[i]))
    if len(groups) != len(batch):
        raise ValueError(f"JMA station columns changed: {len(groups)} for {len(batch)}")
    values = {}
    for pos, (start, name) in enumerate(groups):
        station = batch[pos]
        if clean_name(name) != clean_name(station["name"]):
            raise ValueError(f"JMA station order changed: {name} / {station['name']}")
        end = groups[pos+1][0] if pos+1 < len(groups) else len(header)
        cols = {}
        for col in range(start, end):
            if sub[col]:
                continue
            qcol = col + 1
            if qcol < end and sub[qcol] == "現象なし情報":
                qcol += 1
            if qcol >= end or sub[qcol] != "品質情報":
                continue
            if "平均気温" in label[col]:
                cols["temperature"] = (col, qcol)
            elif "降水量の合計" in label[col]:
                cols["rainfall"] = (col, qcol)
        if "rainfall" not in cols:
            raise ValueError(f"Rainfall column missing: {station['id']}")
        values[station["id"]] = []
        for row in rows[5:]:
            if not row or not row[0].strip():
                continue
            pair = []
            for key in ("temperature", "rainfall"):
                positions = cols.get(key)
                if positions is None:
                    pair.append(None)
                    continue
                col, qcol = positions
                quality = row[qcol] if qcol < len(row) else ""
                raw_value = row[col].strip() if col < len(row) else ""
                if quality != "8" or not raw_value:
                    pair.append(None)
                    continue
                try:
                    number = float(raw_value)
                except ValueError as exc:
                    raise ValueError(f"Unexpected JMA value: {raw_value}") from exc
                if not -100 <= number <= 10000:
                    raise ValueError(f"JMA value out of range: {number}")
                pair.append(number)
            values[station["id"]].append(pair)
    dates = []
    for r in rows[5:]:
        if not r or not r[0].strip():
            continue
        parts = r[0].strip().split("/")
        dates.append("-".join([parts[0], *(p.zfill(2) for p in parts[1:])]))
    if dates != expected_dates:
        raise ValueError(f"JMA dates changed: {period} {dates[:2]} ... {dates[-2:]}")
    return values

def date_axis(begin, end, period):
    result = []
    d = begin
    while d <= end:
        result.append(d.isoformat() if period == "daily" else f"{d.year}-{d.month:02d}")
        d = d + timedelta(days=1) if period == "daily" else (d.replace(day=28) + timedelta(days=4)).replace(day=1)
    return result

def main():
    now = datetime.now(ZoneInfo("Asia/Tokyo")).date()
    last_day = now - timedelta(days=1)
    last_month = now.replace(day=1) - timedelta(days=1)
    daily_begin = last_day - timedelta(days=365)
    months = date_axis(date(2015,1,1), last_month, "monthly")
    days = date_axis(daily_begin, last_day, "daily")
    stations, master_file, master_hash = station_index()
    collected = {s["id"]: {"monthly":None, "daily":None} for s in stations}
    for period, begin, end, axis in (
        ("monthly", date(2015,1,1), last_month, months),
        ("daily", daily_begin, last_day, days),
    ):
        for index in range(0, len(stations), 30):
            batch = stations[index:index+30]
            raw_path = RAW / f"{period}-{index//30:03d}.csv"
            if os.environ.get("DATLUME_JMA_REUSE_RAW") == "1" and raw_path.exists():
                raw = raw_path.read_bytes()
            else:
                raw = request_table(batch, period, begin, end)
                raw_path.write_bytes(raw)
            parsed = parse_table(raw, batch, period, axis)
            for sid, values in parsed.items():
                collected[sid][period] = values
            print(f"{period}: {min(index+30,len(stations))}/{len(stations)}", flush=True)
            time.sleep(.35)
    shard = defaultdict(list)
    usable = 0
    for s in stations:
        entry = {**s, **collected[s["id"]]}
        if any(v is not None for period in ("monthly","daily") for row in entry[period] for v in row):
            usable += 1
        shard[s["regionCode"]].append(entry)
    if usable < 1200:
        raise ValueError(f"Too few stations with observations: {usable}")
    OUT.mkdir(parents=True, exist_ok=True)
    for code, records in shard.items():
        payload = {"schemaVersion":1, "regionCode":code, "months":months, "days":days, "records":records}
        temp = OUT / (code + ".json.tmp")
        temp.write_text(json.dumps(payload, ensure_ascii=False, separators=(",",":")))
        temp.replace(OUT / (code + ".json"))
    index = {
        "schemaVersion":1, "source":"気象庁 過去の気象データ・ダウンロード",
        "sourceUrl":BASE, "masterUrl":MASTER, "masterFile":master_file,
        "masterSha256":master_hash, "generatedAt":datetime.now(timezone.utc).isoformat(),
        "months":months, "days":days, "regions":sorted(shard),
        "stationCount":len(stations), "usableStationCount":usable,
        "municipalityMappedCount":sum(bool(s["municipalityCode"]) for s in stations),
        "stations":stations,
        "note":"観測所地点の値。市区町村全域の代表値ではない。品質情報8（正常値）のみ掲載。欠測・準正常値は補完せず空欄。"
    }
    temp = OUT / "index.json.tmp"
    temp.write_text(json.dumps(index, ensure_ascii=False, separators=(",",":")))
    temp.replace(OUT / "index.json")
    print(f"weather: {len(stations)} stations ({index['municipalityMappedCount']} municipalities mapped); "
          f"{len(months)} months, {len(days)} days; latest {days[-1]}")
    return {"records":usable * (len(months)+len(days)), "stations":len(stations),
            "mappedStations":index["municipalityMappedCount"], "latestDay":days[-1]}

if __name__ == "__main__":
    with SourceRun("jma_weather", "気象庁 過去の気象データ") as run:
        run.set_metrics(**main())
