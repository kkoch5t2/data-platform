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
OUT=ROOT/'public/data/regional-migration-history.json'
RAW=ROOT/'data/raw/regional-migration'; RAW.mkdir(parents=True,exist_ok=True)
UA={'User-Agent':'Mozilla/5.0 DATLUME/1.0'}
TABLES={
    'inMigration':'000040430816',
    'outMigration':'000040430817',
    'netMigration':'000040430818',
}
SOURCE='https://www.e-stat.go.jp/stat-search/files?cycle=0&layout=datalist&tclass=000001039741'
PREFS=['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県']
NS='{http://schemas.openxmlformats.org/spreadsheetml/2006/main}'

def fetch(url):
    with urllib.request.urlopen(urllib.request.Request(url,headers=UA),timeout=90) as r:return r.read()

def col_no(ref):
    letters=re.match(r'[A-Z]+',ref).group()
    n=0
    for ch in letters:n=n*26+ord(ch)-64
    return n

def sheet_rows(blob):
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        shared=[]
        if 'xl/sharedStrings.xml' in z.namelist():
            root=ET.fromstring(z.read('xl/sharedStrings.xml'))
            shared=[''.join(t.text or '' for t in si.iter(NS+'t')) for si in root.findall(NS+'si')]
        root=ET.fromstring(z.read('xl/worksheets/sheet1.xml'))
        out=[]
        for row in root.findall('.//'+NS+'row'):
            vals={}
            for c in row.findall(NS+'c'):
                ref=c.attrib.get('r'); v=c.find(NS+'v')
                if not ref or v is None:continue
                val=v.text
                if c.attrib.get('t')=='s': val=shared[int(val)]
                vals[col_no(ref)]=val
            out.append(vals)
        return out

def parse(blob):
    rows=sheet_rows(blob)
    year_row=next((r for r in rows if sum(str(v).isdigit() and 1950<=int(v)<=2100 for v in r.values())>=20),None)
    if not year_row:raise ValueError('year row not found')
    years={c:int(v) for c,v in year_row.items() if str(v).isdigit() and 1950<=int(v)<=2100}
    result={}
    for row in rows:
        code=str(row.get(1,'')).strip()
        pref=str(row.get(2,'')).strip()
        if not re.fullmatch(r'\d{2}',code) or pref not in PREFS:continue
        vals={}
        for c,year in years.items():
            raw=row.get(c)
            try: vals[year]=int(float(str(raw).replace(',',''))) if raw not in (None,'') else None
            except ValueError: vals[year]=None
        result[pref]=vals
    if len(result)!=47:raise ValueError(f'expected 47 prefectures, got {len(result)}')
    return result

def main():
    parsed={}
    for key,sid in TABLES.items():
        url=f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0'
        blob=fetch(url);(RAW/f'{key}-{sid}.xlsx').write_bytes(blob)
        parsed[key]=parse(blob)
    years=sorted(set().union(*(set(v[p].keys()) for v in parsed.values() for p in v)))
    records=[]
    for pref in PREFS:
        values=[]
        for y in years:
            values.append([y,parsed['inMigration'][pref].get(y),parsed['outMigration'][pref].get(y),parsed['netMigration'][pref].get(y)])
        records.append({'prefecture':pref,'values':values})
    payload={
        'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),
        'source':'総務省統計局 住民基本台帳人口移動報告 長期時系列','sourceUrl':SOURCE,
        'scope':'日本人移動者 / 都道府県別','fields':['year','inMigration','outMigration','netMigration'],
        'years':years,'records':records,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f'regional migration: {len(records)} prefectures / {years[0]}-{years[-1]} / {len(years)} years')
    return {'records':len(records)*len(years),'prefectures':len(records),'startYear':years[0],'endYear':years[-1]}

if __name__=='__main__':
    with SourceRun('regional_migration','総務省統計局 住民基本台帳人口移動報告') as run:
        run.set_metrics(**main())
