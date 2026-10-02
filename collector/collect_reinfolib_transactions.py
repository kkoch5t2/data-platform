#!/usr/bin/env python3
import argparse, csv, gzip, io, json, os, statistics, time, urllib.error, urllib.parse, urllib.request, zipfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.raw_store import save_json as save_raw_json
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.raw_store import save_json as save_raw_json
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "public/data/realestate-transactions.json"
BASE = ROOT / "public/data/municipality-stats-2026.json"
SOURCE_ID = "reinfolib_transactions"
SOURCE_LABEL = "国土交通省 不動産情報ライブラリ「不動産取引価格情報」"
SOURCE_URL = "https://www.reinfolib.mlit.go.jp/realEstatePrices/"
API_MANUAL = "https://www.reinfolib.mlit.go.jp/help/apiManual/xit001/"
API_URL = "https://www.reinfolib.mlit.go.jp/ex-api/external/XIT001"
UA = {"User-Agent": "DATLUME/1.0 (+https://datlume.com/)"}
SEGMENTS = {"land": "宅地(土地)", "house": "宅地(土地と建物)", "condo": "中古マンション等"}
DEFAULT_PERIODS = [(2025,1),(2025,2),(2025,3),(2025,4),(2026,1)]

def number(v):
    s=str(v or '').replace(',','').replace('㎡','').strip()
    if not s or s in {'-','—','不詳'}: return None
    try: return float(s)
    except ValueError: return None

def median(values, digits=0):
    xs=[float(x) for x in values if x is not None and float(x)>0]
    if not xs: return None
    v=statistics.median(xs)
    return round(v,digits) if digits else int(round(v))

def period_key(year, quarter): return f"{int(year)}Q{int(quarter)}"

def reinfolib_api_key():
    import stat
    key=os.environ.get('REINFOLIB_API_KEY','').strip()
    if key: return key
    configured=os.environ.get('DATLUME_REINFOLIB_KEY_FILE','').strip()
    secret_path=Path(configured).expanduser() if configured else Path.home()/'.config'/'datlume'/'reinfolib_api_key'
    if secret_path.exists():
        mode=stat.S_IMODE(secret_path.stat().st_mode)
        if mode & 0o077:
            raise SystemExit(f'ReinfOLib secret file permissions are too open ({oct(mode)}); require 0600 or stricter.')
        key=secret_path.read_text(encoding='utf-8').strip()
        if key: return key
    return ''

def normalize_period(v):
    s=str(v or '')
    import re
    m=re.search(r'(20\d{2}).*?第?([1-4])四半期',s)
    return period_key(m.group(1),m.group(2)) if m else None

def decode_csv(blob):
    for enc in ('cp932','utf-8-sig','shift_jis'):
        try: return blob.decode(enc)
        except UnicodeDecodeError: pass
    raise ValueError('unsupported CSV encoding')

def row_from_csv(row):
    return {
        'type': row.get('種類'),'code': row.get('市区町村コード'),'prefecture': row.get('都道府県名'),
        'municipality': row.get('市区町村名'),'tradePrice': number(row.get('取引価格（総額）')),
        'area': number(row.get('面積（㎡）')),'unitPrice': number(row.get('取引価格（㎡単価）')),
        'floorArea': number(row.get('延床面積（㎡）')),'period': normalize_period(row.get('取引時期')),
    }

def row_from_api(row):
    return {
        'type': row.get('Type'),'code': row.get('MunicipalityCode'),'prefecture': row.get('Prefecture'),
        'municipality': row.get('Municipality'),'tradePrice': number(row.get('TradePrice')),
        'area': number(row.get('Area')),'unitPrice': number(row.get('UnitPrice')),
        'floorArea': number(row.get('TotalFloorArea')),'period': normalize_period(row.get('Period')),
    }

def load_bootstrap(folder, allowed_periods):
    rows=[]
    paths=sorted(Path(folder).glob('*.zip'))
    if len(paths) != 47: raise ValueError(f'expected 47 prefecture ZIPs, got {len(paths)}')
    for path in paths:
        with zipfile.ZipFile(path) as z:
            names=[n for n in z.namelist() if n.lower().endswith('.csv')]
            if len(names)!=1: raise ValueError(f'{path}: expected one CSV')
            reader=csv.DictReader(io.StringIO(decode_csv(z.read(names[0]))))
            rows.extend(r for raw in reader if (r:=row_from_csv(raw))['period'] in allowed_periods)
    return rows

def api_request(key, year, quarter, area):
    params={'year':year,'quarter':quarter,'area':area,'priceClassification':'01','language':'ja'}
    url=API_URL+'?'+urllib.parse.urlencode(params)
    req=urllib.request.Request(url,headers={**UA,'Ocp-Apim-Subscription-Key':key,'Accept-Encoding':'gzip'})
    with urllib.request.urlopen(req,timeout=120) as response:
        data=response.read()
        if 'gzip' in (response.headers.get('Content-Encoding') or '').lower(): data=gzip.decompress(data)
    payload=json.loads(data.decode('utf-8'))
    if payload.get('status')!='OK': raise ValueError(f'XIT001 status not OK for {area} {year}Q{quarter}')
    save_raw_json(SOURCE_ID,f'{year}Q{quarter}-{area}',{'url':url,'data':payload.get('data',[])})
    return [row_from_api(x) for x in payload.get('data',[])]

def load_api(key, periods):
    rows=[]; last_call=0.0
    for year,quarter in periods:
        for n in range(1,48):
            wait=max(0,0.7-(time.monotonic()-last_call))
            if wait: time.sleep(wait)
            rows.extend(api_request(key,year,quarter,f'{n:02d}')); last_call=time.monotonic()
            print(f'XIT001 {year}Q{quarter} pref {n:02d}: total {len(rows):,}',flush=True)
    return rows

def municipality_mapper():
    base=json.loads(BASE.read_text(encoding='utf-8'))['records']
    exact={r['code']:r for r in base}; by_pref=defaultdict(list)
    for r in base: by_pref[r['prefecture']].append(r)
    for pref in by_pref: by_pref[pref].sort(key=lambda r:len(r['municipality']),reverse=True)
    def resolve(row):
        code=str(row.get('code') or '')
        if code in exact: return exact[code]
        name=str(row.get('municipality') or '')
        candidates=[r for r in by_pref.get(row.get('prefecture'),[]) if name.startswith(r['municipality']) and r['municipality'].endswith('市')]
        return candidates[0] if candidates else None
    return resolve

def segment_for(t):
    s=str(t or '').replace('（','(').replace('）',')').replace(' ','')
    for key,label in SEGMENTS.items():
        if s==label.replace(' ',''): return key
    return None

def unit_value(seg,row):
    if seg=='land': return row.get('unitPrice') or ((row['tradePrice']/row['area']) if row.get('tradePrice') and row.get('area') else None)
    if seg=='condo': return (row['tradePrice']/row['area']) if row.get('tradePrice') and row.get('area') else None
    return None

def summarize(rows):
    return {
        'count':len(rows),'medianTradePrice':median([r.get('tradePrice') for r in rows]),
        'medianArea':median([r.get('area') for r in rows],1),
        'medianUnitPrice':median([r.get('unitValue') for r in rows]),
        'medianFloorArea':median([r.get('floorArea') for r in rows],1),
    }

def main(bootstrap_dir=None):
    periods=[period_key(*p) for p in DEFAULT_PERIODS]
    if bootstrap_dir:
        rows=load_bootstrap(bootstrap_dir,set(periods)); acquisition='official-web-csv-bootstrap'
    else:
        key=reinfolib_api_key()
        if not key:
            raise SystemExit('REINFOLIB API key is required: set REINFOLIB_API_KEY or create ~/.config/datlume/reinfolib_api_key with mode 0600 (or pass --bootstrap-dir)')
        rows=load_api(key,DEFAULT_PERIODS); acquisition='official-api-XIT001'
    resolve=municipality_mapper(); mapped=[]; unmapped=0; ignored=0
    for row in rows:
        seg=segment_for(row.get('type'))
        if not seg: ignored+=1; continue
        base=resolve(row)
        if not base: unmapped+=1; continue
        x={**row,'segment':seg,'unitValue':unit_value(seg,row),'code':base['code'],'municipality':base['municipality'],'lon':base['lon'],'lat':base['lat']}
        mapped.append(x)
    by_muni=defaultdict(list); by_pref=defaultdict(list); by_period=defaultdict(list)
    for r in mapped:
        by_muni[r['code']].append(r); by_pref[r['prefecture']].append(r); by_period[r['period']].append(r)
    def segmented(rs): return {k:summarize([r for r in rs if r['segment']==k]) for k in SEGMENTS}
    municipalities=[]
    for code,rs in sorted(by_muni.items()):
        r=rs[0]; municipalities.append({'code':code,'prefecture':r['prefecture'],'municipality':r['municipality'],'lon':r['lon'],'lat':r['lat'],'segments':segmented(rs)})
    prefectures=[{'prefecture':p,'segments':segmented(rs)} for p,rs in sorted(by_pref.items())]
    payload={
        'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),'source':SOURCE_LABEL,'sourceUrl':SOURCE_URL,
        'apiManualUrl':API_MANUAL,'acquisition':acquisition,'priceClassification':'01','periods':periods,'latestPeriod':periods[-1],
        'periodLabel':'2025年第1四半期〜2026年第1四半期','minSampleForMap':5,
        'usageNotice':('このサービスは、国土交通省の不動産情報ライブラリのAPI機能を使用していますが、提供情報の最新性、正確性、完全性等が保証されたものではありません' if acquisition.startswith('official-api') else '出典：国土交通省 不動産情報ライブラリ。公開CSVをDATLUMEで集計・加工しています。'),
        'rawTransactionRecords':len(rows),'publishedResidentialRecords':len(mapped),'ignoredAgricultureForestRecords':ignored,'unmappedRecords':unmapped,
        'national':{'segments':segmented(mapped)},'quarterly':[{'period':p,'segments':segmented(by_period[p])} for p in periods],
        'prefectures':prefectures,'municipalities':municipalities,
        'notes':['価格は取引当事者へのアンケート等に基づく公表値で、数値の丸め以外の補正は行われていません。','最新期のデータ数は翌期以降に変わる可能性があります。','土地・土地と建物・中古マンション等を分けて集計し、異なる種類の価格を混在させていません。']
    }
    OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    print(f"reinfolib transactions: raw {len(rows):,} / residential {len(mapped):,} / municipalities {len(municipalities):,} / unmapped {unmapped:,} / {OUT}")
    return {'records':len(municipalities),'transactionRecords':len(rows),'publishedResidentialRecords':len(mapped),'latestPeriod':periods[-1],'acquisition':acquisition}

if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--bootstrap-dir');args=ap.parse_args()
    with SourceRun(SOURCE_ID,SOURCE_LABEL) as run: run.set_metrics(**main(args.bootstrap_dir))
