"""Small shared HTTP/HTML helpers for independently attributed seasonal sources."""
import socket
import ssl
import datetime as dt
import http.client
import json
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

JST = dt.timezone(dt.timedelta(hours=9), 'Asia/Tokyo')
WN = 'https://weathernews.jp/'
JMC = 'https://n-kishou.com/corp/news-contents/'
KINDS = {'foliage': 'koyo', 'sakura': 'sakura'}


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


class SourceError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def fail(message):
    raise SourceError('source_schema_changed', message)


def norm(value):
    return re.sub(r'\s+', ' ', unicodedata.normalize('NFKC', value)).strip()


def unique(rows, message):
    if len(rows) != 1: fail(message)
    return rows[0]


def unique_json(pairs):
    value = {}
    for key, child in pairs:
        if key in value: fail('Duplicate JSON field.')
        value[key] = child
    return value


def loads(value):
    return json.loads(value, object_pairs_hook=unique_json,
                      parse_constant=lambda value: fail('Non-finite source JSON.'))


def now_jst():
    return dt.datetime.now(JST)


def month_day(raw, year):
    match = re.fullmatch(r'(\d{1,2})[月/](\d{1,2})日?', norm(raw))
    if not match: fail('Unsupported month/day date.')
    return dt.date(year, int(match[1]), int(match[2]))


def wn_url(season, kind='', value=''):
    base = WN + KINDS[season] + '/'
    return base + (kind + '/' + value + '/' if kind else '')


def jmc_url(season):
    return JMC + ('autumn/' if season == 'foliage' else 'sakura/')


def allowed(address):
    p = urllib.parse.urlsplit(address)
    if p.query or p.fragment or p.scheme != 'https': return False
    if p.netloc == 'n-kishou.com':
        return p.path in ('/corp/news-contents/autumn/', '/corp/news-contents/sakura/')
    return p.netloc == 'weathernews.jp' and bool(re.fullmatch(r'/(?:koyo|sakura)/(?:|area/[a-z-]{2,25}/|spot/[1-9]\d{0,7}/)', p.path))


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('unexpected_redirect', 'Redirect rejected; no alternate client or session was used.', http_status=code)


class Client:
    def __init__(self):
        self.started = time.monotonic()
        self.requests = self.response_bytes = self.cache_hits = self.pacing_ms = 0
        self.cache, self.last, self.counts = {}, {}, {}
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, address):
        if not allowed(address): raise SourceError('unsupported_url', 'Only configured public seasonal-source routes are allowed.')
        if address in self.cache:
            self.cache_hits += 1
            return self.cache[address]
        host = urllib.parse.urlsplit(address).hostname
        limit = 2 if host == 'weathernews.jp' else 1
        if self.requests >= 3 or self.counts.get(host, 0) >= limit:
            raise SourceError('request_budget_exhausted', 'Stopped at three total reads, at most two Weathernews and one JMC read.')
        delay = max(0, 1 - (time.monotonic() - self.last[host])) if host in self.last else 0
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay * 1000)
        self.last[host] = time.monotonic()
        self.requests += 1
        self.counts[host] = self.counts.get(host, 0) + 1
        try:
            req = urllib.request.Request(address, headers={'User-Agent': 'japan-travel-skills (anonymous seasonal reader)', 'Accept': 'text/html'})
            with self.opener.open(req, timeout=15) as response:
                if response.status != 200:
                    raise SourceError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(2 * 1024 * 1024 + 1)
                self.response_bytes += len(raw)
                if len(raw) > 2 * 1024 * 1024:
                    raise SourceError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise SourceError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as error:
            extra = {'http_status': error.code}
            if error.headers and error.headers.get('Retry-After'): extra['retry_after'] = error.headers['Retry-After']
            raise SourceError('http_error', 'Source request failed; no retry was attempted.', **extra) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as error:
            if isinstance(error, http.client.IncompleteRead):
                self.response_bytes += len(error.partial)
            raise SourceError('network_error', 'Source could not be read; no retry was attempted.', exception_type=type(error).__name__, network_reason=network_reason(error)) from None
        self.cache[address] = raw, now_jst()
        return self.cache[address]

    def usage(self):
        return dict(http_requests=self.requests, response_body_bytes=self.response_bytes, memory_cache_hits=self.cache_hits,
                    pacing_ms=self.pacing_ms, elapsed_ms=round((time.monotonic()-self.started)*1000),
                    scope='This invocation; body bytes exclude HTTP/TLS overhead. No token or monetary estimate.')


class Node:
    def __init__(self, tag='', attrs=None):
        self.tag, self.attrs, self.children = tag, dict(attrs or []), []

    def text(self, scripts=False):
        if self.tag in ('script', 'style') and not scripts: return ''
        return ''.join(x.text(scripts) if isinstance(x, Node) else x for x in self.children)

    def nodes(self, tag=None, cls=None):
        for child in self.children:
            if not isinstance(child, Node): continue
            if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()): yield child
            yield from child.nodes(tag, cls)


class Page(HTMLParser):
    VOID = {'area','base','br','col','embed','hr','img','input','link','meta','param','source','track','wbr'}
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.root, self.stack = Node(), []
        self.stack = [self.root]
        try: self.feed(raw.decode('utf-8')); self.close()
        except UnicodeError: fail('Seasonal page was not UTF-8.')

    def handle_starttag(self, tag, attrs):
        if len(self.stack) >= 150: fail('Excessive HTML nesting.')
        child = Node(tag, attrs)
        self.stack[-1].children.append(child)
        if tag not in self.VOID: self.stack.append(child)

    def handle_endtag(self, tag):
        for i in range(len(self.stack)-1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data): self.stack[-1].children.append(data)
    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in self.VOID: self.handle_endtag(tag)

    def title(self): return norm(unique(list(self.root.nodes('title')), 'Expected one page title.').text())

    def canonical(self, expected):
        urls = [n.attrs.get('content') for n in self.root.nodes('meta') if n.attrs.get('property') == 'og:url']
        if urls != [expected]: fail('Canonical seasonal page URL does not match the requested identity.')


class Nuxt:
    """Read only selected primitive fields; never execute JS or follow references as URLs."""
    def __init__(self, page):
        script = unique([n for n in page.root.nodes('script') if n.attrs.get('id') == '__NUXT_DATA__'], 'Expected one Nuxt data product.')
        self.data = loads(script.text(scripts=True))
        if not isinstance(self.data, list) or len(self.data) > 50000: fail('Unexpected Nuxt data array.')

    def objects(self, keys):
        return [row for row in self.data if isinstance(row, dict) and set(keys) <= row.keys()]

    def value(self, row, key):
        index = row[key]
        if type(index) is not int or not 0 <= index < len(self.data): fail('Unsupported Nuxt reference.')
        value = self.data[index]
        if not isinstance(value, (str, int, float, bool, type(None))) or isinstance(value, (dict,list)):
            fail('Expected a primitive seasonal field.')
        return value


def error_record(provider, error):
    if isinstance(error, SourceError):
        problem = {'code':error.code,'message':str(error),**error.details}
    else:
        problem = {'code':'source_schema_changed','message':'Unexpected seasonal source structure; no result was guessed.'}
    return {'provider':provider, 'status':'error','state':'unknown','error':problem}
