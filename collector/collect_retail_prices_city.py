#!/usr/bin/env python3
import json, math, re, urllib.request
from datetime import datetime, timezone
from pathlib import Path
from zipfile import ZipFile
from xml.etree import ElementTree as ET
from io import BytesIO

try:
    from core.canonical_metrics import assert_can_publish
    from core.raw_store import save_json as save_raw_json
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.canonical_metrics import assert_can_publish
    from collector.core.raw_store import save_json as save_raw_json
    from collector.core.source_run import SourceRun

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public/data/retail-prices-city-monthly.json'
DATASET=OUT.name
SOURCE_ID='estat_retail_prices_city'
LIST='https://www.e-stat.go.jp/stat-search/files'
SOURCE_PAGE='https://www.e-stat.go.jp/dbview?sid=0003421913'
UA={'User-Agent':'DATLUME/1.0 (+https://datlume.com/)'}
MONTHS_TO_KEEP=24
ITEMS=[
 {'code':'1001','metricId':'city_price.rice.koshihikari','label':'コシヒカリ','category':'食料'},
 {'code':'1021','metricId':'city_price.bread','label':'食パン','category':'食料'},
 {'code':'1201','metricId':'city_price.beef.domestic','label':'牛肉（国産）','category':'食料'},
 {'code':'1211','metricId':'city_price.pork.domestic_belly','label':'豚肉（国産・バラ）','category':'食料'},
 {'code':'1303','metricId':'city_price.milk','label':'牛乳','category':'食料'},
 {'code':'1341','metricId':'city_price.eggs','label':'鶏卵','category':'食料'},
 {'code':'1401','metricId':'city_price.cabbage','label':'キャベツ','category':'食料'},
 {'code':'2133','metricId':'city_price.curry.restaurant','label':'カレーライス（外食）','category':'外食'},
 {'code':'3001','metricId':'city_price.rent.private','label':'民営家賃','category':'住居'},
 {'code':'3511','metricId':'city_price.electricity','label':'電気代','category':'光熱・水道'},
 {'code':'3605','metricId':'city_price.city_gas','label':'都市ガス代','category':'光熱・水道'},
 {'code':'3800','metricId':'city_price.water','label':'水道料','category':'光熱・水道'},
 {'code':'7301','metricId':'city_price.gasoline','label':'ガソリン','category':'交通'},
]
ITEM_BY_CODE={x['code']:x for x in ITEMS}
NS='http://schemas.openxmlformats.org/spreadsheetml/2006/main'
RNS='http://schemas.openxmlformats.org/officeDocument/2006/relationships'

def fetch(url):
 req=urllib.request.Request(url,headers=UA)
 with urllib.request.urlopen(req,timeout=90) as r:return r.read()

def year_page(year,page):
 q=f'?cycle=1&layout=dataset&page={page}&tclass1val=0&toukei=00200571&tstat=000000680001&year={year}0'
 return fetch(LIST+q).decode('utf-8','ignore')

def discover_month_files(years):
 found={}
 for year in years:
  for page in range(1,9):
   html=year_page(year,page)
   blocks=re.findall(r'<article class="stat-resource_list-item[^"]*">.*?</article>',html,re.S)
   if not blocks:break
   page_months=set()
   for block in blocks:
    mm=re.search(r'主要品目の都市別小売価格【(20\d{2})年(\d{1,2})月】',block)
    if not mm:continue
    ym=f'{int(mm.group(1)):04d}-{int(mm.group(2)):02d}'; page_months.add(ym)
    sid=re.search(r'file-download\?statInfId=(\d+)(?:&|&amp;)fileKind=0',block)
    if not sid:continue
    # only the three ranges containing DATLUME's curated items; the 8001+ block is not needed
    text=re.sub(r'<[^>]+>',' ',block)
    if not any(x in text for x in ('1001 うるち米','3001 民営家賃','5011 女性用着物')):continue
    found.setdefault(ym,[]).append(sid.group(1))
 return {m:list(dict.fromkeys(v)) for m,v in found.items()}

def discover_gas_files(years):
 found={}
 for year in years:
  for page in range(1,9):
   q=f'?cycle=1&layout=dataset&page={page}&tclass1=000001035981&tclass2val=0&toukei=00200571&tstat=000000680001&year={year}0'
   html=fetch(LIST+q).decode('utf-8','ignore')
   blocks=re.findall(r'<article class="stat-resource_list-item[^"]*">.*?</article>',html,re.S)
   if not blocks:break
   for block in blocks:
    mm=re.search(r'ガソリン[^【]*【(20\d{2})年(\d{1,2})月】',block)
    sid=re.search(r'file-download\?statInfId=(\d+)(?:&|&amp;)fileKind=0',block)
    if not mm or not sid:continue
    ym=f'{int(mm.group(1)):04d}-{int(mm.group(2)):02d}'
    found.setdefault(ym,sid.group(1))
 return found

def col_num(ref):
 n=0
 for c in ''.join(x for x in ref if x.isalpha()):n=n*26+ord(c.upper())-64
 return n

def xlsx_rows(data):
 with ZipFile(BytesIO(data)) as z:
  strings=[]
  if 'xl/sharedStrings.xml' in z.namelist():
   root=ET.fromstring(z.read('xl/sharedStrings.xml'))
   strings=[''.join(t.text or '' for t in si.iter(f'{{{NS}}}t')) for si in root.findall(f'{{{NS}}}si')]
  wb=ET.fromstring(z.read('xl/workbook.xml')); rel=ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
  rels={x.attrib['Id']:x.attrib['Target'] for x in rel}; sh=wb.find(f'{{{NS}}}sheets/{{{NS}}}sheet')
  target=rels[sh.attrib[f'{{{RNS}}}id']]; target='xl/'+target.lstrip('/') if not target.startswith('xl/') else target
  root=ET.fromstring(z.read(target))
  for row in root.findall(f'.//{{{NS}}}sheetData/{{{NS}}}row'):
   vals={}
   for c in row.findall(f'{{{NS}}}c'):
    ref=c.attrib.get('r',''); typ=c.attrib.get('t'); v=c.find(f'{{{NS}}}v'); value='' if v is None else (v.text or '')
    if typ=='s' and value:value=strings[int(value)]
    elif typ=='inlineStr':value=''.join(t.text or '' for t in c.iter(f'{{{NS}}}t'))
    vals[col_num(ref)]=value
   yield int(row.attrib.get('r','0')),vals

def clean_city(name):
 name=str(name or '').strip()
 if name.startswith('東京都区部'):return '東京都区部'
 m=re.match(r'^(.+?市)',name)
 return m.group(1) if m else name

def number(value):
 s=str(value or '').replace(',','').strip()
 if not s or s in {'-','...','Y','X','x'}:return None
 try:n=float(s)
 except ValueError:return None
 if not math.isfinite(n):return None
 return int(n) if n.is_integer() else n

def parse_book(data,ym):
 rows=list(xlsx_rows(data)); header10=next((v for r,v in rows if r==10),{}); header11=next((v for r,v in rows if r==11),{})
 cities={}
 for col,code in header10.items():
  if col<16 or not re.fullmatch(r'\d{5}',str(code or '').strip()):continue
  cities[str(code).strip()]=clean_city(header11.get(col,''))
 col_by_code={str(code).strip():col for col,code in header10.items() if col>=16 and re.fullmatch(r'\d{5}',str(code or '').strip())}
 values={}; units={}
 for rn,row in rows:
  code=str(row.get(10,'')).strip()
  if code not in ITEM_BY_CODE:continue
  units[code]=str(row.get(12,'')).strip(); vals={}
  for city_code,col in col_by_code.items():
   v=number(row.get(col));
   if v is not None:vals[city_code]=v
  values[code]=vals
 save_raw_json(SOURCE_ID,f'{ym}:{hash(data)}',{'month':ym,'cities':cities,'units':units,'values':values})
 return cities,units,values

def parse_gas_book(data,ym):
 cities={}; values={}
 for rn,row in xlsx_rows(data):
  if rn<11:continue
  code=str(row.get(10,'')).strip()
  if not re.fullmatch(r'\d{5}',code):continue
  value=number(row.get(14))
  cities[code]=clean_city(row.get(11,''))
  if value is not None:values[code]=value
 save_raw_json(SOURCE_ID,f'{ym}:gas:{hash(data)}',{'month':ym,'cities':cities,'unit':'1L','values':values})
 return cities,values

def main():
 now=datetime.now(timezone.utc); latest_year=now.year
 years=range(latest_year-2,latest_year+1)
 files=discover_month_files(years); gas_files=discover_gas_files(years)
 months=sorted(files)[-MONTHS_TO_KEEP:]
 if len(months)<12:raise ValueError(f'too few monthly releases discovered: {len(months)}')
 city_names={}; units={}; by_item={x['code']:{} for x in ITEMS}
 for ym in months:
  month_values={x['code']:{} for x in ITEMS}
  for sid in files[ym]:
   url=f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0'; data=fetch(url)
   cities,u,vals=parse_book(data,ym); city_names.update(cities); units.update(u)
   for code,mapping in vals.items():month_values[code].update(mapping)
  if ym in gas_files:
   sid=gas_files[ym]; data=fetch(f'https://www.e-stat.go.jp/stat-search/file-download?statInfId={sid}&fileKind=0')
   gas_cities,gas_values=parse_gas_book(data,ym); city_names.update(gas_cities)
   for city_code,value in gas_values.items():month_values['7301'].setdefault(city_code,value)
  for code,mapping in month_values.items():
   for city_code,value in mapping.items():by_item[code].setdefault(city_code,{})[ym]=value
  print(f'retail-prices-city: {ym} / {len(city_names)} cities / {sum(len(v) for v in month_values.values())} values')
 latest=months[-1]
 items=[]
 for item in ITEMS:
  field=f"values.{item['code']}"; assert_can_publish(item['metricId'],SOURCE_ID,DATASET,field)
  latest_count=sum(1 for s in by_item[item['code']].values() if latest in s)
  if latest_count<40:raise ValueError(f"latest coverage too low {item['code']}: {latest_count}")
  items.append({**item,'unit':units.get(item['code'],'円'),'latestCoverage':latest_count})
 city_codes=sorted(city_names)
 values={}
 for item in ITEMS:
  code=item['code']; values[code]={}
  for city in city_codes:
   series=by_item[code].get(city,{})
   arr=[series.get(m) for m in months]
   if any(v is not None for v in arr):values[code][city]=arr
 payload={'schemaVersion':1,'generatedAt':now.isoformat(),'source':'総務省統計局 小売物価統計調査（動向編） 主要品目の都市別小売価格','sourceUrl':SOURCE_PAGE,'latestMonth':latest,'months':months,'cityCount':len(city_codes),'items':items,'cities':[{'code':c,'name':city_names[c]} for c in city_codes],'values':values,'missingPolicy':'「-」「...」等の非数値は欠損(null)として保持。公式表に数値の0が記録されている場合は0をそのまま保持。'}
 OUT.parent.mkdir(parents=True,exist_ok=True); OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
 count=sum(sum(1 for value in series if value is not None) for item in values.values() for series in item.values())
 print(f'retail-prices-city: {len(months)} months / {len(city_codes)} cities / {len(items)} items -> {OUT}')
 return {'records':count,'months':len(months),'cities':len(city_codes),'items':len(items),'latestMonth':latest}

if __name__=='__main__':
 with SourceRun('retail_prices_city','総務省統計局 小売物価統計調査（動向編）都市別小売価格') as run:run.set_metrics(**main())
