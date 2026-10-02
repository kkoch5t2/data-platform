#!/usr/bin/env python3
import json, math, sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path: sys.path.insert(0,str(ROOT))
from collector.collect_reinfolib_transactions import api_area_number, normalize_municipality_code
DATA=ROOT/'public/data/realestate-transactions.json'

def main():
    d=json.loads(DATA.read_text(encoding='utf-8')); errors=[]; checks=0
    def ok(cond,msg):
        nonlocal checks; checks+=1
        if not cond: errors.append(msg)
    ok(d.get('source','').startswith('国土交通省 不動産情報ライブラリ'),'source mismatch')
    ok(d.get('priceClassification')=='01','must publish transaction-price information only')
    periods=d.get('periods') or []
    ok(len(periods)==5 and periods==sorted(periods),'expected five sorted quarters')
    ok(d.get('latestPeriod')==periods[-1] if periods else False,'latest period mismatch')
    ok(d.get('acquisition')=='official-api-XIT001','production acquisition must use XIT001 API')
    ok(normalize_municipality_code('1101')=='01101','API municipality-code normalization regression')
    ok(api_area_number('8888') is None and api_area_number('9999') is None,'API land-area sentinel decoding regression')
    ok(api_area_number('9999',floor=True) is None and api_area_number('5',floor=True) is None and api_area_number('0',floor=True) is None,'API floor-area sentinel decoding regression')
    ok(api_area_number('10',floor=True)==10,'API ordinary floor area 10 must remain numeric')
    ok((d.get('rawTransactionRecords') or 0)>100000,'raw transaction volume too low')
    ok((d.get('publishedResidentialRecords') or 0)>50000,'published residential volume too low')
    ok((d.get('unmappedRecords') or 0)==0,'unmapped residential records remain')
    prefs=d.get('prefectures') or []; munis=d.get('municipalities') or []
    ok(len(prefs)==47,'prefecture coverage must be 47')
    ok(len(munis)>=1000,'municipality coverage unexpectedly low')
    ok(len({r.get('code') for r in munis})==len(munis),'duplicate municipality codes')
    segments={'land','house','condo'}
    national=d.get('national',{}).get('segments',{})
    ok(set(national)==segments,'national segment keys mismatch')
    for key in segments:
        s=national.get(key,{})
        ok((s.get('count') or 0)>10000,f'{key}: national count too low')
        ok((s.get('medianTradePrice') or 0)>0,f'{key}: median price missing')
        if key!='house': ok((s.get('medianUnitPrice') or 0)>0,f'{key}: median unit price missing')
    for r in munis:
        code=r.get('code'); checks+=4
        if not (isinstance(code,str) and len(code)==5): errors.append(f'bad code {code}')
        if not (isinstance(r.get('lon'),(int,float)) and isinstance(r.get('lat'),(int,float))): errors.append(f'{code}: coordinates missing')
        if not r.get('prefecture') or not r.get('municipality'): errors.append(f'{code}: names missing')
        if set((r.get('segments') or {}))!=segments: errors.append(f'{code}: segment keys mismatch')
        for key,s in (r.get('segments') or {}).items():
            checks+=2
            if (s.get('count') or 0)<0: errors.append(f'{code}/{key}: negative count')
            for field in ('medianTradePrice','medianArea','medianUnitPrice','medianFloorArea'):
                v=s.get(field); checks+=1
                if v is not None and (not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0): errors.append(f'{code}/{key}: invalid {field}={v}')
    if errors:
        print('reinfolib transaction audit failed:\n- '+'\n- '.join(errors[:80]),file=sys.stderr);raise SystemExit(1)
    print(f'reinfolib transaction audit: {checks} checks / {len(munis)} municipalities / 47 prefectures / 0 failures')
if __name__=='__main__': main()
