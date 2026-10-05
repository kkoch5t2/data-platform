from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sqlite3
import tempfile
import unicodedata
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data/raw/shokuba"
DB = RAW / "workplace.sqlite"
PAGE = "https://shokuba.mhlw.go.jp/shokuba/utilize/utilize010.do"
DOWNLOAD = "https://shokuba.mhlw.go.jp/shokuba/utilize/download010?lang=JA"
LABEL = "厚生労働省 しょくばらぼ"
# Exact official headers: never infer a metric from a similar column.
SPECS = (
    ("overtime", "月平均所定外労働時間", "月平均所定外労働", "時間", "", ""),
    ("legalOvertime", "対象労働者全体の月平均の法定時間外労働時間と法定休日労働時間の合計-平均残業時間（詳細）",
     "月平均の法定時間外・休日労働", "時間",
     "対象労働者全体の月平均の法定時間外労働時間と法定休日労働時間の合計-範囲（詳細）",
     "対象労働者全体の月平均の法定時間外労働時間と法定休日労働時間の合計-注記（詳細）"),
    ("paidLeaveDays", "正社員の有給休暇取得日数", "有給取得日数", "日", "", ""),
    ("paidLeaveRate", "年次有給休暇取得率（全体）-取得率", "有給取得率（全体）", "%",
     "", "年次有給休暇取得率（全体）-注記"),
    ("paidLeaveRateByGroup", "年次有給休暇取得率（雇用管理区分）-取得率（一覧）", "有給取得率（区分別）", "%",
     "年次有給休暇取得率（雇用管理区分）-範囲（一覧）",
     "年次有給休暇取得率（雇用管理区分）-注記(一覧)"),
    ("averageAge", "従業員の平均年齢", "従業員の平均年齢", "歳", "", ""),
)
HIRING = {
    "graduates": ("新卒採用・定着", "新卒者の採用・定着状況(前年度/2年度前/3年度前)"),
    "youngExperienced": ("35歳未満の中途採用・定着", "新卒者等以外（35歳未満）の採用・定着状況(前年度/2年度前/3年度前)"),
}

def text(value):
    return str(value or "").strip()

def number(value, unit):
    value = unicodedata.normalize("NFKC", text(value))
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*" + re.escape(unit), value)
    return float(match.group(1)) if match else None

def normalize_row(row, source_date):
    corp = text(row.get("法人番号"))
    if not re.fullmatch(r"[0-9]{13}", corp):
        return None
    metrics = {}
    for key, column, label, unit, scope_column, note_column in SPECS:
        raw = text(row.get(column))
        value = number(raw, unit)
        if value is None:
            continue
        scope = text(row.get(scope_column))
        if key == "paidLeaveDays":
            scope = "正社員"
        metrics[key] = {"label": label, "value": value, "display": raw, "unit": unit,
                        "scope": scope, "note": text(row.get(note_column)),
                        "sourceColumn": column}
    hiring = {}
    for key, (label, prefix) in HIRING.items():
        vals = {}
        for field, suffix in [("hires", "-男女計"), ("leavers", "-離職者数")]:
            raw = text(row.get(prefix + suffix))
            parts = raw.split("/")
            if len(parts) == 3 and all(number(v, "人") is not None for v in parts):
                vals[field] = [{"value": number(v, "人"), "display": text(v)} for v in parts]
        if vals:
            hiring[key] = {"label": label, **vals}
    if not metrics and not hiring:
        return None
    return {"corporateNumber": corp, "sourceName": text(row.get("企業名")),
            "sourceDate": source_date, "sourceUpdatedAt": text(row.get("更新日時")),
            "sourceUrl": PAGE, "metrics": metrics, "hiring": hiring}

def load_workplaces(numbers):
    if not DB.exists():
        return {}, {}
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    meta = dict(conn.execute("SELECT key,value FROM metadata"))
    result = {}
    for number_ in sorted(set(str(n) for n in numbers if n)):
        row = conn.execute("SELECT payload FROM workplaces WHERE corporate_number=?", (number_,)).fetchone()
        if row:
            result[number_] = json.loads(row[0])
    conn.close()
    return result, meta

def ingest(path):
    RAW.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    handle = tempfile.NamedTemporaryFile(dir=RAW, suffix=".sqlite", delete=False)
    target = Path(handle.name)
    handle.close()
    try:
        conn = sqlite3.connect(target)
        conn.execute("CREATE TABLE workplaces(corporate_number TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        conn.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL)")
        counts = {"records": 0, "usableCompanies": 0, "invalidCorporateNumbers": 0}
        metric_counts = {}
        seen = set()
        with zipfile.ZipFile(path) as z:
            names = [n for n in z.namelist() if re.fullmatch(r"shokuba_\d{8}\.csv", n)]
            if len(names) != 1:
                raise ValueError("Expected one official dated shokuba CSV")
            name = names[0]
            stamp = re.search(r"(\d{8})", name)[1]
            date = datetime.strptime(stamp, "%Y%m%d").date().isoformat()
            if date > datetime.now(ZoneInfo("Asia/Tokyo")).date().isoformat():
                raise ValueError("Source date is in the future")
            reader = csv.DictReader(io.TextIOWrapper(z.open(name), encoding="cp932", newline=""))
            required = {"法人番号", "企業名", "更新日時"}
            required.update(s[1] for s in SPECS)
            required.update(s[4] for s in SPECS if s[4])
            required.update(s[5] for s in SPECS if s[5])
            required.update(prefix + suffix for _, prefix in HIRING.values() for suffix in ("-男女計", "-離職者数"))
            if not required.issubset(reader.fieldnames or []):
                raise ValueError("Official CSV schema changed: missing required headers")
            for row in reader:
                if None in row or any(v is None for v in row.values()):
                    raise ValueError("Malformed CSV row")
                counts["records"] += 1
                corp = text(row.get("法人番号"))
                if not re.fullmatch(r"[0-9]{13}", corp):
                    counts["invalidCorporateNumbers"] += 1
                    continue
                if corp in seen:
                    raise ValueError(f"Duplicate corporate number: {corp}")
                seen.add(corp)
                normalized = normalize_row(row, date)
                if normalized is not None:
                    conn.execute("INSERT INTO workplaces VALUES(?,?)",
                                 (corp, json.dumps(normalized, ensure_ascii=False, separators=(",", ":"))))
                    counts["usableCompanies"] += 1
                    for key in normalized["metrics"]:
                        metric_counts[key] = metric_counts.get(key, 0) + 1
            if counts["records"] < 100000 or counts["usableCompanies"] < 10000:
                raise ValueError(f"Unexpected coverage regression: {counts}")
        old_count = 0
        if DB.exists():
            old = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
            old_count = old.execute("SELECT COUNT(*) FROM workplaces").fetchone()[0]
            old.close()
        if old_count and counts["usableCompanies"] < old_count * .9:
            raise ValueError("Workplace coverage fell by more than 10%")
        meta = {**counts, "sourceDate": date, "sourceFile": name, "sha256": digest,
                "sourceUrl": PAGE, "metricCounts": json.dumps(metric_counts, ensure_ascii=False),
                "normalizedAt": datetime.now(timezone.utc).isoformat()}
        conn.executemany("INSERT INTO metadata VALUES(?,?)", [(k, str(v)) for k, v in meta.items()])
        conn.commit()
        conn.close()
        target.replace(DB)
        return meta
    finally:
        target.unlink(missing_ok=True)

def download():
    RAW.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(DOWNLOAD, headers={"User-Agent": "DATLUME/1.0 (+https://datlume.com/)"})
    with urllib.request.urlopen(req, timeout=180) as response:
        with tempfile.NamedTemporaryFile(dir=RAW, suffix=".zip", delete=False) as file:
            target = Path(file.name)
            try:
                while chunk := response.read(1024 * 1024):
                    file.write(chunk)
                file.flush()
                if not zipfile.is_zipfile(target):
                    raise ValueError("Official download did not return a ZIP")
            except BaseException:
                target.unlink(missing_ok=True)
                raise
    # Keep each original snapshot; do not delete older evidence.
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    destination = RAW / f"shokuba-{datetime.now(timezone.utc).date()}-{digest[:12]}.zip"
    target.replace(destination)
    return destination

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--zip", type=Path)
    args = parser.parse_args()
    with SourceRun("shokuba", LABEL) as run:
        meta = ingest(args.zip or download())
        run.set_metrics(records=int(meta["records"]), usableCompanies=int(meta["usableCompanies"]),
                        sourceDate=meta["sourceDate"], sha256=meta["sha256"])
        print({k: meta[k] for k in ("records", "usableCompanies", "sourceDate", "invalidCorporateNumbers")})

if __name__ == "__main__":
    main()
