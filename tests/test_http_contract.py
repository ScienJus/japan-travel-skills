"""One offline behavior matrix for independent urllib and HTTPX implementations."""
import contextlib
import gzip
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import subprocess
import socket
import ssl
import unittest
from unittest.mock import patch
import urllib.error

from http_test_support import Response

ROOT = Path(__file__).resolve().parents[1]


def load(skill, filename):
    path = ROOT / 'skills' / skill / 'scripts' / filename
    sys.path.insert(0, str(path.parent))
    spec = importlib.util.spec_from_file_location('contract_' + path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class UrllibAdapter:
    def __init__(self, name, module, url, limit, budget, error, kwargs=None, body=b'page'):
        self.name, self.module, self.url = name, module, url
        self.limit, self.budget, self.error = limit, budget, error
        self.kwargs, self.body = kwargs or {}, body
        self.httpx = False

    def create(self, handler):
        client = self.module.Client(**self.kwargs)
        mocked = patch.object(client.opener, 'open', side_effect=handler)
        return client, mocked

    def read(self, client):
        return client.fetch() if self.name == 'holidays' else client.read(self.url)

    def usage(self, client):
        return client.usage()

    def exhaust(self, client):
        client.requests = self.budget

    def caching(self, client):
        return hasattr(client, 'cache')


def urllib_adapters():
    w = load('japan-weather', 'weather_common.py')
    t = load('japan-transit', 'transit_transport.py')
    o = load('japan-transit', 'rail_operations.py')
    h = load('japan-holidays', 'holidays.py')
    d = load('japan-daylight', 'daylight.py')
    s = load('japan-seasons', 'season_common.py')
    f = load('japan-fuji', 'fuji_source.py')
    j = load('japan-hotels', 'jalan.py')
    p = load('japan-passes', 'pass_source.py')
    a = load('japan-weather', 'jma_alerts.py')
    c = load('japan-weather', 'jma_climate.py')
    csv = '国民の祝日・休日月日,国民の祝日・休日名称\n2026/1/1,元日\n2026/11/23,勤労感謝の日\n'.encode('cp932')
    return [
        UrllibAdapter('forecast', w, 'https://www.jma.go.jp/bosai/forecast/data/forecast/170000.json', w.MAX_BYTES, 30, w.WeatherError),
        UrllibAdapter('transit', t, t.BASE, t.MAX_BYTES, 6, t.TransitError),
        UrllibAdapter('operations', o, o.WEST_DATA, o.MAX_BYTES, 1, o.OperationsError),
        UrllibAdapter('holidays', h, h.SOURCE_URL, h.MAX_BYTES, 1, h.HolidayError, body=csv),
        UrllibAdapter('daylight', d, d.BASE, d.MAX_BYTES, 2, d.DaylightError),
        UrllibAdapter('seasons', s, s.jmc_url('foliage'), 2*1024*1024, 3, s.SourceError),
        UrllibAdapter('fuji', f, f.HOME, f.BODY_LIMIT, 4, f.SourceError),
        UrllibAdapter('hotels', j, j.hotel_url('123456'), j.BODY_LIMIT, 2, j.SourceError),
        UrllibAdapter('passes', p, 'https://example.test/catalog', p.LIMIT, 8, p.Error,
                      kwargs={'allowed': lambda url: url == 'https://example.test/catalog'}),
        UrllibAdapter('alerts', a, a.FEED_URL, a.MAX_BYTES, 2, a.WeatherError),
        UrllibAdapter('climate', c, c.url('select/prefecture00.php'), c.MAX_BYTES, 3, c.WeatherError),
    ]


class HTTPXAdapter:
    def __init__(self, name, module, body):
        self.name, self.module, self.body = name, module, body
        self.httpx = True
        self.limit, self.error = module.MAX_BYTES, module.CliError
        self.url = 'https://tabelog.com/' if name == 'tabelog' else 'https://example.test/'

    def create(self, handler):
        import httpx
        session = httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)
        client = self.module.Client(session=session, delay_min_ms=0, delay_max_ms=0)
        return client, contextlib.nullcontext()

    def read(self, client):
        if self.name == 'tabelog':
            return client.read(self.url, 'json')
        if self.name == 'tablecheck':
            return client.read('GET', '/v2/cuisines')
        return client.read('filters')

    def usage(self, client):
        usage = client.usage()
        return {**usage, 'http_requests': usage['network_requests_started']}

    def exhaust(self, client):
        client.max_requests = 0

    def caching(self, client):
        return True


def httpx_adapters():
    import restaurant_test_support
    from tabelog_client import transport as t
    from tablecheck_client import transport as c
    from pocket_concierge_client import transport as p
    return [HTTPXAdapter('tabelog', t, b'{}'), HTTPXAdapter('tablecheck', c, b'{}'),
            HTTPXAdapter('pocket-concierge', p, b'{"data":{"areas":[]}}')]


class HTTPContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.adapters = urllib_adapters() + httpx_adapters()

    def test_typed_network_reasons_are_safe_and_do_not_add_requests(self):
        import httpx
        cases = [
            (lambda: socket.gaierror(socket.EAI_NONAME, 'private-token'), 'dns'),
            (lambda: ssl.SSLCertVerificationError('private-token'), 'tls'),
            (lambda: TimeoutError('private-token'), 'timeout'),
            (lambda: ConnectionRefusedError('private-token'), 'connection_refused'),
            (lambda: ConnectionResetError('private-token'), 'connection_lost'),
            (lambda: http.client.IncompleteRead(b'part', 10), 'protocol'),
        ]
        for adapter in self.adapters:
            for factory, expected in cases:
                cause = factory()
                if adapter.httpx:
                    failure = httpx.ConnectError('private-token')
                    failure.__cause__ = cause
                else:
                    failure = urllib.error.URLError(cause)
                with self.subTest(client=adapter.name, reason=expected), self.client(adapter, failure=failure) as (client, calls):
                    with self.assertRaises(adapter.error) as caught:
                        adapter.read(client)
                    self.assertEqual(caught.exception.code, 'network_error')
                    self.assertEqual(caught.exception.details['network_reason'], expected)
                    self.assertEqual(caught.exception.details['exception_type'], type(failure).__name__)
                    self.assertNotIn('private-token', json.dumps(caught.exception.details))
                    self.assertEqual(len(calls), 1)
                    self.assertEqual(adapter.usage(client)['http_requests'], 1)
                    self.assertFalse(client.cache if hasattr(client, 'cache') else {})

    def test_unknown_messages_context_and_cycles_are_not_diagnoses(self):
        import httpx
        for adapter in self.adapters:
            for kind in ('message', 'context', 'cycle', 'deep'):
                failure = httpx.ConnectError('certificate verify failed: private-token') if adapter.httpx else urllib.error.URLError('DNS timed out: private-token')
                if kind == 'context':
                    failure.__context__ = TimeoutError('private-token')
                elif kind == 'cycle':
                    failure.__cause__ = failure
                elif kind == 'deep':
                    inner = TimeoutError('private-token')
                    for _ in range(9):
                        outer = OSError('private-token')
                        outer.__cause__ = inner
                        inner = outer
                    failure.__cause__ = inner
                with self.subTest(client=adapter.name, case=kind), self.client(adapter, failure=failure) as (client, calls):
                    with self.assertRaises(adapter.error) as caught:
                        adapter.read(client)
                    self.assertEqual(caught.exception.details['network_reason'], 'unknown')
                    self.assertNotIn('private-token', json.dumps(caught.exception.details))
                    self.assertEqual(len(calls), 1)

    def test_httpx_native_timeout_and_protocol_errors(self):
        import httpx
        for adapter in self.adapters:
            if not adapter.httpx:
                continue
            for failure, expected in [(httpx.ReadTimeout('private-token'), 'timeout'),
                                      (httpx.RemoteProtocolError('private-token'), 'protocol')]:
                with self.subTest(client=adapter.name, reason=expected), self.client(adapter, failure=failure) as (client, calls):
                    with self.assertRaises(adapter.error) as caught:
                        adapter.read(client)
                    self.assertEqual(caught.exception.details['network_reason'], expected)
                    self.assertEqual(len(calls), 1)

    def test_curl_exit_reasons_preserve_stopping_and_hide_stderr(self):
        source = load('japan-passes', 'pass_source.py')
        cases = {5: 'dns', 6: 'dns', 7: 'connection_failed', 28: 'timeout', 35: 'tls', 60: 'tls', 99: 'unknown'}
        for code, expected in cases.items():
            client = source.Client(allowed=lambda _: True)
            completed = subprocess.CompletedProcess([], code, b'000', b'private-token')
            with self.subTest(exit_code=code), patch.object(source.subprocess, 'run', return_value=completed) as run:
                with self.assertRaises(source.Error) as caught:
                    client.read('https://example.test/pass', transport='curl')
                self.assertEqual(caught.exception.code, 'transport_error')
                self.assertEqual(caught.exception.details['exit_code'], code)
                self.assertEqual(caught.exception.details['network_reason'], expected)
                self.assertNotIn('private-token', json.dumps(caught.exception.details))
                with self.assertRaises(source.Error) as stopped:
                    client.read('https://example.test/other', transport='curl')
                self.assertEqual(stopped.exception.code, 'source_stopped')
                self.assertEqual(run.call_count, 1)
                self.assertEqual(client.usage()['http_requests'], 1)

    def test_curl_process_timeout_is_typed_and_stops_the_source(self):
        source = load('japan-passes', 'pass_source.py')
        client = source.Client(allowed=lambda _: True)
        failure = subprocess.TimeoutExpired(['curl', 'private-token'], 25, stderr=b'private-token')
        with patch.object(source.subprocess, 'run', side_effect=failure) as run:
            with self.assertRaises(source.Error) as caught:
                client.read('https://example.test/pass', transport='curl')
            self.assertEqual(caught.exception.code, 'network_error')
            self.assertEqual(caught.exception.details['network_reason'], 'timeout')
            self.assertNotIn('private-token', json.dumps(caught.exception.details))
            with self.assertRaises(source.Error) as stopped:
                client.read('https://example.test/other')
            self.assertEqual(stopped.exception.code, 'source_stopped')
            self.assertEqual(run.call_count, 1)

    @contextlib.contextmanager
    def client(self, adapter, body=None, status=200, headers=None, failure=None):
        calls = []
        def handler(*args, **kwargs):
            calls.append((args, kwargs))
            if failure is not None:
                raise failure
            raw = adapter.body if body is None else body
            if adapter.httpx:
                import httpx
                encoded_headers = [(key.encode('ascii'), value.encode('latin-1'))
                                   for key, value in (headers or {}).items()]
                return httpx.Response(status, content=raw, headers=encoded_headers)
            return Response(raw, status, headers)
        client, patched = adapter.create(handler)
        try:
            with patched, patch.object(adapter.module.time, 'sleep'):
                yield client, calls
        finally:
            if hasattr(client, 'close'):
                client.close()

    def test_success_cache_and_measurements(self):
        for adapter in self.adapters:
            with self.subTest(client=adapter.name), self.client(adapter) as (client, calls):
                adapter.read(client)
                if adapter.caching(client):
                    adapter.read(client)
                    self.assertEqual(len(calls), 1)
                usage = adapter.usage(client)
                self.assertEqual(usage['http_requests'], 1)
                self.assertEqual(usage['response_body_bytes'], len(adapter.body))
                self.assertGreaterEqual(usage['elapsed_ms'], 0)
                if not adapter.httpx:
                    self.assertGreater(calls[0][1]['timeout'], 0)
                    self.assertTrue(any(isinstance(h, adapter.module.RejectRedirect)
                                        for h in client.opener.handlers))
                else:
                    timeout = calls[0][0][0].extensions['timeout']
                    self.assertTrue(all(value is not None and value > 0 for value in timeout.values()))

    def test_exhausted_budget_never_opens_a_connection(self):
        for adapter in self.adapters:
            with self.subTest(client=adapter.name), self.client(adapter) as (client, calls):
                adapter.exhaust(client)
                with self.assertRaises(adapter.error):
                    adapter.read(client)
                self.assertEqual(calls, [])

    def test_connection_timeout_and_protocol_failures_are_structured_without_retry(self):
        import httpx
        for adapter in self.adapters:
            failures = ([httpx.ConnectError('private detail'), httpx.ReadTimeout('private detail'),
                         httpx.RemoteProtocolError('private detail'), OSError('private detail')]
                        if adapter.httpx else [urllib.error.URLError('private detail'), TimeoutError('private detail'),
                                               http.client.BadStatusLine('private detail'),
                                               http.client.IncompleteRead(b'part', 8)])
            for failure in failures:
                with self.subTest(client=adapter.name, failure=type(failure).__name__), self.client(adapter, failure=failure) as (client, calls):
                    with self.assertRaises(adapter.error) as caught:
                        adapter.read(client)
                    self.assertEqual(caught.exception.code, 'network_error')
                    self.assertNotIn('private detail', str(caught.exception))
                    self.assertEqual(len(calls), 1)
                    usage = adapter.usage(client)
                    self.assertEqual(usage['http_requests'], 1)
                    if isinstance(failure, http.client.IncompleteRead):
                        self.assertEqual(usage['response_body_bytes'], 4)
                    self.assertFalse(client.cache if hasattr(client, 'cache') else {})

    def test_denial_retains_http_status_and_retry_after_without_reading_alternate_sources(self):
        for adapter in self.adapters:
            failure = None if adapter.httpx else urllib.error.HTTPError(adapter.url, 429, 'limited', {'Retry-After':'120'}, None)
            with self.subTest(client=adapter.name), self.client(adapter, status=429, headers={'Retry-After':'120'}, failure=failure) as (client, calls):
                with self.assertRaises(adapter.error) as caught:
                    adapter.read(client)
                self.assertEqual(caught.exception.details['http_status'], 429)
                details = caught.exception.details
                self.assertNotIn('network_reason', details)
                self.assertTrue(details.get('retry_after') or details.get('retry_not_before'))
                self.assertEqual(len(calls), 1)

    def test_partial_status_is_not_a_successful_document(self):
        for adapter in self.adapters:
            for status in (204, 206):
                with self.subTest(client=adapter.name, status=status), self.client(adapter, status=status) as (client, calls):
                    with self.assertRaises(adapter.error) as caught:
                        adapter.read(client)
                    self.assertEqual(caught.exception.details['http_status'], status)
                    self.assertEqual(len(calls), 1)
                    self.assertFalse(client.cache if hasattr(client, 'cache') else {})

    def test_body_cap_rejects_and_measures_consumed_bytes(self):
        for adapter in self.adapters:
            body = b'x'*(adapter.limit+1)
            with self.subTest(client=adapter.name), self.client(adapter, body=body) as (client, calls):
                with self.assertRaises(adapter.error):
                    adapter.read(client)
                self.assertEqual(len(calls), 1)
                self.assertEqual(adapter.usage(client)['response_body_bytes'], len(body))
                self.assertFalse(client.cache if hasattr(client, 'cache') else {})

    def test_declared_length_mismatch_never_enters_cache(self):
        for adapter in self.adapters:
            for length in ('nonsense', '²', '9'*5000, str(len(adapter.body)+7)):
                with self.subTest(client=adapter.name, length=length), self.client(adapter, headers={'Content-Length':length}) as (client, calls):
                    with self.assertRaises(adapter.error) as caught:
                        adapter.read(client)
                    self.assertEqual(caught.exception.code, 'incomplete_response')
                    self.assertFalse(client.cache if hasattr(client, 'cache') else {})
                    self.assertEqual(adapter.usage(client)['response_body_bytes'], len(adapter.body))

    def test_valid_length_and_identity_encoding_are_accepted(self):
        for adapter in self.adapters:
            headers = {'Content-Length':'000'+str(len(adapter.body)), 'Content-Encoding':'identity'}
            with self.subTest(client=adapter.name), self.client(adapter, headers=headers) as (client, calls):
                adapter.read(client)
                self.assertEqual(len(calls), 1)

    def test_redirect_policy_revalidates_destinations_or_rejects(self):
        for adapter in self.adapters:
            with self.subTest(client=adapter.name):
                if not adapter.httpx:
                    with self.assertRaises(adapter.error):
                        adapter.module.RejectRedirect().redirect_request(None, None, 302, 'moved', {}, 'https://unconfigured.test/')
                else:
                    with self.client(adapter, status=302, headers={'Location':'https://unconfigured.test/'}) as (client, calls):
                        with self.assertRaises(adapter.error):
                            adapter.read(client)
                        self.assertEqual(len(calls), 1)

    def test_httpx_compressed_length_is_not_compared_to_decoded_length(self):
        for adapter in self.adapters:
            if adapter.httpx:
                raw = gzip.compress(adapter.body)
                with self.subTest(client=adapter.name), self.client(adapter, body=raw,
                        headers={'Content-Encoding':'gzip', 'Content-Length':str(len(raw))}) as (client, calls):
                    adapter.read(client)
                    self.assertEqual(adapter.usage(client)['response_body_bytes'], len(adapter.body))

    def test_httpx_interrupted_stream_keeps_consumed_byte_measurement(self):
        import httpx
        class Interrupted(httpx.SyncByteStream):
            def __iter__(self):
                yield b'part'
                raise httpx.RemoteProtocolError('private protocol detail')
        for adapter in self.adapters:
            if not adapter.httpx:
                continue
            session = httpx.Client(transport=httpx.MockTransport(lambda _: httpx.Response(200, stream=Interrupted())))
            client = adapter.module.Client(session=session, delay_min_ms=0, delay_max_ms=0)
            try:
                with self.subTest(client=adapter.name), self.assertRaises(adapter.error) as caught:
                    adapter.read(client)
                self.assertEqual(caught.exception.code, 'network_error')
                self.assertEqual(adapter.usage(client)['response_body_bytes'], 4)
            finally:
                client.close()

    def test_tabelog_redirects_consume_the_network_budget(self):
        import httpx
        adapter = next(a for a in self.adapters if a.name == 'tabelog')
        calls = []
        def handler(request):
            calls.append(request)
            return httpx.Response(302, headers={'Location':'/another'})
        session = httpx.Client(transport=httpx.MockTransport(handler))
        client = adapter.module.Client(session=session, max_requests=1, delay_min_ms=0, delay_max_ms=0)
        try:
            with self.assertRaises(adapter.error) as caught:
                adapter.read(client)
            self.assertEqual(caught.exception.code, 'request_budget')
            self.assertEqual(len(calls), 1)
            self.assertEqual(adapter.usage(client)['http_requests'], 1)
        finally:
            client.close()

    def test_preselected_curl_preserves_limits_denials_and_host_stop(self):
        adapter = next(a for a in self.adapters if a.name == 'passes')
        module = adapter.module
        cases = [
            (200, b'ok', {'Content-Length':'2'}, 0, None),
            (200, b'ok', {'Content-Length':'9'}, 0, 'incomplete_response'),
            (200, b'ok', {'Content-Length':'9'*5000}, 0, 'incomplete_response'),
            (206, b'ok', {}, 0, 'http_error'),
            (429, b'', {'Retry-After':'120'}, 0, 'http_error'),
            (200, b'x'*(module.LIMIT+1), {}, 0, 'response_too_large'),
            (0, b'part', {}, 28, 'transport_error'),
        ]
        for status, body, headers, exit_code, expected in cases:
            calls = []
            def execute(command, **kwargs):
                calls.append(command)
                Path(command[command.index('--output')+1]).write_bytes(body)
                raw_headers = 'HTTP/1.1 '+str(status)+' Status\r\n'
                raw_headers += ''.join(key+': '+value+'\r\n' for key, value in headers.items())
                Path(command[command.index('--dump-header')+1]).write_text(raw_headers+'\r\n')
                self.assertGreater(kwargs['timeout'], 0)
                self.assertNotIn('--location', command)
                self.assertNotIn('--retry', command)
                return subprocess.CompletedProcess(command, exit_code, str(status).encode(), b'private curl detail')
            client = module.Client(lambda url: url.startswith('https://example.test/'))
            with self.subTest(status=status, expected=expected), patch.object(module.shutil, 'which', return_value='/usr/bin/curl'), \
                    patch.object(module.subprocess, 'run', side_effect=execute), \
                    patch.object(client.opener, 'open', side_effect=AssertionError('No alternate transport')):
                if expected is None:
                    self.assertEqual(client.read(adapter.url, 'curl')[0], body)
                    client.read(adapter.url, 'curl')
                    self.assertEqual(client.usage()['memory_cache_hits'], 1)
                else:
                    with self.assertRaises(module.Error) as caught:
                        client.read(adapter.url, 'curl')
                    self.assertEqual(caught.exception.code, expected)
                    if status == 429:
                        self.assertEqual(caught.exception.details['retry_after'], '120')
                    with self.assertRaises(module.Error) as stopped:
                        client.read('https://example.test/another', 'curl')
                    self.assertEqual(stopped.exception.code, 'source_stopped')
                    self.assertFalse(client.cache)
                self.assertEqual(len(calls), 1)
                self.assertEqual(client.usage()['response_body_bytes'], len(body))


if __name__ == '__main__':
    unittest.main()
