#!/usr/bin/env python3
"""Isolated collectors; serialize only publication and preserve interrupted transactions."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
MARKERS = ('last-success-date', 'last-listed-master-refresh', 'last-monthly-refresh',
           'last-monthly-secondary-refresh', 'last-ipss-population-refresh',
           'last-gbiz-activity-refresh', 'last-lodging-statistics-refresh', 'last-jma-weather-refresh', 'last-public-transport-refresh', 'last-reinfolib-check')
SUCCESS = {'daily': 'last-success-date', 'topics': 'last-wikipedia-success-date',
           'weekly': 'last-weekly-success-date'}
LOCKS = {'daily': 'daily-refresh.lock', 'topics': 'wikipedia-topics-refresh.lock',
         'weekly': 'weekly-audit.lock'}
RUNTIME_PATTERNS = ('data/raw/shokuba/workplace.sqlite', 'data/raw/listed-companies/normalized/**/*',
                    'data/raw/listed-companies/documents-index.json')
ROUTES = '/,/realestate/,/topics/,/procurement/,/regional/stays/,/regional/weather/,/transport/,/listed-companies/,/listed-companies/7203/,/unlisted-companies/'


def module(root, name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), root / 'scripts' / (name + '.py'))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    result.ROOT = root
    return result


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)


def copy_file(source, target):
    target.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(['cp', '--reflink=auto', '--preserve=mode,timestamps', '--', str(source), str(target)], check=True)


@contextmanager
def lock(path, blocking=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
        except BlockingIOError:
            yield False
            return
        yield True


def merge_sources(base, candidate, latest):
    """Merge changed source entries, never replace another job's status with an old copy."""
    result = dict(latest)
    keys = set(base) | set(candidate)
    for key in keys - {'sources'}:
        if base.get(key) == candidate.get(key):
            continue
        if latest.get(key) not in (base.get(key), candidate.get(key)):
            raise RuntimeError(f'Concurrent source metadata change: {key}')
        if key in candidate:
            result[key] = candidate[key]
        else:
            result.pop(key, None)
    old = base.get('sources', {})
    new = candidate.get('sources', {})
    merged = dict(latest.get('sources', {}))
    for key in set(old) | set(new):
        if old.get(key) == new.get(key):
            continue
        if merged.get(key) not in (old.get(key), new.get(key)):
            raise RuntimeError(f'Concurrent update of source: {key}')
        if key in new:
            merged[key] = new[key]
        else:
            merged.pop(key, None)
    result['sources'] = merged
    return result


class Refresh:
    def __init__(self, root, job):
        self.root, self.job = Path(root), job
        self.state = self.root / 'data/automation'
        self.workspace = self.state / 'workspaces' / job
        self.transaction = self.state / 'transactions' / job
        self.manifest = self.transaction / 'manifest.json'
        self.markers = self.workspace / 'tmp/refresh-markers'
        self.phase = 'startup'
        self.master_only = False
        self.base = None
        self.log = None
        self.env = dict(os.environ, TZ='Asia/Tokyo')
        runtime = self.root / '.venv/bin'
        if (runtime / 'python3').exists():
            self.env['PATH'] = str(runtime) + ':' + self.env['PATH']
        self.env['PATH'] = str(Path.home() / '.nvm/versions/node/v22.23.2/bin') + ':' + self.env['PATH']

    def git(self, *args, cwd=None, check=True):
        r = subprocess.run(['git', *args], cwd=cwd or self.root, capture_output=True, check=check)
        return r.stdout.decode().strip()

    def command(self, args, cwd=None, extra_env=None):
        print('RUN:', ' '.join(map(str, args)), flush=True)
        proc = subprocess.Popen(args, cwd=cwd or self.workspace,
                                env={**self.env, **(extra_env or {})}, start_new_session=True,
                                stdout=self.log, stderr=subprocess.STDOUT if self.log else None)
        if self.manifest.exists():
            self.phase_save(json.loads(self.manifest.read_text())['phase'], child={'pid': proc.pid, 'start': self.process_start(proc.pid)})
        try:
            code = proc.wait()
        except BaseException:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()
            raise
        finally:
            if self.manifest.exists():
                self.phase_save(json.loads(self.manifest.read_text())['phase'], child=None)
        if code:
            raise subprocess.CalledProcessError(code, args)

    @staticmethod
    def process_start(pid):
        try:
            return Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()[19]
        except FileNotFoundError:
            return None

    def stop_orphan(self, entry):
        child = entry.get('child')
        if not child or not child.get('start') or self.process_start(child['pid']) != child['start']:
            return
        print(f"Stopping interrupted collector group {child['pid']} before restoring state", flush=True)
        try:
            os.killpg(child['pid'], signal.SIGTERM)
        except ProcessLookupError:
            return
        for _ in range(20):
            if self.process_start(child['pid']) is None:
                break
            time.sleep(.1)
        try:
            os.killpg(child['pid'], signal.SIGKILL)
        except ProcessLookupError:
            pass
        for _ in range(50):
            alive = False
            for path in Path('/proc').glob('[0-9]*/stat'):
                try:
                    fields = path.read_text().rsplit(')', 1)[1].split()
                    if int(fields[2]) == child['pid'] and fields[0] != 'Z':
                        alive = True
                        break
                except (OSError, ValueError, IndexError):
                    continue
            if not alive:
                return
            time.sleep(.1)
        raise RuntimeError('Interrupted collector group has not exited; preserve the recovery snapshot')

    def fetch(self):
        self.git('fetch', '--quiet', 'origin', 'main')
        return self.git('rev-parse', 'origin/main')

    def clean_primary(self):
        if self.git('branch', '--show-current') != 'main':
            raise RuntimeError('Primary checkout must be on main')
        if self.git('status', '--porcelain'):
            raise RuntimeError('Primary checkout has existing changes; no files will be discarded')
        latest = self.fetch()
        self.git('merge', '--ff-only', latest)
        return latest

    def ignored_outputs(self, root):
        state = module(self.root, 'procurement-refresh-state')
        # sources.json is tracked and is merged per source instead of copied here.
        return {rel: path for rel, path in state.outputs(root).items() if rel != 'src/data/sources.json'}

    def hydrate(self, source, target):
        files = self.ignored_outputs(source)
        for rel, path in self.ignored_outputs(target).items():
            if rel not in files:
                path.unlink()
        for rel, path in files.items():
            copy_file(path, target / rel)

    def ensure_browser_dependencies(self):
        if not (self.root / 'package.json').exists():
            return
        probe = ['node', '-e', "const {chromium}=require('playwright'); require('fs').accessSync(chromium.executablePath())"]
        if subprocess.run(probe, cwd=self.root, env=self.env, capture_output=True).returncode == 0:
            return
        self.phase = 'browser-dependencies'
        print('Playwright or Chromium missing; restoring browser dependencies before collection', flush=True)
        self.command(['npm', 'ci', '--include=dev'], cwd=self.root)
        if subprocess.run(probe, cwd=self.root, env=self.env, capture_output=True).returncode:
            self.command(['npx', 'playwright', 'install', 'chromium'], cwd=self.root)
        subprocess.run(probe, cwd=self.root, env=self.env, check=True)

    def prepare(self):
        self.phase = 'prepare-workspace'
        with lock(self.state / 'release.lock'):
            self.base = self.clean_primary()
            self.ensure_browser_dependencies()
            self.phase = 'prepare-workspace'
            self.workspace.parent.mkdir(parents=True, exist_ok=True)
            if self.workspace.exists():
                self.git('worktree', 'remove', '--force', str(self.workspace))
            self.git('worktree', 'add', '--detach', str(self.workspace), self.base)
            (self.workspace / 'data').symlink_to(self.root / 'data', target_is_directory=True)
            (self.workspace / 'node_modules').symlink_to(self.root / 'node_modules', target_is_directory=True)
            self.hydrate(self.root, self.workspace)
            self.markers.mkdir(parents=True)
            for name in MARKERS:
                if (self.state / name).exists():
                    copy_file(self.state / name, self.markers / name)

    def runtime_files(self):
        return {p.relative_to(self.root).as_posix(): p for pattern in RUNTIME_PATTERNS
                for p in self.root.glob(pattern) if p.is_file()}

    def snapshot(self):
        self.phase = 'runtime-snapshot'
        if self.transaction.exists():
            shutil.rmtree(self.transaction)
        self.transaction.mkdir(parents=True)
        records = {}
        if self.job != 'topics':
            state = module(self.root, 'procurement-refresh-state')
            database = self.root / 'data/public_it.db'
            if database.exists():
                state.backup_database(self.root, self.transaction / 'public_it.db')
                if self.job == 'daily':
                    backup_dir = self.root / 'data/backups'
                    day = datetime.now(ZoneInfo('Asia/Tokyo')).date()
                    backup = backup_dir / f'public_it-{day.isoformat()}.db'
                    temporary = backup.with_suffix('.tmp')
                    copy_file(self.transaction / 'public_it.db', temporary)
                    temporary.replace(backup)
                    for old in backup_dir.glob('public_it-????-??-??.db'):
                        if old.name[10:20] < (day - timedelta(days=7)).isoformat():
                            old.unlink()
            records = self.runtime_files()
            for rel, path in records.items():
                copy_file(path, self.transaction / 'files' / rel)
        atomic_json(self.manifest, {'phase': 'collecting', 'base': self.base,
                                   'workspace': str(self.workspace), 'runtimeFiles': sorted(records),
                                   'databaseExisted': (self.root / 'data/public_it.db').exists(),
                                   'beforeRecords': json.loads((self.root / 'src/data/summary.json').read_text()).get('records')
                                   if (self.root / 'src/data/summary.json').exists() else None})

    def phase_save(self, phase, **values):
        entry = json.loads(self.manifest.read_text())
        entry.update(phase=phase, **values)
        atomic_json(self.manifest, entry)

    def recover(self):
        """Also handles SIGKILL and a push that succeeded before its reply was lost."""
        if not self.manifest.exists():
            return
        entry = json.loads(self.manifest.read_text())
        self.stop_orphan(entry)
        pushed = False
        candidate = entry.get('candidate')
        if candidate:
            self.fetch()  # Do not restore committed state when the remote cannot be checked.
            pushed = subprocess.run(['git', 'merge-base', '--is-ancestor', candidate, 'origin/main'],
                                    cwd=self.root).returncode == 0
        if pushed:
            with lock(self.state / 'release.lock'):
                self.clean_primary()
                if self.job == 'daily':
                    if not self.workspace.exists():
                        raise RuntimeError('Published transaction workspace missing; preserve recovery files')
                    self.hydrate(self.workspace, self.root)
            print('Published Git state retained; retry will verify/deploy without dirtying primary', flush=True)
        elif self.job != 'topics':
            state = module(self.root, 'procurement-refresh-state')
            entries = entry['runtimeFiles']
            for rel in entries:
                path = Path(rel)
                if path.is_absolute() or '..' in path.parts or not (self.transaction / 'files' / rel).is_file():
                    raise RuntimeError(f'Invalid runtime snapshot entry: {rel}')
            backup = self.transaction / 'public_it.db'
            if backup.exists():
                state.check_database(backup)
            # Collector children are terminated before this point.
            if backup.exists():
                state.restore_database(self.root, backup)
            if not entry.get('databaseExisted', True):
                for suffix in ('', '-journal', '-wal', '-shm'):
                    Path(str(self.root / 'data/public_it.db') + suffix).unlink(missing_ok=True)
            for rel, path in self.runtime_files().items():
                if rel not in entries:
                    path.unlink()
            for rel in entries:
                copy_file(self.transaction / 'files' / rel, self.root / rel)
            print('Unpublished DB, EDINET index and normalized state restored', flush=True)
        evidence = self.workspace / 'src/data/sources.json'
        if evidence.exists():
            stamp = datetime.now(ZoneInfo('Asia/Tokyo')).strftime('%Y%m%dT%H%M%S%f')
            copy_file(evidence, self.state / 'logs' / f'{self.job}-failure-sources-{stamp}.json')
        shutil.rmtree(self.transaction)

    def collect(self):
        self.phase = 'collection'
        if self.job == 'daily':
            worker = 'refresh-listed-master-worker.sh' if self.master_only else 'collect-daily.sh'
            self.command(['bash', 'scripts/' + worker], extra_env={'DATLUME_MARKER_DIR': str(self.markers)})
        elif self.job == 'topics':
            self.command(['python3', 'collector/collect_wikipedia_topics.py', '--days', '14'])
            self.command(['npm', 'run', 'audit:wikipedia-topics'])
            expected = (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
            latest = json.loads((self.workspace / 'public/data/wikipedia-topics.json').read_text())['latestDate']
            if latest < expected:
                raise RuntimeError(f'Wikipedia ranking for {expected} is not available yet (latest={latest}); retry later')
        else:
            self.command(['bash', 'scripts/weekly-audit-worker.sh'])

    def overlay(self):
        tools = module(self.workspace, 'scheduled-refresh-git')
        tools.prune_noops()
        paths = tools.require_generated_only()
        candidate = {rel: (self.workspace / rel).read_bytes() if (self.workspace / rel).exists() else None
                     for rel in paths}
        latest = self.clean_primary()
        upstream = self.git('diff', '--name-only', self.base, latest).splitlines()
        if any(not tools.is_allowed(p) for p in upstream):
            raise RuntimeError('Source code changed during collection; retry against the new source')

        def blob(commit, rel):
            r = subprocess.run(['git', 'show', f'{commit}:{rel}'], cwd=self.root, capture_output=True)
            return r.stdout if r.returncode == 0 else None

        merged = {}
        for rel, content in candidate.items():
            before, now = blob(self.base, rel), blob(latest, rel)
            if before != now and content != now:
                if rel != 'src/data/sources.json' or None in (before, content, now):
                    raise RuntimeError(f'Concurrent generated-file conflict: {rel}')
                content = (json.dumps(merge_sources(json.loads(before), json.loads(content), json.loads(now)),
                                      ensure_ascii=False, indent=2) + '\n').encode()
            merged[rel] = content
        self.git('reset', '--hard', latest, cwd=self.workspace)
        for rel, content in merged.items():
            path = self.workspace / rel
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(content)
        if self.job == 'topics':
            # Always publish the latest successful daily ignored build inputs, never the collection-time copy.
            self.hydrate(self.root, self.workspace)
        return tools, latest

    def browser_checks(self, base):
        self.command(['npm', 'run', 'e2e:deep'], extra_env={'E2E_BASE_URL': base, 'E2E_ONLY': ROUTES})
        self.command(['npm', 'run', 'e2e:workplace'], extra_env={'E2E_BASE_URL': base})
        self.command(['npm', 'run', 'e2e:gbiz-activity'], extra_env={'E2E_BASE_URL': base})
        self.command(['npm', 'run', 'e2e:lodging-statistics'], extra_env={'E2E_BASE_URL': base})
        self.command(['npm', 'run', 'e2e:public-transport'], extra_env={'E2E_BASE_URL': base})
        if self.job == 'daily':
            for script in ('e2e:retail-history', 'e2e:ipss-population', 'e2e:jma-weather', 'e2e:reinfolib-history'):
                self.command(['npm', 'run', script], extra_env={'E2E_BASE_URL': base})

    def checks(self):
        self.phase = 'release-check'
        env = {'DATLUME_RELEASE_LOCK_HELD': '1'}
        self.command(['npm', 'run', 'release:check' if self.job == 'daily' else 'build'], extra_env=env)
        if self.job == 'topics':
            self.command(['npm', 'run', 'audit:wikipedia-topics'])
            self.command(['npm', 'run', 'audit:html'])
        self.local_browser_checks()

    def local_browser_checks(self):
        self.phase = 'local-e2e'
        with socket.socket() as sock, socket.socket() as inspector:
            sock.bind(('127.0.0.1', 0)); inspector.bind(('127.0.0.1', 0))
            port, inspector_port = sock.getsockname()[1], inspector.getsockname()[1]
        runtime_log = self.workspace / 'tmp/local-runtime.log'
        runtime_log.parent.mkdir(parents=True, exist_ok=True)
        output = runtime_log.open('w')
        preview = subprocess.Popen(['npx', 'wrangler', 'pages', 'dev', 'dist', '--ip', '127.0.0.1',
                                    '--port', str(port), '--inspector-port', str(inspector_port),
                                    '--compatibility-date', '2026-10-01', '--show-interactive-dev-session=false'],
                                   cwd=self.workspace, env=self.env, start_new_session=True,
                                   stdout=output, stderr=subprocess.STDOUT)
        try:
            import urllib.request
            url = f'http://127.0.0.1:{port}'
            for _ in range(120):
                if preview.poll() is not None:
                    raise RuntimeError(f'Local Pages runtime exited before E2E; see {runtime_log}')
                try:
                    with urllib.request.urlopen(url + '/', timeout=1):
                        break
                except OSError:
                    time.sleep(.25)
            else:
                raise RuntimeError('Preview did not become ready')
            # Wrangler serves the same Pages Functions and assets as production.
            self.browser_checks(url)
        finally:
            if preview.poll() is None:
                try:
                    os.killpg(preview.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            try:
                preview.wait(timeout=10)
            except subprocess.TimeoutExpired:
                os.killpg(preview.pid, signal.SIGKILL)
                preview.wait()
            output.close()

    def deploy(self):
        self.phase = 'cloudflare-deploy-and-production-verification'
        self.command(['bash', './deploy-datlume.sh'], extra_env={'DATLUME_RELEASE_LOCK_HELD': '1'})

    def publish(self, today):
        self.phase = 'publication-lock'
        with lock(self.state / 'release.lock'):
            tools, latest = self.overlay()
            self.checks()
            paths = tools.require_generated_only()
            if paths:
                self.git('add', '-A', '--', *paths, cwd=self.workspace)
                self.git('diff', '--cached', '--check', cwd=self.workspace)
                self.git('commit', '-m', f'chore(data): {self.job} refresh {today}', cwd=self.workspace)
            commit = self.git('rev-parse', 'HEAD', cwd=self.workspace)
            self.phase_save('publishing', candidate=commit)
            self.phase = 'git-push'
            self.git('push', 'origin', 'HEAD:refs/heads/main', cwd=self.workspace)
            self.phase_save('published', candidate=commit)
            self.clean_primary()
            if self.job == 'daily':
                self.hydrate(self.workspace, self.root)
            self.deploy()
            self.phase = 'production-e2e'
            self.browser_checks('https://datlume.com')
            if self.job == 'daily':
                for name in MARKERS[1:]:
                    if (self.markers / name).exists():
                        copy_file(self.markers / name, self.state / name)
            marker = self.state / SUCCESS[self.job]
            temporary = marker.with_suffix('.tmp')
            temporary.write_text(today + '\n')
            temporary.replace(marker)
            summary = self.workspace / 'src/data/summary.json'
            entry = {'job': self.job, 'finishedAt': datetime.now(ZoneInfo('Asia/Tokyo')).isoformat(),
                     'commit': commit, 'verified': True}
            if summary.exists():
                data = json.loads(summary.read_text())
                before = json.loads(self.manifest.read_text()).get('beforeRecords')
                after = data.get('records')
                entry.update(beforeRecords=before, deltaRecords=after-before if isinstance(before, int) and isinstance(after, int) else None,
                             afterRecords=after, lastDate=data.get('lastDate'),
                             awardRecords=data.get('awardRecords'), companies=data.get('companies'))
            with (self.state / 'history.jsonl').open('a') as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + '\n')
            shutil.rmtree(self.transaction)

    def run(self, scheduled=False):
        self.state.mkdir(parents=True, exist_ok=True)
        today = datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
        if self.master_only:
            marker = self.state / SUCCESS['daily']
            if self.job != 'daily' or not marker.exists() or marker.read_text().strip() != today:
                raise RuntimeError('Master-only mode requires a fully verified daily update today; run the regular refresh first')
        if scheduled:
            marker = Path.home() / '.config/datlume/allow-scheduled-refresh'
            if socket.gethostname() != 'kota-Intel' or not marker.is_file() or marker.read_text().strip() != 'kota-Intel':
                raise RuntimeError('Scheduled updates are authorized only on the production Ubuntu host')
            if self.job == 'daily' and datetime.now(ZoneInfo('Asia/Tokyo')).hour < 6:
                return
        with lock(self.state / LOCKS[self.job], blocking=False) as acquired:
            if not acquired:
                print(f'SKIP: {self.job} is already running', flush=True)
                return
            # Daily/weekly share mutable DB and normalized data; topics never takes this lock.
            with lock(self.state / ('topics-state.lock' if self.job == 'topics' else 'update.lock'), blocking=False) as ready:
                if not ready:
                    print(f'SKIP: runtime state is in use ({self.job})', flush=True)
                    return
                if self.job != 'topics':
                    other = 'weekly' if self.job == 'daily' else 'daily'
                    Refresh(self.root, other).recover()
                self.recover()
                marker = self.state / SUCCESS[self.job]
                fresh = True
                if self.job == 'topics':
                    try:
                        latest = json.loads((self.root / 'public/data/wikipedia-topics.json').read_text())['latestDate']
                        fresh = latest >= (datetime.now(timezone.utc).date() - timedelta(days=1)).isoformat()
                    except (OSError, KeyError, ValueError):
                        fresh = False
                if scheduled and fresh and marker.exists() and marker.read_text().strip() == today:
                    print(f'SKIP: {self.job} already verified for {today}', flush=True)
                    return
                if shutil.disk_usage(self.root).free < 10 * 1024**3:
                    raise RuntimeError('Less than 10 GiB free')
                try:
                    self.prepare()
                    self.snapshot()
                    self.collect()
                    if self.job == 'weekly':
                        shutil.rmtree(self.transaction)
                        (self.state / SUCCESS[self.job]).write_text(today + '\n')
                    else:
                        self.publish(today)
                    print(f'=== {self.job} refresh verified success {datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()} ===', flush=True)
                except BaseException:
                    self.recover()
                    raise


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('job', choices=SUCCESS)
    parser.add_argument('mode', nargs='?', default='scheduled')
    # The historic shell accepts --scheduled as a positional mode.
    args = parser.parse_args([a if a != '--scheduled' else 'scheduled' for a in sys.argv[1:]])
    scheduled = args.mode == 'scheduled'
    runner = Refresh(ROOT, args.job)
    if args.mode == 'listed-master':
        if args.job != 'daily':
            parser.error('listed-master mode requires the daily safety transaction')
        runner.master_only = True
    def interrupted(signum, frame):
        raise InterruptedError(f'Refresh interrupted by signal {signum}')
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGINT, interrupted)
    logs = runner.state / ('weekly-audit-logs' if args.job == 'weekly' else 'logs')
    logs.mkdir(parents=True, exist_ok=True)
    retention = 90 if args.job == 'weekly' else 30
    cutoff = time.time() - retention * 86400
    for old in logs.glob('*.log'):
        if old.stat().st_mtime < cutoff:
            old.unlink()
    date = datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
    prefix = {'daily': '', 'topics': 'wikipedia-topics-', 'weekly': ''}[args.job]
    # Unbuffered stdout goes to a stable per-job daily log as well as the caller.
    with (logs / (prefix + date + '.log')).open('a', buffering=1) as output:
        class Tee:
            def write(self, value):
                output.write(value); sys.__stdout__.write(value)
            def flush(self):
                output.flush(); sys.__stdout__.flush()
        sys.stdout = Tee()
        runner.log = output
        try:
            runner.run(scheduled)
        except BaseException as error:
            failure_log = runner.state / 'wikipedia-failures.log' if args.job == 'topics' else logs / 'failures.log'
            with failure_log.open('a') as handle:
                handle.write(f'{datetime.now(ZoneInfo("Asia/Tokyo")).isoformat()}\tjob={args.job}\tstep={runner.phase}\terror={type(error).__name__}: {error}\n')
            print(f'ERROR: {args.job} stopped at {runner.phase}: {error}', flush=True)
            raise SystemExit(1)
        finally:
            sys.stdout = sys.__stdout__


if __name__ == '__main__':
    main()
