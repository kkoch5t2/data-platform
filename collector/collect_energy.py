#!/usr/bin/env python3
import csv, html, io, json, re, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public" / "data" / "energy.json"
UA = {"User-Agent": "Mozilla/5.0 DATLUME/1.0", "Accept-Language": "ja,en;q=0.8"}

PREF_CAPITAL = {
    "北海道":"札幌市","青森県":"青森市","岩手県":"盛岡市","宮城県":"仙台市","秋田県":"秋田市","山形県":"山形市","福島県":"福島市",
    "茨城県":"水戸市","栃木県":"宇都宮市","群馬県":"前橋市","埼玉県":"さいたま市","千葉県":"千葉市","東京都":"東京都区部","神奈川県":"横浜市",
    "新潟県":"新潟市","富山県":"富山市","石川県":"金沢市","福井県":"福井市","山梨県":"甲府市","長野県":"長野市","岐阜県":"岐阜市",
    "静岡県":"静岡市","愛知県":"名古屋市","三重県":"津市","滋賀県":"大津市","京都府":"京都市","大阪府":"大阪市","兵庫県":"神戸市",
    "奈良県":"奈良市","和歌山県":"和歌山市","鳥取県":"鳥取市","島根県":"松江市","岡山県":"岡山市","広島県":"広島市","山口県":"山口市",
    "徳島県":"徳島市","香川県":"高松市","愛媛県":"松山市","高知県":"高知市","福岡県":"福岡市","佐賀県":"佐賀市","長崎県":"長崎市",
    "熊本県":"熊本市","大分県":"大分市","宮崎県":"宮崎市","鹿児島県":"鹿児島市","沖縄県":"那覇市"
}

SSDSE_B = "https://www.nstac.go.jp/files/SSDSE-B-2026.csv"
ESTAT_71_SEARCH = (
    "https://www.e-stat.go.jp/stat-search/files?cycle=7&cycle_facet=tclass1%3Atclass2%3Atclass3%3Acycle"
    "&data=1&layout=dataset&metadata=1&page=1&query=%E5%85%89%E7%86%B1%E8%B2%BB"
    "&tclass1=000000330001&tclass2=000000330004&tclass3=000000330006&toukei=00200561&tstat=000000330001"
)

def fetch(url, timeout=90):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()

def strip_tags(s):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", s)).split())

def discover_71():
    text = fetch(ESTAT_71_SEARCH).decode("utf-8", "ignore")
    candidates = []
    for m in re.finditer(r"/stat-search/file-download\?statInfId=(\d+)(?:&amp;|&)fileKind=4", text):
        ctx = strip_tags(text[max(0, m.start()-3500):m.start()+2500])
        if "7-1" not in ctx or "電気" not in ctx or "ガス" not in ctx:
            continue
        years = [int(x) for x in re.findall(r"(20\d{2})年", ctx)]
        if years:
            candidates.append((max(years), m.group(1)))
    if not candidates:
        raise RuntimeError("e-Stat 家計調査 7-1 を発見できません")
    return max(candidates)

def discover_11(year):
    url = (
        "https://www.e-stat.go.jp/stat-search/files?cycle=7&layout=datalist&month=0&page=1&result_back=1"
        "&tclass1=000000330001&tclass2=000000330004&tclass3=000000330005&tclass4val=0"
        f"&toukei=00200561&tstat=000000330001&year={year}0"
    )
    text = fetch(url).decode("utf-8", "ignore")
    for m in re.finditer(r"/stat-search/file-download\?statInfId=(\d+)(?:&amp;|&)fileKind=0", text):
        ctx = strip_tags(text[max(0, m.start()-2600):m.start()+1400])
        if "1-1" in ctx and "都市階級・地方・都道府県庁所在市別" in ctx and "二人以上の世帯" in ctx:
            return m.group(1)
    raise RuntimeError("e-Stat 家計調査 1-1 を発見できません")

NS = {"m":"http://schemas.openxmlformats.org/spreadsheetml/2006/main","r":"http://schemas.openxmlformats.org/officeDocument/2006/relationships"}

def colnum(ref):
    letters = "".join(c for c in ref if c.isalpha())
    n = 0
    for c in letters:
        n = n * 26 + ord(c.upper()) - 64
    return n

def xlsx_sheet(blob, sheet_name=None):
    z = zipfile.ZipFile(io.BytesIO(blob))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rel = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    relmap = {x.attrib["Id"]: x.attrib["Target"] for x in rel}
    sheets = [(s.attrib["name"], relmap[s.attrib["{%s}id" % NS["r"]]]) for s in wb.find("m:sheets", NS)]
    name, target = next((x for x in sheets if x[0] == sheet_name), sheets[0])
    path = "xl/" + target if not target.startswith("xl/") else target
    root = ET.fromstring(z.read(path))
    rows = {}
    for rr in root.findall(".//m:sheetData/m:row", NS):
        row = {}
        for c in rr.findall("m:c", NS):
            typ = c.attrib.get("t")
            v = c.find("m:v", NS)
            val = "" if v is None else (v.text or "")
            if typ == "s" and val:
                val = shared[int(val)]
            elif typ == "inlineStr":
                val = "".join(t.text or "" for t in c.iter("{%s}t" % NS["m"]))
            row[colnum(c.attrib["r"])] = val
        rows[int(rr.attrib["r"])] = row
    return rows

def num(v):
    try:
        return float(str(v).replace(",", "").strip())
    except Exception:
        return None

def parse_annual_breakdown(blob):
    rows = xlsx_sheet(blob)
    item_row_no = next(rn for rn, r in rows.items() if any(str(v).startswith("項目名") for v in r.values()))
    item_row = rows[item_row_no]
    wanted = ["光熱・水道","電気代","ガス代","都市ガス","プロパンガス","他の光熱","灯油","上下水道料"]
    fields = {}
    for c, v in item_row.items():
        s = str(v).strip()
        if s in wanted:
            fields[s] = c
    if len(fields) < len(wanted):
        raise RuntimeError("家計調査7-1の必要項目が不足: " + ",".join(set(wanted)-set(fields)))
    out = {}
    for rn, r in rows.items():
        if rn <= item_row_no:
            continue
        loc = str(r.get(8, "")).strip()
        if not loc:
            continue
        key = "全国" if loc.startswith("全国") else next((cap for cap in PREF_CAPITAL.values() if cap in loc), None)
        if not key:
            continue
        out[key] = {k: num(r.get(c)) for k, c in fields.items()}
    return out

def parse_monthly_household(blob):
    rows = xlsx_sheet(blob, "二人")
    header_no = next(rn for rn, r in rows.items() if any("東京都区部" in str(v) for v in r.values()) and any(str(v).strip()=="全国" for v in r.values()))
    header = rows[header_no]
    cols = {"全国": next(c for c,v in header.items() if str(v).strip()=="全国")}
    for cap in PREF_CAPITAL.values():
        c = next((c for c,v in header.items() if cap in str(v)), None)
        if c:
            cols[cap] = c
    label_rows = {}
    for rn, r in rows.items():
        for v in r.values():
            s = str(v).strip()
            if s in ("消費支出", "光熱・水道"):
                label_rows[s] = rn
    if set(label_rows) != {"消費支出","光熱・水道"}:
        raise RuntimeError("家計調査1-1の消費支出/光熱・水道を発見できません")
    out = {}
    for loc, c in cols.items():
        out[loc] = {
            "monthlyConsumptionYen": num(rows[label_rows["消費支出"]].get(c)),
            "monthlyUtilityWaterYen": num(rows[label_rows["光熱・水道"]].get(c)),
        }
    return out

def read_ssdse_trends():
    raw = fetch(SSDSE_B)
    text = raw.decode("cp932")
    rows = list(csv.reader(io.StringIO(text)))
    names = rows[1]
    idx = {name:i for i,name in enumerate(names)}
    c_cons = idx["消費支出（二人以上の世帯）"]
    c_util = idx["光熱・水道費（二人以上の世帯）"]
    out = {p:[] for p in PREF_CAPITAL}
    for r in rows[2:]:
        if len(r) <= max(c_cons,c_util) or r[2] not in out or not r[0].isdigit():
            continue
        cons = num(r[c_cons]); util = num(r[c_util])
        out[r[2]].append({
            "year": int(r[0]),
            "monthlyConsumptionYen": cons,
            "monthlyUtilityWaterYen": util,
            "utilityBurdenRate": round(util/cons*100, 2) if cons and util else None,
        })
    for p in out:
        out[p].sort(key=lambda x:x["year"])
    return out

def find_loc(data, loc):
    if loc in data:
        return data[loc]
    return next((v for k,v in data.items() if loc in k), None)

def round_int(v):
    return int(round(v)) if v is not None else None

def build_record(pref, cap, annual, monthly, price_index, trend):
    a = find_loc(annual, cap) or {}
    m = find_loc(monthly, cap) or {}
    electricity = a.get("電気代")
    gas = a.get("ガス代")
    other_heat = a.get("他の光熱")
    water = a.get("上下水道料")
    parts = [electricity, gas, other_heat]
    energy = sum(parts) if all(v is not None for v in parts) else None
    consumption = m.get("monthlyConsumptionYen")
    monthly_energy = energy / 12 if energy is not None else None
    return {
        "prefecture": pref,
        "capital": cap,
        "annualUtilityWaterYen": round_int(a.get("光熱・水道")),
        "annualEnergyYen": round_int(energy),
        "annualElectricityYen": round_int(electricity),
        "annualGasYen": round_int(gas),
        "annualCityGasYen": round_int(a.get("都市ガス")),
        "annualPropaneYen": round_int(a.get("プロパンガス")),
        "annualOtherHeatYen": round_int(other_heat),
        "annualKeroseneYen": round_int(a.get("灯油")),
        "annualWaterYen": round_int(water),
        "monthlyEnergyYen": round_int(monthly_energy),
        "monthlyUtilityWaterYen": round_int(m.get("monthlyUtilityWaterYen")),
        "monthlyConsumptionYen": round_int(consumption),
        "energyBurdenRate": round(monthly_energy/consumption*100, 2) if monthly_energy and consumption else None,
        "utilityBurdenRate": round((m.get("monthlyUtilityWaterYen") or 0)/consumption*100, 2) if consumption else None,
        "utilityPriceIndex": price_index,
        "trend": trend,
    }

def main():
    year, stat71 = discover_71()
    stat11 = discover_11(year)
    annual_url = f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={stat71}&fileKind=4"
    monthly_url = f"https://www.e-stat.go.jp/stat-search/file-download?statInfId={stat11}&fileKind=0"
    annual = parse_annual_breakdown(fetch(annual_url))
    monthly = parse_monthly_household(fetch(monthly_url))
    trends = read_ssdse_trends()

    price_path = ROOT / "public" / "data" / "economy-prices.json"
    price = json.loads(price_path.read_text(encoding="utf-8")) if price_path.exists() else {"records":[],"year":None}
    price_map = {r["prefecture"]: r.get("utilities") for r in price.get("records", [])}

    records = [
        build_record(pref, cap, annual, monthly, price_map.get(pref), trends.get(pref, []))
        for pref, cap in PREF_CAPITAL.items()
    ]

    nat_a = annual.get("全国") or {}
    nat_m = monthly.get("全国") or {}
    nat_energy = (nat_a.get("電気代") or 0) + (nat_a.get("ガス代") or 0) + (nat_a.get("他の光熱") or 0)
    nationwide = {
        "annualUtilityWaterYen": round_int(nat_a.get("光熱・水道")),
        "annualEnergyYen": round_int(nat_energy),
        "annualElectricityYen": round_int(nat_a.get("電気代")),
        "annualGasYen": round_int(nat_a.get("ガス代")),
        "annualOtherHeatYen": round_int(nat_a.get("他の光熱")),
        "annualKeroseneYen": round_int(nat_a.get("灯油")),
        "annualWaterYen": round_int(nat_a.get("上下水道料")),
        "monthlyEnergyYen": round_int(nat_energy/12),
        "monthlyUtilityWaterYen": round_int(nat_m.get("monthlyUtilityWaterYen")),
        "monthlyConsumptionYen": round_int(nat_m.get("monthlyConsumptionYen")),
        "energyBurdenRate": round((nat_energy/12)/(nat_m.get("monthlyConsumptionYen") or 1)*100, 2),
        "utilityBurdenRate": round((nat_m.get("monthlyUtilityWaterYen") or 0)/(nat_m.get("monthlyConsumptionYen") or 1)*100, 2),
    }

    payload = {
        "schemaVersion": 1,
        "householdYear": year,
        "householdScope": "家計調査・二人以上の世帯。地域値は都道府県庁所在市（東京都は東京都区部）。",
        "priceIndexYear": price.get("year"),
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "sources": {
            "household": f"総務省統計局 家計調査 {year}年 年報 第7-1表・詳細結果表 第1-1表",
            "householdUrl": "https://www.e-stat.go.jp/stat-search/files?cycle=7&toukei=00200561",
            "trend": "独立行政法人 統計センター SSDSE-B-2026",
            "price": "総務省統計局 小売物価統計調査（構造編） 消費者物価地域差指数",
        },
        "nationwide": nationwide,
        "records": records,
        "nationalSnapshot": {
            "period": "2025年11月",
            "publishedAt": "2026-02-27",
            "latestTablePeriod": "2026年2月",
            "latestTableUpdatedAt": "2026-05-29",
            "generation100mKwh": 624.1,
            "demand100mKwh": 632.0,
            "demandYoY": 0.3,
            "mixReported": [
                {"key":"thermal","label":"火力","share":75.7},
                {"key":"nuclear","label":"原子力","share":12.2},
                {"key":"newEnergy","label":"新エネルギー等","share":9.8},
                {"key":"hydro","label":"水力","share":7.4}
            ],
            "thermalFuelShare": [
                {"key":"lng","label":"LNG","share":35.3},
                {"key":"coal","label":"石炭","share":31.1},
                {"key":"oil","label":"石油","share":0.8}
            ],
            "topGeneration": [
                {"prefecture":"千葉県","generation100mKwh":61.8,"share":9.9},
                {"prefecture":"神奈川県","generation100mKwh":52.8,"share":8.5},
                {"prefecture":"愛知県","generation100mKwh":48.9,"share":7.8}
            ],
            "topDemand": [
                {"prefecture":"東京都","demand100mKwh":54.4,"share":9.0},
                {"prefecture":"愛知県","demand100mKwh":42.0,"share":7.0},
                {"prefecture":"大阪府","demand100mKwh":37.8,"share":6.3}
            ],
            "source": "資源エネルギー庁 電力調査統計 2025年11月分 結果概要",
            "sourceUrl": "https://www.enecho.meti.go.jp/statistics/electric_power/ep002/pdf/2025/0-2025.pdf",
            "note": "電力調査統計表そのものは2026年2月分まで更新済み。結果概要は2025年11月分を表示。新エネルギー等には、火力にも計上されるバイオマス・廃棄物が再計上されるため、表示比率を単純合計して100%とはしません。"
        },
        "security": {
            "energySelfSufficiency2024": 16.4,
            "renewableSurchargeFiscalYear": 2026,
            "renewableSurchargeYenPerKwh": 4.18,
            "renewableSurchargeExampleKwh": 400,
            "renewableSurchargeExampleYen": 1672,
            "selfSufficiencySource": "資源エネルギー庁「日本のエネルギー2025」",
            "selfSufficiencyUrl": "https://www.enecho.meti.go.jp/about/pamphlet/energy2025/02.html",
            "surchargeSource": "経済産業省 2026年度の再エネ賦課金単価",
            "surchargeUrl": "https://www.meti.go.jp/press/2025/03/20260319004/20260319004.html"
        }
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"energy: {len(records)} prefectures / household {year} -> {OUT}")
    return {"records": len(records), "year": year}

if __name__ == "__main__":
    with SourceRun("energy", "e-Stat家計調査 / SSDSE / 小売物価統計 / 資源エネルギー庁") as run:
        run.set_metrics(**main())
