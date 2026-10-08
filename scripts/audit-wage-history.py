#!/usr/bin/env python3
"""Compare every published wage field with the saved official workbook cells."""
import argparse, hashlib, io, json, sys, re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from collector.collect_employment_wage_history import TABLES, BREAKS
from collector.collect_employment_economy import PREFECTURE_ORDER,full_pref
p=argparse.ArgumentParser();p.add_argument('--require-raw',action='store_true');args=p.parse_args()
data=json.loads((ROOT/'public/data/employment-wage-history.json').read_text())
assert data['schemaVersion']==2 and data['years']==list(TABLES)
assert data['breaks']==BREAKS
assert [r['prefecture'] for r in data['records']]==PREFECTURE_ORDER
assert len(data['sources'])==len(TABLES)
checks=0;skipped=[]
for source in data['sources']:
    year=source['year'];sid,kind=TABLES[year]
    assert source['statInfId']==sid and source['fileKind']==kind
    assert source['downloadUrl']==f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind={kind}'
    path=ROOT/'data/raw/employment-wage-history'/source['rawFile']
    assert path.name==f'wage-{year}-{sid}.{"xlsx" if kind==4 else "xls"}'
    if not path.exists():
        if args.require_raw: raise AssertionError(f'Missing raw {path.name}')
        skipped.append(year);continue
    raw=path.read_bytes();assert hashlib.sha256(raw).hexdigest()==source['sha256'];checks+=1
    if kind==4:
        from openpyxl import load_workbook
        book=load_workbook(io.BytesIO(raw),data_only=True,read_only=True)
        rows=[list(r) for r in book.worksheets[0].values];book.close()
    else:
        import xlrd
        sheet=xlrd.open_workbook(file_contents=raw).sheet_by_index(0)
        rows=[sheet.row_values(i) for i in range(sheet.nrows)]
    units=next(row for row in rows[:14] if '歳' in row and '千円' in row);offset=units.index('歳')
    original={}
    for row in rows:
        names=[full_pref(v) for v in row[:offset] if isinstance(v,str)]
        matches=[n for n in names if n in PREFECTURE_ORDER]
        if not matches:continue
        assert len(matches)==1 and matches[0] not in original
        age,tenure,hours,overtime,monthly,scheduled,bonus,workers=row[offset:offset+8]
        original[matches[0]]=[year,monthly,scheduled,bonus,round(monthly*12+bonus,1),age,tenure,hours,overtime]
    assert set(original)==set(PREFECTURE_ORDER)
    for record in data['records']:
        published=next(v for v in record['values'] if v[0]==year)
        assert published==original[record['prefecture']],f'{year} {record["prefecture"]}: raw mismatch'
        checks+=len(published)
latest=json.loads((ROOT/'public/data/employment-economy-2026.json').read_text())
for row in latest['records']:
    current=next(r['values'][-1] for r in data['records'] if r['prefecture']==row['prefecture'])
    assert current[1:4]==[row[k] for k in ['monthlyCashSalaryThousandYen','monthlyScheduledSalaryThousandYen','annualBonusThousandYen']]
    checks+=3
print(f'wage history audit: {checks} raw/latest comparisons, 0 failures; missing originals={skipped}')
