"""Serial anonymous GraphQL reads with bounded bodies and fail-closed denials."""
import http.client
import socket
import ssl
import urllib.error
from copy import deepcopy
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from importlib.metadata import version
import json
import random
import re
import sys
import time

import httpx

from .queries import QUERIES

ENDPOINT = 'https://www.pocket-concierge.jp/graphql'
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


def invalid_constant(_value):
    raise ValueError('Non-finite JSON number')


class Client:
    def __init__(self, timeout=15, max_requests=20, delay_min_ms=1000, delay_max_ms=2500, session=None):
        self.timeout, self.max_requests = timeout, max_requests
        self.delay_min_ms, self.delay_max_ms = delay_min_ms, delay_max_ms
        self.session = session or httpx.Client(timeout=timeout, follow_redirects=False,
                                              limits=httpx.Limits(max_connections=1, max_keepalive_connections=1))
        self.cache, self.trace = {}, []
        self.requests = self.bytes = self.hits = self.wait_ms = self.waits = 0
        self.started, self.finished, self.blocked = time.monotonic(), None, None

    def close(self):
        self.session.close()

    def read(self, operation, variables=None, lang='ja'):
        if operation not in QUERIES or lang not in ('ja', 'en') or variables is not None and not isinstance(variables, dict):
            raise CliError('invalid_argument', 'Only fixed anonymous read queries are supported.')
        if self.blocked:
            raise self.blocked
        body = {'query': QUERIES[operation], 'variables': variables or {}}
        key = json.dumps([lang, body], sort_keys=True, allow_nan=False)
        if key in self.cache:
            self.hits += 1
            return deepcopy(self.cache[key])
        if self.requests >= self.max_requests:
            raise CliError('request_budget', 'Request budget reached; remaining coverage is unknown.')
        if self.finished is not None:
            delay = max(0, self.finished+random.uniform(self.delay_min_ms, self.delay_max_ms)/1000-time.monotonic())
            if delay:
                time.sleep(delay)
                self.wait_ms += delay*1000
                self.waits += 1
        entry = {'url': ENDPOINT, 'method': 'POST', 'operation': operation, 'language': lang,
                 'variables': deepcopy(body['variables']), 'status': 'error'}
        self.trace.append(entry)
        self.requests += 1
        started = time.monotonic()
        headers = {'User-Agent': 'japan-restaurant-skills/0.2.0', 'Accept': 'application/json',
                   'Accept-Language': lang, 'X-Auth-Origin': 'GUEST_ORIGIN'}
        try:
            with self.session.stream('POST', ENDPOINT, json=body, headers=headers,
                                     timeout=self.timeout, follow_redirects=False) as response:
                entry['http_status'] = response.status_code
                retry = response.headers.get('Retry-After')
                if response.status_code in (401, 403, 429, 503) or retry is not None:
                    details = {'http_status': response.status_code, 'next_action': 'Stop and honor the server cooldown; do not switch identities.'}
                    if retry:
                        try:
                            deadline = (datetime.now(timezone.utc)+timedelta(seconds=int(retry)) if retry.isdigit()
                                        else parsedate_to_datetime(retry))
                            if deadline.tzinfo is not None:
                                details['retry_not_before'] = deadline.isoformat()
                        except (ValueError, TypeError, OverflowError, OSError):
                            pass
                    code = 'rate_limited' if response.status_code == 429 else 'access_denied' if response.status_code in (401, 403) else 'retry_later'
                    self.blocked = CliError(code, 'Upstream denied or deferred access; inventory is unknown.', **details)
                    raise self.blocked
                if response.status_code != 200:
                    raise CliError('http_error', f'HTTP {response.status_code}; inventory is unknown.', http_status=response.status_code)
                data = bytearray()
                for chunk in response.iter_bytes():
                    self.bytes += len(chunk)
                    if len(data)+len(chunk) > MAX_BYTES or time.monotonic()-started > self.timeout:
                        raise CliError('response_limit', 'Response exceeded the size or time limit.')
                    data.extend(chunk)
                length = response.headers.get('Content-Length')
                if response.headers.get('Content-Encoding', 'identity').strip().lower() in ('', 'identity') and length is not None and (
                    not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(data))
                ):
                    raise CliError('incomplete_response', 'Body size does not match Content-Length.')
                text = data.decode('utf-8', errors='replace')
                if re.search(r'<title>\s*(?:Just a moment|Attention Required)|cf-challenge|challenge-form', text, re.I):
                    self.blocked = CliError('verification_required', 'Upstream verification required; stop this command.')
                    raise self.blocked
                value = json.loads(text, parse_constant=invalid_constant)
                if not isinstance(value, dict) or value.get('errors') not in (None, []) or not isinstance(value.get('data'), dict):
                    self.blocked = CliError('graphql_error', 'GraphQL returned errors or missing data; stop further queries. No empty inventory inferred.')
                    raise self.blocked
                self.cache[key] = value['data']
                entry['status'] = 'ok'
                return deepcopy(value['data'])
        except (httpx.HTTPError, OSError) as failure:
            error = CliError('network_error', 'HTTP retrieval failed; inventory is unknown.',
                             exception_type=type(failure).__name__, timeout_seconds=self.timeout,
                             network_reason=network_reason(failure, timeout_types=(httpx.TimeoutException,),
                                                           protocol_types=(httpx.ProtocolError, httpx.DecodingError)))
            entry['error'] = error.as_dict()
            raise error from None
        except ValueError as failure:
            error = CliError('unexpected_response', 'Source JSON decoding failed; inventory is unknown.',
                             exception_type=type(failure).__name__)
            entry['error'] = error.as_dict()
            raise error from None
        except CliError as error:
            entry['error'] = error.as_dict()
            raise
        finally:
            self.finished = time.monotonic()
            entry['elapsed_ms'] = round((self.finished-started)*1000)

    def usage(self):
        return {'runtime': {'python': sys.version.split()[0]}, 'elapsed_ms': round((time.monotonic()-self.started)*1000),
                'transport_attempts': self.requests, 'network_requests_started': self.requests,
                'response_body_bytes': self.bytes, 'cache_hits': self.hits, 'browser_launches': 0,
                'throttle_wait_ms': round(self.wait_ms), 'throttle_waits': self.waits, 'metrics_complete': True,
                'dependencies': [{'transport': 'http', 'tool': 'Python HTTPX (pooled Client)', 'versions': [version('httpx')],
                                  'attempts': self.requests, 'successful_reads': sum(t['status'] == 'ok' for t in self.trace)}],
                'limits': {'max_transport_attempts': self.max_requests, 'timeout_seconds_per_transport': self.timeout,
                           'delay_min_ms': self.delay_min_ms, 'delay_max_ms': self.delay_max_ms,
                           'concurrency': 1, 'scope': 'one CLI command; coordinate separate processes explicitly'},
                'measurement_scope': 'Client-observed starts and consumed decoded bodies, not wire bytes. No CPU, memory, model tokens or monetary cost measured.'}
