#!/usr/bin/env python3
import argparse, csv, hashlib, http.client, io, json, sqlite3, time, urllib.error, urllib.parse, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, classify, stable_id, norm, init_db, export_json
    from import_geps import MINISTRIES, BID_METHODS, award_method_label, geps_amount_fields, normalize_existing_unit_prices
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, classify, stable_id, norm, init_db, export_json
    from collector.import_geps import MINISTRIES, BID_METHODS, award_method_label, geps_amount_fields, normalize_existing_unit_prices

ROOT=Path(__file__).resolve().parents[1]
RAW=ROOT/'data/raw/geps-open-awards';RAW.mkdir(parents=True,exist_ok=True)
SOURCE_URL='https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201'
DOWNLOAD_URL='https://api.p-portal.go.jp/pps-web-biz/UAB03/OAB0301'
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
def download_zip(year):
    name=f'successful_bid_record_info_all_{year}.zip'
    url=DOWNLOAD_URL+'?'+urllib.parse.urlencode({'fileversion':'v001','filename':name})
    req=urllib.request.Request(url,headers=UA)
    for attempt in range(1,5):
        try:
            with urllib.request.urlopen(req,timeout=60) as r:
                data=r.read()
            break
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.IncompleteRead) as exc:
            if isinstance(exc,urllib.error.HTTPError) and exc.code not in (429,500,502,503,504):
                raise
            if attempt==4:
                raise
            delay=2**attempt
            print(f'geps {year}: download retry {attempt}/3 after {type(exc).__name__}; waiting {delay}s',flush=True)
            time.sleep(delay)
    path=RAW/name;path.write_bytes(data)
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        members=[x for x in z.namelist() if x.lower().endswith('.csv')]
        if len(members)!=1: raise RuntimeError(f'{name}: expected 1 csv, got {members}')
        rows=list(csv.reader(io.TextIOWrapper(z.open(members[0]),encoding='utf-8-sig',newline='')))
    if not rows or any(len(row)!=8 for row in rows[:100]):
        raise RuntimeError(f'{name}: invalid row format')
    return path,rows

def stable_record_id(row):
    case_no,title,award_date,price,ministry_cd,method_cd,winner,corp_no=row
    identity='|'.join([case_no,award_date,corp_no or '',norm(winner or '')])
    return hashlib.sha1(identity.encode('utf-8')).hexdigest()[:16]
def upsert(conn,row):
    case_no,title,award_date,price,ministry_cd,method_cd,winner,corp_no=row
    agency=MINISTRIES.get(ministry_cd)
    if not agency: raise ValueError(f'unknown GEPS ministry code: {ministry_cd}')
    method=BID_METHODS.get(method_cd,method_cd)
    amount,price_detail=geps_amount_fields(title,price)
    is_it,tags,category,category_tags=classify(title)
    org_id=stable_id('org',agency); company_id=stable_id('co',winner) if winner else None
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,agency))
    if company_id: conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)',(company_id,winner,norm(winner)))
    sid=f'geps:{case_no}:{stable_record_id(row)}'; aid=f'{case_no}:{award_date}:{corp_no or company_id or ""}'
    now=datetime.now(timezone.utc).isoformat()
    conn.execute('''INSERT INTO procurements
      (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,
       category,category_tags_json,tags_json,detail_fetched,award_date,contract_method,award_method,
       winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,
       agency=excluded.agency,organization_id=excluded.organization_id,notice_type=excluded.notice_type,
       source_url=excluded.source_url,is_it=excluded.is_it,category=excluded.category,
       category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=1,
       award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,
       winner_name=excluded.winner_name,company_id=excluded.company_id,award_amount=excluded.award_amount,detail_text=excluded.detail_text,collected_at=excluded.collected_at''',
      (sid,int(case_no),aid,title,award_date,agency,org_id,'落札実績（調達ポータル）',SOURCE_URL,int(is_it),category,
       json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),1,award_date,method,
       award_method_label(method),winner or None,company_id,amount,None,price_detail,now))
    return sid
def import_year(conn,year):
    path,rows=download_zip(year)
    dates=[row[2] for row in rows]
    start,end=min(dates),max(dates)
    conn.execute('CREATE TEMP TABLE IF NOT EXISTS geps_expected_ids (sid TEXT PRIMARY KEY)')
    conn.execute('DELETE FROM geps_expected_ids')
    for i,row in enumerate(rows,1):
        sid=upsert(conn,row)
        conn.execute('INSERT OR IGNORE INTO geps_expected_ids VALUES (?)',(sid,))
        if i%5000==0: conn.commit(); print(f'geps {year}: imported={i}/{len(rows)}',flush=True)
    removed=conn.execute('''DELETE FROM procurements WHERE source_id LIKE 'geps:%'
      AND award_date BETWEEN ? AND ? AND source_id NOT IN (SELECT sid FROM geps_expected_ids)''',(start,end)).rowcount
    conn.commit()
    print(f'geps {year}: rows={len(rows)} range={start}..{end} removedStale={removed} file={path.name}',flush=True)
    return len(rows),removed,start,end

def parse_years(value):
    years=[]
    for part in value.split(','):
        part=part.strip()
        if not part: continue
        if '-' in part:
            a,b=map(int,part.split('-',1));years.extend(range(a,b+1))
        else: years.append(int(part))
    return sorted(set(years))
def main():
    now=datetime.now(); fiscal=now.year if now.month>=4 else now.year-1
    ap=argparse.ArgumentParser()
    ap.add_argument('--years',default=str(fiscal))
    ap.add_argument('--no-export',action='store_true')
    args=ap.parse_args();years=parse_years(args.years)
    with SourceRun('geps_awards','調達ポータル 落札実績オープンデータ') as run:
        conn=sqlite3.connect(DB_PATH);init_db(conn)
        total=removed=0;ranges=[]
        for year in years:
            n,r,start,end=import_year(conn,year);total+=n;removed+=r;ranges.append((start,end))
        normalized=normalize_existing_unit_prices(conn)
        print(f'geps unit prices normalized={normalized}',flush=True)
        conn.execute('DELETE FROM companies WHERE company_id NOT IN (SELECT DISTINCT company_id FROM procurements WHERE company_id IS NOT NULL)')
        conn.execute('DELETE FROM organizations WHERE organization_id NOT IN (SELECT DISTINCT organization_id FROM procurements WHERE organization_id IS NOT NULL)')
        conn.commit()
        summary=None if args.no_export else export_json(conn)
        stored=conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%'").fetchone()[0]
        conn.close()
        run.set_metrics(records=stored,fetched=total,removedStale=removed,years=len(years),
          firstDate=min(x[0] for x in ranges) if ranges else '',lastDate=max(x[1] for x in ranges) if ranges else '')
        print(f'geps awards: fetched={total} stored={stored} removedStale={removed} years={years}')
        if summary: print(f'exported records={summary["records"]} awards={summary["awardRecords"]}')

if __name__=='__main__': main()
