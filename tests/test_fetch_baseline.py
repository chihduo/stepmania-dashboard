from contextlib import contextmanager
from http.client import IncompleteRead, RemoteDisconnected
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import call, patch
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ci import fetch_baseline as baseline

URL = 'https://example.github.io/dashboard/banners/abc123.png'


def http_error(code, retry_after=None):
    headers = {} if retry_after is None else {'Retry-After': retry_after}
    return HTTPError(URL, code, 'temporary or permanent test error', headers, io.BytesIO())


class BaselineFetchTests(unittest.TestCase):
    def setUp(self):
        self.open = self.enterContext(patch.object(baseline.urllib.request, 'urlopen'))
        self.sleep = self.enterContext(patch.object(baseline.time, 'sleep'))
        self.log = self.enterContext(patch.object(baseline.sys, 'stderr', new_callable=io.StringIO))

    def test_503_recovers_without_losing_banner_bytes(self):
        self.open.side_effect = [http_error(503), http_error(503), io.BytesIO(b'complete banner')]
        self.assertEqual(baseline.fetch(URL, 64), b'complete banner')
        self.assertEqual(self.sleep.call_args_list, [call(1), call(2)])
        self.assertIn(URL, self.log.getvalue())
        self.assertIn('attempt 3/5', self.log.getvalue())

    def test_temporary_http_statuses_retry(self):
        for code in (408, 429, 500, 502, 503, 504):
            with self.subTest(code=code):
                self.open.side_effect = [http_error(code), io.BytesIO(b'ok')]
                self.assertEqual(baseline.fetch(URL, 2), b'ok')

    def test_permanent_http_errors_fail_immediately(self):
        for code in (400, 401, 403, 404):
            with self.subTest(code=code):
                self.open.reset_mock();self.sleep.reset_mock()
                self.open.side_effect = http_error(code)
                with self.assertRaises(HTTPError): baseline.fetch(URL, 64)
                self.assertEqual(self.open.call_count, 1)
                self.sleep.assert_not_called()

    def test_network_interruptions_retry(self):
        for error in (URLError('temporary DNS failure'), TimeoutError('timed out'),
                      ConnectionResetError('reset'), RemoteDisconnected('closed')):
            with self.subTest(error=type(error).__name__):
                self.open.side_effect = [error, io.BytesIO(b'ok')]
                self.assertEqual(baseline.fetch(URL, 64), b'ok')

    def test_interrupted_response_read_restarts_complete_download(self):
        @contextmanager
        def broken_response():
            class Response:
                def read(self, _limit): raise IncompleteRead(b'partial', 10)
            yield Response()
        self.open.side_effect = [broken_response(), io.BytesIO(b'complete')]
        self.assertEqual(baseline.fetch(URL, 64), b'complete')

    def test_retry_exhaustion_is_bounded_and_names_the_asset(self):
        self.open.side_effect = http_error(503)
        with self.assertRaisesRegex(RuntimeError, 'banners/abc123.png after 5 attempts'):
            baseline.fetch(URL, 64)
        self.assertEqual(self.open.call_count, 5)
        self.assertEqual(self.sleep.call_args_list, [call(1), call(2), call(4), call(8)])

    def test_retry_after_seconds_and_cap(self):
        for header, expected in [('7', 7), ('999', 30), ('-10', 1), ('invalid', 1)]:
            with self.subTest(header=header):
                self.sleep.reset_mock()
                self.open.side_effect = [http_error(503, header), io.BytesIO(b'ok')]
                self.assertEqual(baseline.fetch(URL, 64), b'ok')
                self.sleep.assert_called_once_with(expected)

    def test_retry_after_http_date(self):
        self.open.side_effect = [http_error(503, 'Thu, 01 Jan 1970 00:00:20 GMT'), io.BytesIO(b'ok')]
        with patch.object(baseline.time, 'time', return_value=10):
            self.assertEqual(baseline.fetch(URL, 64), b'ok')
        self.sleep.assert_called_once_with(10)

    def test_oversized_response_is_not_retried(self):
        self.open.return_value = io.BytesIO(b'too long')
        with self.assertRaisesRegex(ValueError, 'exceeds the supported size'):
            baseline.fetch(URL, 3)
        self.assertEqual(self.open.call_count, 1)
        self.sleep.assert_not_called()

    def test_failed_banner_keeps_baseline_step_failed_without_partial_file(self):
        data = json.dumps({'songs': [{'dir': 'Songs/Test/Example/', 'banner': 'banners/abc123.png'}]}).encode()
        self.open.side_effect = [io.BytesIO(data)] + [http_error(503) for _ in range(5)]
        with tempfile.TemporaryDirectory() as temp:
            previous = Path.cwd()
            try:
                os.chdir(temp)
                with patch.dict(os.environ, {'PAGES_URL': 'https://example.github.io/dashboard', 'UPLOAD_PROFILE': '0123456789abcdef'}):
                    with self.assertRaisesRegex(RuntimeError, 'after 5 attempts'):
                        baseline.main()
                self.assertEqual(Path('baseline/data.json').read_bytes(), data)
                self.assertFalse(Path('baseline/banners/abc123.png').exists())
            finally:
                os.chdir(previous)


if __name__ == '__main__':
    unittest.main()
