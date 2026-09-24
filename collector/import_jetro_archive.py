#!/usr/bin/env python3
import json, re, sqlite3
from datetime import datetime, timezone
from pathlib import Path

from collect_jetro import (
    DB_PATH, classify, clean, stable_id, norm, init_db, export_json,
    extract_numbered_fields, choose_detail_block, extract_company_name,
    clean_award_method, parse_reiwa_date, parse_yen
)

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / 'data' / 'jetro_2020_exa.jsonl'

def clean_agency(value):
    value = clean(value)
    return re.sub(r'（[^）]+）$', '', value).strip()

def parse_detail(body, title):
    block = choose_detail_block(extract_numbered_fields(body or ''), title)
    if not block:
        return {}
    winner = extract_company_name(block.get('⑥',''))
    return {
        'contract_method': clean(block.get('④','')),
        'award_date': parse_reiwa_date(block.get('⑤','')),
        'winner_name': winner,
        'award_amount': parse_yen(block.get('⑦','')),
        'award_method': clean_award_method(block.get('⑪','')),
        'estimated_amount': parse_yen(block.get('⑫','')),
        'detail_text': clean(' '.join(block.values()))[:8000],
    }
def upsert_record(conn, row):
    url = row.get('url','')
    m = re.search(r'/articles/(\d+)/(\d+)\.html', url)
    if not m:
        return False
    xid, aid = int(m.group(1)), m.group(2)
    title = clean(row.get('title',''))
    date = row.get('noticeDate','')
    agency = clean_agency(row.get('agency',''))
    notice_type = clean(row.get('noticeType','')) or '落札者等の公示'
    if not title or not re.fullmatch(r'2020-\d{2}-\d{2}', date):
        return False

    is_it, tags, category, category_tags = classify(title)
    org_id = stable_id('org', agency) if agency else None
    if org_id:
        conn.execute('INSERT OR IGNORE INTO organizations VALUES (?,?)', (org_id, agency))

    detail = parse_detail(row.get('body',''), title)
    winner = detail.get('winner_name') or ''
    company_id = stable_id('co', winner) if winner else None
    if company_id:
        conn.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)',
                     (company_id, winner, norm(winner)))
    conn.execute('''INSERT INTO procurements
      (source_id,xid,aid,title,notice_date,agency,organization_id,notice_type,source_url,is_it,
       category,category_tags_json,tags_json,detail_fetched,award_date,contract_method,award_method,
       winner_name,company_id,award_amount,estimated_amount,detail_text,collected_at)
      VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
      ON CONFLICT(source_id) DO UPDATE SET
       title=excluded.title,notice_date=excluded.notice_date,agency=excluded.agency,
       organization_id=excluded.organization_id,notice_type=excluded.notice_type,
       source_url=excluded.source_url,is_it=excluded.is_it,category=excluded.category,
       category_tags_json=excluded.category_tags_json,tags_json=excluded.tags_json,
       detail_fetched=excluded.detail_fetched,award_date=excluded.award_date,
       contract_method=excluded.contract_method,award_method=excluded.award_method,
       winner_name=excluded.winner_name,company_id=excluded.company_id,
       award_amount=excluded.award_amount,estimated_amount=excluded.estimated_amount,
       detail_text=excluded.detail_text,collected_at=excluded.collected_at''', (
        f'jetro:{xid}:{aid}', xid, aid, title, date, agency, org_id, notice_type, url, int(is_it),
        category, json.dumps(category_tags,ensure_ascii=False), json.dumps(tags,ensure_ascii=False),
        int(bool(detail)), detail.get('award_date'), detail.get('contract_method'),
        detail.get('award_method'), winner or None, company_id, detail.get('award_amount'),
        detail.get('estimated_amount'), detail.get('detail_text'),
        datetime.now(timezone.utc).isoformat()
    ))
    return True

def main():
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument('input', nargs='?', default=str(DEFAULT_INPUT))
    args = p.parse_args()
    path = Path(args.input)
    conn = sqlite3.connect(DB_PATH)
    init_db(conn)
    inserted = 0
    seen = set()
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get('url') in seen:
            continue
        seen.add(row.get('url'))
        if upsert_record(conn, row):
            inserted += 1
    conn.commit()
    summary = export_json(conn)
    print(f'archive_rows={inserted} stored={summary["records"]}')

if __name__ == '__main__':
    main()
