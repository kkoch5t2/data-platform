#!/usr/bin/env python3
import io, json, re, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public/data/energy-consumption-history.json'
RAW=ROOT/'data/raw/energy-consumption-history';RAW.mkdir(parents=True,exist_ok=True)
SOURCE_PAGE='https://www.enecho.meti.go.jp/statistics/energy_consumption/ec002/results.html'
ZIP_URL='https://www.enecho.meti.go.jp/statistics/energy_consumption/ec002/xls/20260116_all.zip'
HEADERS={'User-Agent':'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/140 Safari/537.36','Accept-Language':'ja,en-US;q=0.9,en;q=0.8','Referer':'https://www.google.com/'}
M='http://schemas.openxmlformats.org/spreadsheetml/2006/main';R='http://schemas.openxmlformats.org/officeDocument/2006/relationships';NS='{'+M+'}'
CODES={'finalEnergyPerCapita':'500000','commercialPerCapita':'650000','residentialPerCapita':'700000','transportPerCapita':'800000'}

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=HEADERS),timeout=120) as r:return r.read()

def col_letters(ref):return re.match(r'[A-Z]+',ref).group()

def parse_xlsx(blob):
    z=zipfile.ZipFile(io.BytesIO(blob));ns={'m':M,'r':R};shared=[]
    if 'xl/sharedStrings.xml' in z.namelist():
        root=ET.fromstring(z.read('xl/sharedStrings.xml'));shared=[''.join(t.text or '' for t in si.iter(NS+'t')) for si in root.findall('m:si',ns)]
    wb=ET.fromstring(z.read('xl/workbook.xml'));rels=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'));rm={x.attrib['Id']:x.attrib['Target'] for x in rels}
    sh=next(s for s in wb.find('m:sheets',ns) if s.attrib['name']=='指標');root=ET.fromstring(z.read('xl/'+rm[sh.attrib['{'+R+'}id']]))
    rows=[]
    for rr in root.findall('.//m:sheetData/m:row',ns):
        vals={}
        for c in rr.findall('m:c',ns):
            col=col_letters(c.attrib['r']);v=c.find('m:v',ns);val='' if v is None else v.text
            if c.attrib.get('t')=='s' and val!='':val=shared[int(val)]
            elif c.attrib.get('t')=='inlineStr':
                ins=c.find('m:is',ns);val=''.join(t.text or '' for t in ins.iter(NS+'t')) if ins is not None else ''
            vals[col]=val
        rows.append(vals)
    # First block is per-capita energy consumption; later blocks repeat codes for totals/CO2.
    years={k:int(v) for k,v in rows[0].items() if k>='G' and str(v).isdigit() and 1990<=int(v)<=2100}
    pref=str(rows[3].get('A','')).replace('　','').strip()
    out={k:{} for k in CODES}
    wanted={v:k for k,v in CODES.items()}
    for row in rows[10:62]:
        key=wanted.get(str(row.get('A','')).strip())
        if not key:continue
        for col,year in years.items():
            try:out[key][year]=round(float(row[col]),4) if row.get(col) not in ('',None) else None
            except (ValueError,TypeError):out[key][year]=None
    if not pref or any(not out[k] for k in CODES):raise ValueError(f'failed parse {pref or "unknown"}')
    vals=[]
    for y in sorted(years.values()):vals.append([y]+[out[k].get(y) for k in CODES])
    return pref,sorted(years.values()),vals

def main():
    blob=fetch(ZIP_URL);(RAW/'all-prefectures.zip').write_bytes(blob);outer=zipfile.ZipFile(io.BytesIO(blob));records=[];years=None
    for name in sorted(n for n in outer.namelist() if n.lower().endswith('.xlsx') and re.match(r'\d{2}',Path(n).name)):
        pref,ys,vals=parse_xlsx(outer.read(name));years=ys if years is None else years
        if ys!=years:raise ValueError(f'year mismatch {name}')
        records.append({'prefecture':pref,'values':vals})
    if len(records)!=47:raise ValueError(f'expected 47 prefectures, got {len(records)}')
    payload={'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'source':'資源エネルギー庁 都道府県別エネルギー消費統計','sourceUrl':SOURCE_PAGE,'unit':'GJ/人','years':years,'fields':['year']+list(CODES),'records':records,'note':'1人あたりの電力・熱配分後エネルギー消費。1990年度、2005年度、2007年度以降の公表年を収録。'}
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'energy consumption history: {len(records)} prefectures / {years[0]}-{years[-1]} / {len(years)} points each')
    return {'records':len(records)*len(years),'prefectures':len(records),'startYear':years[0],'endYear':years[-1]}

if __name__=='__main__':
    with SourceRun('energy_consumption_history','資源エネルギー庁 都道府県別エネルギー消費統計') as run:run.set_metrics(**main())
