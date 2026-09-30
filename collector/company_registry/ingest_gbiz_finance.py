from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sqlite3
import tempfile
import unicodedata
import zipfile
from datetime import datetime, timezone
from pathlib import Path

from .common import RAW, ensure_dirs, valid_corporate_number

GBIZ_FINANCE_DB = RAW / "gbiz-finance.sqlite"
LEGACY_SOURCE_URL = "https://content.info.gbiz.go.jp/download/legacy/standard/Zaimujoho_UTF-8_20251204.zip"

METRICS = {
    "netSales": ("売上高", "売上高（単位)", "売上高（単位）"),
    "operatingRevenue1": ("営業収益", "営業収益（単位）"),
    "operatingRevenue2": ("営業収入", "営業収入（単位）"),
    "grossOperatingRevenue": ("営業総収入", "営業総収入（単位）"),
    "ordinaryRevenue": ("経常収益", "経常収益（単位）"),
    "netPremiums": ("正味収入保険料", "正味収入保険料（単位）"),
}
METRICS.update({
    "ordinaryIncomeLoss": ("経常利益又は経常損失（△）", "経常利益又は経常損失（△）(単位)"),
    "netIncomeLoss": ("当期純利益又は当期純損失（△）", "当期純利益又は当期純損失（△）(単位)"),
    "capitalStock": ("資本金", "資本金(単位)", "資本金（単位）"),
    "netAssets": ("純資産額", "純資産額(単位)", "純資産額（単位）"),
    "totalAssets": ("総資産額", "総資産額(単位)", "総資産額（単位）"),
    "employees": ("従業員数", "従業員数(単位)", "従業員数（単位）"),
})


def first(row: dict[str, str], *keys: str) -> str:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return str(value).strip()
    return ""


def parse_integer(value: str) -> int | None:
    text = unicodedata.normalize("NFKC", str(value or "")).strip().replace(",", "")
    if not text:
        return None
    if text.startswith("△"):
        text = "-" + text[1:]
    if not re.fullmatch(r"-?\d+", text):
        raise ValueError(f"unexpected numeric value: {value!r}")
    return int(text)
def metric_value(row: dict[str, str], spec: tuple[str, ...]) -> tuple[int | None, str | None]:
    value = parse_integer(first(row, spec[0]))
    unit = first(row, *spec[1:]) or None
    return value, unit


def source_date_from_name(path: Path) -> str | None:
    match = re.search(r"(20\d{6})", path.name)
    if not match:
        return None
    value = match.group(1)
    return f"{value[:4]}-{value[4:6]}-{value[6:]}"


def shareholders(row: dict[str, str]) -> list[dict]:
    result = []
    for i in range(1, 6):
        name = first(row, f"大株主{i}")
        ratio = first(row, f"発行済株式総数に対する所有株式数の割合{i}")
        if name:
            result.append({"name": name, "ratio": float(ratio) if ratio else None})
    return result


def create_schema(conn: sqlite3.Connection) -> None:
    metric_columns = ",\n".join(f"{name} INTEGER, {name}_unit TEXT" for name in METRICS)
    conn.executescript(f"""
    PRAGMA journal_mode=OFF;
    PRAGMA synchronous=OFF;
    CREATE TABLE finance_records (
      corporate_number TEXT NOT NULL, name TEXT, address TEXT, accounting_standard TEXT,
      fiscal_year TEXT, period_order INTEGER NOT NULL, {metric_columns},
      shareholders_json TEXT NOT NULL, data_quality TEXT, source_name TEXT,
      acquisition_date TEXT, update_date TEXT, source_file TEXT NOT NULL,
      source_date TEXT, PRIMARY KEY(corporate_number, period_order, source_file)
    );
    CREATE INDEX idx_finance_corporate ON finance_records(corporate_number);
    CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """)
def ingest_zip(conn: sqlite3.Connection, path: Path) -> dict:
    date = source_date_from_name(path)
    with zipfile.ZipFile(path) as archive:
        csv_names = [x for x in archive.namelist() if x.lower().endswith('.csv')]
        if len(csv_names) != 1:
            raise RuntimeError(f"expected one finance CSV in {path.name}, got {csv_names}")
        with archive.open(csv_names[0]) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding='utf-8-sig', newline=''))
            if not reader.fieldnames or '法人番号' not in reader.fieldnames:
                raise RuntimeError(f"unexpected gBizINFO finance header: {reader.fieldnames}")
            rows = 0
            companies = set()
            for row in reader:
                corporate_number = first(row, '法人番号')
                if not valid_corporate_number(corporate_number):
                    raise RuntimeError(f"invalid corporate number in {path.name}: {corporate_number!r}")
                name = first(row, '法人名', '商号または名称', '法人名（法人番号）')
                address = first(row, '本社所在地', '登記住所', '本社所在地（法人番号）')
                values = []
                for spec in METRICS.values():
                    value, unit = metric_value(row, spec)
                    values.extend((value, unit))
                period = parse_integer(first(row, '回次'))
                if period is None:
                    raise RuntimeError(f"missing period for {corporate_number}")
                conn.execute(INSERT_SQL, (corporate_number, name, address,
                    first(row, '会計基準') or None, first(row, '事業年度') or None,
                    period, *values, json.dumps(shareholders(row), ensure_ascii=False),
                    first(row, 'データ品質') or None, first(row, '出典元') or None,
                    first(row, '最終取得日') or None, first(row, '最終更新日') or None,
                    path.name, date))
                rows += 1
                companies.add(corporate_number)
    conn.commit()
    return {'rows': rows, 'companies': len(companies), 'sourceDate': date}
BASE_COLUMNS = [
    'corporate_number', 'name', 'address', 'accounting_standard', 'fiscal_year', 'period_order'
]
METRIC_COLUMNS = [name for metric in METRICS for name in (metric, f'{metric}_unit')]
TAIL_COLUMNS = [
    'shareholders_json', 'data_quality', 'source_name', 'acquisition_date',
    'update_date', 'source_file', 'source_date'
]
ALL_COLUMNS = BASE_COLUMNS + METRIC_COLUMNS + TAIL_COLUMNS
INSERT_SQL = (
    f"INSERT OR REPLACE INTO finance_records ({','.join(ALL_COLUMNS)}) "
    f"VALUES ({','.join('?' for _ in ALL_COLUMNS)})"
)


def build_database(path: Path, source_url: str | None = None) -> dict:
    ensure_dirs()
    fd, temp_name = tempfile.mkstemp(prefix='gbiz-finance-', suffix='.sqlite', dir=RAW)
    os.close(fd)
    temp_db = Path(temp_name)
    try:
        conn = sqlite3.connect(temp_db)
        create_schema(conn)
        stats = ingest_zip(conn, path)
        meta = {
            'dataset': 'gBizINFO finance', 'sourceFile': path.name,
            'sourceDate': stats.get('sourceDate') or '',
            'sourceUrl': source_url or '',
            'generatedAt': datetime.now(timezone.utc).isoformat(),
            'rows': str(stats['rows']), 'companies': str(stats['companies']),
        }
        conn.executemany('INSERT INTO metadata(key,value) VALUES (?,?)', meta.items())
        conn.commit()
        conn.close()
        temp_db.replace(GBIZ_FINANCE_DB)
        return {**stats, 'db': str(GBIZ_FINANCE_DB), 'sourceUrl': source_url}
    except Exception:
        temp_db.unlink(missing_ok=True)
        raise
def default_input() -> Path:
    current = sorted((RAW / 'gbiz').glob('*.zip'), key=lambda p: p.stat().st_mtime, reverse=True)
    finance_current = [p for p in current if 'zaimu' in p.name.lower() or 'finance' in p.name.lower()]
    if finance_current:
        return finance_current[0]
    legacy = RAW / 'gbiz-legacy' / 'Zaimujoho_UTF-8_20251204.zip'
    if legacy.exists():
        return legacy
    raise SystemExit('No gBizINFO finance ZIP found. Download current finance or bootstrap the legacy snapshot.')


def main(input_path: str | None = None, source_url: str | None = None) -> dict:
    path = Path(input_path).expanduser().resolve() if input_path else default_input().resolve()
    if not path.exists():
        raise SystemExit(f'gBizINFO finance ZIP not found: {path}')
    if source_url is None and '20251204' in path.name:
        source_url = LEGACY_SOURCE_URL
    result = build_database(path, source_url)
    print(f'gbiz finance ingest {result}', flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--input')
    parser.add_argument('--source-url')
    args = parser.parse_args()
    main(args.input, args.source_url)
