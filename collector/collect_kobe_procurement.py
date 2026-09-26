#!/usr/bin/env python3
import argparse, hashlib, html, json, math, re, sqlite3, time, unicodedata, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/kobe-procurement'
RAW.mkdir(parents=True, exist_ok=True)
BASE = 'https://nyusatsukekka.city.kobe.lg.jp/'
HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
TYPES = {'k': '工事', 'b': '物品・サービス', 'c': 'コンサルタント'}


def parse_years(spec):
    years = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = map(int, part.split('-', 1)); years.extend(range(a, b + 1))
        else:
            years.append(int(part))
    return sorted(set(years))


def fetch(url, data=None, retries=3):
    last = None
    payload = urllib.parse.urlencode(data).encode() if data is not None else None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=payload, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e; time.sleep(0.5 * (attempt + 1))
    raise last


def search_params(year):
    return {'fromyy': str(year), 'frommm': '01', 'fromdd': '01', 'toyy': str(year), 'tomm': '12', 'todd': '31',
            'koujimei': '', 'fromkin': '', 'tokin': '', 'anken': '', '-Find': '検索実行'}


def text_only(value):
    return clean(re.sub(r'<[^>]+>', ' ', html.unescape(value or '')))


def jp_date(value):
    s = unicodedata.normalize('NFKC', clean(value))
    m = re.search(r'令和\s*(\d+)年\s*(\d+)月\s*(\d+)日', s)
    if m:
        return f'{2018 + int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.search(r'(20\d{2})年\s*(\d+)月\s*(\d+)日', s)
    return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''


def parse_amount(value):
    s = unicodedata.normalize('NFKC', value or '').replace(',', '')
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*円', s)
    return int(round(float(m.group(1)))) if m else None


def parse_total(raw):
    text = text_only(raw)
    m = re.search(r'該当する\s*([\d,]+)件', text)
    return int(m.group(1).replace(',', '')) if m else 0


def parse_list(raw, typ):
    out = []
    # Kobe's legacy HTML omits some </tr> end tags. Also, cancelled/pending rows
    # can legitimately have no detail link, but still count in the official total.
    for tr in re.split(r'<tr[^>]*>', raw, flags=re.I)[1:]:
        cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr, re.I)
        if len(cells) < 6:
            continue
        number = text_only(cells[0])
        contract = text_only(cells[2])
        title = text_only(cells[4])
        if not number.isdigit() or not contract or not title:
            continue
        m = re.search(rf'detail{typ}1\.php\?rid=(\d+)', tr, re.I)
        out.append({'type': typ, 'rid': m.group(1) if m else '',
                    'notice_date': jp_date(text_only(cells[1])), 'contract': contract,
                    'title': title, 'method': text_only(cells[5])})
    return out


def collect_type_year(year, typ, workers):
    params = search_params(year); endpoint = BASE + f'results{typ}.php'
    first = fetch(endpoint, params); total = parse_total(first); rows = parse_list(first, typ)
    (RAW / f'{year}-{typ}-page0.html').write_text(first, encoding='utf-8')
    pages = math.ceil(total / 25) if total else 0
    if pages > 1:
        urls = []
        q = urllib.parse.urlencode({'rnum': '25', 'fromyy': year, 'frommm': '01', 'fromdd': '01', 'toyy': year, 'tomm': '12', 'todd': '31'})
        for p in range(1, pages):
            urls.append((p, endpoint + f'?start={p * 25}&' + q))
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch, u): (p, u) for p, u in urls}; page_data = {}
            for fut in as_completed(futs):
                p, u = futs[fut]; page_data[p] = (u, fut.result())
        for p in sorted(page_data):
            u, raw = page_data[p]
            expected = min(25, total - p * 25)
            parsed = parse_list(raw, typ)
            # The legacy site occasionally returns a 200 response with an incomplete
            # page under concurrent access. Re-fetch that page conservatively.
            for attempt in range(3):
                if len(parsed) == expected:
                    break
                time.sleep(0.8 * (attempt + 1))
                raw = fetch(u); parsed = parse_list(raw, typ)
            if len(parsed) != expected:
                raise RuntimeError(f'Kobe {year} {TYPES[typ]} page {p} parsed {len(parsed)} != expected {expected}')
            rows.extend(parsed)
    uniq = {f"{x['type']}:{x['contract']}": x for x in rows}
    bad = [x for x in uniq.values() if not x.get('title') or not x.get('notice_date')]
    if bad:
        raise RuntimeError(f'Kobe {year} {TYPES[typ]} has {len(bad)} rows missing title/date')
    if total and len(uniq) != total:
        raise RuntimeError(f'Kobe {year} {TYPES[typ]} parsed {len(uniq)} != official total {total}')
    return list(uniq.values()), total


def detail_text_lines(raw):
    s = re.sub(r'<script[\s\S]*?</script>', ' ', raw, flags=re.I)
    s = re.sub(r'<style[\s\S]*?</style>', ' ', s, flags=re.I)
    s = re.sub(r'<[^>]+>', '\n', s); s = html.unescape(s)
    return [clean(x) for x in s.splitlines() if clean(x) and clean(x) != '-->']


def value_after(lines, label):
    try:
        i = lines.index(label)
    except ValueError:
        return ''
    return lines[i + 1] if i + 1 < len(lines) else ''


def parse_detail(raw):
    lines = detail_text_lines(raw); joined = '\n'.join(lines)
    contract_date = jp_date(value_after(lines, '契約日'))
    amount = parse_amount(value_after(lines, '契約金額(税込)'))
    estimated = parse_amount(value_after(lines, '予定価格(税込)'))
    contract_kind = value_after(lines, '契約種別'); contract_style = value_after(lines, '契約方法')
    winner = ''
    if '契約の相手方' in lines:
        i = lines.index('契約の相手方'); stop = len(lines)
        for marker in ['一覧へ', 'このページの作成者']:
            if marker in lines[i + 1:]: stop = min(stop, lines.index(marker, i + 1))
        candidates = [x for x in lines[i + 1:stop] if x]
        if candidates:
            winner = candidates[-1]
    if winner in {'-', '－', 'なし', '該当なし'}:
        winner = ''
    return {'award_date': contract_date, 'amount': amount, 'estimated': estimated,
            'winner': canonical_company_name(winner) if winner else '', 'contract_kind': contract_kind,
            'contract_style': contract_style, 'detail_text': clean(f'{contract_kind} / {contract_style}')}


def fetch_detail(item):
    if not item.get('rid'):
        return {'source_url': BASE + f"search{item['type']}.php", 'pending': True}
    url = BASE + f"detail{item['type']}2.php?rid={item['rid']}&start=0"
    try:
        raw = fetch(url); d = parse_detail(raw); d['source_url'] = url; return d
    except Exception as e:
        return {'source_url': url, 'error': str(e)[:300]}


def save(conn, items, known):
    now = datetime.now(timezone.utc).isoformat(); org = '神戸市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); upserted = 0
    for x in items:
        if not x['title'] or not x['notice_date']:
            continue
        sid = f"kobe:{x['type']}:{x['contract']}"; d = x.get('detail') or {}
        is_it, tags, category, category_tags = classify(x['title'])
        source_url = d.get('source_url') or (BASE + f"detail{x['type']}1.php?rid={x['rid']}&start=0" if x.get('rid') else BASE + f"search{x['type']}.php")
        if sid in known and not d:
            conn.execute('''UPDATE procurements SET title=?,notice_date=?,notice_type=?,source_url=?,is_it=?,category=?,category_tags_json=?,tags_json=?,
              contract_method=?,award_method=?,collected_at=? WHERE source_id=?''', (
                x['title'], x['notice_date'], f"神戸市入札結果（{TYPES[x['type']]}）", source_url, int(is_it), category,
                json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), x['method'] or None,
                x['method'] or None, now, sid)); upserted += 1; continue
        winner = d.get('winner') or ''; company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        detail_text = clean(' / '.join(v for v in [f"神戸市 {TYPES[x['type']]}", d.get('detail_text', '')] if v))[:1000]
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=excluded.detail_fetched,
          award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,winner_name=excluded.winner_name,
          company_id=excluded.company_id,award_amount=excluded.award_amount,estimated_amount=excluded.estimated_amount,
          detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, int(x['rid']) if x.get('rid') else -int(hashlib.sha1(f"{x['type']}:{x['contract']}".encode()).hexdigest()[:12], 16), x['contract'], x['title'], x['notice_date'], org, org_id, f"神戸市入札結果（{TYPES[x['type']]}）",
            source_url, int(is_it), category, json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False),
            int(bool(d) and not d.get('error') and not d.get('pending')), d.get('award_date') or None, x['method'] or None, x['method'] or None,
            winner or None, company_id, d.get('amount'), d.get('estimated'), detail_text, now))
        upserted += 1
    conn.commit(); return upserted


def main(years, workers=6, do_export=True):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    known = {r[0] for r in conn.execute("SELECT source_id FROM procurements WHERE source_id LIKE 'kobe:%' AND detail_fetched=1")}
    parsed = upserted = details_fetched = 0; by_year = {}
    for year in years:
        year_items = []
        for typ in TYPES:
            rows, official_total = collect_type_year(year, typ, workers); year_items.extend(rows)
            print(f'kobe {year} {TYPES[typ]}: {len(rows)} / official {official_total}', flush=True)
        missing = [x for x in year_items if f"kobe:{x['type']}:{x['contract']}" not in known]
        if missing:
            with ThreadPoolExecutor(max_workers=workers) as ex:
                futs = {ex.submit(fetch_detail, x): x for x in missing}
                for fut in as_completed(futs):
                    item = futs[fut]; item['detail'] = fut.result(); details_fetched += int(not item['detail'].get('error') and not item['detail'].get('pending'))
        upserted += save(conn, year_items, known); parsed += len(year_items); by_year[year] = len(year_items)
        known.update(f"kobe:{x['type']}:{x['contract']}" for x in year_items if x.get('rid') and (x.get('detail') or {}).get('error') is None)
        print(f'kobe {year}: total={len(year_items)} new-details={len(missing)}', flush=True)
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close(); print(f'kobe: parsed={parsed} upserted={upserted} details={details_fetched} total={summary["records"]} years={by_year}', flush=True)
    return {'records': parsed, 'upserted': upserted, 'detailsFetched': details_fetched, 'years': len(by_year),
            'startYear': min(by_year), 'endYear': max(by_year)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser(); ap.add_argument('--years', default=str(datetime.now().year)); ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--no-export', action='store_true'); args = ap.parse_args(); years = parse_years(args.years)
    with SourceRun('kobe_procurement', '神戸市 入札結果') as run:
        run.set_metrics(**main(years, max(1, min(args.workers, 10)), not args.no_export))
