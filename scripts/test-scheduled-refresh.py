#!/usr/bin/env python3
"""Exercise isolated jobs against real Git remotes, SQLite and concurrent publications."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
spec = importlib.util.spec_from_file_location('refresh', ROOT / 'scripts/scheduled-refresh.py')
refresh = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh)


def git(root, *args):
    return subprocess.run(['git', *args], cwd=root, capture_output=True, text=True, check=True).stdout.strip()


class Fixture:
    def __init__(self, directory):
        self.root = Path(directory) / 'primary'
        self.root.mkdir()
        self.remote = Path(directory) / 'remote.git'
        subprocess.run(['git', 'init', '--bare', '-q', str(self.remote)], check=True)
        git(self.root, 'init', '-q', '-b', 'main')
        git(self.root, 'config', 'user.email', 'test@example.invalid')
        git(self.root, 'config', 'user.name', 'Refresh fixture')
        git(self.root, 'remote', 'add', 'origin', str(self.remote))
        (self.root / 'scripts').mkdir()
        for name in ('scheduled-refresh.py', 'scheduled-refresh-git.py', 'procurement-refresh-state.py', 'collect-daily.sh', 'listed-master-refresh-needed.py', 'log-upstream-failure.py'):
            shutil.copy2(ROOT / 'scripts' / name, self.root / 'scripts' / name)
        (self.root / '.gitignore').write_text('/data\n/node_modules\n/tmp/\n/src/data/summary.json\n__pycache__/\n*.pyc\n')
        for folder in ('src/data', 'public/data/listed-companies', 'data/automation', 'node_modules',
                       'data/raw/listed-companies/normalized'):
            (self.root / folder).mkdir(parents=True, exist_ok=True)
        self.sources = {'schemaVersion': 1, 'sources': {'geps': {'date': 'old'}, 'wikipedia_topics': {'date': 'old'}}}
        (self.root / 'src/data/sources.json').write_text(json.dumps(self.sources))
        (self.root / 'src/data/summary.json').write_text('{"records":1,"lastDate":"old"}')
        (self.root / 'public/data/listed-companies/summary.json').write_text('{"companies":1}')
        (self.root / 'public/data/wikipedia-topics.json').write_text('{"latestDate":"old"}')
        (self.root / 'data/automation/last-success-date').write_text('2026-09-01\n')
        (self.root / 'data/automation/last-monthly-refresh').write_text('2026-09\n')
        (self.root / 'data/raw/listed-companies/normalized/financials.json').write_text('old-normalized')
        (self.root / 'data/raw/listed-companies/documents-index.json').write_text('old-index')
        with sqlite3.connect(self.root / 'data/public_it.db') as db:
            db.execute('create table procurements(id integer)')
            db.execute('insert into procurements values(1)')
        git(self.root, 'add', '.')
        git(self.root, 'commit', '-qm', 'fixture')
        git(self.root, 'push', '-qu', 'origin', 'main')

    def count(self):
        with sqlite3.connect(self.root / 'data/public_it.db') as db:
            return db.execute('select count(*) from procurements').fetchone()[0]

    def assert_clean(self, test):
        test.assertEqual(git(self.root, 'status', '--porcelain'), '')
        test.assertEqual(git(self.root, 'rev-parse', 'HEAD'), git(self.root, 'rev-parse', 'origin/main'))


class SmallRefresh(refresh.Refresh):
    failure = None
    def collect(self):
        self.phase = 'collection'
        sources = json.loads((self.workspace / 'src/data/sources.json').read_text())
        source = 'wikipedia_topics' if self.job == 'topics' else 'geps'
        sources['sources'][source] = {'date': 'new-' + self.job}
        (self.workspace / 'src/data/sources.json').write_text(json.dumps(sources))
        if self.job == 'topics':
            (self.workspace / 'public/data/wikipedia-topics.json').write_text('{"latestDate":"new-topics"}')
        else:
            with sqlite3.connect(self.root / 'data/public_it.db') as db:
                db.execute('insert into procurements values(2)')
            raw = self.root / 'data/raw/listed-companies'
            (raw / 'normalized/financials.json').write_text('new-normalized')
            (raw / 'normalized/new.json').write_text('new')
            (raw / 'documents-index.json').write_text('new-index')
            (self.workspace / 'src/data/summary.json').write_text('{"records":2,"lastDate":"new-daily"}')
            (self.workspace / 'public/data/listed-companies/summary.json').write_text('{"companies":2}')
            (self.markers / 'last-monthly-refresh').write_text('new-month\n')
        if self.failure == 'collection':
            raise RuntimeError('injected collector failure')

    def checks(self):
        if self.failure in ('release-check', 'local-e2e'):
            self.phase = self.failure
            raise RuntimeError('injected pre-push failure')

    def deploy(self):
        if self.failure == 'deploy':
            raise RuntimeError('injected deploy failure')

    def browser_checks(self, base):
        if self.failure == 'production-e2e':
            raise RuntimeError('injected production failure')


class Tests(unittest.TestCase):
    def test_scheduled_host_rename_requires_matching_permission(self):
        class GuardPassed(Exception):
            pass

        class Clock(datetime):
            @classmethod
            def now(cls, tz=None):
                return datetime(2026, 10, 16, 12, tzinfo=tz)

        cases = [('kota-Intel', 'kota-Intel', True), ('bmax', 'bmax', True),
                 ('bmax', 'kota-Intel', False), ('kota-Intel', 'bmax', False),
                 ('chuwi', 'chuwi', False), ('bmax', None, False),
                 ('bmax', '', False), ('bmax-ubuntu', 'bmax-ubuntu', True),
                 ('bmax-ubuntu', 'bmax', False), ('bmax', 'bmax-ubuntu', False),
                 ('bmax-ubuntu', None, False), ('bmax-ubuntu', '', False),
                 ('chuwi-ubuntu', 'chuwi-ubuntu', False)]
        for hostname, permission, allowed in cases:
            with self.subTest(hostname=hostname, permission=permission), tempfile.TemporaryDirectory() as directory:
                home = Path(directory) / 'home'
                marker = home / '.config/datlume/allow-scheduled-refresh'
                marker.parent.mkdir(parents=True)
                if permission is not None:
                    marker.write_text(permission + '\n')
                runner = refresh.Refresh(Path(directory) / 'repo', 'daily')
                with patch.object(refresh.Path, 'home', return_value=home), \
                     patch.object(refresh.socket, 'gethostname', return_value=hostname), \
                     patch.object(refresh, 'datetime', Clock), \
                     patch.object(refresh, 'lock', side_effect=GuardPassed):
                    if allowed:
                        with self.assertRaises(GuardPassed):
                            runner.run(scheduled=True)
                    else:
                        with self.assertRaisesRegex(RuntimeError, 'authorized only'):
                            runner.run(scheduled=True)

    def test_history_manifest_and_shards_are_not_pruned_separately(self):
        import hashlib
        with tempfile.TemporaryDirectory() as directory:
            fixture=Fixture(directory)
            folder=fixture.root/'public/data/realestate-history'
            folder.mkdir(parents=True)
            shard=folder/'13.json';index=folder/'index.json'
            shard.write_text('{"generatedAt":"old","value":1}')
            index.write_text(json.dumps({'sha256':hashlib.sha256(shard.read_bytes()).hexdigest()}))
            git(fixture.root,'add','.');git(fixture.root,'commit','-qm','history baseline')
            shard.write_text('{"generatedAt":"new","value":1}')
            index.write_text(json.dumps({'sha256':hashlib.sha256(shard.read_bytes()).hexdigest()}))
            tools=refresh.module(fixture.root,'scheduled-refresh-git')
            tools.prune_noops()
            self.assertEqual(json.loads(index.read_text())['sha256'],hashlib.sha256(shard.read_bytes()).hexdigest())
            self.assertEqual(set(tools.changed_paths()),{'public/data/realestate-history/13.json','public/data/realestate-history/index.json'})

    def test_master_only_keeps_daily_transaction_and_recovery(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            runner = refresh.Refresh(fixture.root, 'daily')
            runner.master_only = True
            today = refresh.datetime.now(refresh.ZoneInfo('Asia/Tokyo')).date().isoformat()
            (fixture.root / 'data/automation/last-success-date').write_text(today+'\n')
            seen = []
            def fail_worker(args, **kwargs):
                seen.append(args)
                (fixture.root / 'data/raw/listed-companies/normalized/financials.json').write_text('changed')
                raise RuntimeError('injected master-only failure')
            runner.command = fail_worker
            with self.assertRaises(RuntimeError):
                runner.run()
            self.assertEqual(seen, [['bash', 'scripts/refresh-listed-master-worker.sh']])
            fixture.assert_clean(self)
            self.assertEqual((fixture.root / 'data/raw/listed-companies/normalized/financials.json').read_text(), 'old-normalized')
            self.assertEqual((fixture.root / 'data/automation/last-success-date').read_text(), today+'\n')


    def test_master_worker_normalizes_before_public_data_and_stops_on_failure(self):
        for failing in ('', 'normalize:listed-incremental'):
            with self.subTest(failing=failing), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'scripts').mkdir(); (root/'bin').mkdir(); (root/'markers').mkdir()
                worker = root/'scripts/refresh-listed-master-worker.sh'
                shutil.copy2(ROOT/'scripts/refresh-listed-master-worker.sh', worker)
                npm = root/'bin/npm'
                npm.write_text('#!/bin/sh\nprintf "%s\\n" "$2" >> "$CALL_LOG"\nif [ "$2" = "$FAIL_STEP" ]; then exit 42; fi\n')
                npm.chmod(0o755)
                log = root/'calls'
                result = subprocess.run(['bash', str(worker)], env={**os.environ,
                    'PATH': str(root/'bin')+':'+os.environ['PATH'], 'CALL_LOG': str(log),
                    'FAIL_STEP': failing, 'DATLUME_MARKER_DIR': str(root/'markers')}, capture_output=True)
                calls = log.read_text().splitlines()
                if failing:
                    self.assertEqual(result.returncode, 42)
                    self.assertNotIn('build:listed-data', calls)
                    self.assertFalse((root/'markers/last-listed-master-refresh').exists())
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertLess(calls.index('normalize:listed-incremental'), calls.index('validate:listed-financials'))
                    self.assertLess(calls.index('validate:listed-financials'), calls.index('build:listed-data'))
                    self.assertTrue((root/'markers/last-listed-master-refresh').exists())

    def test_master_only_cannot_mark_an_unprocessed_daily_update_successful(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            runner = refresh.Refresh(fixture.root, 'daily'); runner.master_only = True
            with self.assertRaisesRegex(RuntimeError, 'fully verified daily update'):
                runner.run()
            self.assertEqual((fixture.root / 'data/automation/last-success-date').read_text(), '2026-09-01\n')
            fixture.assert_clean(self)

    def test_failed_collect_build_and_local_e2e_restore_all_runtime_and_primary(self):
        for job in ('daily', 'topics', 'weekly'):
            for failure in ('collection', 'release-check', 'local-e2e'):
                if job == 'daily' and failure != 'collection':
                    continue  # successful source collection is retained for release-only retries
                if job == 'weekly' and failure != 'collection':
                    continue
                with self.subTest(job=job, failure=failure), tempfile.TemporaryDirectory() as directory:
                    fixture = Fixture(directory)
                    runner = SmallRefresh(fixture.root, job)
                    runner.failure = failure
                    with self.assertRaises(RuntimeError):
                        runner.run()
                    fixture.assert_clean(self)
                    self.assertEqual(fixture.count(), 1)
                    self.assertEqual((fixture.root / 'data/raw/listed-companies/normalized/financials.json').read_text(), 'old-normalized')
                    self.assertFalse((fixture.root / 'data/raw/listed-companies/normalized/new.json').exists())
                    self.assertEqual((fixture.root / 'data/raw/listed-companies/documents-index.json').read_text(), 'old-index')
                    self.assertEqual(json.loads((fixture.root / 'src/data/summary.json').read_text())['records'], 1)
                    self.assertEqual((fixture.root / 'data/automation/last-monthly-refresh').read_text(), '2026-09\n')
                    self.assertEqual((fixture.root / 'data/automation/last-success-date').read_text(), '2026-09-01\n')
                    self.assertEqual(json.loads((fixture.root / 'src/data/sources.json').read_text()), fixture.sources)
                    self.assertTrue(list((fixture.root / 'data/automation/logs').glob('*failure-sources*')))

    def test_release_failure_retries_only_release_and_preserves_source_results(self):
        for failure in ('release-check', 'local-e2e'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                fixture=Fixture(directory)
                first=SmallRefresh(fixture.root,'daily');first.failure=failure
                with self.assertRaises(RuntimeError): first.run()
                self.assertEqual(fixture.count(),2)
                self.assertEqual(json.loads(first.manifest.read_text())['phase'],'collected')
                self.assertEqual((fixture.root/'data/automation/last-success-date').read_text(),'2026-09-01\n')
                if failure == 'release-check':
                    SmallRefresh(fixture.root,'topics').run()  # Generated-only concurrent commit may merge.
                second=SmallRefresh(fixture.root,'daily')
                with patch.object(second,'collect',side_effect=AssertionError('successful sources must not rerun')):
                    second.run()
                fixture.assert_clean(self)
                self.assertEqual(fixture.count(),2)
                self.assertFalse(second.manifest.exists())

    def test_failed_procurement_source_does_not_block_later_sources_and_only_it_retries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('scripts', 'bin', 'data', 'markers'):
                (root / folder).mkdir()
            shutil.copy2(ROOT / 'scripts/collect-daily.sh', root / 'scripts/collect-daily.sh')
            stub = root / 'bin/python3'
            stub.write_text("""#!/usr/bin/env bash
if [[ "$1" == "-" ]]; then echo 1; exit 0; fi
if [[ "$1" == "scripts/restore-failed-source.py" ]]; then echo yokohama_procurement; exit 0; fi
if [[ "$1" == "scripts/listed-master-refresh-needed.py" ]]; then exit 1; fi
if [[ "$1" == "collector/collect_sendai_procurement.py" && "$2" == "--probe" ]]; then exit 1; fi
if [[ "$1" == "collector/collect_yokohama_procurement.py" ]]; then
  echo yokohama >> "$CALL_LOG"
  if [[ ! -f "$MARKER_DIR/yokohama-failed-once" ]]; then
    touch "$MARKER_DIR/yokohama-failed-once"
    exit 42
  fi
fi
if [[ "$1" == "collector/collect_sapporo_procurement.py" ]]; then echo sapporo >> "$CALL_LOG"; fi
if [[ "$1" == "collector/collect_kobe_procurement.py" ]]; then echo kobe >> "$CALL_LOG"; fi
if [[ "$1" == "collector/check_health.py" ]]; then echo health >> "$CALL_LOG"; fi
exit 0
""")
            stub.chmod(0o755)
            npm = root / 'bin/npm'
            npm.write_text('#!/bin/sh\nexit 0\n')
            npm.chmod(0o755)
            markers = root / 'markers'
            month = datetime.now().strftime('%Y-%m')
            week = datetime.now().strftime('%G-W%V')
            for name in ('last-monthly-refresh', 'last-monthly-secondary-refresh',
                         'last-ipss-population-refresh', 'last-gbiz-activity-refresh',
                         'last-lodging-statistics-refresh', 'last-jma-weather-refresh',
                         'last-public-transport-refresh'):
                (markers / name).write_text(month + '\n')
            (markers / 'last-reinfolib-check').write_text(week + '\n')
            log = root / 'calls'
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'DATLUME_MARKER_DIR': str(markers), 'MARKER_DIR': str(markers),
                   'CALL_LOG': str(log)}
            first = subprocess.run(['bash', 'scripts/collect-daily.sh'], cwd=root, env=env,
                                   capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn('restored previous snapshot for procurement-yokohama', first.stdout)
            self.assertEqual(log.read_text().splitlines()[:3], ['yokohama', 'sapporo', 'kobe'])
            self.assertEqual(log.read_text().splitlines().count('health'), 12)
            self.assertFalse((markers / 'completed-steps/procurement-yokohama').exists())
            self.assertTrue((markers / 'completed-steps/procurement-sapporo').exists())
            self.assertFalse((markers / 'retry-unsafe').exists())
            second = subprocess.run(['bash', 'scripts/collect-daily.sh'], cwd=root, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual(calls[:3], ['yokohama', 'sapporo', 'kobe'])
            self.assertEqual(calls.count('yokohama'), 2)
            self.assertEqual(calls.count('sapporo'), 1)
            self.assertEqual(calls.count('kobe'), 1)
            self.assertEqual(calls.count('health'), 13)
            self.assertIn('already collected: procurement-sapporo', second.stdout)

    def test_failed_sendai_restore_preserves_other_source_rows_and_status(self):
        spec = importlib.util.spec_from_file_location('source_restore', ROOT / 'scripts/restore-failed-source.py')
        restore = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(restore)
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            root = fixture.root
            status = json.loads((root / 'src/data/sources.json').read_text())
            status['sources'].update({
                'sendai_procurement': {'status': 'ok', 'finishedAt': '2026-10-10T00:00:00+00:00'},
                'yokohama_procurement': {'status': 'ok', 'finishedAt': '2026-10-10T00:00:00+00:00'},
            })
            (root / 'src/data/sources.json').write_text(json.dumps(status))
            git(root, 'add', 'src/data/sources.json'); git(root, 'commit', '-qm', 'verified snapshots')
            with sqlite3.connect(root / 'data/public_it.db') as db:
                db.execute('drop table procurements')
                db.execute('create table procurements(source_id text primary key, title text)')
                db.execute('create table companies(company_id text primary key)')
                db.execute('create table organizations(organization_id text primary key)')
                db.executemany('insert into procurements values(?,?)', [
                    ('sendai:old', 'previous'), ('yokohama:old', 'previous')])
            backup = root / 'data/automation/baseline.db'
            with sqlite3.connect(root / 'data/public_it.db') as db, sqlite3.connect(backup) as old:
                db.backup(old)
            with sqlite3.connect(root / 'data/public_it.db') as db:
                db.execute("update procurements set title='bad' where source_id='sendai:old'")
                db.execute("insert into procurements values('sendai:new','bad')")
                db.execute("insert into procurements values('yokohama:new','healthy')")
            status['sources']['sendai_procurement'] = {'status': 'error'}
            status['sources']['yokohama_procurement'] = {'status': 'ok', 'finishedAt': '2026-10-12T00:00:00+00:00'}
            (root / 'src/data/sources.json').write_text(json.dumps(status))
            with patch.object(restore, 'ROOT', root), patch('collector.collect_jetro.export_json'):
                self.assertEqual(restore.restore('procurement-sendai', backup), 'sendai_procurement')
            with sqlite3.connect(root / 'data/public_it.db') as db:
                self.assertEqual(db.execute('select source_id,title from procurements order by source_id').fetchall(),
                                 [('sendai:old', 'previous'), ('yokohama:new', 'healthy'),
                                  ('yokohama:old', 'previous')])
            after = json.loads((root / 'src/data/sources.json').read_text())['sources']
            self.assertEqual(after['sendai_procurement'], {'status': 'ok', 'finishedAt': '2026-10-10T00:00:00+00:00'})
            self.assertEqual(after['yokohama_procurement']['finishedAt'], '2026-10-12T00:00:00+00:00')

    def test_published_source_checkpoints_survive_new_daily_transaction(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            state = fixture.root / 'data/automation'
            old = state / 'source-checkpoints'
            old.mkdir()
            (old / 'monthly-failed-source').write_text('2026-09\n')
            month = datetime.now(refresh.ZoneInfo('Asia/Tokyo')).strftime('%Y-%m')
            week = datetime.now(refresh.ZoneInfo('Asia/Tokyo')).strftime('%G-W%V')
            class Completed(SmallRefresh):
                def collect(self):
                    super().collect()
                    steps = self.markers / 'completed-steps'
                    steps.mkdir(exist_ok=True)
                    (steps / 'monthly-land-prices').write_text(month + '\n')
                    (steps / 'procurement-yokohama').write_text('completed')
                    (steps / 'weekly-reinfolib-history').write_text(week + '\n')
                    (self.markers / 'source-stale-since.json').write_text('{"sendai_procurement":"2026-10-10"}')
            Completed(fixture.root, 'daily').run()
            self.assertEqual((old / 'monthly-land-prices').read_text(), month + '\n')
            self.assertTrue((old / 'procurement-yokohama').exists())
            self.assertEqual((state / 'pending-source-retries.txt').read_text(), '')
            self.assertEqual((old / 'weekly-reinfolib-history').read_text(), week + '\n')
            self.assertFalse((old / 'monthly-failed-source').exists())
            next_day = refresh.Refresh(fixture.root, 'daily')
            next_day.prepare()
            self.assertTrue((next_day.markers / 'completed-steps/monthly-land-prices').exists())
            self.assertTrue((next_day.markers / 'completed-steps/procurement-yokohama').exists())
            self.assertTrue((next_day.markers / 'completed-steps/weekly-reinfolib-history').exists())
            self.assertFalse((next_day.markers / 'completed-steps/monthly-failed-source').exists())
            self.assertEqual(json.loads((next_day.markers / 'source-stale-since.json').read_text()),
                             {'sendai_procurement': '2026-10-10'})

    def test_pending_source_retries_after_publication_and_then_scheduled_run_skips(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            home = Path(directory) / 'home'
            permission = home / '.config/datlume/allow-scheduled-refresh'
            permission.parent.mkdir(parents=True)
            permission.write_text('kota-Intel')
            class Clock(datetime):
                @classmethod
                def now(cls, tz=None):
                    return datetime(2026, 10, 12, 12, tzinfo=tz)
            class First(SmallRefresh):
                def collect(self):
                    super().collect()
                    steps = self.markers / 'completed-steps'
                    steps.mkdir(exist_ok=True)
                    (steps / 'procurement-yokohama').write_text('2026-10-12')
                    (self.markers / 'stale-upstream-sources.txt').write_text('sendai_procurement\n')
            class StillFailed(SmallRefresh):
                def collect(self):
                    self.phase = 'collection'
                    (self.markers / 'stale-upstream-sources.txt').write_text('sendai_procurement\n')
            class Recovered(SmallRefresh):
                def collect(self):
                    self.assert_completed = (self.markers / 'completed-steps/procurement-yokohama').exists()
                    super().collect()
                    (self.markers / 'stale-upstream-sources.txt').write_text('')
            with patch.object(refresh, 'datetime', Clock), \
                 patch.object(refresh.Path, 'home', return_value=home), \
                 patch.object(refresh.socket, 'gethostname', return_value='kota-Intel'):
                First(fixture.root, 'daily').run()
                pending = fixture.root / 'data/automation/pending-source-retries.txt'
                self.assertEqual(pending.read_text(), 'sendai_procurement\n')
                history = fixture.root / 'data/automation/history.jsonl'
                before_history = history.read_text()
                StillFailed(fixture.root, 'daily').run(scheduled=True)
                self.assertEqual(pending.read_text(), 'sendai_procurement\n')
                self.assertEqual(history.read_text(), before_history)
                self.assertEqual(fixture.count(), 2)
                second = Recovered(fixture.root, 'daily')
                second.run(scheduled=True)
                self.assertTrue(second.assert_completed)
                self.assertEqual(pending.read_text(), '')
                third = Recovered(fixture.root, 'daily')
                with patch.object(third, 'collect', side_effect=AssertionError('resolved sources should skip')):
                    third.run(scheduled=True)

    def test_source_health_failure_retries_only_that_source(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for folder in ('scripts', 'bin', 'data', 'markers'):
                (root / folder).mkdir()
            shutil.copy2(ROOT / 'scripts/collect-daily.sh', root / 'scripts/collect-daily.sh')
            stub = root / 'bin/python3'
            stub.write_text("""#!/usr/bin/env bash
if [[ "$1" == "-" ]]; then echo 1; exit 0; fi
if [[ "$1" == "scripts/restore-failed-source.py" ]]; then echo yokohama_procurement; exit 0; fi
if [[ "$1" == "scripts/listed-master-refresh-needed.py" ]]; then exit 1; fi
if [[ "$1" == "collector/collect_sendai_procurement.py" && "$2" == "--probe" ]]; then exit 1; fi
case "$1" in
  collector/collect_yokohama_procurement.py) echo yokohama >> "$CALL_LOG" ;;
  collector/collect_sapporo_procurement.py) echo sapporo >> "$CALL_LOG" ;;
  collector/check_health.py)
    if [[ "$*" == *"yokohama_procurement"* && ! -f "$MARKER_DIR/failed-once" ]]; then
      touch "$MARKER_DIR/failed-once"
      exit 1
    fi ;;
esac
exit 0
""")
            stub.chmod(0o755)
            npm = root / 'bin/npm'
            npm.write_text('#!/bin/sh\nexit 0\n')
            npm.chmod(0o755)
            markers = root / 'markers'
            month = datetime.now().strftime('%Y-%m')
            for name in ('last-monthly-refresh', 'last-monthly-secondary-refresh',
                         'last-ipss-population-refresh', 'last-gbiz-activity-refresh',
                         'last-lodging-statistics-refresh', 'last-jma-weather-refresh',
                         'last-public-transport-refresh'):
                (markers / name).write_text(month + '\n')
            (markers / 'last-reinfolib-check').write_text(datetime.now().strftime('%G-W%V') + '\n')
            log = root / 'calls'
            env = {**os.environ, 'PATH': str(root / 'bin') + ':' + os.environ['PATH'],
                   'DATLUME_MARKER_DIR': str(markers), 'MARKER_DIR': str(markers), 'CALL_LOG': str(log)}
            first = subprocess.run(['bash', 'scripts/collect-daily.sh'], cwd=root, env=env,
                                   capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            self.assertIn('restored previous snapshot for procurement-yokohama', first.stdout)
            self.assertFalse((markers / 'completed-steps/procurement-yokohama').exists())
            self.assertTrue((markers / 'completed-steps/procurement-sapporo').exists())
            self.assertFalse((markers / 'retry-unsafe').exists())
            second = subprocess.run(['bash', 'scripts/collect-daily.sh'], cwd=root, env=env,
                                    capture_output=True, text=True)
            self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
            calls = log.read_text().splitlines()
            self.assertEqual(calls.count('yokohama'), 2)
            self.assertEqual(calls.count('sapporo'), 1)

    def test_partial_collection_retries_only_unfinished_source_steps(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture=Fixture(directory)
            class Partial(SmallRefresh):
                def collect(self):
                    marker=self.markers/'completed-steps'/'geps'
                    if marker.exists():
                        self.phase='collection'
                        return
                    super().collect()
                    marker.parent.mkdir(parents=True)
                    marker.write_text('success')
                    raise RuntimeError('injected next-source failure')
            first=Partial(fixture.root,'daily')
            with self.assertRaises(RuntimeError):first.run()
            self.assertEqual(fixture.count(),2)
            self.assertEqual(json.loads(first.manifest.read_text())['phase'],'collecting')
            second=Partial(fixture.root,'daily')
            second.run()
            self.assertEqual(fixture.count(),2)
            fixture.assert_clean(self)

    def test_topics_publish_while_daily_runtime_lock_is_held_and_daily_preserves_new_topics(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            daily = SmallRefresh(fixture.root, 'daily')
            with refresh.lock(fixture.root / 'data/automation/update.lock'):
                daily.prepare(); daily.snapshot(); daily.collect()
                SmallRefresh(fixture.root, 'topics').run()
                # Topic publication must use the primary's published ignored snapshot.
                self.assertEqual(json.loads((fixture.root / 'src/data/summary.json').read_text())['records'], 1)
                daily.publish('2026-10-05')
            fixture.assert_clean(self)
            sources = json.loads((fixture.root / 'src/data/sources.json').read_text())['sources']
            self.assertEqual(sources['wikipedia_topics']['date'], 'new-topics')
            self.assertEqual(sources['geps']['date'], 'new-daily')
            self.assertEqual(json.loads((fixture.root / 'public/data/wikipedia-topics.json').read_text())['latestDate'], 'new-topics')
            self.assertEqual(json.loads((fixture.root / 'src/data/summary.json').read_text())['records'], 2)
            self.assertEqual(fixture.count(), 2)

    def test_post_push_failures_keep_committed_state_and_do_not_mark_success(self):
        for failure in ('deploy', 'production-e2e'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(directory)
                runner = SmallRefresh(fixture.root, 'daily'); runner.failure = failure
                with self.assertRaises(RuntimeError):
                    runner.run()
                fixture.assert_clean(self)
                self.assertEqual(fixture.count(), 2)
                self.assertEqual(json.loads((fixture.root / 'src/data/summary.json').read_text())['records'], 2)
                self.assertEqual((fixture.root / 'data/automation/last-success-date').read_text(), '2026-09-01\n')
                self.assertEqual((fixture.root / 'data/automation/last-monthly-refresh').read_text(), '2026-09\n')
                SmallRefresh(fixture.root, 'topics').run()
                fixture.assert_clean(self)
                self.assertEqual(json.loads((fixture.root / 'src/data/summary.json').read_text())['records'], 2)

    def test_interrupted_runtime_transaction_stops_orphan_before_database_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            runner = SmallRefresh(fixture.root, 'daily')
            runner.prepare(); runner.snapshot(); runner.collect()
            child = subprocess.Popen(['python3', '-c', 'import time; time.sleep(30)'], start_new_session=True)
            runner.phase_save('collecting', child={'pid': child.pid, 'start': runner.process_start(child.pid)})
            try:
                runner.recover()
                child.wait(timeout=5)
                self.assertNotEqual(child.returncode, 0)
                self.assertEqual(fixture.count(), 1)
                fixture.assert_clean(self)
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL); child.wait()

    def test_conflicting_generated_file_or_new_code_blocks_release_without_overwriting(self):
        for change in ('public/data/listed-companies/summary.json', 'code.txt'):
            with self.subTest(change=change), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(directory)
                runner = SmallRefresh(fixture.root, 'daily')
                runner.prepare(); runner.snapshot(); runner.collect()
                (fixture.root / change).write_text('{"companies":3}' if change.endswith('.json') else 'external change')
                git(fixture.root, 'add', change); git(fixture.root, 'commit', '-qm', 'concurrent change')
                git(fixture.root, 'push', '-q', 'origin', 'main')
                with self.assertRaises(RuntimeError):
                    runner.publish('2026-10-05')
                runner.recover()
                self.assertEqual(fixture.count(), 1)
                fixture.assert_clean(self)
                self.assertIn('3' if change.endswith('.json') else 'external', (fixture.root / change).read_text())

    def test_monthly_secondary_datasets_can_be_published_but_code_changes_cannot(self):
        paths = ('public/data/housing-land-2023.json', 'public/data/municipality-social-indicators.json',
                 'public/data/retail-prices-city-monthly.json', 'public/data/municipality-population-projections.json',
                 'public/data/transport/index.json', 'public/data/transport/stations.json',
                 'public/data/transport/commute.json', 'public/data/transport/usage.json',
                 'public/data/realestate-history/index.json', 'public/data/realestate-history/13.json')
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            class Monthly(SmallRefresh):
                def collect(self):
                    super().collect()
                    for rel in paths:
                        (self.workspace / rel).parent.mkdir(parents=True, exist_ok=True)
                        (self.workspace / rel).write_text('{"records":1}')
                    (self.markers / 'last-public-transport-refresh').write_text('new-transport-month\n')
            Monthly(fixture.root, 'daily').run()
            fixture.assert_clean(self)
            for rel in paths:
                self.assertEqual(json.loads((fixture.root / rel).read_text())['records'], 1)
            self.assertEqual((fixture.root / 'data/automation/last-public-transport-refresh').read_text(), 'new-transport-month\n')
            tools = refresh.module(fixture.root, 'scheduled-refresh-git')
            self.assertFalse(tools.is_allowed('scripts/collector.py'))
            self.assertTrue(tools.is_allowed('public/data/realestate-history/index.json'))
            self.assertTrue(tools.is_allowed('public/data/realestate-history/13.json'))
            self.assertFalse(tools.is_allowed('public/data/realestate-history/raw.json'))
            self.assertFalse(tools.is_allowed('public/data/realestate-history/13.json.bak'))

    def test_early_manual_success_does_not_skip_new_ranking_at_1415(self):
        class Clock:
            @staticmethod
            def now(tz):
                return datetime(2026, 10, 5, 5, 15, tzinfo=timezone.utc).astimezone(tz)
        for latest in ('2026-10-03', '2026-10-04'):
            with self.subTest(latest=latest), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(directory)
                root = fixture.root
                (root/'public/data/wikipedia-topics.json').write_text(json.dumps({'latestDate': latest}))
                git(root, 'add', 'public/data/wikipedia-topics.json'); git(root, 'commit', '-qm', 'ranking'); git(root, 'push', '-q')
                (root/'data/automation/last-wikipedia-success-date').write_text('2026-10-05\n')
                home = Path(directory)/'home'
                marker = home/'.config/datlume/allow-scheduled-refresh'
                marker.parent.mkdir(parents=True); marker.write_text('kota-Intel')
                runner = SmallRefresh(root, 'topics')
                with patch.object(refresh, 'datetime', Clock), patch.object(refresh.socket, 'gethostname', return_value='kota-Intel'), patch.object(refresh.Path, 'home', return_value=home):
                    runner.run(scheduled=True)
                if latest == '2026-10-04':
                    self.assertFalse(runner.workspace.exists())
                else:
                    self.assertEqual(json.loads((root/'public/data/wikipedia-topics.json').read_text())['latestDate'], 'new-topics')

    def test_existing_user_changes_are_not_discarded(self):
        with tempfile.TemporaryDirectory() as directory:
            fixture = Fixture(directory)
            path = fixture.root / 'src/data/sources.json'
            path.write_text('user edit')
            with self.assertRaises(RuntimeError):
                SmallRefresh(fixture.root, 'daily').run()
            self.assertEqual(path.read_text(), 'user edit')
            self.assertEqual(fixture.count(), 1)

    def test_actual_daily_worker_failures_in_collection_health_regression_listed_and_monthly(self):
        for failure in ('collection', 'health', 'regression', 'listed', 'monthly'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                fixture = Fixture(directory)
                root = fixture.root
                (root / 'collector').mkdir()
                mutate = '''from pathlib import Path
import sqlite3
import sys
p=Path.cwd()
(p/'src/data/sources.json').write_text('{"sources":{"geps":{"error":"injected"}}}')
(p/'src/data/summary.json').write_text('{"records":2}')
with sqlite3.connect(p/'data/public_it.db') as db: db.execute('insert into procurements values(2)')
'''
                (root / 'collector/collect_geps_awards.py').write_text(mutate + ('raise SystemExit(1)' if failure == 'collection' else ''))
                for source in ('jetro', 'jetro_local', 'yokohama_procurement', 'sapporo_procurement',
                               'kobe_procurement', 'fukuoka_procurement', 'chiba_procurement', 'kyoto_procurement',
                               'kawasaki_procurement', 'sendai_procurement'):
                    (root / f'collector/collect_{source}.py').write_text('')
                (root / 'collector/check_health.py').write_text('raise SystemExit(1)' if failure == 'health' else '')
                (root / 'scripts/check-procurement-regression.py').write_text('raise SystemExit(1)' if failure == 'regression' else '')
                (root / 'collector/collect_land_prices.py').write_text('raise SystemExit(1)')
                git(root, 'add', 'collector', 'scripts/check-procurement-regression.py'); git(root, 'commit', '-qm', 'worker fixtures'); git(root, 'push', '-q')
                binpath = Path(directory) / 'bin'; binpath.mkdir()
                npm = binpath / 'npm'
                npm.write_text('#!/bin/bash\n' + ('if [[ "$*" == *"normalize:listed-incremental"* ]]; then echo changed > data/raw/listed-companies/normalized/financials.json; exit 1; fi\n' if failure == 'listed' else '') + 'exit 0\n')
                npm.chmod(0o755)
                runner = refresh.Refresh(root, 'daily')
                runner.env['PATH'] = str(binpath) + ':' + runner.env['PATH']
                with self.assertRaises(subprocess.CalledProcessError) as raised:
                    runner.run()
                self.assertEqual(raised.exception.returncode, {'collection':25, 'health':25, 'regression':24, 'listed':25, 'monthly':25}[failure])
                fixture.assert_clean(self)
                if failure in ('collection','health','regression','listed','monthly'):
                    self.assertEqual(fixture.count(), 2)
                    self.assertEqual(json.loads(runner.manifest.read_text())['phase'],'collecting')
                    if failure == 'listed':
                        npm.write_text('#!/bin/bash\nexit 0\n')
                        again=refresh.Refresh(root,'daily')
                        again.env['PATH']=str(binpath)+':'+again.env['PATH']
                        with self.assertRaises(subprocess.CalledProcessError) as retry:
                            again.run()  # The next monthly source fails; GEPS must remain at two records.
                        self.assertEqual(retry.exception.returncode,25)
                        self.assertEqual(fixture.count(),2)
                    runner.recover()  # Explicit rollback remains available for abandoned checkpoints.
                self.assertEqual(fixture.count(), 1)
                self.assertEqual((root / 'data/raw/listed-companies/normalized/financials.json').read_text(), 'old-normalized')


if __name__ == '__main__':
    unittest.main(verbosity=2)
