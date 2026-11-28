#!/usr/bin/env python3
import argparse, hashlib, html, io, json, re, sqlite3, unicodedata, urllib.parse, urllib.request, zipfile
import xml.etree.ElementTree as ET
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
try:
    from core.source_run import SourceRun
    from collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name, sapporo_contract_key
except ModuleNotFoundError:
    from collector.core.source_run import SourceRun
    from collector.collect_jetro import DB_PATH, init_db, classify, export_json, stable_id, norm, clean, canonical_company_name, sapporo_contract_key

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / 'data/raw/sapporo-procurement'
RAW.mkdir(parents=True, exist_ok=True)
PAGE = 'https://www.city.sapporo.jp/zaisei/keiyaku-kanri/anken/kekka.html'
HEADERS = {'User-Agent': 'Mozilla/5.0 DATLUME/1.0'}
M = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
NS = '{' + M + '}'

def fetch(url):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=90) as r:
        return r.read()

def fiscal_year_now():
    now = datetime.now()
    return now.year if now.month >= 4 else now.year - 1

def parse_years(spec):
    years = []
    for part in spec.split(','):
        part = part.strip()
        if not part:
            continue
        if '-' in part:
            a, b = map(int, part.split('-', 1))
            years.extend(range(a, b + 1))
        else:
            years.append(int(part))
    return sorted(set(years))

def discover_files():
    raw = fetch(PAGE)
    text = raw.decode('utf-8', 'replace')
    (RAW / 'results.html').write_bytes(raw)
    out = []
    for href in re.findall(r'href=["\']([^"\']+\.(?:xlsx|pdf))["\']', text, re.I):
        name = Path(urllib.parse.urlparse(href).path).name.lower()
        m = re.fullmatch(r'([kz])_kekkaichiran_ruikei(\d+)\.(xlsx|pdf)', name)
        if not m:
            continue
        era = int(m.group(2))
        year = 2018 + era
        out.append((m.group(1), year, urllib.parse.urljoin(PAGE, html.unescape(href))))
    selected = {}
    for kind, year, url in out:
        key = (kind, year)
        if key not in selected or url.lower().endswith('.xlsx'):
            selected[key] = url
    return [(kind, year, selected[kind, year]) for kind, year in sorted(selected)]

def col_letters(ref):
    m = re.match(r'[A-Z]+', ref)
    return m.group() if m else ''

def sheet_rows(blob):
    z = zipfile.ZipFile(io.BytesIO(blob))
    ns = {'m': M, 'r': R}
    shared = []
    if 'xl/sharedStrings.xml' in z.namelist():
        root = ET.fromstring(z.read('xl/sharedStrings.xml'))
        shared = [''.join(t.text or '' for t in si.iter(NS + 't')) for si in root.findall('m:si', ns)]
    wb = ET.fromstring(z.read('xl/workbook.xml'))
    rels = ET.fromstring(z.read('xl/_rels/workbook.xml.rels'))
    relmap = {x.attrib['Id']: x.attrib['Target'] for x in rels}
    sheet = next(iter(wb.find('m:sheets', ns)))
    root = ET.fromstring(z.read('xl/' + relmap[sheet.attrib['{' + R + '}id']]))
    rows = []
    for rr in root.findall('.//m:sheetData/m:row', ns):
        vals = {}
        for c in rr.findall('m:c', ns):
            v = c.find('m:v', ns)
            val = '' if v is None else (v.text or '')
            if c.attrib.get('t') == 's' and val != '':
                val = shared[int(val)]
            elif c.attrib.get('t') == 'inlineStr':
                ins = c.find('m:is', ns)
                val = ''.join(t.text or '' for t in ins.iter(NS + 't')) if ins is not None else ''
            vals[col_letters(c.attrib.get('r', ''))] = clean(val)
        rows.append(vals)
    return rows

def jp_date(value):
    s = clean(value)
    if re.fullmatch(r'\d+(?:\.\d+)?', s):
        serial = float(s)
        if 30000 <= serial <= 80000:
            return (datetime(1899, 12, 30) + timedelta(days=serial)).date().isoformat()
    m = re.fullmatch(r'([RrHh])(\d+)\.(\d+)\.(\d+)', s)
    if m:
        base = 2018 if m.group(1).upper() == 'R' else 1988
        parts = (base + int(m.group(2)), int(m.group(3)), int(m.group(4)))
    else:
        m = re.fullmatch(r'(20\d{2})[./-](\d{1,2})[./-](\d{1,2})', s)
        if not m:
            return ''
        parts = tuple(map(int, m.groups()))
    try:
        return date(*parts).isoformat()
    except ValueError:
        return ''

def parse_amount(value):
    s = re.sub(r'[^0-9.-]', '', str(value or ''))
    if not s:
        return None
    try:
        return int(round(float(s)))
    except ValueError:
        return None

def clean_source_url(value, fallback):
    raw = clean(value).replace('ｈ', 'h').replace('ｔ', 't').replace('ｐ', 'p').replace('ｓ', 's')
    m = re.search(r'https?://[^\s　]+', raw, re.I)
    if not m:
        return fallback
    return m.group(0).rstrip('。．、,)）]】')

def parse_items(blob, kind, year, source_file):
    rows = sheet_rows(blob)
    items = []
    for row in rows[1:]:
        title = clean(row.get('C', ''))
        if not title:
            continue
        if kind == 'k':
            method, award_date, dept, reason = clean(row.get('F', '')), jp_date(row.get('H', '')), clean(row.get('L', '')), ''
        else:
            method, award_date, dept, reason = '随意契約', jp_date(row.get('F', '')), clean(row.get('K', '')), clean(row.get('J', ''))
        raw_url = clean(row.get('A', ''))
        items.append({'year': year, 'kind': kind, 'title': title, 'winner': clean(row.get('D', '')),
            'amount': parse_amount(row.get('E')), 'notice_date': jp_date(row.get('B', '')), 'award_date': award_date,
            'method': method, 'dept': dept, 'reason': reason, 'url': clean_source_url(raw_url, source_file),
            'id_url': raw_url or source_file})
    return items

def pdf_text(value):
    return clean((value or '').replace('\n', ''))


def normalized(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', str(value or '')))


def identity(kind, title, winner, amount, award, method):
    return (kind, normalized(title), normalized(canonical_company_name(winner or '')),
            amount, award, normalized(method))


def parse_pdf_items(blob, kind, year, source_file):
    import pdfplumber
    items = []
    expected = (['掲載日', '契約の名称', '契約の相手方', '契約金額（円）',
                 '契約方法', '被指名者数', '契約締結年月日', '履行期間', '担当課']
                if kind == 'k' else
                ['掲載日', '調達契約件名', '契約の相手方', '契約金額（円）',
                 '契約締結年月日', '履行期間',
                 '随意契約によることとした理由(契約の相手方を特定した理由を含む。)', '担当課'])
    with pdfplumber.open(io.BytesIO(blob)) as pdf:
        for page in pdf.pages:
            tables = page.extract_tables()
            if len(tables) != 1 or list(map(normalized,tables[0][0])) != list(map(normalized,expected)):
                raise ValueError(f'Sapporo {kind}: unexpected PDF table on page {page.page_number}')
            rows = []
            for row in tables[0][1:]:
                if len(row) != len(expected):
                    raise ValueError(f'Sapporo {kind}: unexpected row width on page {page.page_number}')
                if jp_date(row[0] or ''):
                    rows.append(row)
                elif row[0] is None and rows:
                    for i, value in enumerate(row):
                        if value:
                            rows[-1][i] = (rows[-1][i] or '') + '\n' + value
                else:
                    raise ValueError(f'Sapporo {kind}: unrecognized row on page {page.page_number}')
            for row in rows:
                title, winner = pdf_text(row[1]), pdf_text(row[2])
                amount_text = pdf_text(row[3])
                award = jp_date(pdf_text(row[6] if kind == 'k' else row[4]))
                notice = jp_date(pdf_text(row[0]))
                method = pdf_text(row[4]) if kind == 'k' else '随意契約'
                if not (title and winner and award and notice and method and re.fullmatch(r'[0-9,]+', amount_text)):
                    raise ValueError(f'Sapporo {kind}: incomplete contract on page {page.page_number}')
                items.append({'year': year, 'kind': kind, 'title': title, 'winner': winner,
                    'amount': parse_amount(amount_text), 'notice_date': notice, 'award_date': award,
                    'method': method, 'dept': clean(row[-1] or ''),
                    'reason': '' if kind == 'k' else pdf_text(row[-2]),
                    'url': source_file, 'id_url': source_file})
    if not items:
        raise ValueError(f'Sapporo {kind}: no contracts extracted')
    return items


def save_pdf_items(conn, items):
    # Compare stable material contract facts across the XLSX/PDF migration.
    grouped = {}
    for item in items:
        key = (item['year'], *identity(item['kind'], item['title'], item['winner'],
               item['amount'], item['award_date'], item['method']))
        previous = grouped.setdefault(key, [])
        if previous and normalized(previous[0]['dept'] + previous[0]['reason']) != normalized(item['dept'] + item['reason']):
            raise ValueError('Sapporo PDF: ambiguous repeated contract')
        previous.append(item)
    prior = {}
    for year in sorted({x['year'] for x in items}):
        for sid, typ, title, winner, amount, award, method in conn.execute(
            'SELECT source_id,notice_type,title,winner_name,award_amount,award_date,contract_method FROM procurements WHERE source_id LIKE ?',
            (f'sapporo:{year}:%',)):
            key = (year, *identity('z' if '随意' in typ else 'k', title, winner, amount, award, method))
            prior.setdefault(key, []).append(sid)
    matches, fresh = [], []
    for key, group in grouped.items():
        found = prior.get(key, [])
        if len(found) > 1:
            raise ValueError('Sapporo PDF: ambiguous prior contract')
        if found:
            matches.append((found[0], key, group))
        else:
            fresh.append(min(group, key=lambda x: x['notice_date']))
    if fresh:
        save(conn, fresh)
    now = datetime.now(timezone.utc).isoformat()
    for sid, key, group in matches:
        for item in group:
            notice = item['notice_date']
            raw = 'sapporo-pdf:' + hashlib.sha256(json.dumps([key, notice], ensure_ascii=False).encode()).hexdigest()[:24]
            conn.execute('INSERT OR IGNORE INTO procurement_publications VALUES (?,?,?,?)', (sid, notice, raw, now))
            conn.execute('UPDATE procurements SET notice_date=CASE WHEN notice_date<? THEN notice_date ELSE ? END, collected_at=? WHERE source_id=?', (notice, notice, now, sid))
    conn.commit()
    print(f'Sapporo PDF: rows={len(items)} unique={len(grouped)} existing={len(matches)} new={len(fresh)}')
    return len(fresh) + len(matches)


def save(conn, items):
    now = datetime.now(timezone.utc).isoformat()
    org = '札幌市'
    org_id = stable_id('org', org)
    conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, org))
    added = 0
    for x in items:
        winner = canonical_company_name(x['winner'])
        company_id = stable_id('co', winner) if winner else None
        if company_id:
            conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, winner, norm(winner)))
        digest = hashlib.sha1('|'.join([
            str(x['year']), x['kind'], x['title'], x['notice_date'], x['award_date'],
            winner, str(x['amount'] or ''), x.get('id_url') or x['url']
        ]).encode()).hexdigest()[:20]
        raw_sid = f"sapporo:{x['year']}:{digest}"
        is_it, tags, category, category_tags = classify(x['title'])
        detail = clean(' / '.join(v for v in [x['dept'], x['reason']] if v))[:1000]
        notice_type = '札幌市競争入札結果' if x['kind'] == 'k' else '札幌市随意契約結果'
        contract_key=sapporo_contract_key(x['year'],notice_type,x['title'],x['award_date'],
          winner,x['amount'],x['url'],detail,x['method'])
        prior=conn.execute('SELECT source_id FROM procurements WHERE contract_key=?',(contract_key,)).fetchone()
        sid=prior[0] if prior else raw_sid
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,
           detail_fetched,award_date,contract_method,award_method,winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=CASE WHEN procurements.notice_date<excluded.notice_date THEN procurements.notice_date ELSE excluded.notice_date END,source_url=excluded.source_url,
          is_it=excluded.is_it,category=excluded.category,category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,
          award_date=excluded.award_date,contract_method=excluded.contract_method,award_method=excluded.award_method,
          winner_name=excluded.winner_name,company_id=excluded.company_id,award_amount=excluded.award_amount,
          detail_text=excluded.detail_text,collected_at=excluded.collected_at''',
          (sid, x['year'], digest, x['title'], x['notice_date'], org, org_id, notice_type, x['url'], int(is_it), category,
           json.dumps(category_tags, ensure_ascii=False), json.dumps(tags, ensure_ascii=False), 1, x['award_date'], x['method'],
           x['method'], winner or None, company_id, x['amount'], None, detail, now))
        conn.execute('''UPDATE procurements SET contract_key=?,
          notice_date=CASE WHEN notice_date<? THEN notice_date ELSE ? END
          WHERE source_id=?''',(contract_key,x['notice_date'],x['notice_date'],sid))
        conn.execute('INSERT OR IGNORE INTO procurement_publications VALUES (?,?,?,?)',
          (sid,x['notice_date'] or '',raw_sid,now))
        added += 1
    conn.commit()
    return added

def main(years, do_export=True):
    files = [x for x in discover_files() if x[1] in years]
    expected = {(kind, year) for year in years for kind in ('k', 'z')}
    if {(kind, year) for kind, year, _ in files} != expected:
        raise RuntimeError(f'incomplete Sapporo annual Excel/PDF files for {years}')
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    items, pdf_items = [], []
    by_year = {}
    for kind, year, url in files:
        blob = fetch(url)
        name = Path(urllib.parse.urlparse(url).path).name
        (RAW / name).write_bytes(blob)
        if name.lower().endswith('.pdf'):
            parsed = parse_pdf_items(blob, kind, year, url)
            pdf_items.extend(parsed)
        else:
            parsed = parse_items(blob, kind, year, url)
            items.extend(parsed)
        by_year[year] = by_year.get(year, 0) + len(parsed)
        print(f'sapporo {year} {kind}: {len(parsed)}')
    added = save(conn, items) if items else 0
    if pdf_items:
        added += save_pdf_items(conn, pdf_items)
    summary = export_json(conn) if do_export else {'records': conn.execute('SELECT COUNT(*) FROM procurements').fetchone()[0]}
    conn.close()
    print(f'sapporo: parsed={len(items) + len(pdf_items)} upserted={added} total={summary["records"]} years={by_year}')
    return {'records': len(items) + len(pdf_items), 'upserted': added, 'years': len(by_year), 'startYear': min(by_year), 'endYear': max(by_year)}

if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--years', default=str(fiscal_year_now()))
    ap.add_argument('--no-export', action='store_true')
    args = ap.parse_args()
    years = parse_years(args.years)
    with SourceRun('sapporo_procurement', '札幌市 入札等結果一覧') as run:
        run.set_metrics(**main(years, not args.no_export))
