#!/usr/bin/env python3
"""Run the actual daily shell in isolated fixtures with injected collection failures."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]

class RecoveryTests(unittest.TestCase):
    def test_failure_paths_restore_database_outputs_and_keep_evidence(self):
        for failure in ('collection','health','regression'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root=Path(directory)
                for folder in ['scripts','collector','src/data','public/data/company-details','data/automation']:
                    (root/folder).mkdir(parents=True)
                for name in ['daily-refresh.sh','procurement-refresh-state.py']:
                    shutil.copy2(ROOT/'scripts'/name,root/'scripts'/name)
                before={'src/data/sources.json':'{"sources":{}}', 'src/data/summary.json':'{"records":1}',
                        'src/data/procurements-2026.json':'[1]', 'src/data/companies.json':'[1]',
                        'public/data/dashboard-meta.json':'{"records":1}',
                        'public/data/company-details/00.json':'[1]'}
                for name,value in before.items():(root/name).write_text(value)
                unrelated=root/'public/data/wikipedia-topics.json'; unrelated.write_text('untouched')
                marker=root/'data/automation/last-success-date';marker.write_text('2026-10-03\n')
                with sqlite3.connect(root/'data/public_it.db') as db:
                    db.execute('create table procurements(id integer)');db.execute('insert into procurements values(1)')
                mutator='''from pathlib import Path
import sqlite3
root=Path.cwd()
(root/'src/data/sources.json').write_text('{"error":"injected failure"}')
(root/'src/data/summary.json').write_text('{"records":2}')
(root/'src/data/companies.json').write_text('[2]')
(root/'src/data/procurements-2099.json').write_text('[2]')
(root/'public/data/company-details/00.json').write_text('[2]')
with sqlite3.connect(root/'data/public_it.db') as db:db.execute('insert into procurements values(2)')
'''
                (root/'collector/collect_geps_awards.py').write_text(mutator+('raise SystemExit(1)\n' if failure=='collection' else ''))
                for source in ['jetro','jetro_local','yokohama_procurement','sapporo_procurement','kobe_procurement',
                               'fukuoka_procurement','chiba_procurement','kyoto_procurement','kawasaki_procurement','sendai_procurement']:
                    (root/f'collector/collect_{source}.py').write_text('')
                (root/'collector/check_health.py').write_text('raise SystemExit(1)' if failure=='health' else '')
                (root/'scripts/check-procurement-regression.py').write_text('raise SystemExit(1)')
                result=subprocess.run(['bash',str(root/'scripts/daily-refresh.sh')],cwd=root,text=True,capture_output=True,timeout=30)
                self.assertEqual(result.returncode,{'collection':1,'health':21,'regression':24}[failure],result.stdout+result.stderr)
                for name,value in before.items():self.assertEqual((root/name).read_text(),value,name)
                self.assertFalse((root/'src/data/procurements-2099.json').exists())
                self.assertEqual(unrelated.read_text(),'untouched')
                self.assertEqual(marker.read_text(),'2026-10-03\n')
                with sqlite3.connect(root/'data/public_it.db') as db:self.assertEqual(db.execute('select count(*) from procurements').fetchone()[0],1)
                evidence=list((root/'data/automation/logs').glob('procurement-failure-sources-*.json'))
                self.assertEqual(len(evidence),1)
                self.assertIn('injected failure',evidence[0].read_text())

    def test_shared_update_lock_skips_both_jobs(self):
        import fcntl
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir();(root/'data/automation').mkdir(parents=True)
            with (root/'data/automation/update.lock').open('w') as lock:
                fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
                for name in ['daily-refresh.sh','refresh-wikipedia-topics.sh']:
                    shutil.copy2(ROOT/'scripts'/name,root/'scripts'/name)
                    result=subprocess.run(['bash',str(root/'scripts'/name),'manual'],capture_output=True,text=True,timeout=5)
                    self.assertEqual(result.returncode,0,result.stderr)
                    self.assertFalse((root/'data/automation/last-success-date').exists())

    def test_yokohama_retries_timeout_then_succeeds_and_raises_after_limit(self):
        import sys
        sys.path.insert(0,str(ROOT))
        from collector import collect_yokohama_procurement as collector
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return b'ok'
        class Opener:
            def __init__(self,failures):self.failures=failures;self.calls=0
            def open(self,req,timeout):
                self.calls+=1
                if self.calls<=self.failures:raise TimeoutError('injected timeout')
                return Response()
        with patch.object(collector.time,'sleep'):
            opener=Opener(2)
            self.assertEqual(collector.post_result_page(opener,2026,3),'ok');self.assertEqual(opener.calls,3)
            opener=Opener(5)
            with self.assertRaises(TimeoutError):collector.post_result_page(opener,2026,3)
            self.assertEqual(opener.calls,5)

if __name__=='__main__':unittest.main(verbosity=2)
