#!/usr/bin/env python3
import csv, io, json, statistics, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data" / "land-prices-2026.json"
URL = "https://nlftp.mlit.go.jp/ksj/old/data/L01/L01-2026P/L01-2026P-48-01.0a.zip"
YEAR = 2026

def num(v, kind=float):
    try:
        return kind(str(v).replace(",", "").strip())
    except Exception:
        return None

def fetch_zip():
    req = urllib.request.Request(URL, headers={"User-Agent": "public-market-data/1.0"})
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()

def prefecture(address):
    names = ["北海道", "東京都", "京都府", "大阪府"]
    names += [x + "県" for x in "青森 岩手 宮城 秋田 山形 福島 茨城 栃木 群馬 埼玉 千葉 神奈川 新潟 富山 石川 福井 山梨 長野 岐阜 静岡 愛知 三重 滋賀 兵庫 奈良 和歌山 鳥取 島根 岡山 広島 山口 徳島 香川 愛媛 高知 福岡 佐賀 長崎 熊本 大分 宮崎 鹿児島 沖縄".split()]
    return next((p for p in names if address.startswith(p)), "")

def main():
    blob = fetch_zip()
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith(".csv"))
        text = zf.read(csv_name).decode("cp932")
    rows = csv.DictReader(io.StringIO(text))
    records, prices = [], []
    for r in rows:
        lon = num(r.get("経度")); lat = num(r.get("緯度"))
        price = num(r.get("価格R08"), int)
        if lon is None or lat is None or not price:
            continue
        lon /= 3600; lat /= 3600
        address = (r.get("所在・地番") or "").replace("　", " ").strip()
        yoy = num(r.get("対前年変動率"))
        records.append([
            f"{r.get('行政区域コード','')}-{r.get('番号用途区分','')}-{r.get('番号連番','')}",
            round(lon, 6), round(lat, 6), price, yoy,
            r.get("標準地名", ""), address, prefecture(address),
            r.get("駅名", ""), num(r.get("駅距離"), int),
            r.get("利用現況", ""), num(r.get("地積"), int),
        ])
        prices.append(price)
    payload = {
        "schemaVersion": 1,
        "year": YEAR,
        "source": "国土交通省 国土数値情報 地価公示",
        "sourceUrl": URL,
        "license": "CC BY 4.0",
        "dataAsOf": "2026-01-01",
        "fields": ["id","lon","lat","price","yoy","name","address","prefecture","station","stationDistance","use","area"],
        "stats": {"records": len(records), "medianPrice": int(statistics.median(prices)), "averagePrice": int(sum(prices)/len(prices))},
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"land-prices: {len(records)} points -> {OUT}")
    return payload["stats"]

if __name__ == "__main__":
    with SourceRun("land_prices", "国土交通省 地価公示") as run:
        stats = main()
        run.set_metrics(records=stats["records"], medianPrice=stats["medianPrice"], averagePrice=stats["averagePrice"])
