#!/usr/bin/env python3
"""Verify history files, source coverage and all count conservation."""
import argparse,gzip,hashlib,json,math,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from collector.backfill_reinfolib_history import compact
from collector.collect_reinfolib_transactions import row_from_api,segment_for,unit_value
def main(raw=False):
    folder=ROOT/'public/data/realestate-history';d=json.loads((folder/'index.json').read_text())
    assert d['priceClassification']=='01' and d['startPeriod']=='2005Q3'
    periods=d['periods'];latest=d['latestPeriod']
    expected=[f'{y}Q{q}' for y in range(2005,int(latest[:4])+1) for q in range(1,5) if '2005Q3'<=f'{y}Q{q}'<=latest]
    assert periods==expected and len(d['prefectures'])==47
    assert len(d['rawSources'])==47*(int(latest[:4])-2005+1)
    assert {x['code'] for x in d['prefectures']}=={f'{n:02}' for n in range(1,48)}
    assert {(x['year'],x['prefectureCode']) for x in d['rawSources']}=={(y,f'{n:02}') for y in range(2005,int(latest[:4])+1) for n in range(1,48)}
    assert len({(s['year'],s['prefectureCode']) for s in d['rawSources']})==len(d['rawSources'])
    assert sum(s['records'] for s in d['rawSources'])==d['rawTransactionRecords']
    shards={};checks=0;total=0
    for info in d['prefectures']:
        body=(folder/(info['code']+'.json')).read_bytes()
        assert len(body)==info['bytes'] and hashlib.sha256(body).hexdigest()==info['sha256']
        shard=json.loads(body);shards[info['code']]=shard
        assert shard['periods']==periods and shard['priceClassification']=='01'
        assert len(shard['municipalities'])==info['municipalities']
        assert len({m['id'] for m in shard['municipalities']})==len(shard['municipalities'])
        for m in shard['municipalities']:
            assert m['id']==m['code']+':'+m['name'] and m['code'].startswith(info['code'])
            for p,segs in m['quarterly'].items():
                assert p in periods
                for seg,s in segs.items():
                    assert seg in ('land','house','condo')
                    assert isinstance(s['count'],int) and s['count']>=0
                    for field in ('medianTradePrice','medianArea','medianUnitPrice','medianFloorArea'):
                        v=s[field];assert v is None or isinstance(v,(int,float)) and math.isfinite(v) and v>0
                    assert all(isinstance(n,int) and 0<=n<=s['count'] for n in s['validCounts'].values())
                    checks+=6
        for p in periods:
            for seg in ('land','house','condo'):
                n=shard['quarterly'].get(p,{}).get(seg,{}).get('count',0)
                assert n==sum(m['quarterly'].get(p,{}).get(seg,{}).get('count',0) for m in shard['municipalities'])
                total+=n;checks+=1
    assert total==d['publishedResidentialRecords']
    for p in periods:
        for seg in ('land','house','condo'):
            assert d['quarterly'][p][seg]['count']==sum(s['quarterly'].get(p,{}).get(seg,{}).get('count',0) for s in shards.values())
            checks+=1
    if raw:
        current_year=None; national_rows={}
        def check_national():
            for p,rows in national_rows.items(): assert compact(rows)==d['quarterly'][p]
        for source in d['rawSources']:
            if source['year']!=current_year:
                check_national();national_rows={};current_year=source['year']
            pref=source['prefectureCode'];path=ROOT/'data/raw/reinfolib-history'/str(source['year'])/(pref+'.json.gz')
            assert hashlib.sha256(path.read_bytes()).hexdigest()==source['sha256']
            with gzip.open(path,'rt',encoding='utf-8') as f: original=json.load(f)
            assert len(original['data'])==source['records']
            if source['httpStatus']==404: assert original['message']=='検索結果がありません。' and not original['data']
            groups={};cities={}
            for row in original['data']:
                r=row_from_api(row);assert r['period'].startswith(str(source['year'])+'Q') and r['code'].startswith(pref)
                seg=segment_for(r['type'])
                if not seg or r['period'] not in periods: continue
                r.update(segment=seg,unitValue=unit_value(seg,r))
                groups.setdefault(r['period'],[]).append(r)
                national_rows.setdefault(r['period'],[]).append(r)
                cities.setdefault((r['code']+':'+r['municipality'],r['period']),[]).append(r)
            for p,rows in groups.items(): assert compact(rows)==shards[pref]['quarterly'][p];checks+=1
            muni={m['id']:m for m in shards[pref]['municipalities']}
            for (identity,p),rows in cities.items(): assert compact(rows)==muni[identity]['quarterly'][p];checks+=1
        check_national()
    print(f'ReinfOLib history audit: {checks:,} checks, {len(periods)} quarters, {total:,} residential records, raw={raw}, failures=0')
if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--require-raw',action='store_true');a=ap.parse_args();main(a.require_raw)
