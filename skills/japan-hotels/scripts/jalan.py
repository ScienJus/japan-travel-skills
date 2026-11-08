"""Bounded anonymous Jalan discovery/profile reader. No reservation endpoints."""
import socket
import ssl
import datetime as dt
import http.client
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse as urlparse
import urllib.request
from html.parser import HTMLParser

HOME = 'https://www.jalan.net'
DIRECTORY = r'/([0-9]{6})/spt_(guide[0-9]{12})/'
FILTERS = {'bath': ('careBath', '内湯・大浴場'), 'station5': ('careStation5', '駅から徒歩5分以内')}
JST = dt.timezone(dt.timedelta(hours=9), 'Asia/Tokyo')
BODY_LIMIT = 4 * 1024 * 1024


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


def now_jst():
    return dt.datetime.now(JST)


def text(value):
    return re.sub(r'\s+', ' ', value).strip()


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def one(values, message):
    values = list(values)
    if len(values) != 1: fail(message)
    return values[0]


def directory_url(value, page=1, filters=()):
    p = urlparse.urlsplit(value)
    if (p.scheme != 'https' or p.netloc != 'www.jalan.net' or p.query or p.fragment
            or not re.fullmatch(DIRECTORY, p.path)):
        raise SourceError('unsupported_url', 'Use a query-free Jalan spt_guide directory URL; resolve its native landmark name first.')
    if not 1 <= page <= 10: raise SourceError('invalid_options', 'Use --page from 1 to 10; one page per invocation.')
    if any(f not in FILTERS for f in filters): raise SourceError('invalid_options', 'Unsupported hotel filter.')
    path = p.path + ('page%d.html' % page if page > 1 else '')
    query = [('dateUndecided', '1')] + [(FILTERS[f][0], '1') for f in sorted(filters)]
    return HOME + path + '?' + urlparse.urlencode(query)


def hotel_url(hotel_id, rooms=False):
    if not re.fullmatch(r'[0-9]{6}', hotel_id): raise SourceError('invalid_options', 'Use the six-digit native Jalan hotel ID.')
    return HOME + '/yad' + hotel_id + ('/room/' if rooms else '/') + '?dateUndecided=1'


def allowed(url):
    p = urlparse.urlsplit(url)
    if p.scheme != 'https' or p.netloc != 'www.jalan.net' or p.fragment: return False
    if re.fullmatch(r'/kankou/spt_guide[0-9]{12}/', p.path): return not p.query
    query = urlparse.parse_qsl(p.query, keep_blank_values=True)
    if p.path in ('/uw/uwp1700/uww1701.do', '/uw/uwp1700/uww1702.do'):
        fields = dict(query)
        if fields.get('reShFlg') == '1':
            required = {'spotId', 'kenCd', 'distCd', 'dateUndecided', 'activeSort', 'genreTypeYad', 'reShFlg',
                        'centerPosX', 'centerPosY', 'zoomLevel', 'resetZoomLevel'}
            paging = p.path.endswith('uww1702.do')
            if paging: required |= {'screenId', 'idx', 'nowPage', 'searchResultYadCount'}
            if len(query) != len(fields) or not required <= set(fields) or set(fields)-required-{'careBath', 'careStation5'}: return False
            try:
                lon, lat = float(fields['centerPosX']), float(fields['centerPosY'])
                zoom = int(fields['zoomLevel'])
            except (ValueError, TypeError, OverflowError): return False
            return (math.isfinite(lat) and math.isfinite(lon) and 20 <= lat <= 46 and 122 <= lon <= 154
                    and bool(re.fullmatch(r'guide[0-9]{12}', fields['spotId']))
                    and bool(re.fullmatch(r'[0-9]{6}', fields['kenCd']))
                    and fields['distCd'] == '10' and fields['dateUndecided'] == '1' and fields['activeSort'] == '10'
                    and fields['genreTypeYad'] == '1' and 11 <= zoom <= 20
                    and fields['zoomLevel'] == str(zoom)
                    and fields['resetZoomLevel'] == fields['zoomLevel']
                    and all(fields.get(k, '1') == '1' for k in ('careBath', 'careStation5'))
                    and (not paging or (fields['screenId'] == 'UWW1701' and fields['idx'] == '0'
                         and fields['nowPage'] in {str(n) for n in range(2, 11)}
                         and bool(re.fullmatch(r'[1-9][0-9]{0,3}', fields['searchResultYadCount']))
                         and int(fields['searchResultYadCount']) <= 9000)))
        required = {'spotId', 'distCd', 'kenCd', 'lrgCd', 'smlCd', 'dateUndecided', 'activeSort'}
        if p.path.endswith('uww1702.do'): required.add('idx')
        if len(query) != len(fields) or not required <= set(fields) or set(fields)-required-{'careBath', 'careStation5'}: return False
        return (bool(re.fullmatch(r'guide[0-9]{12}', fields['spotId']))
                and all(re.fullmatch(r'[0-9]{6}', fields[k]) for k in ('kenCd', 'lrgCd', 'smlCd'))
                and fields['distCd'] == '10' and fields['dateUndecided'] == '1' and fields['activeSort'] == '10'
                and all(fields.get(k, '1') == '1' for k in ('careBath', 'careStation5'))
                and ('idx' not in fields or fields['idx'] == '30'))
    if not query or query[0] != ('dateUndecided', '1') or len(query) != len(set(k for k, v in query)): return False
    if any(v != '1' or k not in ('dateUndecided', 'careBath', 'careStation5') for k, v in query): return False
    if re.fullmatch(DIRECTORY + r'(?:page(?:[2-9]|10)\.html)?', p.path): return True
    return bool(re.fullmatch(r'/yad[0-9]{6}/(?:room/)?', p.path)) and len(query) == 1


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('unexpected_redirect', 'Redirect rejected; no retry, alternate client or session was used.', http_status=code)


class Client:
    def __init__(self, request_limit=2):
        if request_limit not in (2, 4): raise ValueError('Unsupported hotel request budget.')
        self.request_limit = request_limit
        self.started = time.monotonic()
        self.requests = self.response_bytes = self.pacing_ms = 0
        self.last = None
        self.last_source = None
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url):
        if not allowed(url): raise SourceError('unsupported_url', 'Only configured public Jalan discovery/profile routes are allowed.')
        if self.requests >= self.request_limit: raise SourceError('request_budget_exhausted', 'Hotel anonymous-read budget exhausted.', limit=self.request_limit)
        delay = max(0, 1.5 - (time.monotonic() - self.last)) if self.last is not None else 0
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay * 1000)
        self.last = time.monotonic()
        self.requests += 1
        self.last_source = {'url': url, 'retrieved_at': None, 'publisher': 'じゃらんnet'}
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'japan-travel-skills (anonymous hotel reader)', 'Accept': 'text/html'})
            with self.opener.open(req, timeout=15) as response:
                if response.status != 200:
                    raise SourceError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(BODY_LIMIT + 1)
                self.response_bytes += len(raw)
                if len(raw) > BODY_LIMIT:
                    raise SourceError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise SourceError("incomplete_response", "Body size does not match Content-Length.")
                modified = response.headers.get('Last-Modified')
        except urllib.error.HTTPError as error:
            details = {'http_status': error.code}
            if error.headers and error.headers.get('Retry-After'): details['retry_after'] = error.headers['Retry-After']
            raise SourceError('http_error', 'Source request failed; no retry was attempted.', **details) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as error:
            if isinstance(error, http.client.IncompleteRead):
                self.response_bytes += len(error.partial)
            raise SourceError('network_error', 'Source could not be read; no retry was attempted.', exception_type=type(error).__name__, network_reason=network_reason(error)) from None
        self.last_source = {'url': url, 'retrieved_at': now_jst().isoformat(), 'publisher_updated_at': None,
                            'http_last_modified_raw': modified, 'publisher': 'じゃらんnet', 'processed': True}
        return raw, self.last_source

    def usage(self):
        return {'http_requests': self.requests, 'response_body_bytes': self.response_bytes,
                'pacing_ms': self.pacing_ms, 'elapsed_ms': round((time.monotonic() - self.started) * 1000),
                'scope': 'This invocation; body bytes exclude HTTP/TLS overhead. No token or monetary estimate.'}


class Node:
    def __init__(self, tag='', attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def nodes(self, tag=None, cls=None):
        for child in self.children:
            if isinstance(child, Node):
                if (tag is None or child.tag == tag) and (cls is None or cls in child.attrs.get('class', '').split()): yield child
                yield from child.nodes(tag, cls)

    def text(self):
        if self.tag in ('script', 'style'): return ''
        return ' '.join(c.text() if isinstance(c, Node) else c for c in self.children)


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        try: self.html = raw.decode('cp932')
        except UnicodeError: fail('Jalan page is not valid Windows-31J.')
        self.root = Node()
        self.stack = [self.root]
        self.feed(self.html)
        self.close()
        if not any('じゃらん' in n.text() for n in self.root.nodes('title')): fail('Jalan page identity is missing (possibly a challenge page).')

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs)
        self.stack[-1].children.append(n)
        if tag not in ('area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'): self.stack.append(n)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, value):
        self.stack[-1].children.append(value)


def class_text(node, cls):
    values = list(node.nodes(cls=cls))
    if not values: return None
    return text(one(values, 'Duplicate hotel field: ' + cls).text()) or None


def opening_notice(name, intro, today):
    value = norm(name + ' ' + (intro or ''))
    dates = []
    for m in re.finditer(r'(20[0-9]{2})年([0-9]{1,2})月([0-9]{1,2})日(?:新規)?(?:開業|オープン|OPEN)', value, re.I):
        try: dates.append(dt.date(*map(int, m.groups())))
        except ValueError: fail('Invalid explicit opening date.')
    future = [d for d in dates if d > today]
    return {'state': 'planned_opening' if future else 'unknown', 'opening_date': min(future).isoformat() if future else None,
            'evidence_ja': text(name + ' ' + (intro or '')) if future else None}


def walking_review(access, filters):
    # Keep evidence tied to native clauses. No inferred station, route or distance conversion.
    clauses = re.split(r'[。；;\n]', unicodedata.normalize('NFKC', access or ''))
    claims, distances = [], []
    for clause in clauses:
        for m in re.finditer(r'徒歩(?:で)?(?:約)?([0-9]+)(?:[~〜～-]([0-9]+))?分', clause):
            claims.append({'minutes_min': int(m[1]), 'minutes_max': int(m[2] or m[1]), 'evidence_ja': clause.strip()})
        for m in re.finditer(r'徒歩(?:距離)?(?:で)?(?:約)?([0-9]+(?:\.[0-9]+)?)(?:[~〜～-]([0-9]+(?:\.[0-9]+)?))?(km|m|キロメートル|メートル)', clause, re.I):
            factor = 1000 if m[3].lower() in ('km', 'キロメートル') else 1
            distances.append({'metres_min': float(m[1])*factor, 'metres_max': float(m[2] or m[1])*factor,
                              'evidence_ja': clause.strip(), 'kind': 'publisher_walking_claim'})
    conflict = 'station5' in filters and any(c['minutes_max'] > 5 and '駅' in c['evidence_ja'] for c in claims)
    return {'claims': claims, 'distance_claims': distances, 'station5_assessment': 'potential_conflict' if conflict else ('needs_access_review' if 'station5' in filters else 'not_requested'),
            'note': 'Publisher claims only. A station5 filter can refer to another station; verify the requested station/exit and route.'}


def parse_search(raw, directory, expected, page_number, filters, today):
    p = Page(raw)
    match = re.fullmatch(DIRECTORY, urlparse.urlsplit(directory).path)
    if not match: raise SourceError('invalid_options', 'Invalid directory.')
    headings = [text(n.text()) for n in p.root.nodes('h1')]
    heading = one(headings, 'Missing/duplicate directory heading.')
    if page_number > 1:
        m = re.search(r'\(([0-9]+)/([0-9]+)\)$', heading)
        if not m or int(m[1]) != page_number or int(m[2]) < page_number: fail('Directory heading page mismatch.')
        heading = heading[:m.start()]
    suffix = '周辺のホテル・旅館・宿泊施設'
    if not heading.endswith(suffix): fail('Unsupported directory heading.')
    landmark = heading[:-len(suffix)]
    if norm(landmark) != norm(expected): raise SourceError('location_mismatch', 'Directory is for a different native landmark.', expected=expected, actual=landmark)
    form = one((n for n in p.root.nodes('form') if n.attrs.get('id') == 'jalan_form'), 'Missing/duplicate native search form.')
    for key, wanted in [('spotId', match[2]), ('displayKencd', match[1])]:
        actual = {n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name') == key}
        if actual != {wanted}: fail('Directory route/form identity mismatch.')
    for key, (field, label) in FILTERS.items():
        inputs = list(n for n in form.nodes('input') if n.attrs.get('name') == field)
        if len(inputs) != 1 or ('checked' in inputs[0].attrs) != (key in filters): fail('Publisher did not preserve requested filters.')
    pages = re.findall(r'"currentPage"\s*:\s*"([0-9]+)"', p.html)
    if pages != [str(page_number)]: fail('Publisher page number does not match request.')
    total_raw = class_text(p.root, 'jlnpc-listInformation--count')
    if total_raw is None or not re.fullmatch(r'[0-9,]+', total_raw): fail('Missing source result count.')
    total = int(total_raw.replace(',', ''))
    cards, ids = [], set()
    for n in p.root.nodes('a', 'jlnpc-yadoCassette__link'):
        href = urlparse.urlsplit(urlparse.urljoin(HOME, n.attrs.get('href', '')))
        m = re.fullmatch(r'/yad([0-9]{6})/', href.path)
        if href.scheme != 'https' or href.netloc != 'www.jalan.net' or not m or m[1] in ids: fail('Invalid/duplicate main hotel identity.')
        ids.add(m[1])
        name = text(one(n.nodes('h2'), 'Missing/duplicate main hotel name.').text())
        if not name: fail('Empty hotel name.')
        intro = class_text(n, 'p-searchResultItem__description')
        access = class_text(n, 'p-searchResultItem__accessValue')
        cards.append({'hotel_id': m[1], 'name_ja': name, 'url': hotel_url(m[1]), 'introduction_ja': intro,
                      'access_ja': access, 'walking_review': walking_review(access, filters),
                      'operating_status': opening_notice(name, intro, today)})
    if len(cards) > 30 or (total > 0 and not cards) or total < len(cards) or (total == 0 and page_number != 1) or (cards and (page_number - 1) * 30 + len(cards) > total): fail('Result count/main-card contract changed; empty coverage is unknown.')
    return {'landmark_ja': landmark, 'directory_url': directory, 'source_total': total,
            'source_total_scope': 'landmark_directory', 'candidate_source': 'jalan_landmark_directory', 'page': page_number,
            'page_size': 30, 'source_cards_on_page': len(cards), 'selected_filters': [FILTERS[k][1] for k in sorted(filters)],
            'hotels': cards, 'has_next_page': page_number * 30 < total,
            'coverage': 'One publisher page only; source directory scope is not a walking radius or exhaustive hotel inventory.'}


def profile_page(raw, hotel_id, expected=None, rooms=False):
    p = Page(raw)
    ids = {n.attrs.get('value') for n in p.root.nodes('input') if n.attrs.get('name') == 'yadNo'}
    if ids != {hotel_id}: fail('Hotel profile native ID mismatch.')
    heading = text(one(p.root.nodes('h1', 'jlnpc-yado__subTitle'), 'Missing/duplicate hotel heading.').text())
    suffix = 'の部屋' if rooms else 'の施設概要'
    if not heading.endswith(suffix): fail('Unsupported hotel profile heading.')
    name = heading[:-len(suffix)]
    if not name: fail('Empty hotel profile name.')
    if expected and norm(name) != norm(expected): raise SourceError('hotel_mismatch', 'Hotel name does not match requested property.', expected=expected, actual=name)
    return p, name


def direct_cells(row):
    return [c for c in row.children if isinstance(c, Node) and c.tag in ('th', 'td')]


def fields_from_table(table):
    result = []
    for row in table.nodes('tr'):
        cells = direct_cells(row)
        if len(cells) == 2 and cells[0].tag == 'th' and cells[1].tag == 'td':
            result.append({'label_ja': text(cells[0].text()), 'value_ja': text(cells[1].text()) or None})
    return result


def parse_detail(raw, hotel_id, expected, today):
    p, name = profile_page(raw, hotel_id, expected)
    sections = []
    for cls, label in [('jlnpc-shisetsu-accessparking-table', 'アクセス・パーキング'),
                       ('shisetsu-roomsetsubi_body', '部屋・部屋施設'), ('shisetsu-bath_body', '温泉・風呂'),
                       ('shisetsu-amenityservice_body', 'アメニティ・施設・サービス'),
                       ('shisetsu-amenityspec_body', 'アメニティ一覧')]:
        roots = [p.root]
        if cls == 'shisetsu-amenityspec_body':
            roots = list(p.root.nodes(cls='shisetsu-amenityspec_body_wrap'))
            if len(roots) > 1: fail('Duplicate hotel amenity section container.')
        tables = [table for root in roots for table in root.nodes('table', cls)]
        if len(tables) > 1: fail('Duplicate hotel profile section.')
        sections.append({'section_ja': label, 'state': 'published' if tables else 'unknown',
                         'fields': fields_from_table(tables[0]) if tables else [],
                         'source_rows': [[{'kind': c.tag, 'label_ja': text(c.text()),
                                          'colspan': c.attrs.get('colspan', '1'), 'rowspan': c.attrs.get('rowspan', '1')}
                                          for c in direct_cells(row)] for row in tables[0].nodes('tr')] if tables else []})
    if not any(s['fields'] for s in sections): fail('No supported hotel profile fields.')
    intro = class_text(p.root, 'facility-overview-text')
    room_links = [n.attrs.get('href', '') for n in p.root.nodes('a')
                  if urlparse.urlsplit(urlparse.urljoin(HOME, n.attrs.get('href', ''))).path == '/yad' + hotel_id + '/room/'
                  and urlparse.urlsplit(urlparse.urljoin(HOME, n.attrs.get('href', ''))).netloc == 'www.jalan.net']
    return {'hotel_id': hotel_id, 'name_ja': name, 'introduction_ja': intro, 'sections': sections,
            'operating_status': opening_notice(name, intro, today), 'rooms_link_published': bool(room_links),
            'rooms': {'state': 'not_requested', 'room_types': []}}


def parse_rooms(raw, hotel_id, expected):
    p, name = profile_page(raw, hotel_id, expected, rooms=True)
    candidates = []
    for table in p.root.nodes('table'):
        rows = list(table.nodes('tr'))
        if rows and [norm(c.text()) for c in direct_cells(rows[0])][:3] == ['部屋タイプ', '室数', '広さ']: candidates.append(rows)
    if not candidates: return {'state': 'unknown', 'room_types': [], 'note': 'No supported room-type table; photo captions were not guessed into room records.'}
    rows = one(candidates, 'Duplicate room-type tables.')
    header = [norm(c.text()) for c in direct_cells(rows[0])]
    if len(header) != 4 or header[3] != '通常料金(消費税込み)': fail('Room table columns changed.')
    rooms = []
    for row in rows[1:]:
        cells = direct_cells(row)
        if len(cells) != 4: fail('Room row columns changed.')
        values = [text(c.text()) for c in cells]
        area = unicodedata.normalize('NFKC', values[2])
        m = re.fullmatch(r'([0-9]+(?:\.[0-9]+)?)(?:[~〜～-]([0-9]+(?:\.[0-9]+)?))?m2', area)
        rooms.append({'name_ja': values[0], 'published_room_count_ja': values[1], 'size_ja': values[2],
                      'area_m2_min': float(m[1]) if m else None, 'area_m2_max': float(m[2] or m[1]) if m else None})
    if not rooms: fail('Empty room table.')
    notes = []
    for row in p.root.nodes('tr'):
        cells = direct_cells(row)
        if len(cells) == 3 and norm(cells[0].text()) in ('部屋タイプ補足事項', 'インターネット接続', 'こだわり', '部屋設備補足事項', 'その他'):
            notes.append({'label_ja': text(cells[0].text()), 'value_ja': text(cells[2].text())})
    return {'state': 'published', 'name_ja': name, 'room_types': rooms, 'notes': notes,
            'scope': 'Static room-type table, not inventory or a complete room catalog. Profile summaries and room-page records can differ; retain both.'}
