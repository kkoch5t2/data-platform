#!/usr/bin/env python3
import csv, io, json, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public/data/business-industry-history.json'
RAW=ROOT/'data/raw/business-industry-history';RAW.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
# SSDSE-E-2022 carries the 2016 Economic Census activity values;
# SSDSE-E-2024 switches the same fields to the 2021 Economic Census activity values.
SOURCES={2016:'https://www.nstac.go.jp/files/SSDSE-E-2022.csv',2021:'https://www.nstac.go.jp/files/SSDSE-E-2024.csv'}
SOURCE_PAGE='https://www.nstac.go.jp/use/literacy/ssdse/'
INDUSTRIES=[
 ('construction','建設業'),('manufacturing','製造業'),('information','情報通信業'),
 ('retail','卸売業、小売業'),('hospitality','宿泊業、飲食サービス業'),
 ('personal','生活関連サービス業、娯楽業'),('medical','医療、福祉'),
]

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=60) as r:return r.read()

def norm(s):return str(s or '').replace('，','、').replace(' ','')
def num(v):
    try:return int(float(str(v).replace(',','').strip()))
    except:return None

def parse(raw, expected_year):
    rows=list(csv.reader(io.StringIO(raw.decode('cp932'))));years=rows[1];heads=rows[2]
    idx={norm(h):i for i,h in enumerate(heads)}
    total_est=idx[norm('事業所数（民営）')];total_emp=idx[norm('従業者数（民営）')]
    if int(years[total_est])!=expected_year or int(years[total_emp])!=expected_year:
        raise ValueError(f'field year mismatch: expected {expected_year}, got {years[total_est]}/{years[total_emp]}')
    inds=[]
    for key,label in INDUSTRIES:
        ei=idx[norm(f'事業所数（民営）（{label}）')];wi=idx[norm(f'従業者数（民営）（{label}）')]
        inds.append((key,label,ei,wi))
    out=[]
    for r in rows[3:]:
        if len(r)<3 or r[1] in ('','全国'):continue
        item={'prefecture':r[1],'code':r[0],'establishments':num(r[total_est]),'employees':num(r[total_emp]),'industries':{}}
        for key,label,ei,wi in inds:
            item['industries'][key]={'label':label,'establishments':num(r[ei]),'employees':num(r[wi])}
        out.append(item)
    if len(out)!=47:raise ValueError(f'expected 47 prefectures, got {len(out)}')
    return out

def main():
    snapshots=[]
    for year,url in SOURCES.items():
        raw=fetch(url);(RAW/f'SSDSE-E-{year}.csv').write_bytes(raw);records=parse(raw,year)
        snapshots.append({'year':year,'records':records});print(f'business history {year}: {len(records)} prefectures')
    payload={'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'source':'統計センター SSDSE-E（経済センサス活動調査由来）','sourceUrl':SOURCE_PAGE,'years':sorted(SOURCES),'industries':[{'key':k,'label':l} for k,l in INDUSTRIES],'snapshots':snapshots}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return {'records':47*len(SOURCES),'prefectures':47,'startYear':min(SOURCES),'endYear':max(SOURCES)}

if __name__=='__main__':
    with SourceRun('business_industry_history','SSDSE-E / 経済センサス産業構造時系列') as run:run.set_metrics(**main())
