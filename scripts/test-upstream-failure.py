#!/usr/bin/env python3
"""Log-only upstream failure behavior and source safety regression tests."""
import importlib.util
import json
from datetime import datetime
from pathlib import Path
import tempfile
import unittest
from zoneinfo import ZoneInfo

spec = importlib.util.spec_from_file_location('failure', Path(__file__).with_name('log-upstream-failure.py'))
failure = importlib.util.module_from_spec(spec)
spec.loader.exec_module(failure)


class UpstreamFailureTests(unittest.TestCase):
    def test_record_and_append_only(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'logs' / 'upstream-collection-failures.jsonl'
            now = datetime(2026, 10, 11, 19, 0, tzinfo=ZoneInfo('Asia/Tokyo'))
            for source in ('jetro', 'jetro_local', 'sendai_procurement'):
                failure.record(source, path, now=now)
            lines = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertEqual([item['source'] for item in lines], sorted(failure.SOURCES))
            self.assertEqual(len(lines), 3)
            self.assertTrue(all(item['event'] == 'upstream-probe-failed' for item in lines))

    def test_unexpected_source_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'failures.jsonl'
            with self.assertRaises(ValueError):
                failure.record('geps_awards', path)
            self.assertFalse(path.exists())


if __name__ == '__main__':
    unittest.main()
