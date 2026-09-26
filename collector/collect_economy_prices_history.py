#!/usr/bin/env python3
import json
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_economy_prices import fetch, parse_table
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_economy_prices import fetch, parse_table

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'public/data/economy-prices-history.json'
RAW=ROOT/'data/raw/economy-prices-history';RAW.mkdir(parents=True,exist_ok=True)
YEARS=range(2013,2026)
SOURCE='https://www.stat.go.jp/data/kouri/kouzou/gaiyou.html'
FIELDS=['overall','overallExRent','food','housing','utilities','household','clothing','medical','transport','education','recreation','misc']

def main():
    snapshots=[]
    for year in YEARS:
        url=f'https://www.stat.go.jp/data/kouri/kouzou/pdf/g_{year}.pdf'
        raw=fetch(url);(RAW/f'g_{year}.pdf').write_bytes(raw);records=parse_table(raw)
        if len(records)!=47:raise ValueError(f'{year}: expected 47 prefectures, got {len(records)}')
        snapshots.append({'year':year,'records':records});print(f'economy prices history {year}: 47 prefectures')
    payload={
      'schemaVersion':1,'generatedAt':datetime.now(timezone.utc).isoformat(),
      'source':'総務省統計局 小売物価統計調査（構造編） 消費者物価地域差指数','sourceUrl':SOURCE,
      'note':'各年とも全国平均=100の地域差指数。CPIのような時系列物価上昇率ではなく、同一年内の地域間比較用。基準改定をまたぐ単純な水準比較には注意。',
      'years':list(YEARS),'fields':FIELDS,'snapshots':snapshots,
    }
    OUT.parent.mkdir(parents=True,exist_ok=True);OUT.write_text(json.dumps(payload,ensure_ascii=False,separators=(',',':')),encoding='utf-8')
    return {'records':47*len(list(YEARS)),'prefectures':47,'startYear':min(YEARS),'endYear':max(YEARS)}

if __name__=='__main__':
    with SourceRun('economy_prices_history','総務省統計局 消費者物価地域差指数 時系列') as run:run.set_metrics(**main())
