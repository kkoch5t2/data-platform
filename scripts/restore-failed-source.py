#!/usr/bin/env python3
"""Restore one failed collector from the pre-refresh snapshot, preserving peers."""
from __future__ import annotations
import argparse
import json
import shutil
from pathlib import Path
import sqlite3
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
PROCUREMENT = {
    'procurement-geps-awards': ('geps_awards', 'geps:'),
    'procurement-jetro': ('jetro', 'jetro:'),
    'procurement-jetro-local': ('jetro_local', 'jetro-local:'),
    'procurement-yokohama': ('yokohama_procurement', 'yokohama:'),
    'procurement-sapporo': ('sapporo_procurement', 'sapporo:'),
    'procurement-kobe': ('kobe_procurement', 'kobe:'),
    'procurement-fukuoka': ('fukuoka_procurement', 'fukuoka:'),
    'procurement-chiba': ('chiba_procurement', 'chiba:'),
    'procurement-kyoto': ('kyoto_procurement', 'kyoto:'),
    'procurement-kawasaki': ('kawasaki_procurement', 'kawasaki:'),
    'procurement-sendai': ('sendai_procurement', 'sendai:'),
}
FILES = {
    'monthly-land-prices': ('land_prices', ('public/data/land-prices-2026.json', 'public/data/land-survey-2026.json', 'public/data/land-price-history.json')),
    'monthly-living-layers': (None, tuple('public/data/' + name for name in (
        'municipality-stats-2026.json', 'crime-prefecture-2025.json', 'traffic-accidents-2024.json',
        'poi-schools-2023.json', 'poi-hospitals-2020.json', 'poi-stations-2025.json'))),
    'monthly-regional-trends': ('regional_trends', ('public/data/regional-trends-2026.json',)),
    'monthly-regional-migration': ('regional_migration', ('public/data/regional-migration-history.json',)),
    'monthly-employment-economy': ('employment_economy', ('public/data/employment-economy-2026.json',)),
    'monthly-employment-wage': ('employment_wage_history', ('public/data/employment-wage-history.json',)),
    'monthly-business-industry': ('business_industry', ('public/data/business-industry-2026.json',)),
    'monthly-business-history': ('business_industry_history', ('public/data/business-industry-history.json',)),
    'monthly-economy-prices': ('economy_prices', ('public/data/economy-prices.json',)),
    'monthly-economy-history': ('economy_prices_history', ('public/data/economy-prices-history.json',)),
    'monthly-energy': ('energy', ('public/data/energy.json',)),
    'monthly-energy-history': ('energy_consumption_history', ('public/data/energy-consumption-history.json',)),
    'monthly-lodging-statistics': ('lodging_statistics', ('public/data/lodging-statistics.json',)),
    'monthly-public-transport': ('public_transport', tuple('public/data/transport/' + name for name in
        ('index.json', 'stations.json', 'commute.json', 'usage.json'))),
    'monthly-jma-weather': ('jma_weather', tuple('public/data/weather/' + name for name in
        ('index.json', *(f'{n:02}.json' for n in range(1, 48)), *(f'{n:02}.json' for n in range(51, 66))))),
    'monthly-housing-land': ('housing_land_2023', ('public/data/housing-land-2023.json',)),
    'monthly-social-population': ('social_population', ('public/data/municipality-social-indicators.json',)),
    'monthly-retail-prices-city': ('retail_prices_city', ('public/data/retail-prices-city-monthly.json',)),
    'monthly-ipss-population': ('ipss_population', ('public/data/municipality-population-projections.json',)),
    'weekly-reinfolib-transactions': ('reinfolib_transactions', ('public/data/realestate-transactions.json',)),
    'weekly-reinfolib-history': (None, tuple('public/data/realestate-history/' + ('index' if n == 0 else f'{n:02}') + '.json'
        for n in range(48))),
    'reinfolib-history-if-new': (None, tuple('public/data/realestate-history/' + ('index' if n == 0 else f'{n:02}') + '.json'
        for n in range(48))),
}
# A source without a published prior snapshot is not eligible for fallback.
def baseline(rel: str) -> bytes | None:
    result = subprocess.run(['git', 'show', f'HEAD:{rel}'], cwd=ROOT, capture_output=True)
    return result.stdout if result.returncode == 0 else None

def restore_status(key: str | None) -> None:
    if key is None:
        return
    path = ROOT / 'src/data/sources.json'
    old = json.loads(baseline('src/data/sources.json') or b'{}').get('sources', {}).get(key)
    if not old or old.get('status') != 'ok':
        raise RuntimeError(f'{key}: no previously verified source snapshot')
    data = json.loads(path.read_text()) if path.exists() else {'schemaVersion': 1, 'sources': {}}
    data.setdefault('sources', {})[key] = old
    tmp = path.with_suffix('.tmp')
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    tmp.replace(path)

def restore_files(paths: tuple[str, ...]) -> None:
    expanded = set()
    for rel in paths:
        if rel.endswith('/'):
            tracked = subprocess.run(['git', 'ls-files', '--', rel], cwd=ROOT,
                                     capture_output=True, text=True, check=True).stdout.splitlines()
            expanded.update(p for p in tracked if p.endswith('.json'))
            expanded.update(p.relative_to(ROOT).as_posix() for p in (ROOT / rel).rglob('*.json'))
        else:
            expanded.add(rel)
    bodies = [(rel, baseline(rel)) for rel in sorted(expanded)]
    if not any(body is not None for _, body in bodies):
        raise RuntimeError('No previously published source file to restore')
    for rel, body in bodies:
        target = ROOT / rel
        if body is None:
            target.unlink(missing_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            tmp = target.with_suffix(target.suffix + '.restore')
            tmp.write_bytes(body)
            tmp.replace(target)

def restore_procurement(prefix: str, backup: Path) -> None:
    if not backup.is_file():
        raise RuntimeError(f'Procurement backup missing: {backup}')
    from collector.collect_jetro import export_json
    with sqlite3.connect(ROOT / 'data/public_it.db') as db:
        db.execute('ATTACH DATABASE ? AS prior', (str(backup),))
        tables = ('procurements', 'source_quality_issues', 'procurement_publications',
                  'company_corporate_numbers')
        pattern = prefix + '*'
        for table in tables:
            columns = [row[1] for row in db.execute(f'PRAGMA table_info({table})')]
            if not columns:
                continue
            names = ','.join('"' + col + '"' for col in columns)
            db.execute(f'DELETE FROM main.{table} WHERE source_id GLOB ?', (pattern,))
            db.execute(f'INSERT INTO main.{table} ({names}) SELECT {names} FROM prior.{table} WHERE source_id GLOB ?', (pattern,))
        # Dimension rows introduced exclusively by the failed source are not published.
        db.execute('DELETE FROM companies WHERE company_id NOT IN (SELECT company_id FROM procurements WHERE company_id IS NOT NULL) AND company_id NOT IN (SELECT company_id FROM prior.companies)')
        db.execute('DELETE FROM organizations WHERE organization_id NOT IN (SELECT organization_id FROM procurements WHERE organization_id IS NOT NULL) AND organization_id NOT IN (SELECT organization_id FROM prior.organizations)')
        db.commit()
        export_json(db)
        db.commit()

def restore_runtime_group(backup: Path, rel_dir: str, pattern: str) -> None:
    before = backup.parent / 'files' / rel_dir
    target = ROOT / rel_dir
    saved = {p.name: p for p in before.glob(pattern)} if before.exists() else {}
    if not saved:
        raise RuntimeError(f'No prior runtime snapshot for {rel_dir}/{pattern}')
    target.mkdir(parents=True, exist_ok=True)
    for current in target.glob(pattern):
        if current.name not in saved:
            current.unlink()
    for name, source in saved.items():
        replacement = target / (name + '.restore')
        shutil.copy2(source, replacement)
        replacement.replace(target / name)


def restore_listed(backup: Path) -> None:
    runtime = backup.parent / 'files/data/raw/listed-companies'
    before = runtime / 'normalized'
    target = ROOT / 'data/raw/listed-companies/normalized'
    if not before.is_dir():
        raise RuntimeError('Previous listed normalized snapshot is missing')
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(before, target)
    index = runtime / 'documents-index.json'
    if not index.is_file():
        raise RuntimeError('Previous listed documents index is missing')
    shutil.copy2(index, ROOT / 'data/raw/listed-companies/documents-index.json')
    restore_files(('public/data/listed-companies/',))


def restore(step: str, backup: Path) -> str:
    if step.startswith('listed-'):
        restore_listed(backup)
        return 'listed_companies'
    if step == 'shokuba-workplace':
        source = backup.parent / 'files/data/raw/shokuba/workplace.sqlite'
        if not source.is_file():
            raise RuntimeError('Previous workplace snapshot is missing')
        shutil.copy2(source, ROOT / 'data/raw/shokuba/workplace.sqlite')
        restore_status('shokuba')
        return 'shokuba'
    if step in ('monthly-gbiz-subsidy', 'monthly-gbiz-patent'):
        kind = 'subsidy' if step.endswith('subsidy') else 'patent'
        prefix = 'Hojokinjoho' if kind == 'subsidy' else 'Tokkyojoho'
        key = f'gbiz_{kind}'
        if json.loads(baseline('src/data/sources.json') or b'{}').get('sources', {}).get(key, {}).get('status') != 'ok':
            raise RuntimeError(f'{key}: no previously verified source snapshot')
        restore_runtime_group(backup, 'data/raw/company-registry/gbiz', prefix + '_UTF-8_*.zip')
        restore_status(key)
        return key
    if step in PROCUREMENT:
        key, prefix = PROCUREMENT[step]
        if json.loads(baseline('src/data/sources.json') or b'{}').get('sources', {}).get(key, {}).get('status') != 'ok':
            raise RuntimeError(f'{key}: no previously verified source snapshot')
        restore_procurement(prefix, backup)
        restore_status(key)
        return key
    if step in FILES:
        key, paths = FILES[step]
        restore_files(paths)
        restore_status(key)
        return key or step
    raise RuntimeError(f'{step}: no isolated rollback recipe; publication remains blocked')

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('step')
    ap.add_argument('--backup', type=Path, required=True)
    args = ap.parse_args()
    print(restore(args.step, args.backup), flush=True)

if __name__ == '__main__':
    main()
