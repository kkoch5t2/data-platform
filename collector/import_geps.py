#!/usr/bin/env python3
import argparse, csv, hashlib, json, sqlite3
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from collect_jetro import (
    DB_PATH, classify, stable_id, norm, init_db, export_json
)

ROOT = Path(__file__).resolve().parents[1]
SOURCE_URL = 'https://www.p-portal.go.jp/pps-web-biz/UAB02/OAB0201'

MINISTRIES = {
    'A1':'衆議院','B1':'参議院','C1':'国立国会図書館','D1':'最高裁判所',
    'E1':'会計検査院','F1':'人事院','F2':'国家公務員倫理審査会',
    'G1':'内閣官房','H1':'内閣法制局','I1':'安全保障会議',
    'J1':'内閣府','J2':'宮内庁','J3':'公正取引委員会','J4':'国家公安委員会',
    'J5':'警察庁','J6':'金融庁','J7':'消費者庁','J8':'個人情報保護委員会',
    'J9':'カジノ管理委員会','K1':'総務省','K2':'公害等調整委員会','K3':'消防庁',
    'L1':'法務省','L2':'検察庁','L3':'公安審査委員会','L4':'公安調査庁',
    'M1':'外務省','N1':'財務省','N2':'国税庁',
    'O1':'文部科学省','O2':'文化庁','O3':'スポーツ庁',
    'P1':'厚生労働省','P2':'中央労働委員会',
    'Q1':'農林水産省','Q2':'林野庁','Q3':'水産庁',
    'R1':'経済産業省','R2':'資源エネルギー庁','R3':'特許庁','R4':'中小企業庁',
    'S1':'国土交通省','S2':'運輸安全委員会','S3':'観光庁','S4':'気象庁','S5':'海上保安庁',
    'T1':'環境省','T2':'原子力規制委員会','U1':'防衛省','V1':'復興庁',
    'W1':'デジタル庁','JA':'こども家庭庁','JB':'サイバー通信情報監理委員会',
}

BID_METHODS = {
    '8002010':'一般競争入札・最低価格',
    '8002020':'一般競争入札・最高価格',
    '8002040':'一般競争入札・総合評価',
    '8002050':'一般競争入札・複数落札',
    '8003010':'指名競争入札・最低価格',
    '8003020':'指名競争入札・最高価格',
    '8003040':'指名競争入札・総合評価',
    '8003050':'指名競争入札・複数落札',
    '8004025':'随意契約方式・複数業者',
    '8001010':'随意契約方式・オープンカウンタ',
    '8004020':'随意契約方式・特定業者',
    '8004030':'随意契約方式・公募型プロポーザル方式',
    '8014025':'随意契約方式・複数業者・少額',
    '8011010':'随意契約方式・オープンカウンタ・少額',
    '8014020':'随意契約方式・特定業者・少額',
    '8014030':'随意契約方式・公募型プロポーザル方式・少額',
}

def award_method_label(method):
    if '総合評価' in method: return '総合評価'
    if '最低価格' in method: return '最低価格'
    if '最高価格' in method: return '最高価格'
    if '複数落札' in method: return '複数落札'
    return ''

def record_id(row):
    raw='|'.join(row)
    return hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]

def iter_rows(paths, start, end):
    for path in paths:
        with open(path, encoding='utf-8-sig', newline='') as f:
            for row in csv.reader(f):
                if len(row) != 8: continue
                if start <= row[2] <= end:
                    yield row
def upsert(conn, row):
    case_no,title,award_date,price,ministry_cd,method_cd,winner,corp_no=row
    source_id=f'geps:{case_no}:{record_id(row)}'
    agency=MINISTRIES.get(ministry_cd)
    if not agency:
        raise ValueError(f'unknown GEPS ministry code: {ministry_cd}')
    method=BID_METHODS.get(method_cd,method_cd)
    decimal_amount=Decimal(price)
    amount=int(decimal_amount) if decimal_amount==decimal_amount.to_integral_value() else float(decimal_amount)
    is_it,tags,category,category_tags=classify(title)
    org_id=stable_id('org',agency) if agency else None
    company_id=stable_id('co',winner) if winner else None
    if org_id:
        conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,agency))
    if company_id:
        conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)',(company_id,winner,norm(winner)))
    aid=f'{case_no}:{award_date}:{corp_no or company_id or ""}'
    xid=int(case_no)
    now=datetime.now(timezone.utc).isoformat()
    conn.execute('''INSERT INTO procurements
      (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,
       category,category_tags_json,tags_json,detail_fetched,award_date,contract_method,award_method,
       winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(source_id) DO UPDATE SET
       title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
       organization_id=excluded.organization_id,notice_type=excluded.notice_type,
       source_url=excluded.source_url,is_it=excluded.is_it,category=excluded.category,
       category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,
       detail_fetched=1,award_date=excluded.award_date,contract_method=excluded.contract_method,
       award_method=excluded.award_method,winner_name=excluded.winner_name,
       company_id=excluded.company_id,award_amount=excluded.award_amount,collected_at=excluded.collected_at''',
      (source_id,xid,aid,title,award_date,agency,org_id,'落札実績（調達ポータル）',SOURCE_URL,int(is_it),
       category,json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),1,
       award_date,method,award_method_label(method),winner or None,company_id,amount,None,None,now))
def main():
    p=argparse.ArgumentParser()
    p.add_argument('--start',default='2020-01-01')
    p.add_argument('--end',default='2021-03-31')
    p.add_argument('files',nargs='+')
    args=p.parse_args()
    conn=sqlite3.connect(DB_PATH); init_db(conn)
    count=0
    for row in iter_rows(args.files,args.start,args.end):
        upsert(conn,row); count+=1
        if count%5000==0:
            conn.commit(); print('imported',count,flush=True)
    conn.commit()
    summary=export_json(conn)
    print('imported',count,'stored',summary['records'])

if __name__=='__main__':
    main()
