#!/usr/bin/env python3
import argparse, hashlib, html, json, re, sqlite3, time, urllib.parse, urllib.request
from datetime import datetime, timezone
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name

HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
ROOTS = [
    'https://www2.city.kyoto.lg.jp/rizai/chodo/ebid/anken.htm',
    'https://www2.city.kyoto.lg.jp/rizai/chodo/ebid/kekka.htm',
]
KINDS = {'buppin': '物品', 'kouji': '工事・測量設計等'}
RESULT_RE = re.compile(r'(?:^|/)(buppin|kouji)/kekka_(?:buppin|kouji)(\d{4})[a-z]?\.htm$', re.I)

def fetch(url, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read()
            return body.decode('cp932', 'replace')
        except Exception as e:
            last = e
            time.sleep(0.5 * (attempt + 1))
    raise last


def text_only(value):
    return clean(re.sub(r'<[^>]+>', ' ', html.unescape(value or '')))


def parse_years(spec):
    if not spec: return None
    years = set()
    for part in spec.split(','):
        part = part.strip()
        if not part: continue
        if '-' in part:
            a, b = map(int, part.split('-', 1)); years.update(range(a, b + 1))
        else: years.add(int(part))
    return years

def discover_pages(target_years=None):
    urls = set()
    for root in ROOTS:
        raw = fetch(root)
        for href in re.findall(r'<a[^>]+href=["\']([^"\']+)["\']', raw, re.I):
            href = html.unescape(href)
            m = RESULT_RE.search(href)
            if not m: continue
            page_year = int(m.group(2))
            if target_years and not any(y in {page_year, page_year + 1} for y in target_years):
                continue
            url = urllib.parse.urljoin(root, href)
            if url.startswith('http://'): url = 'https://' + url[7:]
            urls.add(url)
    return sorted(urls)


def parse_amount(value):
    s = (value or '').replace(',', '')
    m = re.search(r'([0-9]+(?:\.[0-9]+)?)', s)
    return int(round(float(m.group(1)))) if m else None


def clean_winner(value):
    s = clean(value)
    if not s or any(x in s for x in ('不成立', '不調', '中止', '取止', '辞退')): return ''
    s = re.sub(r'(?:代表者|代表取締役(?:社長|副社長|会長)?|取締役(?:社長|支店長)?|代表社員|支店長|営業所長|事業所長|所長|理事長)(?:執行役員|社長執行役員)?[^\n]*$', '', s)
    return canonical_company_name(s)

def parse_page(url, target_years=None):
    raw = fetch(url); kind = 'buppin' if '/buppin/' in url else 'kouji'; out = []
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', raw, re.I):
        raw_cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr, re.I)
        cells = [text_only(x) for x in raw_cells]
        if len(cells) < 6 or not re.fullmatch(r'20\d{2}\.\d{2}\.\d{2}', cells[0] if cells else ''):
            continue
        award_date = cells[0].replace('.', '-')
        if target_years and int(award_date[:4]) not in target_years: continue
        link = re.search(r'<a[^>]+href=["\']([^"\']+)', raw_cells[3], re.I)
        source_url = urllib.parse.urljoin(url, html.unescape(link.group(1))) if link else url
        out.append({
            'kind': kind, 'award_date': award_date, 'bid_no': cells[1], 'industry': cells[2],
            'title': cells[3], 'winner': cells[4], 'amount': parse_amount(cells[5]),
            'source_url': source_url,
        })
    return out


def save(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '京都市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); count = 0
    for x in items:
        key = f"{x['kind']}|{x['award_date']}|{x['bid_no']}|{x['source_url']}"
        digest = hashlib.sha1(key.encode()).hexdigest(); sid = f"kyoto:{x['kind']}:{digest[:16]}"; xid = int(digest[:12], 16)
        winner = clean_winner(x['winner']); company_id = stable_id('co', winner) if winner else None
        if company_id: conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        is_it, tags, category, category_tags = classify(x['title'])
        detail = clean(f"京都市 {KINDS[x['kind']]} / {x['industry']} / 公式ページ掲載の落札額（税抜き）")[:1000]
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,
          award_date=excluded.award_date,winner_name=excluded.winner_name,company_id=excluded.company_id,
          award_amount=excluded.award_amount,detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, xid, x['bid_no'] or digest[:16], x['title'], x['award_date'], org, org_id,
            f"京都市電子入札結果（{KINDS[x['kind']]}）", x['source_url'], int(is_it), category,
            json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 0,
            x['award_date'], None, None, winner or None, company_id, x['amount'], None, detail, now))
        count += 1
    conn.commit(); return count

def main(target_years=None, do_export=True):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    parsed = upserted = 0; dates = []; by_kind = {k: 0 for k in KINDS}
    pages = discover_pages(target_years)
    for url in pages:
        rows = parse_page(url, target_years)
        if not rows: continue
        n = save(conn, rows); parsed += len(rows); upserted += n
        for x in rows: by_kind[x['kind']] += 1; dates.append(x['award_date'])
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'kyoto: pages={len(pages)} parsed={parsed} upserted={upserted} total={summary["records"]} kinds={by_kind}', flush=True)
    return {'records': parsed, 'upserted': upserted, 'pages': len(pages),
            'startDate': min(dates) if dates else None, 'endDate': max(dates) if dates else None}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default='')
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args(); years = parse_years(args.years)
    with SourceRun('kyoto_procurement', '京都市 電子入札執行結果') as run:
        run.set_metrics(**main(years, not args.no_export))
