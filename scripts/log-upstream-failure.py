#!/usr/bin/env python3
"""Record an upstream probe failure independently of daily publication success."""
import argparse
from datetime import datetime
import json
from pathlib import Path
from zoneinfo import ZoneInfo

SOURCES = {'jetro', 'jetro_local', 'sendai_procurement'}


def record(source: str, path: Path, now=None):
    if source not in SOURCES:
        raise ValueError(f'Unsupported upstream source: {source}')
    when = now or datetime.now(ZoneInfo('Asia/Tokyo'))
    if when.tzinfo is None:
        raise ValueError('timezone required')
    entry = {'at': when.isoformat(), 'job': 'daily', 'event': 'upstream-probe-failed',
             'source': source, 'action': 'kept-last-verified-snapshot'}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True, choices=sorted(SOURCES))
    parser.add_argument('--log', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(record(args.source, args.log), ensure_ascii=False))


if __name__ == '__main__':
    main()
