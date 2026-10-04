#!/usr/bin/env python3
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from threading import Thread
from functools import partial
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('verification', Path(__file__).with_name('verify-production.py'))
verification = importlib.util.module_from_spec(spec); spec.loader.exec_module(verification)


class Tests(unittest.TestCase):
    def fixture(self, root):
        paths = verification.REQUIRED + ('data/company-details/00.json', 'data/listed-companies/details/00.json',
                                         'data/company-registry/details/00.json')
        for rel in paths:
            path = root / rel; path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('<urlset/>' if rel.endswith('.xml') else '{"date":"new","records":100}')
        expected = verification.write_manifest(root)
        def request(base, rel, release):
            if rel.startswith('/'):
                return b'<html><h1>DATLUME</h1></html>'
            return (root / rel).read_bytes()
        return expected, request

    def test_exact_release_passes_and_writes_report(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); expected, request = self.fixture(root)
            report = root / 'report.json'
            with patch.object(verification, 'request', side_effect=request):
                result = verification.verify(expected, 'https://test.invalid', attempts=1, report=report)
            self.assertTrue(result['ok']); self.assertTrue(json.loads(report.read_text())['ok'])

    def test_http_200_old_release_old_json_broken_xml_and_wrong_page_are_failures(self):
        for failure in ('manifest', 'json', 'xml', 'page'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root = Path(directory); expected, good = self.fixture(root)
                def request(base, rel, release):
                    if (failure == 'manifest' and rel == verification.MANIFEST):
                        return json.dumps({**expected, 'releaseId': 'old'}).encode()
                    if failure == 'json' and rel == 'data/wikipedia-topics.json':
                        return b'{"date":"old","records":100}'
                    if failure == 'xml' and rel == 'sitemap.xml':
                        return b'<broken'
                    if failure == 'page' and rel == '/topics/':
                        return b'<html>Maintenance</html>'
                    return good(base, rel, release)
                with patch.object(verification, 'request', side_effect=request), self.assertRaises(RuntimeError):
                    verification.verify(expected, 'https://test.invalid', attempts=1)

    def test_real_http_200_stale_json_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); expected, _ = self.fixture(root)
            for route in verification.PAGES:
                page = root/route.strip('/')/'index.html'; page.parent.mkdir(parents=True, exist_ok=True)
                page.write_text('<html><h1>DATLUME</h1></html>')
            class Handler(SimpleHTTPRequestHandler):
                def log_message(self, *args):
                    pass
            server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Handler, directory=str(root)))
            thread = Thread(target=server.serve_forever, daemon=True); thread.start()
            base = f'http://127.0.0.1:{server.server_port}'
            try:
                self.assertTrue(verification.verify(expected, base, attempts=1)['ok'])
                (root/'data/wikipedia-topics.json').write_text('{"date":"old","records":100}')
                with self.assertRaises(RuntimeError):
                    verification.verify(expected, base, attempts=1)
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)

    def test_cache_propagation_retries_then_succeeds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory); expected, good = self.fixture(root)
            first = True
            def request(base, rel, release):
                nonlocal first
                if rel == verification.MANIFEST and first:
                    first = False
                    return json.dumps({**expected, 'releaseId': 'old'}).encode()
                return good(base, rel, release)
            with patch.object(verification, 'request', side_effect=request):
                self.assertEqual(verification.verify(expected, 'https://test.invalid', attempts=2, delay=0)['attempt'], 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
