#!/usr/bin/env python3
import argparse, hashlib, html, json, re, sqlite3, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify_with_context, export_json, stable_id, clean
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify_with_context, export_json, stable_id, clean

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/sendai-procurement'
RAW.mkdir(parents=True, exist_ok=True)
BASE = 'https://www.city.sendai.jp'
HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
DIVISIONS = {
    'buppin': ('物品', '/buppin/jigyosha/keyaku/kekka/r{era}buppin/index.html'),
    'itaku': ('委託', '/buppin/jigyosha/keyaku/kekka/r{era}itaku/index.html'),
}


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
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e; time.sleep(0.5 * (attempt + 1))
    raise last


def text_only(value):
    value = re.sub(r'<script[\s\S]*?</script>|<style[\s\S]*?</style>', ' ', value or '', flags=re.I)
    return clean(re.sub(r'<[^>]+>', ' ', html.unescape(value)))


def jp_date(value):
    m = re.search(r'令和\s*(\d+)年\s*(\d+)月\s*(\d+)日', value or '')
    if not m:
        return ''
    return f'{2018 + int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}'


def annual_url(fiscal_year, division):
    era = fiscal_year - 2018
    return urllib.parse.urljoin(BASE, DIVISIONS[division][1].format(era=era))


def parse_index(raw, fiscal_year, division, source_url):
    out = []
    for m in re.finditer(r'<h2[^>]*>([\s\S]*?)</h2>([\s\S]*?)(?=<h2\b|$)', raw, re.I):
        notice_date = jp_date(text_only(m.group(1)))
        if not notice_date:
            continue
        block = m.group(2)
        for li in re.findall(r'<li[^>]*>([\s\S]*?)</li>', block, re.I):
            a = re.search(r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>([\s\S]*?)</a>', li, re.I)
            if not a:
                continue
            href, title = html.unescape(a.group(1)), text_only(a.group(2))
            if not title or '/kekka/' not in href:
                continue
            cancelled = bool(re.search(r'class=["\']strike["\']|入札中止|発注中止', li, re.I))
            detail_url = urllib.parse.urljoin(source_url, href)
            out.append({
                'fiscal_year': fiscal_year, 'division': division, 'notice_date': notice_date,
                'title': title, 'url': detail_url, 'cancelled': cancelled,
            })
    # Same announcement page can link multiple titles to one detail page, but title/date is the record key.
    uniq = {(x['division'], x['notice_date'], x['title']): x for x in out}
    return list(uniq.values())


def detail_metadata(raw, title):
    plain = text_only(raw)
    # Prefer the structured procurement-summary occurrence over breadcrumb/navigation text.
    pos = plain.find('発注案件の概要')
    scoped = plain[pos:] if pos >= 0 else plain
    title_pos = scoped.find(title)
    if title_pos >= 0:
        scoped = scoped[title_pos:title_pos + 1800]
    method = ''
    m = re.search(r'入札方式\s+(.+?)\s+(?:入札説明書等交付場所|参加申請書提出期限|入札執行予定日|詳細について)', scoped)
    if m:
        method = clean(m.group(1))
    bid_date = ''
    m = re.search(r'入札執行予定日\s+(令和\s*\d+年\s*\d+月\s*\d+日)', scoped)
    if m:
        bid_date = jp_date(m.group(1))
    return method, bid_date


def enrich(items, workers=6):
    urls = sorted({x['url'] for x in items})
    fetched = {}
    with ThreadPoolExecutor(max_workers=max(1, min(workers, 8))) as ex:
        futs = {ex.submit(fetch, u): u for u in urls}
        for fut in as_completed(futs):
            u = futs[fut]
            try:
                fetched[u] = fut.result()
            except Exception as e:
                print(f'WARNING sendai detail {u}: {e}', flush=True)
                fetched[u] = ''
    for i, x in enumerate(items):
        raw = fetched.get(x['url'], '')
        if raw:
            digest = hashlib.sha1(x['url'].encode()).hexdigest()[:16]
            (RAW / f'detail-{digest}.html').write_text(raw, encoding='utf-8')
        method, bid_date = detail_metadata(raw, x['title']) if raw else ('', '')
        x['method'] = method; x['bid_date'] = bid_date
    return items


def collect_year(fiscal_year, workers=6):
    items = []
    for division in DIVISIONS:
        url = annual_url(fiscal_year, division)
        raw = fetch(url)
        (RAW / f'{fiscal_year}-{division}-index.html').write_text(raw, encoding='utf-8')
        parsed = parse_index(raw, fiscal_year, division, url)
        print(f'sendai FY{fiscal_year} {DIVISIONS[division][0]}: index={len(parsed)}', flush=True)
        items.extend(parsed)
    items = enrich(items, workers)
    bad = [x for x in items if not x['title'] or not x['notice_date'] or not x['url']]
    if bad:
        raise RuntimeError(f'Sendai FY{fiscal_year}: {len(bad)} rows missing core fields')
    return items


def save(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '仙台市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); upserted = 0
    for x in items:
        digest = hashlib.sha1('|'.join([x['division'], x['notice_date'], x['title'], x['url']]).encode()).hexdigest()[:20]
        sid = f"sendai:{x['division']}:{digest}"
        division_name = DIVISIONS[x['division']][0]
        status = '・入札中止' if x['cancelled'] else ''
        notice_type = f'仙台市発注情報（{division_name}{status}）'
        detail_bits = ['仙台市財政局契約課', division_name]
        if x['method']: detail_bits.append(x['method'])
        if x['bid_date']: detail_bits.append(f"入札予定日 {x['bid_date']}")
        if x['cancelled']: detail_bits.append('公式ページで入札中止表示')
        detail = clean(' / '.join(detail_bits))[:1000]
        is_it, tags, category, category_tags = classify_with_context(x['title'], sid, notice_type, detail)
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=excluded.detail_fetched,
          contract_method=excluded.contract_method,detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, x['fiscal_year'], digest, x['title'], x['notice_date'], org, org_id, notice_type, x['url'], int(is_it), category,
            json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 1, None,
            x['method'] or None, None, None, None, None, None, detail, now))
        upserted += 1
    conn.commit(); return upserted


def main(years, workers=6, do_export=True):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    parsed = upserted = 0; by_year = {}; cancelled = 0
    for fiscal_year in years:
        items = collect_year(fiscal_year, workers); n = save(conn, items)
        parsed += len(items); upserted += n; cancelled += sum(1 for x in items if x['cancelled']); by_year[fiscal_year] = len(items)
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'sendai: parsed={parsed} upserted={upserted} cancelled={cancelled} total={summary["records"]} years={by_year}', flush=True)
    return {'records': parsed, 'upserted': upserted, 'cancelled': cancelled, 'years': len(by_year), 'startYear': min(by_year), 'endYear': max(by_year)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=str(datetime.now().year))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args(); years = parse_years(args.years)
    with SourceRun('sendai_procurement', '仙台市 本庁契約課 発注情報（物品・委託）') as run:
        run.set_metrics(**main(years, args.workers, not args.no_export))
