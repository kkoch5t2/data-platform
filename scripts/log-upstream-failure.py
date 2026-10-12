#!/usr/bin/env python3
"""Record an upstream probe failure independently of daily publication success."""
import argparse
from datetime import datetime
import json
import re
from pathlib import Path
from zoneinfo import ZoneInfo

def record(source: str, path: Path, now=None, event='upstream-probe-failed'):
    if not re.fullmatch(r'[a-z][a-z0-9_-]{0,79}', source):
        raise ValueError(f'Invalid source identifier: {source}')
    if event not in ('upstream-probe-failed', 'source-fallback', 'source-fallback-unavailable'):
        raise ValueError(f'Invalid failure event: {event}')
    when = now or datetime.now(ZoneInfo('Asia/Tokyo'))
    if when.tzinfo is None:
        raise ValueError('timezone required')
    entry = {'at': when.isoformat(), 'job': 'daily', 'event': event,
             'source': source, 'action': ('publication-blocked' if event == 'source-fallback-unavailable'
                                        else 'kept-last-verified-snapshot')}
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as stream:
        stream.write(json.dumps(entry, ensure_ascii=False) + '\n')
    return entry


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', required=True)
    parser.add_argument('--event', default='upstream-probe-failed', choices=('upstream-probe-failed', 'source-fallback', 'source-fallback-unavailable'))
    parser.add_argument('--log', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(record(args.source, args.log, event=args.event), ensure_ascii=False))


if __name__ == '__main__':
    main()
