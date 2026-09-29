#!/usr/bin/env python3
import csv, io, sqlite3, sys, zipfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'collector'))
import collect_jetro as jetro
from import_geps import geps_amount_fields

DB=ROOT/'data/public_it.db'
RAW=ROOT/'data/raw/geps-open-awards'
failures=[]
checks=0

def check(ok,message):
    global checks
    checks+=1
    if not ok: failures.append(message)

def zip_rows(path):
    with zipfile.ZipFile(path) as z:
        csvs=[n for n in z.namelist() if n.lower().endswith('.csv')]
        check(len(csvs)==1,f'{path.name}: expected exactly one CSV')
        if len(csvs)!=1:return []
        return list(csv.reader(io.TextIOWrapper(z.open(csvs[0]),encoding='utf-8-sig',newline='')))
def main():
    conn=sqlite3.connect(DB)
    geps_total=0
    for path in sorted(RAW.glob('successful_bid_record_info_all_20*.zip')):
        rows=zip_rows(path)
        if not rows:continue
        dates=[r[2] for r in rows if len(r)==8]
        start,end=min(dates),max(dates)
        actual=conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%' AND award_date BETWEEN ? AND ?",(start,end)).fetchone()[0]
        check(actual==len(rows),f'{path.name}: DB={actual} official={len(rows)}')
        expected_unit=sum(1 for r in rows if len(r)==8 and geps_amount_fields(r[1],r[3])[0] is None)
        amounts,unit=conn.execute("""SELECT
          SUM(CASE WHEN award_amount>0 THEN 1 ELSE 0 END),
          SUM(CASE WHEN award_amount IS NULL AND detail_text LIKE '落札価格（単価）:%' THEN 1 ELSE 0 END)
          FROM procurements WHERE source_id LIKE 'geps:%' AND award_date BETWEEN ? AND ?""",(start,end)).fetchone()
        check((amounts or 0)+(unit or 0)==len(rows),f'{path.name}: classified={amounts}+{unit} official={len(rows)}')
        check((unit or 0)==expected_unit,f'{path.name}: unit prices DB={unit} expected={expected_unit}')
        geps_total+=len(rows)
    cutoff=jetro.prepare_canonical_procurements(conn)
    duplicate_jetro=conn.execute("SELECT COUNT(*) FROM canonical_procurements WHERE source_id LIKE 'jetro:%' AND notice_type LIKE '%落札者等の公示%' AND notice_date BETWEEN '2021-04-01' AND ?",(cutoff,)).fetchone()[0] if cutoff else 0
    check(duplicate_jetro==0,f'canonical view contains {duplicate_jetro} duplicate JETRO award notices through {cutoff}')
    real_amounts=conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%' AND typeof(award_amount)='real'").fetchone()[0]
    check(real_amounts==0,f'GEPS contains {real_amounts} fractional total amounts')
    explicit_unit_totals=conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%' AND title LIKE '%単価%' AND award_amount IS NOT NULL").fetchone()[0]
    check(explicit_unit_totals==0,f'GEPS contains {explicit_unit_totals} explicit unit-price rows as totals')
    geps_db=conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%'").fetchone()[0]
    historical=conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%' AND award_date<'2021-04-01'").fetchone()[0]
    check(geps_db==historical+geps_total,f'GEPS total mismatch db={geps_db} historical={historical} annual={geps_total}')
    yok=conn.execute("SELECT COUNT(*),SUM(CASE WHEN award_amount>0 THEN 1 ELSE 0 END) FROM canonical_procurements WHERE source_id LIKE 'yokohama:%' AND detail_fetched=1").fetchone()
    check((yok[0] or 0)>0,'Yokohama result rows missing')
    check((yok[1] or 0)<=yok[0],f'Yokohama amount count invalid {yok}')
    print(f'procurement award audit: {checks} checks / GEPS annual={geps_total} / cutoff={cutoff} / failures={len(failures)}')
    for f in failures:print('FAIL',f)
    if failures:raise SystemExit(1)

if __name__=='__main__':main()
