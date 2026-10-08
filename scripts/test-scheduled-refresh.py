#!/usr/bin/env python3
"""Exercise isolated jobs against real Git remotes, SQLite and concurrent publications."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import sqlite3
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
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
        for name in ('scheduled-refresh.py', 'scheduled-refresh-git.py', 'procurement-refresh-state.py', 'collect-daily.sh', 'listed-master-refresh-needed.py'):
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
                self.assertEqual(raised.exception.returncode, {'collection':1, 'health':21, 'regression':24, 'listed':1, 'monthly':1}[failure])
                fixture.assert_clean(self)
                self.assertEqual(fixture.count(), 1)
                self.assertEqual((root / 'data/raw/listed-companies/normalized/financials.json').read_text(), 'old-normalized')


if __name__ == '__main__':
    unittest.main(verbosity=2)
