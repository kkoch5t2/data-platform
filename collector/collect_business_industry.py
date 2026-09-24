#!/usr/bin/env python3
import csv, io, json, urllib.request
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public'/'data'/'business-industry-2026.json'
RAW=ROOT/'data'/'raw'/'business-industry'
RAW.mkdir(parents=True,exist_ok=True)
SOURCE_URL='https://www.nstac.go.jp/files/SSDSE-E-2026.csv'
SOURCE_PAGE='https://www.nstac.go.jp/use/literacy/ssdse/'
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
PREF_MAP={'北海道':'北海道','東京':'東京都','京都':'京都府','大阪':'大阪府'}

INDUSTRIES=[
 ('construction','建設業'),
 ('manufacturing','製造業'),
 ('information','情報通信業'),
 ('wholesaleRetail','卸売業、小売業'),
 ('hospitality','宿泊業、飲食サービス業'),
 ('lifestyle','生活関連サービス業、娯楽業'),
 ('medicalWelfare','医療、福祉'),
]

def full_pref(name):
    n=str(name or '').strip()
    if n in PREF_MAP:return PREF_MAP[n]
    if n in ('全国',''):return n
    return n if n.endswith(('都','道','府','県')) else n+'県'

def num(v):
    s=str(v or '').replace(',','').strip()
    if not s:return None
    try:
        n=float(s)
        return int(n) if n.is_integer() else n
    except ValueError:return None

def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=90) as r:return r.read()

def main():
    raw=fetch(SOURCE_URL)
    (RAW/'SSDSE-E-2026.csv').write_bytes(raw)
    rows=list(csv.reader(io.StringIO(raw.decode('cp932'))))
    years,headers=rows[1],rows[2]
    idx={h:i for i,h in enumerate(headers)}
    required=['総人口','15～64歳人口','事業所数（民営）','従業者数（民営）']
    for _,label in INDUSTRIES:
        required += [f'事業所数（民営）（{label}）',f'従業者数（民営）（{label}）']
    missing=[x for x in required if x not in idx]
    if missing: raise ValueError('SSDSE-E columns missing: '+','.join(missing))

    records=[]
    for row in rows[3:]:
        if len(row)<3 or not row[1] or row[1]=='全国':continue
        pref=full_pref(row[1])
        item={
          'prefecture':pref,'code':row[0],
          'population':num(row[idx['総人口']]),
          'workingAgePopulation':num(row[idx['15～64歳人口']]),
          'establishments':num(row[idx['事業所数（民営）']]),
          'employees':num(row[idx['従業者数（民営）']]),
        }
        emp=item['employees'] or 0
        est=item['establishments'] or 0
        item['employeesPerEstablishment']=round(emp/est,2) if est else None
        industry=[]
        for key,label in INDUSTRIES:
            establishments=num(row[idx[f'事業所数（民営）（{label}）']])
            employees=num(row[idx[f'従業者数（民営）（{label}）']])
            industry.append({
              'key':key,'label':label,'establishments':establishments,'employees':employees,
              'employeeShare':round((employees or 0)/emp*100,2) if emp else None,
              'establishmentShare':round((establishments or 0)/est*100,2) if est else None,
              'employeesPerEstablishment':round((employees or 0)/(establishments or 1),2) if establishments else None,
            })
        item['industries']=industry
        ranked=sorted(industry,key=lambda x:x.get('employees') or 0,reverse=True)
        item['largestIndustry']=ranked[0]['label'] if ranked else None
        item['largestIndustryShare']=ranked[0]['employeeShare'] if ranked else None
        records.append(item)

    if len(records)!=47: raise ValueError(f'expected 47 prefectures, got {len(records)}')
    est_year=int(years[idx['事業所数（民営）']])
    emp_year=int(years[idx['従業者数（民営）']])
    totals={
      'establishments':sum(r['establishments'] or 0 for r in records),
      'employees':sum(r['employees'] or 0 for r in records),
    }
    totals['employeesPerEstablishment']=round(totals['employees']/totals['establishments'],2)
    totals['industries']=[]
    for key,label in INDUSTRIES:
        es=sum(next(x for x in r['industries'] if x['key']==key)['establishments'] or 0 for r in records)
        em=sum(next(x for x in r['industries'] if x['key']==key)['employees'] or 0 for r in records)
        totals['industries'].append({
          'key':key,'label':label,'establishments':es,'employees':em,
          'employeeShare':round(em/totals['employees']*100,2),
          'establishmentShare':round(es/totals['establishments']*100,2),
          'employeesPerEstablishment':round(em/es,2) if es else None,
        })

    payload={
      'schemaVersion':1,
      'generatedAt':datetime.now(timezone.utc).isoformat(),
      'source':'独立行政法人 統計センター SSDSE-E-2026',
      'sourceUrl':SOURCE_PAGE,
      'downloadUrl':SOURCE_URL,
      'establishmentYear':est_year,
      'employeeYear':emp_year,
      'populationYear':int(years[idx['総人口']]),
      'industryCoverageNote':'産業別内訳はSSDSE-Eで収録される主要7産業。全産業の合計ではありません。',
      'industries':[{'key':k,'label':l} for k,l in INDUSTRIES],
      'totals':totals,
      'records':records,
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'business-industry: {len(records)} prefectures / {OUT}')
    return {'records':len(records),'prefectures':len(records),'year':est_year,'establishments':totals['establishments'],'employees':totals['employees']}

if __name__=='__main__':
    with SourceRun('business_industry','統計センター SSDSE-E-2026') as run:
        run.set_metrics(**main())
