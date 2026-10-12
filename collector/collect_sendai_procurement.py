#!/usr/bin/env python3
import argparse, hashlib, html, http.cookiejar, json, re, sqlite3, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify_with_context, export_json, stable_id, clean, norm, canonical_company_name
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify_with_context, export_json, stable_id, clean, norm, canonical_company_name

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



EPI_BASE = 'https://www.epi-cloud.fwd.ne.jp'
EPI_ENTRY = EPI_BASE + '/koukai/do/KF001ShowAction?name1=0620060006800640'
EPI_SOURCE_URL = 'https://www.city.sendai.jp/kojikeyaku/jigyosha/keyaku/denshi/'
EPI_TYPES = {
    'construction': ('工事', '00', 'KK', 'KFK'),
    'consulting': ('コンサル', '01', 'KK', 'KFK'),
    'goods-services': ('物品・役務', '11', 'KB', 'KFB'),
}


def probe_epi(timeout=20):
    req = urllib.request.Request(EPI_ENTRY, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as response:
        response.read(1)


def epi_open(opener, url, data=None):
    payload = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=payload, headers=HEADERS)
    with opener.open(req, timeout=60) as r:
        return r.read().decode('cp932', 'replace')


def epi_session(kind):
    label, supply, prefix, frame_prefix = EPI_TYPES[kind]
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    epi_open(opener, EPI_ENTRY)
    epi_open(opener, EPI_BASE + '/koukai/do/KK000ShowAction', {
        'hachukikan_hidden': '1042ZZZZZZ', 'hachukikan_name': '仙台市',
        'bukyoku': '', 'kakakari': '', 'kasho_name': '', 'supplytype': supply,
    })
    epi_open(opener, EPI_BASE + '/koukai/do/koukai_main')
    epi_open(opener, EPI_BASE + f'/koukai/do/{prefix}401ShowAction', {
        'select_kikan': '0000ZZZZZZ', 'auth': '', 'gyosyu_type': '',
    })
    return opener, label, prefix, frame_prefix


def epi_result_payload(year, prefix):
    d = {
        'A094': '030', 'nendo': str(year), 'A046': '', 'ITEM_1_CONTENT': '',
        'hizukeKubun': '020', 'date_start': '', 'date_end': '',
        'orderKey1': '020', 'orderKey2': '020', 'A300': '040',
        'perPage': '100', 'curPage': '1', 'recCount': '', 'checkList': '',
    }
    if prefix == 'KK':
        d.update({'gyosyu': '', 'koujimei': '', 'koujiNo': '', 'koujibangou': ''})
    else:
        d.update({'kenmei': '', 'koujiNo': ''})
    return d


def epi_cell(row, col):
    m = re.search(rf'<td[^>]*class=["\'][^"\']*listCol{col}[^"\']*["\'][^>]*>([\s\S]*?)</td>', row, re.I)
    return text_only(re.sub(r'<script[\s\S]*?</script>', ' ', m.group(1), flags=re.I)) if m else ''


def parse_epi_frame(raw, fiscal_year, kind, label):
    out = []
    for row in re.findall(r'<tr\b[^>]*>[\s\S]*?</tr>', raw, re.I):
        m_id = re.search(r"doEdit030\(\s*['\"]([^'\"]+)", row, re.I)
        if not m_id:
            continue
        date_text = epi_cell(row, 2)
        m_date = re.search(r'(\d{4})/(\d{1,2})/(\d{1,2})', date_text)
        if not m_date:
            continue
        result_date = f'{int(m_date.group(1)):04d}-{int(m_date.group(2)):02d}-{int(m_date.group(3)):02d}'
        title = epi_cell(row, 3)
        contract = epi_cell(row, 4)
        method = epi_cell(row, 5)
        winner_raw = epi_cell(row, 6)
        winner = '' if winner_raw in {'', '-', '－', '―'} else canonical_company_name(winner_raw)
        amount_cell = re.search(r'<td[^>]*class=["\'][^"\']*listCol7[^"\']*["\'][^>]*>([\s\S]*?)</td>', row, re.I)
        amount_raw = ''
        if amount_cell:
            sm = re.search(r"sMoney\s*=\s*['\"]([^'\"]*)", amount_cell.group(1), re.I)
            amount_raw = clean(sm.group(1)) if sm else text_only(amount_cell.group(1))
        amount = int(re.sub(r'\D', '', amount_raw)) if re.fullmatch(r'[\d,]+', amount_raw or '') else None
        department = epi_cell(row, 8)
        out.append({
            'fiscal_year': fiscal_year, 'kind': kind, 'division_name': label,
            'result_id': m_id.group(1), 'notice_date': result_date, 'title': title,
            'contract': contract, 'method': method, 'winner': winner, 'amount': amount,
            'status': '' if amount is not None else amount_raw, 'department': department,
            'url': EPI_SOURCE_URL,
        })
    return out


def collect_epi_results(fiscal_year, kind):
    opener, label, prefix, frame_prefix = epi_session(kind)
    search_url = EPI_BASE + f'/koukai/do/{prefix}401SearchAction'
    raw = epi_open(opener, search_url, epi_result_payload(fiscal_year, prefix))
    m = re.search(r'name=["\']recCount["\']\s+value=["\'](\d+)', raw, re.I)
    expected = int(m.group(1)) if m else 0
    pages = (expected + 99) // 100 if expected else 0
    items = []
    for page in range(1, pages + 1):
        if page > 1:
            epi_open(opener, search_url + '?' + urllib.parse.urlencode({'page': page}))
        frame = epi_open(opener, EPI_BASE + f'/koukai/do/{frame_prefix}401FrameShow')
        items.extend(parse_epi_frame(frame, fiscal_year, kind, label))
    uniq = {x['result_id']: x for x in items}
    if len(uniq) != expected:
        raise RuntimeError(f'Sendai EPI FY{fiscal_year} {label}: official={expected} parsed={len(uniq)}')
    print(f'sendai EPI FY{fiscal_year} {label}: {len(uniq)}', flush=True)
    return list(uniq.values())


def save_epi(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '仙台市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); upserted = 0
    for x in items:
        winner = x['winner']; company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        sid = f"sendai:epi:{x['kind']}:{x['result_id']}"
        notice_type = f"仙台市入札・見積結果（{x['division_name']}）"
        detail = clean(' / '.join(v for v in [x['department'], x['method'], x['status']] if v))[:1000]
        is_it, tags, category, category_tags = classify_with_context(x['title'], sid, notice_type, detail)
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
          organization_id=excluded.organization_id,notice_type=excluded.notice_type,source_url=excluded.source_url,is_it=excluded.is_it,
          category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,detail_fetched=excluded.detail_fetched,
          award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,
          winner_name=excluded.winner_name,company_id=excluded.company_id,award_amount=excluded.award_amount,
          detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, x['fiscal_year'], x['contract'] or x['result_id'], x['title'], x['notice_date'], org, org_id, notice_type, x['url'],
            int(is_it), category, json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 1,
            x['notice_date'] if (x['winner'] or x['amount'] is not None) else None, x['method'] or None, x['method'] or None,
            winner or None, company_id, x['amount'], None, detail, now))
        upserted += 1
    conn.commit(); return upserted


def delete_legacy_duplicates(conn, epi_items):
    titles = {norm(x['title']) for x in epi_items if x['title']}
    if not titles:
        return 0
    rows = conn.execute("SELECT source_id,title FROM procurements WHERE source_id LIKE 'sendai:buppin:%' OR source_id LIKE 'sendai:itaku:%'").fetchall()
    ids = [sid for sid, title in rows if norm(title) in titles]
    if ids:
        conn.executemany('DELETE FROM procurements WHERE source_id=?', [(x,) for x in ids]); conn.commit()
    return len(ids)

def dedupe_announcement_items(items):
    uniq = {}
    for x in items:
        key = (x['notice_date'], norm(x['title']), x['url'])
        # Some Sendai pages appear in both 物品 and 委託 indexes. Keep one public record.
        if key not in uniq or (x['division'] == 'buppin' and uniq[key]['division'] != 'buppin'):
            uniq[key] = x
    return list(uniq.values())


def delete_announcement_duplicates(conn):
    rows = conn.execute("""SELECT source_id,notice_date,title,source_url FROM procurements
                         WHERE source_id LIKE 'sendai:buppin:%' OR source_id LIKE 'sendai:itaku:%'
                         ORDER BY source_id""").fetchall()
    groups = {}
    for sid, notice_date, title, source_url in rows:
        groups.setdefault((notice_date, norm(title), source_url or ''), []).append(sid)
    remove = []
    for ids in groups.values():
        if len(ids) <= 1:
            continue
        keep = next((sid for sid in ids if sid.startswith('sendai:buppin:')), ids[0])
        remove.extend(sid for sid in ids if sid != keep)
    if remove:
        conn.executemany('DELETE FROM procurements WHERE source_id=?', [(sid,) for sid in remove]); conn.commit()
    return len(remove)


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
    parsed = upserted = cancelled = deduped = 0; by_year = {}
    for fiscal_year in years:
        epi_items = []
        for kind in EPI_TYPES:
            epi_items.extend(collect_epi_results(fiscal_year, kind))
        deduped += delete_legacy_duplicates(conn, epi_items)
        upserted += save_epi(conn, epi_items)
        result_titles = {norm(x['title']) for x in epi_items}
        announcements = [x for x in collect_year(fiscal_year, workers) if norm(x['title']) not in result_titles]
        announcements = dedupe_announcement_items(announcements)
        upserted += save(conn, announcements)
        deduped += delete_announcement_duplicates(conn)
        cancelled += sum(1 for x in announcements if x['cancelled'])
        year_count = len(epi_items) + len(announcements); parsed += year_count; by_year[fiscal_year] = year_count
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'sendai: parsed={parsed} upserted={upserted} cancelled={cancelled} legacyDeduped={deduped} total={summary["records"]} years={by_year}', flush=True)
    return {'records': parsed, 'upserted': upserted, 'cancelled': cancelled, 'legacyDeduped': deduped, 'years': len(by_year), 'startYear': min(by_year), 'endYear': max(by_year)}



if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    now = datetime.now()
    current_fiscal_year = now.year if now.month >= 4 else now.year - 1
    ap.add_argument('--years', default=str(current_fiscal_year))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--no-export', action='store_true')
    ap.add_argument('--probe', action='store_true')
    args = ap.parse_args()
    if args.probe:
        try:
            probe_epi()
        except Exception as exc:
            print(f'Sendai EPI probe failed: {type(exc).__name__}: {exc}', file=sys.stderr, flush=True)
            raise SystemExit(1)
        print('Sendai EPI probe ok', flush=True)
        raise SystemExit(0)
    years = parse_years(args.years)
    with SourceRun('sendai_procurement', '仙台市 入札・契約結果 / 本庁契約課発注情報') as run:
        run.set_metrics(**main(years, args.workers, not args.no_export))
