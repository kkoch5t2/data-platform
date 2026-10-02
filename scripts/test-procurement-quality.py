#!/usr/bin/env python3
"""Regression checks for date semantics, source identity, and health timestamps."""
import contextlib
import io
import json
import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from collector import check_health
from collector.collect_fukuoka_procurement import parse_date
from collector.collect_jetro import canonical_company_name, extract_company_name, init_db, normalize_existing_company_names, stable_id
from collector.collect_sapporo_procurement import save


class ProcurementQualityTests(unittest.TestCase):
    def test_calendar_dates_and_company_prefix(self):
        self.assertEqual(parse_date('2026/2/29'), '')
        self.assertEqual(parse_date('2024/2/29'), '2024-02-29')
        self.assertEqual(extract_company_name('（株）青空システム'), '株式会社青空システム')

    def test_existing_winner_spelling_merges_without_changing_company_ids(self):
        db = sqlite3.connect(':memory:')
        init_db(db)
        names = ['株式会社ＮＴＴデータ', '株式会社NTTデータ', '株式会社One', '株式会社ONE', 'NTTドコモビジネス株式会社']
        for i, name in enumerate(names):
            canonical = canonical_company_name(name)
            company_id = stable_id('co', canonical)
            db.execute('INSERT OR IGNORE INTO companies VALUES (?,?,?)', (company_id, name, canonical))
            db.execute('''INSERT INTO procurements
                (source_id,xid,aid,title,source_url,winner_name,company_id,award_amount,collected_at)
                VALUES (?,?,?,?,?,?,?,?,?)''',
                (f'test:{i}', i, str(i), 'test', 'https://example.org', name, company_id, 100, '2026-10-03'))
        db.commit()
        self.assertEqual(normalize_existing_company_names(db), (1, 2))
        self.assertEqual(normalize_existing_company_names(db), (0, 0))
        rows = db.execute('SELECT winner_name,company_id FROM procurements ORDER BY source_id').fetchall()
        self.assertEqual(rows[0], rows[1])
        self.assertEqual(rows[2], rows[3])
        self.assertNotEqual(rows[1][1], rows[2][1])
        self.assertNotEqual(rows[3][1], rows[4][1])
        self.assertEqual(db.execute('SELECT COUNT(*) FROM companies').fetchone()[0], 3)
        db.close()

    def test_sapporo_publication_history(self):
        db = sqlite3.connect(':memory:')
        init_db(db)
        item = dict(year=2025, kind='k', title='同一工事', notice_date='2025-10-01',
                    award_date='2025-09-20', winner='株式会社青空', amount=10000,
                    url='https://example.org/contract', id_url='https://example.org/contract',
                    dept='土木部', reason='', method='一般競争')
        save(db, [item])
        save(db, [dict(item, notice_date='2025-10-10')])
        save(db, [dict(item, notice_date='2025-10-10')])
        rows = db.execute("SELECT source_id,notice_date FROM procurements WHERE source_id LIKE 'sapporo:%'").fetchall()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][1], '2025-10-01')
        self.assertEqual(db.execute('SELECT COUNT(*) FROM procurement_publications').fetchone()[0], 2)
        save(db, [dict(item, amount=20000, notice_date='2025-10-10')])
        self.assertEqual(db.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'sapporo:%'").fetchone()[0], 2)
        db.close()

    def test_health_rejects_future_and_missing_timestamps(self):
        key = next(iter(check_health.CATALOG))
        cfg = check_health.CATALOG[key]
        with tempfile.TemporaryDirectory() as tmp:
            status = Path(tmp) / 'sources.json'
            base = {'sources': {key: {'status': 'ok', 'metrics': {'records': cfg.get('minRecords', 1)}}}}
            with mock.patch.object(check_health, 'STATUS_PATH', status), mock.patch.object(sys, 'argv', ['check_health', '--source', key]):
                for finished in (None, (datetime.now(timezone.utc) + timedelta(days=1)).isoformat()):
                    base['sources'][key]['finishedAt'] = finished
                    status.write_text(json.dumps(base))
                    with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as err:
                        check_health.main()
                    self.assertEqual(err.exception.code, 1)


if __name__ == '__main__':
    unittest.main()
