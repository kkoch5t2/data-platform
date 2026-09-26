#!/usr/bin/env python3
import argparse, hashlib, html, json, re, sqlite3, time, unicodedata
import urllib.parse, urllib.request
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name

ROOT = Path(__file__).resolve().parents[1]
BASE = 'https://www.city.chiba.jp'
HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
CATEGORIES = {
    'koji': '建設工事', 'sokuryo': '測量・コンサルタント', 'buppin': '物品',
    'itaku': '業務委託', 'other': 'その他',
}
INDEX = '/portal/business/index19/nyusatsujoho/kekka/{category}/index.html'

def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last


def text_only(value):
    return clean(re.sub(r'<[^>]+>', ' ', html.unescape(value or '')))


def page_links(raw, base):
    out = []
    for href, label in re.findall(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>', raw, re.I | re.S):
        out.append((urllib.parse.urljoin(base, html.unescape(href)), text_only(label)))
    return out

def parse_years(spec):
    if not spec:
        return None
    years = set()
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = map(int, part.split('-', 1)); years.update(range(a, b + 1))
        else:
            years.add(int(part))
    return years


def fiscal_year(label):
    s = unicodedata.normalize('NFKC', label or '')
    m = re.search(r'令和\s*(\d+)年度', s)
    if m: return 2018 + int(m.group(1))
    m = re.search(r'平成\s*(\d+)年度', s)
    if m: return 1988 + int(m.group(1))
    return None


def parse_date(value):
    s = unicodedata.normalize('NFKC', value or '')
    m = re.search(r'令和\s*(\d+)年\s*(\d+)月\s*(\d+)日', s)
    if m: return f'{2018+int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.search(r'平成\s*(\d+)年\s*(\d+)月\s*(\d+)日', s)
    if m: return f'{1988+int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'
    m = re.search(r'((?:19|20)\d{2})[./年](\d{1,2})[./月](\d{1,2})', s)
    return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''


def parse_amount(value):
    s = unicodedata.normalize('NFKC', value or '').replace(',', '')
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)', s)
    return int(round(float(m.group(1)))) if m else None


def month_fiscal_year(url):
    m = re.search(r'/(\d{2})(\d{2})\.html$', urllib.parse.urlparse(url).path)
    if not m: return None
    era_year, month = int(m.group(1)), int(m.group(2))
    year = (1988 + era_year) if era_year >= 24 else (2018 + era_year)
    return year if month >= 4 else year - 1


def discover_pages(category, target_years=None):
    index = urllib.parse.urljoin(BASE, INDEX.format(category=category))
    raw = fetch(index); pages = set()
    year_re = re.compile(rf'/kekka/{category}/(?:r\d+|\d+)\.html$')
    month_re = re.compile(rf'/kekka/{category}/\d{{4}}\.html$')
    for year_url, label in page_links(raw, index):
        if not year_re.search(urllib.parse.urlparse(year_url).path): continue
        fy = fiscal_year(label)
        if target_years and fy not in target_years: continue
        try: year_raw = fetch(year_url)
        except Exception: continue
        for url, _ in page_links(year_raw, year_url):
            if not month_re.search(urllib.parse.urlparse(url).path): continue
            if target_years and month_fiscal_year(url) not in target_years: continue
            pages.add(url)
    return sorted(pages)

def header_index(headers, *needles):
    for i, value in enumerate(headers):
        key = re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))
        if any(n in key for n in needles): return i
    return None


def parse_page(category, url):
    raw = fetch(url); out = []
    for table in re.findall(r'<table[^>]*>([\s\S]*?)</table>', raw, re.I):
        rows = re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', table, re.I)
        if not rows: continue
        headers = [text_only(x) for x in re.findall(r'<t[dh][^>]*>([\s\S]*?)</t[dh]>', rows[0], re.I)]
        title_i = header_index(headers, '案件名'); winner_i = header_index(headers, '契約の相手方', '落札業者')
        amount_i = header_index(headers, '契約金額', '落札金額'); date_i = header_index(headers, '落札決定日')
        method_i = header_index(headers, '入札契約方式', '契約方式'); dept_i = header_index(headers, '入札担当課')
        corp_i = header_index(headers, '法人番号')
        if title_i is None or date_i is None: continue
        for tr in rows[1:]:
            raw_cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr, re.I)
            cells = [text_only(x) for x in raw_cells]
            if title_i >= len(cells): continue
            title = cells[title_i]
            if not title or title.startswith('該当期間') or title.startswith('現在このページ'): continue
            award_date = parse_date(cells[date_i] if date_i < len(cells) else '')
            if not award_date: continue
            link = re.search(r'<a[^>]+href=["\']([^"\']+)', raw_cells[title_i], re.I) if title_i < len(raw_cells) else None
            source_url = urllib.parse.urljoin(url, html.unescape(link.group(1))) if link else url
            out.append({
                'category': category, 'title': title, 'award_date': award_date, 'source_url': source_url,
                'winner': cells[winner_i] if winner_i is not None and winner_i < len(cells) else '',
                'amount': parse_amount(cells[amount_i]) if amount_i is not None and amount_i < len(cells) else None,
                'method': cells[method_i] if method_i is not None and method_i < len(cells) else '',
                'department': cells[dept_i] if dept_i is not None and dept_i < len(cells) else '',
                'corporate_number': cells[corp_i] if corp_i is not None and corp_i < len(cells) else '',
            })
    return out


def usable_winner(value):
    s = clean(value)
    if not s or any(x in s for x in ('入札不調', '不調', '不成立', '中止', '取止')): return ''
    return canonical_company_name(s)


def save(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '千葉市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); count = 0
    for x in items:
        key = x['source_url'] + '|' + x['award_date'] + '|' + x['title']
        digest = hashlib.sha1(key.encode()).hexdigest(); sid = f"chiba:{digest[:16]}"
        xid = int(digest[:12], 16); winner = usable_winner(x['winner']); company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        is_it, tags, category, category_tags = classify(x['title'])
        detail = clean(' / '.join(v for v in [f"千葉市 {CATEGORIES[x['category']]}", x['department'],
            f"法人番号:{x['corporate_number']}" if x['corporate_number'] else '', '契約金額は公式ページの税込表示'] if v))[:1000]
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=excluded.detail_fetched,
          award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,winner_name=excluded.winner_name,
          company_id=excluded.company_id,award_amount=excluded.award_amount,estimated_amount=excluded.estimated_amount,detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, xid, digest[:16], x['title'], x['award_date'], org, org_id, f"千葉市入札結果（{CATEGORIES[x['category']]}）",
            x['source_url'], int(is_it), category, json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False),
            1, x['award_date'], x['method'] or None, x['method'] or None, winner or None, company_id,
            x['amount'], None, detail, now))
        count += 1
    conn.commit(); return count

def main(target_years=None, do_export=True):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    page_count = 0; all_rows = []; raw_by_type = {}
    for category in CATEGORIES:
        pages = discover_pages(category, target_years); rows = []
        for url in pages:
            rows.extend(parse_page(category, url)); page_count += 1
        raw_by_type[category] = len(rows); all_rows.extend(rows)
        print(f'chiba {CATEGORIES[category]}: pages={len(pages)} raw_records={len(rows)}', flush=True)
    # A small number of Chiba contracts are published under multiple result categories.
    # De-duplicate across every category by the canonical official detail URL/date/title tuple.
    unique = {}
    for x in all_rows:
        key = f"{x['source_url']}|{x['award_date']}|{x['title']}"
        unique.setdefault(key, x)
    rows = list(unique.values())
    if target_years is None:
        conn.execute("DELETE FROM procurements WHERE source_id LIKE 'chiba:%'")
        conn.commit()
    upserted = save(conn, rows)
    by_type = {k: 0 for k in CATEGORIES}
    for x in rows: by_type[x['category']] += 1
    dates = [x['award_date'] for x in rows]
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'chiba: raw={len(all_rows)} unique={len(rows)} duplicates={len(all_rows)-len(rows)} '
          f'upserted={upserted} pages={page_count} total={summary["records"]} types={by_type}', flush=True)
    return {'records': len(rows), 'upserted': upserted, 'pages': page_count,
            'duplicatesRemoved': len(all_rows)-len(rows),
            'startDate': min(dates) if dates else None, 'endDate': max(dates) if dates else None}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default='')
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args(); years = parse_years(args.years)
    with SourceRun('chiba_procurement', '千葉市 入札（見積）結果') as run:
        run.set_metrics(**main(years, not args.no_export))
