#!/usr/bin/env python3
import argparse, calendar, html, json, math, re, sqlite3, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify, classify_with_context, export_json, stable_id, norm, clean, canonical_company_name
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify, classify_with_context, export_json, stable_id, norm, clean, canonical_company_name

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/fukuoka-procurement'
RAW.mkdir(parents=True, exist_ok=True)
BASE = 'https://keiyaku.city.fukuoka.lg.jp/php/'
SEARCH_PAGE = BASE + 'fkks1010.php'
RESULT_PAGE = BASE + 'fkks1020.php'
HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
DIVISIONS = {'1': '工事', '2': '委託', '3': '物品', '4': '物品売払'}
PAGE_SIZE = 5000  # backend accepts larger batches than the 30-row UI selector


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


def fetch_post(params, retries=3):
    data = urllib.parse.urlencode(params).encode()
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(RESULT_PAGE, data=data, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read().decode('utf-8', 'replace')
        except Exception as e:
            last = e; time.sleep(0.6 * (attempt + 1))
    raise last


def params_for(year, division, page=0):
    params = {
        'txtThisPage': 'fkks1010.php' if page == 0 else 'fkks1020.php',
        'rdoDevision': division, 'cmbIndustry': '',
        'cmbBidFromYear': str(year), 'cmbBidFromMonth': '1', 'cmbBidFromDay': '1',
        'cmbBidToYear': str(year), 'cmbBidToMonth': '12', 'cmbBidToDay': '31',
        'txtSubject': '', 'cmbContract': '', 'txtTraderName': '',
        'cmbSortItem': '0', 'rdoSort': 'asc', 'cmbRecCount': str(PAGE_SIZE),
        'txtContract': '', 'txtPageIndex': str(page)
    }
    if page == 0:
        params['btnSearch'] = ' 検索実行 '
    return params


def text_only(value):
    return clean(re.sub(r'<[^>]+>', ' ', html.unescape(value or '')))


def parse_amount(value):
    s = re.sub(r'[^0-9.-]', '', str(value or '').replace(',', ''))
    if not s or s in {'-', '.', '-.'}:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None


def parse_date(value):
    m = re.search(r'((?:19|20)\d{2})/(\d{1,2})/(\d{1,2})', value or '')
    return f'{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}' if m else ''


def parse_total(raw):
    m = re.search(r'/\s*([\d,]+)件中', raw)
    return int(m.group(1).replace(',', '')) if m else 0


def parse_rows(raw, division):
    out = []
    for tr in re.findall(r'<tr[^>]*>([\s\S]*?)</tr>', raw, re.I):
        m = re.search(r"TranFormDetail\('([^']+)'\)", tr)
        if not m:
            continue
        cells = re.findall(r'<td[^>]*>([\s\S]*?)</td>', tr, re.I)
        if len(cells) < 8:
            continue
        out.append({
            'division': division, 'contract': m.group(1), 'title': text_only(cells[0]),
            'industry': text_only(cells[1]), 'winner': text_only(cells[2]),
            'estimated': parse_amount(text_only(cells[3])), 'amount': parse_amount(text_only(cells[4])),
            'notice_date': parse_date(text_only(cells[5])), 'award_date': parse_date(text_only(cells[6])),
            'method': text_only(cells[7]),
        })
    return out


def collect_division_year(year, division, workers):
    first = fetch_post(params_for(year, division, 0))
    total = parse_total(first); rows = parse_rows(first, division)
    (RAW / f'{year}-{division}-page0.html').write_text(first, encoding='utf-8')
    pages = math.ceil(total / PAGE_SIZE) if total else 0
    if pages > 1:
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = {ex.submit(fetch_post, params_for(year, division, p)): p for p in range(1, pages)}
            page_data = {}
            for fut in as_completed(futs):
                p = futs[fut]; page_data[p] = fut.result()
            for p in sorted(page_data):
                raw = page_data[p]
                expected = min(PAGE_SIZE, total - p * PAGE_SIZE)
                parsed = parse_rows(raw, division)
                for attempt in range(3):
                    if len(parsed) == expected:
                        break
                    time.sleep(0.8 * (attempt + 1))
                    raw = fetch_post(params_for(year, division, p)); parsed = parse_rows(raw, division)
                if len(parsed) != expected:
                    raise RuntimeError(f'Fukuoka {year} {DIVISIONS[division]} page {p} parsed {len(parsed)} != expected {expected}')
                rows.extend(parsed)
    uniq = {f"{x['division']}:{x['contract']}": x for x in rows}
    bad = [x for x in uniq.values() if not x.get('title') or not x.get('notice_date')]
    if bad:
        raise RuntimeError(f'Fukuoka {year} {DIVISIONS[division]} has {len(bad)} rows missing title/date')
    if total and len(uniq) != total:
        raise RuntimeError(f'Fukuoka {year} {DIVISIONS[division]} parsed {len(uniq)} != official total {total}')
    return list(uniq.values()), total


def usable_winner(value):
    s = clean(value)
    if not s or s in {'-', '－', '―', '不調', '中止', '取止め', '該当なし'}:
        return ''
    return canonical_company_name(s)


def save(conn, items):
    now = datetime.now(timezone.utc).isoformat(); org = '福岡市'; org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org)); upserted = 0
    for x in items:
        if not x['title'] or not x['notice_date']:
            continue
        winner = usable_winner(x['winner']); company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        sid = f"fukuoka:{x['division']}:{x['contract']}"
        notice_type = f"福岡市入札結果（{DIVISIONS[x['division']]}）"
        detail = clean(f"福岡市財政局契約課 / {DIVISIONS[x['division']]} / {x['industry']}")[:1000]
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
          estimated_amount=excluded.estimated_amount,detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
            sid, int(x['contract']) if x['contract'].isdigit() else None, x['contract'], x['title'], x['notice_date'], org, org_id,
            notice_type, SEARCH_PAGE, int(is_it), category,
            json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 1, x['award_date'] or None,
            x['method'] or None, x['method'] or None, winner or None, company_id, x['amount'], x['estimated'], detail, now))
        upserted += 1
    conn.commit(); return upserted


def main(years, workers=6, do_export=True):
    conn = sqlite3.connect(DB_PATH); init_db(conn)
    parsed = upserted = 0; by_year = {}
    for year in years:
        ycount = 0
        for division in DIVISIONS:
            rows, official_total = collect_division_year(year, division, workers)
            n = save(conn, rows); parsed += len(rows); upserted += n; ycount += len(rows)
            print(f'fukuoka {year} {DIVISIONS[division]}: {len(rows)} / official {official_total}', flush=True)
        by_year[year] = ycount
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'fukuoka: parsed={parsed} upserted={upserted} total={summary["records"]} years={by_year}', flush=True)
    return {'records': parsed, 'upserted': upserted, 'years': len(by_year), 'startYear': min(by_year), 'endYear': max(by_year)}


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=str(datetime.now().year))
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args(); years = parse_years(args.years)
    with SourceRun('fukuoka_procurement', '福岡市 財政局契約課 入札結果') as run:
        run.set_metrics(**main(years, max(1, min(args.workers, 10)), not args.no_export))
