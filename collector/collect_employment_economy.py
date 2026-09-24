#!/usr/bin/env python3
import csv, io, json, re, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public'/'data'/'employment-economy-2026.json'
RAW=ROOT/'data'/'raw'/'employment-economy'
RAW.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
SSDSE_E='https://www.nstac.go.jp/files/SSDSE-E-2026.csv'
SSDSE_B='https://www.nstac.go.jp/files/SSDSE-B-2026.csv'
WAGE_STAT_ID='000040421202'
WAGE_URL=f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={WAGE_STAT_ID}&fileKind=4'
WAGE_SOURCE='https://www.e-stat.go.jp/stat-search/files?stat_infid='+WAGE_STAT_ID

PREF_MAP={'北海道':'北海道','東京':'東京都','京都':'京都府','大阪':'大阪府'}
def full_pref(name):
    n=re.sub(r'\s+','',name or '').replace('全国ゼンコク','全国')
    if n in PREF_MAP:return PREF_MAP[n]
    if n in ('全国',''):return n
    return n if n.endswith(('都','道','府','県')) else n+'県'

def fetch(url):
    req=urllib.request.Request(url,headers=UA)
    with urllib.request.urlopen(req,timeout=90) as r:return r.read()

def num(v):
    s=str(v or '').replace(',','').strip()
    if not s:return None
    try:
        n=float(s);return int(n) if n.is_integer() else n
    except ValueError:return None

def read_csv_bytes(raw):
    return list(csv.reader(io.StringIO(raw.decode('cp932'))))

def parse_wage_xlsx(raw):
    ns='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        ss=ET.fromstring(z.read('xl/sharedStrings.xml'))
        shared=[''.join((t.text or '') for t in si.iter(ns+'t')) for si in ss.findall(ns+'si')]
        sh=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        out={}
        for row in sh.findall('.//'+ns+'row'):
            vals={}
            for c in row.findall(ns+'c'):
                ref=c.attrib.get('r',''); m=re.match(r'[A-Z]+',ref)
                if not m:continue
                col=m.group(); v=c.find(ns+'v'); value=None
                if v is not None:
                    value=v.text
                    if c.attrib.get('t')=='s': value=shared[int(value)]
                    else:
                        try:
                            value=float(value);value=int(value) if value.is_integer() else value
                        except Exception: pass
                vals[col]=value
            pref=full_pref(vals.get('C'))
            if not pref or pref=='全国' or vals.get('I') is None: continue
            monthly=num(vals.get('I')); scheduled=num(vals.get('J')); bonus=num(vals.get('K'))
            out[pref]={
                'averageAge':num(vals.get('E')),
                'averageTenureYears':num(vals.get('F')),
                'scheduledHours':num(vals.get('G')),
                'overtimeHours':num(vals.get('H')),
                'monthlyCashSalaryThousandYen':monthly,
                'monthlyScheduledSalaryThousandYen':scheduled,
                'annualBonusThousandYen':bonus,
                'workerCountTenPeople':num(vals.get('L')),
                'estimatedAnnualCashThousandYen':round(monthly*12+bonus,1) if monthly is not None and bonus is not None else None,
            }
        return out

def main():
    e_raw=fetch(SSDSE_E); b_raw=fetch(SSDSE_B); w_raw=fetch(WAGE_URL)
    (RAW/'SSDSE-E-2026.csv').write_bytes(e_raw);(RAW/'SSDSE-B-2026.csv').write_bytes(b_raw);(RAW/'wage-2025.xlsx').write_bytes(w_raw)
    erows=read_csv_bytes(e_raw); brows=read_csv_bytes(b_raw); wage=parse_wage_xlsx(w_raw)
    eyears=erows[1]; eheaders=erows[2]; eidx={h:i for i,h in enumerate(eheaders)}
    efields={
      'population':'総人口','workingAgePopulation':'15～64歳人口','gdpMillionYen':'県内総生産額（平成27年基準）',
      'prefecturalIncomeMillionYen':'県民所得（平成27年基準）','incomePerCapitaThousandYen':'1人当たり県民所得（平成27年基準）',
      'establishments':'事業所数（民営）','employees':'従業者数（民営）','constructionEstablishments':'事業所数（民営）（建設業）','constructionEmployees':'従業者数（民営）（建設業）',
      'infoEstablishments':'事業所数（民営）（情報通信業）',
      'infoEmployees':'従業者数（民営）（情報通信業）','manufacturingEstablishments':'事業所数（民営）（製造業）',
      'manufacturingEmployees':'従業者数（民営）（製造業）','retailEstablishments':'事業所数（民営）（卸売業、小売業）',
      'retailEmployees':'従業者数（民営）（卸売業、小売業）','medicalEmployees':'従業者数（民営）（医療、福祉）',
      'hospitalityEmployees':'従業者数（民営）（宿泊業、飲食サービス業）'
    }
    missing=[v for v in efields.values() if v not in eidx]
    if missing: raise ValueError('SSDSE-E columns missing: '+','.join(missing))
    records=[]
    for r in erows[3:]:
        if len(r)<3 or not r[1] or r[1]=='全国':continue
        pref=full_pref(r[1]); item={'prefecture':pref,'code':r[0]}
        for key,label in efields.items(): item[key]=num(r[eidx[label]])
        item.update(wage.get(pref,{}))
        wa=item.get('workingAgePopulation') or 0; pop=item.get('population') or 0
        item['workingAgeShare']=round(wa/pop*100,2) if pop else None
        emp=item.get('employees') or 0
        item['constructionEmployeeShare']=round((item.get('constructionEmployees') or 0)/emp*100,2) if emp else None
        item['infoEmployeeShare']=round((item.get('infoEmployees') or 0)/emp*100,2) if emp else None
        item['manufacturingEmployeeShare']=round((item.get('manufacturingEmployees') or 0)/emp*100,2) if emp else None
        item['retailEmployeeShare']=round((item.get('retailEmployees') or 0)/emp*100,2) if emp else None
        item['medicalEmployeeShare']=round((item.get('medicalEmployees') or 0)/emp*100,2) if emp else None
        records.append(item)
    # Attach latest job opening ratio and full time-series from SSDSE-B.
    bheaders=brows[1]; bidx={h:i for i,h in enumerate(bheaders)}
    for label in ('月間有効求職者数（一般）','月間有効求人数（一般）'):
        if label not in bidx: raise ValueError('SSDSE-B column missing: '+label)
    trends={}
    for r in brows[2:]:
        if len(r)<3 or not str(r[0]).isdigit() or not r[2]:continue
        pref=full_pref(r[2]); seekers=num(r[bidx['月間有効求職者数（一般）']]); openings=num(r[bidx['月間有効求人数（一般）']])
        ratio=round(openings/seekers,3) if seekers else None
        trends.setdefault(pref,[]).append({'year':int(r[0]),'jobOpeningRatio':ratio,'jobSeekers':seekers,'jobOpenings':openings})
    for item in records:
        ts=sorted(trends.get(item['prefecture'],[]),key=lambda x:x['year']); item['jobTrend']=ts
        latest=next((x for x in reversed(ts) if x.get('jobOpeningRatio') is not None),None)
        item['jobOpeningRatio']=latest['jobOpeningRatio'] if latest else None
        item['jobOpeningRatioYear']=latest['year'] if latest else None
    if len(records)!=47 or len(wage)!=47: raise ValueError(f'expected 47 prefectures, got economy={len(records)} wage={len(wage)}')
    payload={
      'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),
      'wageYear':2025,'wageSource':'厚生労働省 賃金構造基本統計調査 令和7年 一般労働者 都道府県別 参考表1','wageSourceUrl':WAGE_SOURCE,
      'regionalSource':'独立行政法人 統計センター SSDSE-E-2026 / SSDSE-B-2026','regionalSourceUrl':SSDSE_E,
      'fieldYears':{key:int(eyears[eidx[label]]) for key,label in efields.items() if str(eyears[eidx[label]]).isdigit()},
      'prefectures':[r['prefecture'] for r in records],'records':records
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'employment-economy: {len(records)} prefectures / wage={len(wage)} / {OUT}')
    return {'records':len(records),'prefectures':len(records),'wageYear':2025}

if __name__=='__main__':
    with SourceRun('employment_economy','厚生労働省 賃金構造基本統計 / 統計センター SSDSE') as run:
        stats=main();run.set_metrics(**stats)
