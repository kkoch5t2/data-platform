#!/usr/bin/env python3
"""Verify a deployed release by content hashes, not HTTP status alone."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import time
import urllib.parse
import urllib.request
import uuid
from xml.etree import ElementTree

MANIFEST = 'data/release-manifest.json'
REQUIRED = ('data/dashboard-meta.json', 'data/listed-companies/summary.json',
            'data/listed-companies/index.json', 'data/company-registry/summary.json',
            'data/company-registry/unlisted-index.json', 'data/wikipedia-topics.json',
            'data/weather/index.json', 'data/weather/44.json', 'sitemap.xml')
PAGES = ('/', '/topics/', '/procurement/', '/procurement/companies/', '/procurement/companies/page/2/', '/regional/weather/', '/listed-companies/', '/unlisted-companies/')


def digest(body):
    return hashlib.sha256(body).hexdigest()


def write_manifest(dist):
    dist = Path(dist)
    paths = set(REQUIRED)
    paths.update(p.relative_to(dist).as_posix() for p in (dist / 'data').glob('*.json')
                 if p.name != 'release-manifest.json' and not p.name.startswith('dashboard'))
    dashboards = sorted((dist / 'data').glob('dashboard-[0-9]*.json'))
    paths.update(p.relative_to(dist).as_posix() for p in dashboards[-5:])
    paths.update(p.relative_to(dist).as_posix() for p in dist.glob('sitemap-*.xml'))
    # Sample both ends of each shard set on every release.
    for folder in ('data/company-details', 'data/listed-companies/details', 'data/company-registry/details',
                   'data/weather'):
        shards = sorted((dist / folder).glob('*.json'))
        if not shards:
            raise RuntimeError(f'Missing published shards: {folder}')
        paths.update(p.relative_to(dist).as_posix() for p in (shards[0], shards[-1]))
    files = {}
    for rel in sorted(paths):
        body = (dist / rel).read_bytes()
        if rel.endswith('.json'):
            json.loads(body)
        elif rel.endswith('.xml'):
            ElementTree.fromstring(body)
        files[rel] = {'sha256': digest(body), 'bytes': len(body)}
    commit = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=dist.parent,
                            capture_output=True, text=True, check=False).stdout.strip()
    payload = {'schemaVersion': 1, 'releaseId': uuid.uuid4().hex, 'commit': commit,
               'builtAt': datetime.now(timezone.utc).isoformat(), 'files': files,
               'pages': list(PAGES)}
    path = dist / MANIFEST
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(',', ':')) + '\n')
    print(f'Release verification manifest: {len(files)} data/XML files, {len(PAGES)} pages')
    return payload


def request(base, rel, release):
    url = base.rstrip('/') + '/' + rel.lstrip('/')
    separator = '&' if '?' in url else '?'
    url += separator + urllib.parse.urlencode({'datlume_release': release})
    req = urllib.request.Request(url, headers={'User-Agent': 'DATLUME release verification/1.0',
                                              'Cache-Control': 'no-cache'})
    with urllib.request.urlopen(req, timeout=30) as response:
        if response.status != 200:
            raise RuntimeError(f'{rel}: HTTP {response.status}')
        return response.read()


def verify(expected, base, attempts=6, delay=10, report=None):
    errors = []
    release = expected['releaseId']
    for attempt in range(1, attempts + 1):
        errors = []
        try:
            live = json.loads(request(base, MANIFEST, release))
            if live != expected:
                raise RuntimeError('Production release manifest differs from the expected deployment')
            def check_file(item):
                rel, metadata = item
                try:
                    body = request(base, rel, release)
                    if len(body) != metadata['bytes'] or digest(body) != metadata['sha256']:
                        raise RuntimeError('content differs from the built release')
                    if rel.endswith('.json'):
                        json.loads(body)
                    elif rel.endswith('.xml'):
                        ElementTree.fromstring(body)
                    return None
                except Exception as error:
                    return f'{rel}: {error}'
            with ThreadPoolExecutor(max_workers=4) as pool:
                errors.extend(x for x in pool.map(check_file, expected['files'].items()) if x)
            for route in expected['pages']:
                try:
                    body = request(base, route, release).decode('utf-8')
                    if route.startswith('/procurement/companies/') and len(body.encode('utf-8')) > 300_000:
                        raise RuntimeError('Company ranking page exceeds 300 KB')
                    if '<h1' not in body.lower() or 'DATLUME' not in body:
                        raise RuntimeError('Expected page content is missing')
                except Exception as error:
                    errors.append(f'{route}: {error}')
        except Exception as error:
            errors.append(str(error))
        if not errors:
            result = {'ok': True, 'releaseId': release, 'commit': expected['commit'],
                      'verifiedAt': datetime.now(timezone.utc).isoformat(), 'attempt': attempt,
                      'dataFiles': len(expected['files']), 'pages': len(expected['pages'])}
            if report:
                Path(report).parent.mkdir(parents=True, exist_ok=True)
                Path(report).write_text(json.dumps(result, indent=2) + '\n')
            print(f'Production verified: release={release} files={result["dataFiles"]} pages={result["pages"]}')
            return result
        print(f'Production verification attempt {attempt}/{attempts} failed: ' + '; '.join(errors[:8]), flush=True)
        if attempt < attempts:
            time.sleep(delay)
    result = {'ok': False, 'releaseId': release, 'errors': errors,
              'verifiedAt': datetime.now(timezone.utc).isoformat()}
    if report:
        Path(report).parent.mkdir(parents=True, exist_ok=True)
        Path(report).write_text(json.dumps(result, indent=2) + '\n')
    raise RuntimeError('Production verification failed: ' + '; '.join(errors[:8]))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    parser.add_argument('--base-url', default='https://datlume.com')
    parser.add_argument('--write-manifest', action='store_true')
    parser.add_argument('--attempts', type=int, default=6)
    parser.add_argument('--retry-delay', type=float, default=10)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.write_manifest:
        write_manifest(args.dist)
    else:
        expected = json.loads((args.dist / MANIFEST).read_text())
        # Detect accidental changes to the build after its manifest was generated.
        for rel, metadata in expected['files'].items():
            if digest((args.dist / rel).read_bytes()) != metadata['sha256']:
                raise RuntimeError(f'Local build changed after manifest creation: {rel}')
        verify(expected, args.base_url, args.attempts, args.retry_delay, args.report)


if __name__ == '__main__':
    main()
