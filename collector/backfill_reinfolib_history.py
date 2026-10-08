#!/usr/bin/env python3
"""Build quarterly history from annual XIT001 responses, preserving source geography."""
import argparse, gzip, hashlib, json, os, sys, time, urllib.error, urllib.parse, urllib.request
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from collector.collect_reinfolib_transactions import API_URL,API_MANUAL,SOURCE_LABEL,SOURCE_URL,UA,reinfolib_api_key,row_from_api,segment_for,unit_value,summarize
CACHE=ROOT/'data/raw/reinfolib-history'
OUT=ROOT/'public/data/realestate-history'
def fetch(year,pref,key,refresh=False):
    path=CACHE/str(year)/(pref+'.json.gz')
    if path.exists() and not refresh:
        with gzip.open(path,'rt',encoding='utf-8') as f: return json.load(f)
    url=API_URL+'?'+urllib.parse.urlencode(dict(year=year,area=pref,priceClassification='01',language='ja'))
    for attempt in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url,headers={**UA,'Ocp-Apim-Subscription-Key':key,'Accept-Encoding':'gzip'}),timeout=120) as r:
                body=r.read()
                if 'gzip' in r.headers.get('Content-Encoding','').lower(): body=gzip.decompress(body)
            payload=json.loads(body)
            if payload.get('status')!='OK': raise ValueError('unexpected API status')
            data=payload.get('data')
            if not isinstance(data,list): raise ValueError('missing data array')
            for raw in data:
                row=row_from_api(raw)
                if not row['period'] or not row['period'].startswith(str(year)+'Q'): raise ValueError('period outside requested year')
                if not row['code'].startswith(pref): raise ValueError('municipality outside requested prefecture')
                if raw.get('PriceCategory') not in (None,'','不動産取引価格情報'): raise ValueError('mixed price category')
            result={'url':url,'fetchedAt':datetime.now(timezone.utc).isoformat(),'data':data}
            path.parent.mkdir(parents=True,exist_ok=True)
            temp=path.with_suffix('.tmp')
            with gzip.open(temp,'wt',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,separators=(',',':'))
            temp.replace(path)
            return result
        except urllib.error.HTTPError as e:
            message=json.loads(e.read().decode('utf-8')).get('message') if e.code==404 else None
            if e.code==404 and message=='検索結果がありません。':
                result={'url':url,'fetchedAt':datetime.now(timezone.utc).isoformat(),'httpStatus':404,'message':message,'data':[]}
                path.parent.mkdir(parents=True,exist_ok=True)
                with gzip.open(path,'wt',encoding='utf-8') as f: json.dump(result,f,ensure_ascii=False,separators=(',',':'))
                return result
            if attempt==3: raise RuntimeError(f'API HTTP failure: {year}/{pref} status={e.code}') from None
            time.sleep(2**attempt)
        except (urllib.error.URLError,TimeoutError) as e:
            if attempt==3: raise RuntimeError(f'API request failed: {year}/{pref} {type(e).__name__}') from None
            time.sleep(2**attempt)
def compact(rows):
    result={}
    for segment in ('land','house','condo'):
        items=[r for r in rows if r['segment']==segment]
        result[segment]=summarize(items)
        result[segment]['validCounts']={field:sum(isinstance(r.get(source),(int,float)) and r[source]>0 for r in items) for field,source in [('medianTradePrice','tradePrice'),('medianUnitPrice','unitValue'),('medianArea','area'),('medianFloorArea','floorArea')]}
    return result
def write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix('.tmp')
    temp.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    temp.replace(path)
def build(start=2005,refresh_recent=False):
    latest=json.loads((ROOT/'public/data/realestate-transactions.json').read_text())['latestPeriod']
    end=int(latest[:4]);periods=[f'{y}Q{q}' for y in range(start,end+1) for q in range(1,5) if f'{y}Q{q}'>='2005Q3' and f'{y}Q{q}'<=latest]
    key=reinfolib_api_key()
    if not key: raise RuntimeError('REINFOLIB API key missing')
    prefs={};national=defaultdict(list);source_files=[];raw_total=0;published=0
    # Process one year at a time; public files are written only after all requests succeed.
    for year in range(start,end+1):
        year_rows=[]
        with ThreadPoolExecutor(max_workers=4) as pool:
            responses=list(pool.map(lambda p:(p,fetch(year,p,key,refresh_recent and year>=end-1)),[f'{n:02}' for n in range(1,48)]))
        for pref,response in responses:
            raw_total+=len(response['data'])
            path=CACHE/str(year)/(pref+'.json.gz')
            source_files.append({'year':year,'prefectureCode':pref,'httpStatus':response.get('httpStatus',200),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'records':len(response['data'])})
            for raw in response['data']:
                r=row_from_api(raw);seg=segment_for(r['type'])
                if not seg or r['period'] not in periods: continue
                r.update(segment=seg,unitValue=unit_value(seg,r));year_rows.append(r);published+=1
                item=prefs.setdefault(pref,{'code':pref,'prefecture':r['prefecture'],'quarterly':{},'municipalities':{}})
                # Name changes under the same code remain separate series.
                identity=r['code']+':'+r['municipality']
                muni=item['municipalities'].setdefault(identity,{'id':identity,'code':r['code'],'name':r['municipality'],'quarterly':{}})
                muni['quarterly'].setdefault(r['period'],[]).append(r)
                item['quarterly'].setdefault(r['period'],[]).append(r)
        by_period=defaultdict(list)
        for r in year_rows: by_period[r['period']].append(r)
        for p,rows in by_period.items(): national[p]=compact(rows)
        # Compact lists now so historical years do not accumulate raw objects.
        for item in prefs.values():
            for p in list(item['quarterly']):
                if isinstance(item['quarterly'][p],list): item['quarterly'][p]=compact(item['quarterly'][p])
            for muni in item['municipalities'].values():
                for p in list(muni['quarterly']):
                    if isinstance(muni['quarterly'][p],list): muni['quarterly'][p]=compact(muni['quarterly'][p])
        print(f'History {year}: raw={sum(len(r["data"]) for _,r in responses):,} residential={len(year_rows):,}; completed={year-start+1}/{end-start+1}',flush=True)
    if len(prefs)!=47 or any(p not in national for p in periods): raise ValueError('incomplete national coverage')
    meta={'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'source':SOURCE_LABEL,'sourceUrl':SOURCE_URL,'apiManualUrl':API_MANUAL,'priceClassification':'01','periods':periods,'startPeriod':periods[0],'latestPeriod':latest,'rawTransactionRecords':raw_total,'publishedResidentialRecords':published,'minSample':5,
          'notes':['取引価格の中央値であり、同じ物件の値上がり率や住宅価格指数ではありません。地域内の物件構成の変化も影響します。','市区町村は原典のコードと名称で区別します。合併・名称や境界の変更前後を補正して接続していません。','選択指標の価格を計算できる取引が5件未満の地域・四半期はグラフに表示しません。欠損は補完しません。2005年は第3・第4四半期のみです。']}
    manifest=[]
    for pref,item in sorted(prefs.items()):
        item['municipalities']=sorted(item['municipalities'].values(),key=lambda x:(x['code'],x['name']))
        payload={**meta,**item}
        write(OUT/(pref+'.json'),payload)
        b=(OUT/(pref+'.json')).read_bytes()
        manifest.append({'code':pref,'name':item['prefecture'],'municipalities':len(item['municipalities']),'sha256':hashlib.sha256(b).hexdigest(),'bytes':len(b)})
    write(OUT/'index.json',{**meta,'prefectures':manifest,'quarterly':dict(national),'rawSources':source_files})
    print(f'History complete: {periods[0]}–{latest}, {published:,} residential records, 47 prefectures',flush=True)
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--start-year',type=int,default=2005);ap.add_argument('--refresh-recent',action='store_true');ap.add_argument('--if-new',action='store_true');a=ap.parse_args()
    if not 2005<=a.start_year<=2024: ap.error('start year must be 2005..2024')
    if a.if_new and (OUT/'index.json').exists():
        existing=json.loads((OUT/'index.json').read_text())
        latest=json.loads((ROOT/'public/data/realestate-transactions.json').read_text())['latestPeriod']
        if existing.get('startPeriod')=='2005Q3' and existing.get('latestPeriod')==latest and len(existing.get('prefectures',[]))==47:
            print('ReinfOLib history is current: '+latest);raise SystemExit(0)
    build(a.start_year,a.refresh_recent)
