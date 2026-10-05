#!/usr/bin/env python3
"""SQLite restoration and collector regression tests. Full job recovery: test-scheduled-refresh.py."""
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
    def test_sqlite_backup_captures_wal_and_restore_discards_hot_journal(self):
        spec=importlib.util.spec_from_file_location('refresh_state',ROOT/'scripts/procurement-refresh-state.py')
        state=importlib.util.module_from_spec(spec);spec.loader.exec_module(state)
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'data').mkdir()
            target=root/'data/public_it.db';backup=root/'data/backup.db'
            with sqlite3.connect(target) as db:
                db.execute('PRAGMA journal_mode=WAL')
                db.execute('create table procurements(id integer, value text)')
                db.execute("insert into procurements values(1,'committed')")
                db.commit()
                state.backup_database(root,backup)
            db.close()
            with sqlite3.connect(target) as db:db.execute('PRAGMA journal_mode=DELETE')
            db.close()
            code="import sqlite3,os;db=sqlite3.connect("+repr(str(target))+ ");db.execute('BEGIN IMMEDIATE');db.execute(\"update procurements set value='uncommitted'\");os._exit(1)"
            subprocess.run(['python3','-c',code],check=False)
            self.assertTrue(Path(str(target)+'-journal').exists())
            state.restore_database(root,backup)
            self.assertFalse(Path(str(target)+'-journal').exists())
            with sqlite3.connect(target) as db:
                self.assertEqual(db.execute('select value from procurements').fetchone()[0],'committed')
                self.assertEqual(db.execute('pragma integrity_check').fetchall(),[('ok',)])

    def test_existing_seed_skips_classification_but_preserves_agency_repair(self):
        import sys
        sys.path.insert(0,str(ROOT))
        from collector import collect_jetro as collector
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as db:
            data=Path(directory)
            collector.init_db(db)
            rows=[{'id':'jetro:1:example','title':'existing title','agency':'original agency',
                   'winnerName':'example company','category':'original category'}]
            file=data/'procurements-2026.json';file.write_text(json.dumps(rows))
            with patch.object(collector,'DATA_DIR',data), patch.object(collector,'JSON_PATH',data/'missing.json'):
                collector.seed_from_json(db)
                original=db.execute('SELECT title,category,collected_at FROM procurements').fetchone()
                rows[0].update(agency='repaired agency',title='must preserve existing title')
                file.write_text(json.dumps(rows))
                with patch.object(collector,'classify',side_effect=AssertionError('existing row reclassified')):
                    self.assertEqual(collector.seed_from_json(db),1)
                self.assertEqual(db.execute('SELECT title,category,collected_at FROM procurements').fetchone(),original)
                self.assertEqual(db.execute('SELECT agency FROM procurements').fetchone()[0],'repaired agency')
                rows[0]['agency']='';file.write_text(json.dumps(rows))
                collector.seed_from_json(db)
                self.assertEqual(db.execute('SELECT agency FROM procurements').fetchone()[0],'repaired agency')
                rows.append({'id':'jetro:2:new','title':'new title','agency':'new agency'})
                file.write_text(json.dumps(rows))
                with patch.object(collector,'classify',return_value=(False,[],'new category',[])) as classify:
                    self.assertEqual(collector.seed_from_json(db),2)
                    classify.assert_called_once_with('new title')
                self.assertEqual(db.execute("SELECT category FROM procurements WHERE source_id='jetro:2:new'").fetchone()[0],'new category')

    def test_geps_snapshot_corrections_are_not_resurrected_by_jetro_seed(self):
        import sys
        sys.path.insert(0,str(ROOT))
        from collector import collect_jetro as jetro
        sys.path.insert(0,str(ROOT / "collector"))
        import collect_geps_awards as geps
        old=['0000000000000532757','作業衣購入','2025-07-31','2370300','J5','8002010','旧社名株式会社','1111111111111']
        corrected=old.copy();corrected[6]='訂正社名株式会社'
        withdrawn=old.copy();withdrawn[0]='0000000000000532758'
        joint=corrected.copy();joint[6]='別受注者株式会社';joint[7]='2222222222222'
        prior=old.copy();prior[0]='0000000000000432757';prior[2]='2024-07-31'
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as db:
            data=Path(directory);jetro.init_db(db)
            old_id=geps.upsert(db,old);withdrawn_id=geps.upsert(db,withdrawn);prior_id=geps.upsert(db,prior)
            data.joinpath('procurements-2025.json').write_text(json.dumps([
                {'id':old_id,'title':old[1],'agency':'警察庁','awardDate':old[2],'winnerName':old[6]},
                {'id':withdrawn_id,'title':withdrawn[1],'awardDate':withdrawn[2]},
                {'id':'jetro:2:new','title':'新規公示','agency':'警察庁'},
            ]))
            with patch.object(geps,'download_zip',return_value=(data/'official.zip',[corrected,joint])):
                count,removed,_,_=geps.import_year(db,2025)
            self.assertEqual((count,removed),(2,2))
            expected={prior_id,'geps:'+corrected[0]+':'+geps.stable_record_id(corrected),
                      'geps:'+joint[0]+':'+geps.stable_record_id(joint)}
            with patch.object(jetro,'DATA_DIR',data),patch.object(jetro,'JSON_PATH',data/'missing.json'):
                jetro.seed_from_json(db)
                jetro.seed_from_json(db)
            actual={r[0] for r in db.execute("SELECT source_id FROM procurements WHERE source_id LIKE 'geps:%'")}
            self.assertEqual(actual,expected)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM procurements WHERE source_id='jetro:2:new'").fetchone()[0],1)
            self.assertEqual(db.execute('PRAGMA integrity_check').fetchall(),[('ok',)])

    def test_geps_json_bootstrap_remains_available_without_geps_records(self):
        import sys
        sys.path.insert(0,str(ROOT))
        from collector import collect_jetro as jetro
        with tempfile.TemporaryDirectory() as directory, sqlite3.connect(':memory:') as db:
            data=Path(directory);jetro.init_db(db)
            rows=[{'id':'geps:1:first','title':'公式落札','awardDate':'2025-07-31'},
                  {'id':'geps:2:second','title':'別の公式落札','awardDate':'2025-08-01'}]
            data.joinpath('procurements-2025.json').write_text(json.dumps(rows))
            with patch.object(jetro,'DATA_DIR',data),patch.object(jetro,'JSON_PATH',data/'missing.json'):
                self.assertEqual(jetro.seed_from_json(db),2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM procurements WHERE source_id LIKE 'geps:%'").fetchone()[0],2)

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
