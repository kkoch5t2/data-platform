#!/usr/bin/env python3
import csv, io, json, statistics, urllib.request, zipfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from core.source_run import SourceRun
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / 'public' / 'data'
RAW = ROOT / 'data' / 'raw' / 'land-prices'
RAW.mkdir(parents=True, exist_ok=True)
YEAR = 2026
HISTORY_YEARS = range(2020, YEAR + 1)
UA = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
PREFS = ['北海道','青森県','岩手県','宮城県','秋田県','山形県','福島県','茨城県','栃木県','群馬県','埼玉県','千葉県','東京都','神奈川県','新潟県','富山県','石川県','福井県','山梨県','長野県','岐阜県','静岡県','愛知県','三重県','滋賀県','京都府','大阪府','兵庫県','奈良県','和歌山県','鳥取県','島根県','岡山県','広島県','山口県','徳島県','香川県','愛媛県','高知県','福岡県','佐賀県','長崎県','熊本県','大分県','宮崎県','鹿児島県','沖縄県']
PREF_BY_CODE = {f'{i:02d}': p for i, p in enumerate(PREFS, 1)}


def num(v, kind=float):
    try:
        return kind(str(v).replace(',', '').strip())
    except Exception:
        return None


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=90) as res:
        return res.read()


def url_for(kind, year):
    return f'https://nlftp.mlit.go.jp/ksj/old/data/{kind}/{kind}-{year}P/{kind}-{year}P-48-01.0a.zip'


def pref_from_address(address):
    text = str(address or '').replace('　', '').strip()
    return next((p for p in PREFS if text.startswith(p)), '')


def pref_from_row(row, name_key=''):
    pref = pref_from_address(row.get('所在・地番') or row.get('住居表示') or '')
    if not pref and name_key:
        pref = pref_from_address(row.get(name_key, ''))
    if pref:
        return pref
    code = str(row.get('行政区域コード') or row.get('所在地コード') or '').strip()
    return PREF_BY_CODE.get(code[:2], '') if len(code) >= 2 else ''


def read_rows(kind, year):
    url = url_for(kind, year)
    raw_path = RAW / f'{kind}-{year}.zip'
    blob = fetch(url)
    raw_path.write_bytes(blob)
    with zipfile.ZipFile(io.BytesIO(blob)) as zf:
        csv_name = next(n for n in zf.namelist() if n.lower().endswith('.csv'))
        text = zf.read(csv_name).decode('cp932')
    rows = list(csv.DictReader(io.StringIO(text)))
    if not rows:
        raise ValueError(f'{kind}-{year}: no rows')
    price_cols = [k for k in rows[0].keys() if '価格' in k and '変動' not in k]
    if not price_cols:
        raise ValueError(f'{kind}-{year}: price column missing')
    return rows, price_cols[-1], url


def compact_points(kind, year):
    rows, price_col, url = read_rows(kind, year)
    records, prices = [], []
    name_key = '標準地名' if kind == 'L01' else '基準地地名'
    for r in rows:
        lon = num(r.get('経度')); lat = num(r.get('緯度')); price = num(r.get(price_col), int)
        if lon is None or lat is None or not price:
            continue
        lon /= 3600; lat /= 3600
        address = (r.get('所在・地番') or r.get('住居表示') or '').replace('　', ' ').strip()
        pref = pref_from_row(r, name_key)
        records.append([
            f"{r.get('行政区域コード') or r.get('所在地コード') or ''}-{r.get('番号用途区分') or r.get('用途') or ''}-{r.get('番号連番') or r.get('連番') or ''}",
            round(lon, 6), round(lat, 6), price, num(r.get('対前年変動率')),
            r.get(name_key, ''), address, pref,
            r.get('駅名', ''), num(r.get('駅距離'), int),
            r.get('利用現況', ''), num(r.get('地積'), int),
        ])
        prices.append(price)
    return records, prices, url


def aggregate(kind, year):
    rows, price_col, _ = read_rows(kind, year)
    buckets = {p: [] for p in PREFS}
    all_prices = []
    for r in rows:
        price = num(r.get(price_col), int)
        if not price:
            continue
        name_key = '標準地名' if kind == 'L01' else '基準地地名'
        pref = pref_from_row(r, name_key)
        if pref:
            buckets[pref].append(price)
        all_prices.append(price)
    result = []
    for pref in PREFS:
        vals = buckets[pref]
        if vals:
            result.append({'prefecture': pref, 'count': len(vals), 'medianPrice': int(statistics.median(vals)), 'averagePrice': int(sum(vals)/len(vals))})
    return {
        'year': year,
        'count': len(all_prices),
        'medianPrice': int(statistics.median(all_prices)) if all_prices else None,
        'averagePrice': int(sum(all_prices)/len(all_prices)) if all_prices else None,
        'prefectures': result,
    }


def write_latest(kind, filename, label):
    records, prices, url = compact_points(kind, YEAR)
    payload = {
        'schemaVersion': 2,
        'year': YEAR,
        'source': label,
        'sourceUrl': url,
        'license': 'CC BY 4.0',
        'dataAsOf': f'{YEAR}-01-01' if kind == 'L01' else f'{YEAR}-07-01',
        'fields': ['id','lon','lat','price','yoy','name','address','prefecture','station','stationDistance','use','area'],
        'stats': {'records': len(records), 'medianPrice': int(statistics.median(prices)), 'averagePrice': int(sum(prices)/len(prices))},
        'records': records,
    }
    path = DATA / filename
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    print(f'{filename}: {len(records)} points')
    return payload


def write_history():
    series = {'landPrice': [], 'landSurvey': []}
    for y in HISTORY_YEARS:
        for key, kind in [('landPrice', 'L01'), ('landSurvey', 'L02')]:
            try:
                item = aggregate(kind, y)
                series[key].append(item)
                print(f'history {kind} {y}: {item["count"]}')
            except Exception as e:
                print(f'WARNING: history {kind} {y} skipped: {e}')
    payload = {
        'schemaVersion': 1,
        'generatedAt': datetime.now(timezone.utc).isoformat(),
        'years': sorted({x['year'] for v in series.values() for x in v}),
        'sources': {
            'landPrice': '国土交通省 国土数値情報 地価公示',
            'landSurvey': '国土交通省 国土数値情報 都道府県地価調査',
        },
        'series': series,
    }
    (DATA / 'land-price-history.json').write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')), encoding='utf-8')
    return payload


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    latest = write_latest('L01', 'land-prices-2026.json', '国土交通省 国土数値情報 地価公示')
    survey = write_latest('L02', 'land-survey-2026.json', '国土交通省 国土数値情報 都道府県地価調査')
    history = write_history()
    return {'records': latest['stats']['records'], 'surveyRecords': survey['stats']['records'], 'historyYears': len(history['years'])}


if __name__ == '__main__':
    with SourceRun('land_prices', '国土交通省 地価公示 / 都道府県地価調査') as run:
        run.set_metrics(**main())
