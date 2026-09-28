#!/usr/bin/env python3
import csv, io, json, math, urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.canonical_metrics import assert_can_publish
    from core.raw_store import save_json as save_raw_json
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.canonical_metrics import assert_can_publish
    from collector.core.raw_store import save_json as save_raw_json
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
BASE_DATA = ROOT / "public" / "data" / "municipality-stats-2026.json"
OUT = ROOT / "public" / "data" / "municipality-social-indicators.json"
DATASET = OUT.name
SOURCE_ID = "estat_dashboard_social_population"
API = "https://dashboard.e-stat.go.jp/api/1.0/Csv/getData"
SOURCE_PAGE = "https://dashboard.e-stat.go.jp/"
API_GUIDE = "https://dashboard.e-stat.go.jp/static/api"
UA = {"User-Agent": "DATLUME/1.0 (+https://datlume.com/)"}

METRICS = [
    {"metricId":"municipality.health.physicians","field":"physicians","label":"医師数","indicatorCode":"1505040000000010000","cycle":3,"unit":"人","integer":True,"minCoverage":0.99},
    {"metricId":"municipality.health.hospital_beds","field":"hospitalBeds","label":"病院病床数","indicatorCode":"1505030000000010000","cycle":3,"unit":"床","integer":True,"minCoverage":0.99},
    {"metricId":"municipality.environment.waste_daily_per_capita","field":"wasteDailyPerCapita","label":"1人1日当たりごみ排出量","indicatorCode":"1405050102000010010","cycle":4,"unit":"g/人日","minCoverage":0.98},
    {"metricId":"municipality.environment.recycling_rate","field":"recyclingRate","label":"ごみリサイクル率","indicatorCode":"1405050800000020010","cycle":4,"unit":"%","minCoverage":0.98},
    {"metricId":"municipality.education.libraries","field":"libraries","label":"図書館数","indicatorCode":"1202010400000010010","cycle":3,"unit":"館","integer":True,"minCoverage":0.99},
]


def fetch_csv(metric):
    params = {
        "Lang": "JP", "IndicatorCode": metric["indicatorCode"], "Cycle": metric["cycle"],
        "RegionalRank": 4, "IsSeasonalAdjustment": 1, "MetaGetFlg": "Y", "SectionHeaderFlg": 1,
    }
    url = API + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as response:
        text = response.read().decode("utf-8-sig")
    rows = list(csv.reader(io.StringIO(text)))
    header_idx = next((i for i, row in enumerate(rows) if row and row[0] == "indicatorCd"), None)
    if header_idx is None:
        raise ValueError(f"e-Stat API header not found: {metric['metricId']}")
    header = rows[header_idx]
    records = [dict(zip(header, row)) for row in rows[header_idx + 1:] if len(row) >= len(header)]
    save_raw_json(SOURCE_ID, metric["indicatorCode"], {"url": url, "metricId": metric["metricId"], "rows": records})
    return url, records


def number(value, integer=False):
    s = str(value or "").replace(",", "").strip()
    if not s or s in {"-", "...", "x", "X"}:
        return None
    try:
        n = float(s)
    except ValueError:
        return None
    if not math.isfinite(n):
        return None
    return int(n) if integer and n.is_integer() else n


def latest_values(metric, allowed_codes):
    url, rows = fetch_csv(metric)
    usable = [r for r in rows if r.get("regionCd") in allowed_codes and number(r.get("value"), metric.get("integer", False)) is not None]
    times = sorted({r.get("timeCd") for r in usable if r.get("timeCd")})
    if not times:
        raise ValueError(f"no usable e-Stat values: {metric['metricId']}")
    latest = times[-1]
    selected = [r for r in usable if r.get("timeCd") == latest]
    by_code = {r["regionCd"]: number(r.get("value"), metric.get("integer", False)) for r in selected}
    coverage = len(by_code) / max(1, len(allowed_codes))
    minimum = metric.get("minCoverage", 0.0)
    if coverage < minimum:
        raise ValueError(f"coverage too low for {metric['metricId']}: {len(by_code)}/{len(allowed_codes)} < {minimum:.0%}")
    period_name = next((r.get("timeNm") for r in selected if r.get("timeNm")), None)
    year = int(latest[:4]) if latest[:4].isdigit() else None
    return {"url": url, "timeCd": latest, "period": period_name or (str(year) if year else latest), "year": year, "values": by_code, "coverageCount": len(by_code), "coverageRate": round(coverage * 100, 2)}


def main():
    base = json.loads(BASE_DATA.read_text(encoding="utf-8"))
    base_rows = base.get("records", [])
    if len(base_rows) != 1741 or len({r.get("code") for r in base_rows}) != 1741:
        raise ValueError(f"canonical municipality base must contain 1741 unique codes, got {len(base_rows)}")
    by_code = {r["code"]: r for r in base_rows}
    allowed_codes = set(by_code)

    results, metric_meta = {}, []
    for metric in METRICS:
        assert_can_publish(metric["metricId"], SOURCE_ID, DATASET, metric["field"])
        result = latest_values(metric, allowed_codes)
        results[metric["field"]] = result["values"]
        metric_meta.append({k: metric[k] for k in ("metricId", "field", "label", "indicatorCode", "unit")} | {
            "year": result["year"], "period": result["period"],
            "coverageCount": result["coverageCount"], "coverageRate": result["coverageRate"],
        })
        print(f"{metric['field']}: {result['period']} / {result['coverageCount']}/{len(allowed_codes)} ({result['coverageRate']}%)")

    records = []
    for code, base_row in by_code.items():
        row = {k: base_row.get(k) for k in ("code", "prefecture", "municipality", "lon", "lat")}
        for metric in METRICS:
            row[metric["field"]] = results[metric["field"]].get(code)
        records.append(row)

    payload = {
        "schemaVersion": 1,
        "generatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "e-Stat 統計ダッシュボード（社会・人口統計体系）",
        "sourceUrl": SOURCE_PAGE,
        "apiGuideUrl": API_GUIDE,
        "credit": "「e-Stat 統計ダッシュボード」（https://dashboard.e-stat.go.jp/）を加工して作成",
        "canonicalMunicipalityBase": BASE_DATA.name,
        "municipalityCount": len(records),
        "metrics": metric_meta,
        "records": records,
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    min_coverage = min(m["coverageRate"] for m in metric_meta)
    print(f"social-population: {len(records)} municipalities / {len(metric_meta)} metrics / min coverage {min_coverage}% / {OUT}")
    return {"records": len(records), "municipalities": len(records), "metricCount": len(metric_meta), "minCoverageRate": min_coverage}


if __name__ == "__main__":
    with SourceRun("social_population", "e-Stat 統計ダッシュボード（社会・人口統計体系）") as run:
        run.set_metrics(**main())
