#!/usr/bin/env python3
"""Annual prefecture wage reference tables, retaining original survey breaks."""
import argparse
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
    from collect_employment_economy import fetch, full_pref, num, PREFECTURE_ORDER, xlsx_cells, xlsx_shared
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_employment_economy import fetch, full_pref, num, PREFECTURE_ORDER, xlsx_cells, xlsx_shared

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'public/data/employment-wage-history.json'
RAW = ROOT / 'data/raw/employment-wage-history'
TABLES = {
    2001: ('000001256992', 0), 2002: ('000001256869', 0),
    2003: ('000001256747', 0), 2004: ('000001256625', 0),
    2005: ('000001256459', 0), 2006: ('000001182365', 0),
    2007: ('000001254439', 0), 2008: ('000002951843', 0),
    2009: ('000007334729', 0), 2010: ('000008283875', 0),
    2011: ('000012743203', 0), 2012: ('000016356587', 0),
    2013: ('000023602759', 0), 2014: ('000028447495', 0),
    2015: ('000028996942', 0), 2016: ('000031228837', 0),
    2017: ('000031559899', 0), 2018: ('000031683197', 0),
    2019: ('000031919912', 0), 2020: ('000032088463', 0),
    2021: ('000032183057', 4), 2022: ('000040029286', 4),
    2023: ('000040163846', 4), 2024: ('000040247959', 4),
    2025: ('000040421202', 4),
}
SOURCE = 'https://www.e-stat.go.jp/stat-search/files?toukei=00450091&tstat=000001011429'
FIELDS = ['monthlyCashSalaryThousandYen', 'monthlyScheduledSalaryThousandYen',
          'annualBonusThousandYen', 'estimatedAnnualCashThousandYen',
          'averageAge', 'averageTenureYears', 'scheduledHours', 'overtimeHours']
CHANGES_URL = 'https://www.mhlw.go.jp/toukei/list/dl/chingin_zenkoku_b-1.pdf'
BREAKS = [
    {'year': 2004, 'label': '産業分類変更', 'sourceUrl': CHANGES_URL},
    {'year': 2005, 'label': '調査項目・雇用形態区分変更', 'sourceUrl': CHANGES_URL},
    {'year': 2009, 'label': '産業分類変更', 'sourceUrl': CHANGES_URL},
    {'year': 2018, 'label': '労働者の定義変更', 'sourceUrl': 'https://www.mhlw.go.jp/toukei/list/dl/chinginkouzou_02.pdf'},
    {'year': 2019, 'label': '調査対象産業の範囲変更', 'sourceUrl': 'https://www.mhlw.go.jp/toukei/itiran/roudou/chingin/kouzou/19/dl/02.pdf'},
    {'year': 2020, 'label': '調査項目・推計方法変更', 'sourceUrl': 'https://www.mhlw.go.jp/toukei/itiran/roudou/chingin/kouzou/detail/sokyu.html'},
]

def compact(value):
    return re.sub(r'\s+', '', str(value or ''))

def table_rows(raw):
    if raw[:2] == b'PK':
        ns = '{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            cells = xlsx_cells(z, 1, xlsx_shared(z, ns), ns)
        def col(ref):
            n = 0
            for c in re.match(r'[A-Z]+', ref).group(): n = n * 26 + ord(c) - 64
            return n - 1
        width = max(map(col, cells)) + 1
        rows = [[''] * width for _ in range(max(int(re.search(r'\d+', r).group()) for r in cells))]
        for ref, value in cells.items(): rows[int(re.search(r'\d+', ref).group()) - 1][col(ref)] = value
        return rows
    import xlrd
    book = xlrd.open_workbook(file_contents=raw)
    sheet = book.sheet_by_index(0)
    if sheet.name not in ('全労働者', '全', '男女計', '参考４'):
        raise ValueError(f'Unexpected sex-total sheet: {sheet.name}')
    return [sheet.row_values(r) for r in range(sheet.nrows)]

def parse_table(raw):
    rows = table_rows(raw)
    header = ''.join(compact(v) for row in rows[:11] for v in row)
    if not all(t in header for t in ('都道府県', '現金', '所定内', '年間賞与')):
        raise ValueError('Wage reference table headers changed')
    if not ('男女計' in header or '全労働者' in header):
        raise ValueError('Sex-total scope missing')
    unit_rows = [r for r in rows[:14] if '歳' in r and '千円' in r]
    if len(unit_rows) != 1: raise ValueError('Unit row missing or ambiguous')
    units = unit_rows[0]
    age_col = units.index('歳')
    if len(units[age_col:age_col + 8]) != 8 or not all(str(v).startswith(u) for v, u in zip(units[age_col:age_col + 8], ['歳', '年', '時間', '時間', '千円', '千円', '千円', '十人'])):
        raise ValueError('Wage units/column order changed')
    out = {}
    for row in rows:
        names = [full_pref(v) for v in row[:age_col] if isinstance(v, str)]
        matches = [n for n in names if n in PREFECTURE_ORDER]
        if not matches: continue
        if len(matches) != 1 or matches[0] in out: raise ValueError('Duplicate/ambiguous prefecture')
        vals = [num(v) for v in row[age_col:age_col + 8]]
        age, tenure, hours, overtime, monthly, scheduled, bonus, workers = vals
        if any(v is None for v in vals): raise ValueError('Missing wage fields')
        if not (0 < scheduled <= monthly < 1000 and bonus >= 0 and 15 <= age <= 80 and 0 <= tenure <= 60 and 0 < hours <= 250 and 0 <= overtime <= 100 and workers > 0):
            raise ValueError('Invalid wage table values')
        out[matches[0]] = [monthly, scheduled, bonus, round(monthly * 12 + bonus, 1), age, tenure, hours, overtime]
    if set(out) != set(PREFECTURE_ORDER): raise ValueError(f'Expected 47 canonical prefectures, got {len(out)}')
    return out

def main(offline=False):
    RAW.mkdir(parents=True, exist_ok=True)
    per_year, sources = {}, []
    for year, (sid, kind) in TABLES.items():
        url = f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}'
        path = RAW / f'wage-{year}-{sid}.{"xlsx" if kind == 4 else "xls"}'
        raw = path.read_bytes() if offline else fetch(url)
        data = parse_table(raw)
        if not offline: path.write_bytes(raw)
        per_year[year] = data
        sources.append({'year': year, 'statInfId': sid, 'fileKind': kind,
                        'sourceUrl': f'https://www.e-stat.go.jp/stat-search/files?stat_infid={sid}',
                        'downloadUrl': url, 'rawFile': path.name, 'sha256': hashlib.sha256(raw).hexdigest()})
        print(f'wage history {year}: {len(data)} prefectures')
    payload = {'schemaVersion': 2, 'generatedAt': datetime.now(timezone.utc).isoformat(),
               'source': '厚生労働省 賃金構造基本統計調査 都道府県別参考表',
               'sourceUrl': SOURCE, 'years': sorted(TABLES), 'fields': ['year'] + FIELDS,
               'scope': '一般労働者・男女計・産業計・企業規模10人以上。各年の公表値（遡及再集計系列ではない）',
               'breaks': BREAKS, 'sources': sources,
               'periodNote': '月額は調査年6月、賞与等は原則として調査前年1年間。推計年収は月額×12＋賞与等のDATLUME算出参考値。',
               'records': [{'prefecture': p, 'values': [[y] + per_year[y][p] for y in TABLES]} for p in PREFECTURE_ORDER]}
    OUT.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return {'records': len(PREFECTURE_ORDER) * len(TABLES), 'prefectures': 47, 'startYear': min(TABLES), 'endYear': max(TABLES)}

if __name__ == '__main__':
    args = argparse.ArgumentParser()
    args.add_argument('--offline', action='store_true', help='Rebuild using saved official originals')
    options = args.parse_args()
    with SourceRun('employment_wage_history', '厚生労働省 賃金構造基本統計 都道府県別時系列') as run:
        run.set_metrics(**main(options.offline))
