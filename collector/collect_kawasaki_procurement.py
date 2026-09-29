#!/usr/bin/env python3
import argparse, hashlib, html, json, re, shutil, sqlite3, subprocess, time, urllib.parse, urllib.request
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
PORTAL = 'https://www.city.kawasaki.jp/233300/'
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
    # backtitles is an opaque Shift-JIS value controlled by the official portal.
    # Read the current official link instead of guessing it; stale values return HTTP 404.
    portal = fetch_utf8(PORTAL)
    search_url = ''
    for m in re.finditer(r'href=["\']([^"\']*keiyaku\.city\.kawasaki\.jp[^"\']*job=KekkaSearch[^"\']*)', portal, re.I):
        candidate = html.unescape(m.group(1))
        q = urllib.parse.parse_qs(urllib.parse.urlparse(candidate).query)
        if (q.get('kyoku_cd') or [''])[0] == kyoku and (q.get('syubetu_cd') or [''])[0] == division:
            search_url = candidate
            break
    if not search_url:
        raise RuntimeError(f'Kawasaki official search link not found kyoku={kyoku} division={division}')
    raw = fetch(search_url)
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



HOSPITAL_ARCHIVE = 'https://www.city.kawasaki.jp/830-1/category/345-5-0-0-0-0-0-0-0-0.html'
TRAFFIC_ROOTS = {
    '工事': 'https://www.city.kawasaki.jp/820/category/8-5-3-1-0-0-0-0-0-0.html',
    '委託': 'https://www.city.kawasaki.jp/820/category/8-5-3-2-0-0-0-0-0-0.html',
    '物品': 'https://www.city.kawasaki.jp/820/category/8-5-3-3-0-0-0-0-0-0.html',
}


def fetch_utf8(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e; time.sleep(0.5 * (attempt + 1))
    raise last


def fetch_bytes(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            last = e; time.sleep(0.5 * (attempt + 1))
    raise last


def clean_link_title(value):
    value = re.sub(r'\s*\[[12]\d{3}年[^\]]*\]\s*(?:新着)?\s*$', '', text_only(value))
    return clean(value)


def parse_traffic_link(text, url, division):
    text = clean_link_title(text)
    m_date = re.search(r'【(?:[^】]*】)*?令和\s*(\d+)年\s*(\d+)月\s*(\d+)日[^】]*】', text)
    if not m_date:
        m_date = re.search(r'令和\s*(\d+)年\s*(\d+)月\s*(\d+)日', text)
    if not m_date:
        return None
    result_date = f'{2018 + int(m_date.group(1)):04d}-{int(m_date.group(2)):02d}-{int(m_date.group(3)):02d}'
    brackets = re.findall(r'【([^】]+)】', text)
    method = ''
    status = ''
    for value in brackets:
        if '不調' in value or '中止' in value or '取止' in value:
            status = value
        if '一般競争' in value:
            method = '一般競争入札'
        elif '随意契約' in value:
            method = '随意契約'
        elif '指名競争' in value:
            method = '指名競争入札'
    title = re.sub(r'^(?:【[^】]+】)+', '', text).strip()
    title = re.sub(r'\s*入札結果\s*$', '', title).strip()
    if not title:
        return None
    return {
        'bureau': '交通局', 'division': division, 'notice_date': result_date,
        'title': title, 'method': method, 'status': status, 'winner': '', 'amount': None,
        'contract': '', 'industry': '', 'item': '', 'url': url,
    }


def collect_traffic_results(years):
    wanted = set(years); out = []
    for division, root in TRAFFIC_ROOTS.items():
        root_raw = fetch_utf8(root)
        year_pages = []
        for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', root_raw, re.I):
            href = urllib.parse.urljoin(root, html.unescape(m.group(1))); label = text_only(m.group(2))
            if re.fullmatch(r'令和\s*\d+年度', label):
                year_pages.append(href)
        for page in dict.fromkeys(year_pages):
            raw = fetch_utf8(page)
            for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', raw, re.I):
                href = urllib.parse.urljoin(page, html.unescape(m.group(1)))
                label = text_only(m.group(2))
                if '/820/page/' not in href or '令和' not in label:
                    continue
                item = parse_traffic_link(label, href, division)
                if item and int(item['notice_date'][:4]) in wanted:
                    out.append(item)
    uniq = {x['url']: x for x in out}
    print(f'kawasaki traffic: {len(uniq)} records', flush=True)
    return list(uniq.values())


def visible_pdf_link(cell, page_url):
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+\.pdf(?:\?[^"\']*)?)["\'][^>]*>([\s\S]*?)</a>', cell, re.I):
        label = text_only(m.group(2))
        if not label or '内訳' in label:
            continue
        return urllib.parse.urljoin(page_url, html.unescape(m.group(1))), re.sub(r'\s*\(PDF[^)]*\)\s*$', '', label, flags=re.I).strip()
    return '', ''


def parse_hospital_page(raw, page_url):
    out = []
    for tr in re.findall(r'<tr\b[^>]*>[\s\S]*?</tr>', raw, re.I):
        cells = re.findall(r'<td\b[^>]*>([\s\S]*?)</td>', tr, re.I)
        if len(cells) < 5:
            continue
        notice_date = jp_date(text_only(cells[0]))
        if not notice_date:
            continue
        # 2021-2022 pages have five columns (no 種目); newer pages have six.
        title_idx, method_idx = (4, 5) if len(cells) >= 6 else (3, 4)
        pdf_url, link_title = visible_pdf_link(cells[title_idx], page_url)
        title = link_title or text_only(cells[title_idx])
        if not title:
            continue
        division_raw = text_only(cells[1])
        division_hits = [x for x in ('工事', '委託', '物品') if x in division_raw]
        division = '・'.join(division_hits) if division_hits else division_raw
        out.append({
            'bureau': '病院局', 'division': division, 'notice_date': notice_date,
            'title': title, 'method': text_only(cells[method_idx]), 'status': '', 'winner': '', 'amount': None,
            'contract': '', 'industry': text_only(cells[2]), 'item': text_only(cells[3]) if len(cells) >= 6 else '',
            'url': page_url, 'pdf_url': pdf_url,
        })
    return out


def extract_pdf_text(url):
    if not url or not shutil.which('pdftotext'):
        return ''
    try:
        data = fetch_bytes(url)
        p = subprocess.run(['pdftotext', '-layout', '-', '-'], input=data, capture_output=True, timeout=60)
        return p.stdout.decode('utf-8', 'replace') if p.returncode == 0 else ''
    except Exception as e:
        print(f'WARNING kawasaki hospital PDF {url}: {e}', flush=True)
        return ''


def enrich_hospital_pdf(item):
    text = extract_pdf_text(item.get('pdf_url', ''))
    if not text:
        return item
    m = re.search(r'契約番号\s*[:：]\s*([^\s]+)', text)
    if m:
        item['contract'] = clean(m.group(1))
    m = re.search(r'落札金額\s*[:：]\s*([\d,]+)\s*円', text)
    if m:
        item['amount'] = parse_amount(m.group(1))
    for line in text.splitlines():
        m = re.match(r'\s*(.+?)\s+([\d,]+)\s*円\s+落札(?:\s|$)', line)
        if m:
            item['winner'] = usable_winner(m.group(1)); break
    if not item['winner']:
        m = re.search(r'(?:落札業者名|落札者|契約相手方)\s*[:：]\s*(.+)', text)
        if m:
            item['winner'] = usable_winner(m.group(1).splitlines()[0])
    if not item['amount'] and ('不調' in text or '取止' in text or '中止' in text):
        item['status'] = '入札不調・中止等'
    return item


def collect_hospital_results(years, workers=6):
    wanted = set(years); archive = fetch_utf8(HOSPITAL_ARCHIVE); pages = []
    for m in re.finditer(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', archive, re.I):
        label = text_only(m.group(2)); mm = re.search(r'令和\s*(\d+)年\s*(\d+)月入札結果公表', label)
        if not mm or 2018 + int(mm.group(1)) not in wanted:
            continue
        pages.append(urllib.parse.urljoin(HOSPITAL_ARCHIVE, html.unescape(m.group(1))))
    items = []
    for page in dict.fromkeys(pages):
        raw = fetch_utf8(page)
        digest = hashlib.sha1(page.encode()).hexdigest()[:12]
        (RAW / f'hospital-{digest}.html').write_text(raw, encoding='utf-8')
        items.extend(parse_hospital_page(raw, page))
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
        items = list(ex.map(enrich_hospital_pdf, items))
    uniq = {}
    for x in items:
        key = x['contract'] or hashlib.sha1((x['notice_date'] + '|' + x['title'] + '|' + x['url']).encode()).hexdigest()[:20]
        uniq[key] = x
    print(f'kawasaki hospital: {len(uniq)} records', flush=True)
    return list(uniq.values())


def save_bureau_results(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '川崎市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); upserted = 0
    for x in items:
        winner = usable_winner(x.get('winner', '')); company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        ident = x.get('contract') or hashlib.sha1((x['notice_date'] + '|' + x['title'] + '|' + x['url']).encode()).hexdigest()[:20]
        bureau_key = 'traffic' if x['bureau'] == '交通局' else 'hospital'
        sid = f"kawasaki:{bureau_key}:{ident}"
        notice_type = f"川崎市落札結果（{x.get('division') or 'その他'}・{x['bureau']}）"
        detail = clean(' / '.join(v for v in [x['bureau'], x.get('industry',''), x.get('item',''), x.get('method',''), x.get('status','')] if v))[:1000]
        is_it, tags, category, category_tags = classify_with_context(x['title'], sid, notice_type, detail)
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=excluded.detail_fetched,
          award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,winner_name=excluded.winner_name,
          company_id=excluded.company_id,award_amount=excluded.award_amount,detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, int(x['notice_date'][:4]), x.get('contract') or ident, x['title'], x['notice_date'], org, org_id, notice_type, x['url'], int(is_it), category,
            json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 1, x['notice_date'],
            x.get('method') or None, x.get('method') or None, winner or None, company_id, x.get('amount'), None, detail, now))
        upserted += 1
    conn.commit(); return upserted

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


def main(years, workers=6, do_export=True, bureau_years=None):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    parsed = upserted = requests = 0; by_year = {}; bureau_years = bureau_years or years
    for year in years:
        items, reqs = collect_year(year, workers); n = save(conn, items)
        parsed += len(items); upserted += n; requests += reqs; by_year[year] = len(items)
        print(f'kawasaki {year}: parsed={len(items)} requests={reqs}', flush=True)
    traffic = collect_traffic_results(bureau_years)
    hospital = collect_hospital_results(bureau_years, workers)
    bureau_items = traffic + hospital
    upserted += save_bureau_results(conn, bureau_items); parsed += len(bureau_items)
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'kawasaki: parsed={parsed} upserted={upserted} total={summary["records"]} years={by_year}', flush=True)
    all_years = sorted(set(years) | set(bureau_years))
    return {'records': parsed, 'upserted': upserted, 'requests': requests, 'trafficRecords': len(traffic), 'hospitalRecords': len(hospital), 'years': len(all_years), 'startYear': min(all_years), 'endYear': max(all_years)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=str(datetime.now().year))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--bureau-years', default='', help='交通局・病院局の取得年。省略時は--yearsと同じ')
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args(); years = parse_years(args.years); bureau_years = parse_years(args.bureau_years) if args.bureau_years else years
    with SourceRun('kawasaki_procurement', '川崎市 入札情報・落札結果') as run:
        run.set_metrics(**main(years, args.workers, not args.no_export, bureau_years))
