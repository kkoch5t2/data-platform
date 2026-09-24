#!/usr/bin/env python3
import csv, io, json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data" / "regional-trends-2026.json"
URL = "https://www.nstac.go.jp/files/SSDSE-B-2026.csv"
UA = {"User-Agent": "Mozilla/5.0 PublicMarketData/1.0"}
PREFECTURE_ORDER = ['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県']

FIELDS = {
    "population": "総人口",
    "under15": "15歳未満人口",
    "workingAge": "15～64歳人口",
    "elderly": "65歳以上人口",
    "births": "出生数",
    "deaths": "死亡数",
    "inMigration": "転入者数（日本人移動者）",
    "outMigration": "転出者数（日本人移動者）",
    "jobSeekers": "月間有効求職者数（一般）",
    "jobOpenings": "月間有効求人数（一般）",
    "housingStarts": "着工新設住宅戸数",
    "hotelNights": "延べ宿泊者数",
    "foreignNights": "外国人延べ宿泊者数",
    "residentialLandPrice": "標準価格（平均価格）（住宅地）",
    "commercialLandPrice": "標準価格（平均価格）（商業地）",
    "recycleRate": "ごみのリサイクル率",
    "childcareWaitlist": "保育所等利用待機児童数",
}

def fetch():
    req = urllib.request.Request(URL, headers=UA)
    with urllib.request.urlopen(req, timeout=60) as res:
        return res.read()

def number(v):
    s = str(v or "").replace(",", "").strip()
    if not s:
        return None
    try:
        n = float(s)
        return int(n) if n.is_integer() else n
    except ValueError:
        return None

def main():
    raw = fetch()
    text = raw.decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    names = rows[1]
    idx = {name: i for i, name in enumerate(names)}
    missing = [name for name in FIELDS.values() if name not in idx]
    if missing:
        raise ValueError("SSDSE-B columns missing: " + ",".join(missing))
    records = []
    for r in rows[2:]:
        if len(r) < 3 or not r[0].isdigit() or not r[2]:
            continue
        item = {"year": int(r[0]), "code": r[1], "prefecture": r[2]}
        for key, label in FIELDS.items():
            item[key] = number(r[idx[label]])
        pop = item.get("population") or 0
        elderly = item.get("elderly") or 0
        item["elderlyRate"] = round(elderly / pop * 100, 2) if pop else None
        item["netMigration"] = (item.get("inMigration") or 0) - (item.get("outMigration") or 0)
        seekers = item.get("jobSeekers") or 0
        item["jobOpeningRatio"] = round((item.get("jobOpenings") or 0) / seekers, 3) if seekers else None
        nights = item.get("hotelNights") or 0
        item["foreignStayShare"] = round((item.get("foreignNights") or 0) / nights * 100, 2) if nights else None
        records.append(item)
    years = sorted({r["year"] for r in records})
    present = {r["prefecture"] for r in records}
    prefs = [p for p in PREFECTURE_ORDER if p in present]
    payload = {
        "schemaVersion": 1,
        "dataset": "SSDSE-B-2026",
        "source": "独立行政法人 統計センター SSDSE-県別推移",
        "sourceUrl": URL,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "years": years,
        "prefectures": prefs,
        "records": records,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"regional-trends: {len(records)} rows / {len(prefs)} prefectures / {len(years)} years -> {OUT}")
    return {"records": len(records), "prefectures": len(prefs), "years": len(years)}

if __name__ == "__main__":
    with SourceRun("regional_trends", "統計センター SSDSE-県別推移") as run:
        stats = main()
        run.set_metrics(**stats)
