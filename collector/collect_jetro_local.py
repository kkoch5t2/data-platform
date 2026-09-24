#!/usr/bin/env python3
import argparse, sqlite3, time

from collect_jetro import DB_PATH, export_json, init_db, seed_from_json
from backfill_available import fetch_local_page, make_local_opener, save_local_items
from core.source_run import SourceRun

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--pages', type=int, default=20)
    args = p.parse_args()

    with SourceRun('jetro_local', 'JETRO 地方政府公共調達データベース') as run:
        conn = sqlite3.connect(DB_PATH)
        init_db(conn)
        seed_from_json(conn)
        op, ref = make_local_opener()
        saved = 0
        for page in range(max(0, args.pages)):
            data = fetch_local_page(op, ref, page * 30)
            saved += save_local_items(conn, data.get('items', []))
            time.sleep(0.10)
        summary = export_json(conn)
        local_records = conn.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'jetro-local:%'").fetchone()[0]
        run.set_metrics(records=local_records, fetched=saved, totalRecords=summary['records'])
        print(f'local_fetched={saved} local_stored={local_records} stored={summary["records"]}')

if __name__ == '__main__':
    main()
