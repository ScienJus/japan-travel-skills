"""Bounded, serial anonymous reads of explicitly allowed consumer endpoints."""
import http.client
import socket
import ssl
import urllib.error
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from importlib.metadata import version
import json
import random
import re
import sys
import time

import httpx

MAX_BYTES = 8 * 1024 * 1024


def network_reason(error, *, timeout_types=(), protocol_types=()):
    """Classify typed evidence only; never inspect exception messages or implicit context."""
    seen = set()
    for _ in range(8):
        if not isinstance(error, BaseException) or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, (TimeoutError,) + timeout_types):
            return "timeout"
        if isinstance(error, socket.gaierror):
            return "dns"
        if isinstance(error, ssl.SSLError):
            return "tls"
        if isinstance(error, ConnectionRefusedError):
            return "connection_refused"
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return "connection_lost"
        if isinstance(error, (http.client.HTTPException,) + protocol_types):
            return "protocol"
        reason = error.reason if isinstance(error, urllib.error.URLError) else None
        error = reason if isinstance(reason, BaseException) else error.__cause__
    return "unknown"


class CliError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details

    def as_dict(self):
        return {'code': self.code, 'message': str(self), **self.details}


def stamp():
    return datetime.now(timezone.utc).isoformat().replace('+00:00', 'Z')


def sanitize(value):
    if isinstance(value, dict):
        return {key: '[REDACTED]' if re.search(r'token|secret|api.?key|password|cookie|authorization', key, re.I)
                else sanitize(item) for key, item in value.items()}
    if isinstance(value, list):
        return [sanitize(item) for item in value]
    if isinstance(value, str):
        def redact_tag(match):
            tag = match[0]
            if re.search(r'''\b(?:name|id)\s*=\s*(["'])(?:csrf[-_]?token|authenticity_token|access_token|refresh_token)\1''', tag, re.I):
                return re.sub(r'''(\b(?:value|content)\s*=\s*)(["'])(.*?)\2''', lambda m: m[1]+m[2]+'[REDACTED]'+m[2], tag, flags=re.I|re.S)
            return tag
        value = re.sub(r'<(?:meta|input)\b[^>]*>', redact_tag, value, flags=re.I)
        return re.sub(r'AIza[0-9A-Za-z_-]{35}', '[REDACTED]', value)
    return value


class Client:
    def __init__(self, timeout=15, max_requests=20, delay_min_ms=1000, delay_max_ms=2500, session=None):
        self.timeout, self.max_requests = timeout, max_requests
        self.delay_min_ms, self.delay_max_ms = delay_min_ms, delay_max_ms
        self.session = session or httpx.Client(timeout=timeout, follow_redirects=False,
                                              limits=httpx.Limits(max_connections=1, max_keepalive_connections=1))
        self.trace, self.cache = [], {}
        self.requests, self.bytes, self.hits, self.wait_ms, self.waits = 0, 0, 0, 0, 0
        self.started, self.finished, self.blocked = time.monotonic(), None, None

    def close(self):
        self.session.close()

    def read(self, method, path, params=None, body=None):
        api = method == 'GET' and re.fullmatch(r'/v2/(?:shops/[a-z0-9][a-z0-9-]{0,80}|cuisines|shop_search|autocomplete)', path)
        api = api or method == 'POST' and path in ('/v2/hub/menu_items', '/v2/hub/availability_calendar_v2')
        page = method == 'GET' and re.fullmatch(r'/en/shops/[a-z0-9][a-z0-9-]{0,80}/(?:reserve|available(?:/timetable)?)', path)
        if not (api or page) or method == 'GET' and body is not None:
            raise CliError('invalid_argument', 'Only supported anonymous read endpoints are allowed.')
        url = ('https://production.tablecheck.com' if api else 'https://www.tablecheck.com') + path
        key = json.dumps([method, url, params, body], sort_keys=True, allow_nan=False)
        if self.blocked:
            raise self.blocked
        if key in self.cache:
            self.hits += 1
            return self.cache[key]
        if self.requests >= self.max_requests:
            raise CliError('request_budget', 'Request budget reached; remaining coverage is unknown.')
        if self.finished is not None:
            wait = max(0, self.finished + random.uniform(self.delay_min_ms, self.delay_max_ms)/1000 - time.monotonic())
            if wait:
                time.sleep(wait)
                self.wait_ms += wait*1000
                self.waits += 1
        entry = {'url': url, 'method': method, 'parameters': sanitize(params or body or {}), 'status': 'error'}
        self.trace.append(entry)
        self.requests += 1
        started = time.monotonic()
        headers = {'User-Agent': 'japan-restaurant-skills/0.2.0', 'Accept': 'application/json' if api or '/available' in path else 'text/html',
                   'Accept-Language': 'en,ja;q=0.9'}
        try:
            with self.session.stream(method, url, params=params, json=body, headers=headers,
                                     timeout=self.timeout, follow_redirects=False) as response:
                entry['http_status'] = response.status_code
                if response.status_code in (401, 403, 429, 503) or response.headers.get('Retry-After'):
                    details = {'http_status': response.status_code, 'next_action': 'Stop; honor the server cooldown. Do not switch identities.'}
                    retry = response.headers.get('Retry-After')
                    if retry:
                        try:
                            deadline = (datetime.fromtimestamp(time.time()+int(retry), timezone.utc) if retry.isdigit()
                                        else parsedate_to_datetime(retry))
                            details['retry_not_before'] = deadline.isoformat()
                        except (ValueError, TypeError, OverflowError, OSError):
                            pass
                    code = 'rate_limited' if response.status_code == 429 else 'access_denied' if response.status_code in (401, 403) else 'retry_later'
                    self.blocked = CliError(code, 'Upstream denied or deferred access; data is unknown.', **details)
                    raise self.blocked
                if response.status_code != 200:
                    raise CliError('http_error', f'HTTP {response.status_code}; data is unknown.', http_status=response.status_code)
                data = bytearray()
                for part in response.iter_bytes():
                    self.bytes += len(part)
                    if len(data) + len(part) > MAX_BYTES or time.monotonic()-started > self.timeout:
                        raise CliError('response_limit', 'Response exceeded the size or time limit.')
                    data.extend(part)
                length = response.headers.get('Content-Length')
                if response.headers.get('Content-Encoding', 'identity').strip().lower() in ('', 'identity') and length is not None and (
                    not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(data))
                ):
                    raise CliError('incomplete_response', 'Body size does not match Content-Length.')
                text = data.decode('utf-8', errors='replace')
                if re.search(r'<title>\s*(?:Just a moment|Attention Required)|cf-challenge|challenge-form', text, re.I):
                    self.blocked = CliError('verification_required', 'Upstream verification required; stop this command.')
                    raise self.blocked
                try:
                    def reject_constant(_value):
                        raise ValueError('Non-finite JSON number')
                    value = json.loads(text, parse_constant=reject_constant) if api or '/available' in path else text
                except ValueError:
                    raise CliError('unexpected_response', 'Expected JSON; upstream response was not recognized.') from None
                self.cache[key] = value
                entry.update(status='ok', observed_at=stamp())
                return value
        except CliError as error:
            entry['error'] = error.as_dict()
            raise
        except (httpx.HTTPError, OSError) as failure:
            error = CliError('network_error', 'HTTP retrieval failed; data is unknown.',
                             exception_type=type(failure).__name__, timeout_seconds=self.timeout,
                             network_reason=network_reason(failure, timeout_types=(httpx.TimeoutException,),
                                                           protocol_types=(httpx.ProtocolError, httpx.DecodingError)))
            entry['error'] = error.as_dict()
            raise error from None
        finally:
            self.finished = time.monotonic()
            entry['elapsed_ms'] = round((self.finished-started)*1000)

    def usage(self):
        return {'runtime': {'python': sys.version.split()[0]}, 'elapsed_ms': round((time.monotonic()-self.started)*1000),
                'transport_attempts': self.requests, 'network_requests_started': self.requests, 'response_body_bytes': self.bytes,
                'cache_hits': self.hits, 'browser_launches': 0, 'throttle_wait_ms': round(self.wait_ms), 'throttle_waits': self.waits,
                'metrics_complete': True, 'dependencies': [{'transport': 'http', 'tool': 'Python HTTPX (pooled Client)',
                    'versions': [version('httpx')], 'attempts': self.requests, 'successful_reads': sum(x['status']=='ok' for x in self.trace)}],
                'limits': {'max_transport_attempts': self.max_requests, 'timeout_seconds_per_transport': self.timeout,
                    'delay_min_ms': self.delay_min_ms, 'delay_max_ms': self.delay_max_ms, 'concurrency': 1,
                    'scope': 'one CLI command; coordinate separate processes explicitly'},
                'measurement_scope': 'Client-observed starts and decoded body bytes, not wire traffic. No CPU, memory, tokens or monetary cost measured.'}
