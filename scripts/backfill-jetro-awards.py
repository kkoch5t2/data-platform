#!/usr/bin/env python3
import argparse
import sqlite3
import sys
import threading
import time
import urllib.request
try:
    import requests
except ModuleNotFoundError:
    requests = None
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector import collect_jetro as jetro

_tls = threading.local()

def detail_client():
    if requests is not None:
        if not hasattr(_tls, 'session'):
            _tls.session = requests.Session()
            _tls.session.headers.update({'User-Agent':'Mozilla/5.0 PublicMarketData/0.3','Referer':jetro.BASE + jetro.LIST_PATH})
        return _tls.session
    if not hasattr(_tls, 'opener'):
        _tls.opener = urllib.request.build_opener()
    return _tls.opener

def fetch_one(row):
    source_id, title, source_url = row
    try:
        client = detail_client()
        if requests is not None:
            response = None
            for attempt in range(4):
                try:
                    response = client.get(source_url, timeout=20)
                    if response.status_code in (403, 429, 500, 502, 503, 504) and attempt < 3:
                        time.sleep(min(8, 2 ** (attempt + 1)))
                        continue
                    response.raise_for_status()
                    break
                except requests.RequestException:
                    if attempt == 3:
                        raise
                    time.sleep(min(8, 2 ** (attempt + 1)))
            response.encoding = 'utf-8'
            detail = jetro.parse_detail_html(response.text, title)
        else:
            detail = jetro.fetch_detail(client, source_url, title)
        if not detail or not detail.get('detail_text'):
            return source_id, None, 'empty detail'
        return source_id, detail, None
    except Exception as exc:
        return source_id, None, f'{type(exc).__name__}: {exc}'

def apply_detail(conn, source_id, detail):
    winner = detail.get('winner_name') or ''
    company_id = jetro.stable_id('co', winner) if winner else None
    if company_id:
        conn.execute(
            'INSERT OR IGNORE INTO companies VALUES (?,?,?)',
            (company_id, winner, jetro.norm(winner)),
        )
    conn.execute(
        '''UPDATE procurements SET detail_fetched=1, award_date=?, contract_method=?,
           award_method=?, winner_name=?, company_id=?, award_amount=?, estimated_amount=?,
           detail_text=? WHERE source_id=?''',
        (detail.get('award_date'), detail.get('contract_method'), detail.get('award_method'),
         winner or None, company_id, detail.get('award_amount'), detail.get('estimated_amount'),
         detail.get('detail_text'), source_id),
    )

def select_rows(conn, retry_missing_amounts=False, limit=0, it_only=False, since='', until=''):
    missing = 'detail_fetched=0'
    if retry_missing_amounts:
        missing = '(detail_fetched=0 OR award_amount IS NULL OR award_amount<=0)'
    filters = ["source_id LIKE 'jetro:%'", "notice_type LIKE '%落札者等の公示%'", missing]
    params = []
    if it_only:
        filters.append('is_it=1')
    if since:
        filters.append('notice_date>=?'); params.append(since)
    if until:
        filters.append('notice_date<=?'); params.append(until)
    rows = conn.execute(
        'SELECT source_id,title,source_url FROM procurements WHERE ' + ' AND '.join(filters) +
        ' ORDER BY notice_date DESC, source_id DESC', params
    ).fetchall()
    return rows[:limit] if limit and limit > 0 else rows

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--db', default=str(ROOT / 'data' / 'public_it.db'))
    parser.add_argument('--workers', type=int, default=4, help='conservative default to avoid JETRO rate limiting')
    parser.add_argument('--limit', type=int, default=0, help='0 means all missing details')
    parser.add_argument('--retry-missing-amounts', action='store_true')
    parser.add_argument('--it-only', action='store_true', help='backfill only rows classified as IT')
    parser.add_argument('--since', default='', help='minimum notice_date YYYY-MM-DD')
    parser.add_argument('--until', default='', help='maximum notice_date YYYY-MM-DD')
    parser.add_argument('--chunk-size', type=int, default=120)
    args = parser.parse_args()
    if not 1 <= args.workers <= 12:
        parser.error('--workers must be between 1 and 12')

    conn = sqlite3.connect(args.db)
    jetro.init_db(conn)
    rows = select_rows(conn, args.retry_missing_amounts, args.limit, args.it_only, args.since, args.until)
    total = len(rows)
    print(f'targets={total} workers={args.workers}', flush=True)
    if not rows:
        return
    started = time.time()
    done = amounts = errors = 0
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        for start in range(0, total, args.chunk_size):
            chunk = rows[start:start + args.chunk_size]
            futures = {executor.submit(fetch_one, row): row[0] for row in chunk}
            since_commit = 0
            for future in as_completed(futures):
                source_id = futures[future]
                try:
                    source_id, detail, error = future.result()
                except Exception as exc:
                    detail = None
                    error = f'{type(exc).__name__}: {exc}'
                done += 1
                if error:
                    errors += 1
                    print(f'detail_error {source_id}: {error}', flush=True)
                else:
                    apply_detail(conn, source_id, detail)
                    since_commit += 1
                    if detail.get('award_amount'):
                        amounts += 1
                if since_commit >= 30:
                    conn.commit()
                    since_commit = 0
                if done % 30 == 0 or done == total:
                    elapsed = max(time.time() - started, 0.001)
                    print(
                        f'progress={done}/{total} amounts={amounts} errors={errors} '
                        f'rate={done/elapsed:.2f}/s',
                        flush=True,
                    )
            conn.commit()
    conn.execute(
        'DELETE FROM companies WHERE company_id NOT IN '
        '(SELECT DISTINCT company_id FROM procurements WHERE company_id IS NOT NULL)'
    )
    conn.commit()
    elapsed = time.time() - started
    print(
        f'complete={done} amounts={amounts} errors={errors} elapsed={elapsed:.1f}s',
        flush=True,
    )

if __name__ == '__main__':
    main()
