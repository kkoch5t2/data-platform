#!/usr/bin/env python3
import argparse, hashlib, html, json, re, sqlite3, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify_with_context, export_json, stable_id, norm, clean, canonical_company_name
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify_with_context, export_json, stable_id, norm, clean, canonical_company_name

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/kawasaki-procurement'
RAW.mkdir(parents=True, exist_ok=True)
BASE = 'https://keiyaku.city.kawasaki.jp/epc/servlet/p'
HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
BUREAUS = {'01': '財政局', '02': '上下水道局'}
DIVISIONS = {'1': '工事', '2': '委託', '3': '物品'}


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


def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode('shift_jis', 'ignore')
        except Exception as e:
            last = e; time.sleep(0.5 * (attempt + 1))
    raise last


def text_only(value):
    return clean(re.sub(r'<[^>]+>', ' ', html.unescape(value or '')))


def jp_date(value):
    m = re.search(r'令和\s*(\d+)年\s*(\d+)月\s*(\d+)日', value or '')
    if not m:
        return ''
    return f'{2018 + int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'


def parse_amount(value):
    s = re.sub(r'[^0-9.-]', '', str(value or '').replace(',', ''))
    if not s or s in {'-', '.', '-.'}:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def search_template(kyoku, division):
    # The official system validates backlink parameters, so derive a valid list URL
    # from its own search page instead of hard-coding opaque Shift-JIS parameters.
    params = {
        'backlinks': '../index.htm', 'backtitles': 'カワサキ', 'job': 'KekkaSearch',
        'kyoku_cd': kyoku, 'syubetu_cd': division,
    }
    raw = fetch(BASE + '?' + urllib.parse.urlencode(params, encoding='shift_jis', errors='ignore'))
    m = re.search(r'href="([^"]*job=KekkaList[^"]+)"', raw, re.I)
    if not m:
        raise RuntimeError(f'Kawasaki list URL not found kyoku={kyoku} division={division}')
    url = urllib.parse.urljoin(BASE, html.unescape(m.group(1)))
    parsed = urllib.parse.parse_qs(urllib.parse.urlparse(url).query, keep_blank_values=True)
    return {k: v[-1] for k, v in parsed.items()}


def week_starts(year):
    d = date(year, 1, 1)
    d -= timedelta(days=d.weekday())
    end = date(year, 12, 31)
    while d <= end:
        yield d
        d += timedelta(days=7)


def list_url(template, start, page):
    p = dict(template)
    p['week_sdate'] = start.strftime('%Y%m%d') + '0000'
    p['week_edate'] = (start + timedelta(days=6)).strftime('%Y%m%d') + '2359'
    p['searchtype'] = 'R'
    p['page_no'] = str(page)
    return BASE + '?' + urllib.parse.urlencode(p)


def parse_rows(raw, kyoku, division, source_url):
    out = []
    for tr in re.findall(r'<tr[^>]*>[\s\S]*?</tr>', raw, re.I):
        if 'KekkaDetail' not in tr:
            continue
        cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr, re.I)
        if len(cells) < 8:
            continue
        href = re.search(r'href="([^"]*KekkaDetail[^"]+)"', cells[1], re.I)
        detail_url = urllib.parse.urljoin(BASE, html.unescape(href.group(1))) if href else source_url
        q = urllib.parse.parse_qs(urllib.parse.urlparse(detail_url).query)
        contract = (q.get('keiyaku_no') or [''])[0]
        award_date = jp_date(text_only(cells[0]))
        title = text_only(cells[1])
        if not title or not award_date:
            continue
        out.append({
            'kyoku': kyoku, 'division': division, 'contract': contract,
            'award_date': award_date, 'title': title, 'winner': text_only(cells[2]),
            'amount': parse_amount(text_only(cells[3])), 'industry': text_only(cells[4]),
            'method': text_only(cells[5]), 'budget_dept': text_only(cells[6]),
            'contract_dept': text_only(cells[7]), 'url': detail_url,
        })
    return out


def collect_week(template, kyoku, division, start):
    first_url = list_url(template, start, 1)
    raw = fetch(first_url)
    plain = text_only(raw)
    if 'パラメータの値が不正です' in plain:
        raise RuntimeError(f'Kawasaki invalid query {kyoku}/{division}/{start}')
    m = re.search(r'(\d+)\s*/\s*(\d+)', plain)
    pages = int(m.group(2)) if m else 1
    rows = parse_rows(raw, kyoku, division, first_url)
    blobs = [(1, raw)]
    for page in range(2, pages + 1):
        u = list_url(template, start, page)
        r = fetch(u); blobs.append((page, r)); rows.extend(parse_rows(r, kyoku, division, u))
    return rows, blobs, pages


def collect_year(year, workers=6):
    jobs = []
    for kyoku in BUREAUS:
        for division in DIVISIONS:
            template = search_template(kyoku, division)
            for start in week_starts(year):
                # Only retain rows whose award date belongs to the requested calendar year.
                jobs.append((template, kyoku, division, start))
    rows = []; requests = 0
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
        futs = {ex.submit(collect_week, *job): job for job in jobs}
        for fut in as_completed(futs):
            template, kyoku, division, start = futs[fut]
            parsed, blobs, pages = fut.result(); requests += pages
            for page, raw in blobs:
                name = f'{year}-{kyoku}-{division}-{start.isoformat()}-p{page}.html'
                (RAW / name).write_text(raw, encoding='utf-8')
            rows.extend(x for x in parsed if x['award_date'].startswith(str(year)))
    # A contract may be exposed by overlapping first/last weeks across years; key by official contract number.
    uniq = {}
    for x in rows:
        key = (x['kyoku'], x['division'], x['contract'] or hashlib.sha1((x['award_date'] + x['title']).encode()).hexdigest())
        uniq[key] = x
    bad = [x for x in uniq.values() if not x['title'] or not x['award_date']]
    if bad:
        raise RuntimeError(f'Kawasaki {year}: {len(bad)} rows missing title/date')
    return list(uniq.values()), requests


def usable_winner(value):
    s = clean(value)
    if not s or s in {'-', '－', '―', '不調', '中止', '取止め', '該当なし'}:
        return ''
    return canonical_company_name(s)


def save(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '川崎市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org))
    upserted = 0
    for x in items:
        winner = usable_winner(x['winner']); company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        contract = x['contract'] or hashlib.sha1('|'.join([x['award_date'], x['title'], winner]).encode()).hexdigest()[:20]
        sid = f"kawasaki:{x['kyoku']}:{x['division']}:{contract}"
        notice_type = f"川崎市落札結果（{DIVISIONS[x['division']]}・{BUREAUS[x['kyoku']]}）"
        detail = clean(' / '.join(v for v in [BUREAUS[x['kyoku']], x['industry'], x['budget_dept'], x['contract_dept']] if v))[:1000]
        is_it, tags, category, category_tags = classify_with_context(x['title'], sid, notice_type, detail)
        xid = int(contract) if contract.isdigit() and len(contract) <= 18 else None
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=excluded.detail_fetched,
          award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,
          winner_name=excluded.winner_name,company_id=excluded.company_id,award_amount=excluded.award_amount,
          estimated_amount=excluded.estimated_amount,detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, xid, contract, x['title'], x['award_date'], org, org_id, notice_type, x['url'], int(is_it), category,
            json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 1, x['award_date'],
            x['method'] or None, x['method'] or None, winner or None, company_id, x['amount'], None, detail, now))
        upserted += 1
    conn.commit(); return upserted


def main(years, workers=6, do_export=True):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    parsed = upserted = requests = 0; by_year = {}
    for year in years:
        items, reqs = collect_year(year, workers); n = save(conn, items)
        parsed += len(items); upserted += n; requests += reqs; by_year[year] = len(items)
        print(f'kawasaki {year}: parsed={len(items)} requests={reqs}', flush=True)
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'kawasaki: parsed={parsed} upserted={upserted} total={summary["records"]} years={by_year}', flush=True)
    return {'records': parsed, 'upserted': upserted, 'requests': requests, 'years': len(by_year), 'startYear': min(by_year), 'endYear': max(by_year)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=str(datetime.now().year))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args(); years = parse_years(args.years)
    with SourceRun('kawasaki_procurement', '川崎市 入札情報・落札結果') as run:
        run.set_metrics(**main(years, args.workers, not args.no_export))
