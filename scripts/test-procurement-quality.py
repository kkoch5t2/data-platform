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
from collector.collect_jetro import extract_company_name, init_db
from collector.collect_sapporo_procurement import save


class ProcurementQualityTests(unittest.TestCase):
    def test_calendar_dates_and_company_prefix(self):
        self.assertEqual(parse_date('2026/2/29'), '')
        self.assertEqual(parse_date('2024/2/29'), '2024-02-29')
        self.assertEqual(extract_company_name('（株）青空システム'), '株式会社青空システム')

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
