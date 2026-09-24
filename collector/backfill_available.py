#!/usr/bin/env python3
import http.cookiejar, json, math, sqlite3, time
import urllib.parse, urllib.request
from datetime import datetime, timezone

from collect_jetro import (
    BASE, DB_PATH, classify, clean, export_json, fetch_page,
    init_db, make_opener, open_with_retry, parse_date,
    reclassify_existing, save_items, seed_from_json, stable_id,
)

LOCAL_LIST_PATH = '/gov_procurement/local/list.html'
LOCAL_API_PATH = '/view_interface.php?blockId=33686978'

def make_local_opener():
    referer = BASE + LOCAL_LIST_PATH
    jar = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
    req = urllib.request.Request(referer, headers={'User-Agent':'Mozilla/5.0 PublicMarketData/0.3'})
    with open_with_retry(op, req, timeout=30) as res:
        res.read()
    return op, referer
def fetch_local_page(op, referer, offset=0):
    q = {'current': offset}
    url = BASE + LOCAL_API_PATH + '&' + urllib.parse.urlencode(q)
    headers = {
        'User-Agent':'Mozilla/5.0 PublicMarketData/0.3',
        'Referer':referer,
        'Accept':'application/json, text/javascript, */*; q=0.01',
        'X-Requested-With':'XMLHttpRequest',
    }
    with open_with_retry(op, urllib.request.Request(url, headers=headers), timeout=30) as res:
        return json.loads(res.read().decode('utf-8'))

def save_local_items(conn, items):
    now = datetime.now(timezone.utc).isoformat()
    saved = 0
    for item in items:
        title = clean(item.get('title',''))
        is_it, tags, category, category_tags = classify(title)
        xid, aid = int(item.get('xid') or 0), str(item['aid'])
        agency = clean(item.get('agency',''))
        org_id = stable_id('org',agency) if agency else None
        if org_id:
            conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)',(org_id,agency))
        conn.execute('''INSERT INTO procurements
          (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,category,category_tags_json,tags_json,collected_at)
          VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
          ON CONFLICT(source_id) DO UPDATE SET title=excluded.title,notice_date=excluded.notice_date,
            agency=excluded.agency,organization_id=excluded.organization_id,notice_type=excluded.notice_type,
            source_url=excluded.source_url,is_it=excluded.is_it,category=excluded.category,
            category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,collected_at=excluded.collected_at''',(
          f'jetro-local:{xid}:{aid}',xid,aid,title,parse_date(item.get('date','')),agency,org_id,
          '地方政府調達',f'{BASE}/gov_procurement/local/articles/{aid}.html',int(is_it),category,
          json.dumps(category_tags,ensure_ascii=False),json.dumps(tags,ensure_ascii=False),now))
        saved += 1
    conn.commit()
    return saved

def crawl_national(conn):
    op, ref = make_opener({})
    first = fetch_page(op, ref, 0, {})
    total = int(first.get('pagination',{}).get('total') or 0)
    pages = math.ceil(total / 30)
    saved = 0
    print(f'national total={total} pages={pages}', flush=True)
    for page in range(pages):
        data = first if page == 0 else fetch_page(op, ref, page * 30, {})
        saved += save_items(conn, data.get('items',[]))
        if page % 100 == 0 or page == pages - 1:
            print(f'national page={page+1}/{pages} saved_calls={saved}', flush=True)
        time.sleep(0.10)
    return total

def crawl_local(conn):
    op, ref = make_local_opener()
    first = fetch_local_page(op, ref, 0)
    total = int(first.get('pagination',{}).get('total') or 0)
    pages = math.ceil(total / 30)
    saved = 0
    print(f'local total={total} pages={pages}', flush=True)
    for page in range(pages):
        data = first if page == 0 else fetch_local_page(op, ref, page * 30)
        saved += save_local_items(conn, data.get('items',[]))
        if page % 100 == 0 or page == pages - 1:
            print(f'local page={page+1}/{pages} saved_calls={saved}', flush=True)
        time.sleep(0.10)
    return total
def main():
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    seed_from_json(conn)
    reclassify_existing(conn)
    national_total = crawl_national(conn)
    local_total = crawl_local(conn)
    summary = export_json(conn)
    years = conn.execute(
        "select substr(notice_date,1,4),count(*) from procurements group by 1 order by 1"
    ).fetchall()
    scopes = conn.execute(
        "select case when source_id like 'jetro-local:%' then 'local' else 'national' end,count(*) "
        "from procurements group by 1 order by 1"
    ).fetchall()
    print('DONE', summary, flush=True)
    print('YEARS', years, flush=True)
    print('SCOPES', scopes, flush=True)
    print('SOURCE_TOTALS', national_total, local_total, flush=True)

if __name__ == '__main__':
    main()
