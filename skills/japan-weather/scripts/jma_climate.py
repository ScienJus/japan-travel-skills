"""Live JMA monthly station normals, separate from forecasts and warnings."""
import datetime as dt
import http.client
import json
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

from weather_common import JST, MAX_BYTES, WeatherError, network_reason

BASE = 'https://www.data.jma.go.jp/stats/etrn/'
PATHS = {'select/prefecture00.php', 'select/prefecture.php', 'view/nml_sfc_ym.php'}
# Header paths, rather than column offsets, bind values to quantities/units.
FIELDS = {
    'mean_temperature_c': ('気温/平均(℃)', 'Monthly mean temperature', 'degC'),
    'mean_daily_high_c': ('気温/日最高(℃)', 'Monthly mean of daily maximum temperature', 'degC'),
    'mean_daily_low_c': ('気温/日最低(℃)', 'Monthly mean of daily minimum temperature', 'degC'),
    'precipitation_total_mm': ('降水量/合計(mm)', 'Normal monthly precipitation total', 'mm'),
    'sunshine_total_hours': ('日照時間/合計(時)', 'Normal monthly sunshine duration', 'hours'),
    'snowfall_total_cm': ('雪/降雪の深さ/合計(cm)', 'Normal monthly total snowfall depth', 'cm'),
    'maximum_snow_depth_cm': ('雪/最深積雪(cm)', 'Normal of monthly maximum snow depth', 'cm'),
    'snow_days': ('大気現象/雪日数', 'Normal monthly number of snow days', 'days'),
}
WARNINGS = [
    'Climate normals are historical station statistics, not forecasts for any trip date or year.',
    'Daily high/low fields are monthly averages, not extremes or a guaranteed temperature range.',
    'Precipitation is a monthly total, not rain probability or the number of rainy days.',
    'Station statistics do not describe a whole municipality, mountain, trail or foliage timing.',
    'Missing/no-phenomenon markers remain null; reference/incomplete values retain their flags.',
]


def changed(message):
    raise WeatherError('source_schema_changed', message)


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def url(path, prec='', block=''):
    return BASE + path + '?' + urllib.parse.urlencode(dict(prec_no=prec, block_no=block, year='', month='', day='', view=''))


def allowed_url(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'https' or parsed.netloc != 'www.data.jma.go.jp' or parsed.fragment:
        return False
    path = parsed.path.removeprefix('/stats/etrn/')
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if path not in PATHS or set(params) != {'prec_no', 'block_no', 'year', 'month', 'day', 'view'}:
        return False
    if any(len(v) != 1 for v in params.values()) or any(params[k] != [''] for k in ('year', 'month', 'day', 'view')):
        return False
    prec, block = params['prec_no'][0], params['block_no'][0]
    if path == 'select/prefecture00.php':
        return prec == block == ''
    if not re.fullmatch(r'\d{2}', prec) or prec == '99':
        return False
    return block == '' if path == 'select/prefecture.php' else bool(re.fullmatch(r'\d{5}', block))


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WeatherError('unexpected_redirect', 'Climate redirect rejected; no alternate client or route was used.', http_status=code)


class Client:
    def __init__(self):
        self.started = time.monotonic()
        self.last_started = None
        self.requests = self.response_bytes = self.cache_hits = self.pacing_ms = 0
        self.cache = {}
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, address):
        if not allowed_url(address):
            raise WeatherError('unsupported_url', 'Only configured anonymous JMA climate routes are supported.')
        if address in self.cache:
            self.cache_hits += 1
            return self.cache[address]
        if self.requests >= 3:
            raise WeatherError('request_budget_exhausted', 'Stopped at three climate reads per invocation.')
        delay = max(0, 1 - (time.monotonic() - self.last_started)) if self.last_started is not None else 0
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay * 1000)
        self.last_started = time.monotonic()
        self.requests += 1
        try:
            request = urllib.request.Request(address, headers={'User-Agent': 'japan-travel-skills (anonymous climate reader)', 'Accept': 'text/html'})
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise WeatherError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes += len(raw)
                if len(raw) > MAX_BYTES:
                    raise WeatherError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise WeatherError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as error:
            details = {'http_status': error.code}
            if error.headers and error.headers.get('Retry-After'):
                details['retry_after'] = error.headers['Retry-After']
            raise WeatherError('http_error', 'JMA climate request failed; no retry was attempted.', **details) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError) as error:
            if isinstance(error, http.client.IncompleteRead):
                self.response_bytes += len(error.partial)
            raise WeatherError('network_error', 'Could not read JMA climate data; no retry was attempted.', exception_type=type(error).__name__, network_reason=network_reason(error)) from None
        self.cache[address] = raw
        return raw

    def usage(self):
        return dict(http_requests=self.requests, response_body_bytes=self.response_bytes, memory_cache_hits=self.cache_hits,
                    pacing_ms=self.pacing_ms, elapsed_ms=round((time.monotonic() - self.started) * 1000),
                    scope='This invocation; body bytes exclude HTTP/TLS overhead. No token or monetary estimate.')


class Page(HTMLParser):
    def __init__(self, raw):
        super().__init__(convert_charrefs=True)
        self.areas, self.images, self.links, self.headings, self.rows = [], [], [], [], []
        self.map_name = None
        self.heading = self.row = self.cell = None
        self.in_table = False
        self.table_count = 0
        try:
            self.feed(raw.decode('utf-8'))
            self.close()
        except UnicodeError:
            changed('Climate page was not UTF-8.')
        if self.in_table or self.cell is not None or self.row is not None:
            changed('Climate table was truncated.')

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'map': self.map_name = attrs.get('name')
        if tag == 'area' and self.map_name == 'point': self.areas.append(attrs)
        if tag == 'img': self.images.append(attrs)
        if tag == 'a': self.links.append(attrs.get('href', ''))
        if tag == 'h3': self.heading = []
        if tag == 'table' and attrs.get('id') == 'tablefix1':
            self.table_count += 1
            if self.in_table: changed('Nested climate table.')
            self.in_table = True
        elif tag == 'table' and self.in_table:
            changed('Nested climate table.')
        if self.in_table and tag == 'tr':
            if self.row is not None: changed('Unclosed climate table row.')
            self.row = []
        if self.in_table and tag in ('th', 'td'):
            if self.cell is not None or self.row is None: changed('Invalid climate cell structure.')
            self.cell = []
            self.spans = int(attrs.get('rowspan', 1)), int(attrs.get('colspan', 1))
            if any(not 1 <= n <= 40 for n in self.spans): changed('Unsupported climate cell span.')

    def handle_data(self, data):
        if self.cell is not None: self.cell.append(data)
        if self.heading is not None: self.heading.append(data)

    def handle_endtag(self, tag):
        if tag == 'map': self.map_name = None
        if tag == 'h3' and self.heading is not None:
            self.headings.append(''.join(self.heading))
            self.heading = None
        if self.in_table and tag in ('th', 'td') and self.cell is not None:
            self.row.append((''.join(self.cell).strip(), *self.spans))
            self.cell = None
        if self.in_table and tag == 'tr' and self.row is not None:
            if self.cell is not None: changed('Unclosed climate cell.')
            self.rows.append(self.row)
            self.row = None
        if tag == 'table' and self.in_table:
            if self.row is not None: changed('Unclosed climate row.')
            self.in_table = False


def link_params(href, base, expected_path):
    parsed = urllib.parse.urlsplit(urllib.parse.urljoin(base, href))
    if parsed.scheme != 'https' or parsed.netloc != 'www.data.jma.go.jp' or parsed.path != expected_path or parsed.fragment:
        changed('Unexpected climate discovery link.')
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
    if set(params) != {'prec_no', 'block_no', 'year', 'month', 'day', 'view'} or any(len(v) != 1 for v in params.values()):
        changed('Unexpected climate discovery parameters.')
    if any(params[k] != [''] for k in ('year', 'month', 'day', 'view')):
        changed('Climate discovery no longer describes an undated menu.')
    return params['prec_no'][0], params['block_no'][0]


def regions(raw):
    rows = {}
    for area in Page(raw).areas:
        prec, block = link_params(area.get('href', ''), url('select/prefecture00.php'), '/stats/etrn/select/prefecture.php')
        if not re.fullmatch(r'\d{2}', prec) or block or not area.get('alt'): changed('Invalid JMA climate region identity.')
        if prec == '99': continue  # Antarctica is outside Japan travel coverage.
        row = {'prec_no': prec, 'name_ja': area['alt']}
        if prec in rows and rows[prec] != row: changed('Conflicting climate region identity.')
        rows[prec] = row
    if not rows: changed('No climate regions found; the HTML shell is not a catalog.')
    return list(rows.values())


def select(query, rows, key):
    matches = [row for row in rows if norm(query) == norm(row[key])]
    if len(matches) != 1:
        raise WeatherError('unknown_or_ambiguous_climate_location', 'Use an exact native name from the live climate catalog; no nearby station was selected.', query=query, candidates=rows)
    return matches[0]


def stations(raw, region):
    page = Page(raw)
    expected_alt = '地点選択用' + region['name_ja'] + '地図'
    if sum(image.get('alt') == expected_alt for image in page.images) != 1:
        changed('Climate station map does not match the requested region.')
    rows = {}
    for area in page.areas:
        # Neighbouring-region and all-station links are not station records.
        callback = area.get('onmouseover', '')
        if not callback.startswith('javascript:viewPoint('): continue
        prec, block = link_params(area.get('href', ''), url('select/prefecture.php', region['prec_no']), '/stats/etrn/index.php')
        if prec != region['prec_no']: changed('Climate station belongs to another region.')
        match = re.match(r"javascript:viewPoint\('([as])','(\d{4,5})','([^']+)'[,]", callback)
        if not match or match[2] != block or match[3] != area.get('alt'): changed('Climate station name/code contract changed.')
        if match[1] != 's': continue  # AMeDAS has a different table contract.
        if not re.fullmatch(r'\d{5}', block): changed('Invalid surface climate station identity.')
        row = {**region, 'station_name_ja': area['alt'], 'block_no': block, 'station_kind': 'surface'}
        if block in rows and rows[block] != row: changed('Conflicting climate station identity.')
        rows[block] = row
    if not rows: changed('No supported surface stations found; no AMeDAS substitute was chosen.')
    return list(rows.values())


def grid(rows):
    cells = {}
    if len(rows) > 40: changed('Climate table has too many rows.')
    for r, row in enumerate(rows):
        c = 0
        for value, height, width in row:
            while (r, c) in cells: c += 1
            if c + width > 40 or r + height > len(rows): changed('Invalid climate table dimensions.')
            for rr in range(r, r + height):
                for cc in range(c, c + width):
                    if (rr, cc) in cells: changed('Overlapping climate cells.')
                    cells[rr, cc] = value
            c += width
    width = max((c for r, c in cells), default=-1) + 1
    if not width or len(cells) != len(rows) * width: changed('Incomplete climate table grid.')
    return [[cells[r, c] for c in range(width)] for r in range(len(rows))]


def numeric(raw):
    cleaned = norm(raw)
    missing = {'': 'missing', '///': 'missing_or_not_observed', '×': 'missing', '#': 'questionable',
               '--': 'no_phenomenon', '---': 'no_phenomenon'}
    if cleaned in missing: return {'value': None, 'quality': missing[cleaned], 'raw': raw}
    match = re.fullmatch(r'(-?\d+(?:\.\d+)?)([@)\]])?', cleaned)
    if not match: changed('Unsupported climate numeric value or quality marker.')
    quality = {None: 'normal', '@': 'reference', ')': 'quasi_normal', ']': 'insufficient'}[match[2]]
    value = float(match[1])
    if not math.isfinite(value): changed('Non-finite climate value.')
    return {'value': value, 'quality': quality, 'raw': raw}


def monthly(raw, station, months):
    page = Page(raw)
    expected = '{}({})平年値(年・月ごとの値)主な要素'.format(station['station_name_ja'], station['name_ja'])
    if [norm(h) for h in page.headings] != [norm(expected)]: changed('Monthly climate page station/region/product identity mismatch.')
    identity = (station['prec_no'], station['block_no'])
    if not any(link_params(href, url('view/nml_sfc_ym.php', *identity), '/stats/etrn/index.php') == identity
               for href in page.links if urllib.parse.urlsplit(urllib.parse.urljoin(BASE+'view/', href)).path == '/stats/etrn/index.php'):
        changed('Climate page lacks the requested native station-code link.')
    if page.table_count != 1: changed('Expected exactly one climate data table.')
    table = grid(page.rows)
    if len(table) != 18 or any(norm(row[0]) != '要素' for row in table[:3]): changed('Unexpected monthly climate table layout.')
    headers = ['/'.join(dict.fromkeys(norm(table[r][c]) for r in range(3))) for c in range(len(table[0]))]
    columns = {}
    for key, (path, label, unit) in FIELDS.items():
        matches = [i for i, h in enumerate(headers) if h == norm(path)]
        if len(matches) != 1: changed('Missing or duplicated climate quantity/unit header: ' + key)
        columns[key] = matches[0]
    expected_rows = ['統計期間', '資料年数'] + [str(n)+'月' for n in range(1,13)] + ['年']
    if [norm(row[0]) for row in table[3:]] != expected_rows: changed('Monthly climate rows are missing, duplicated or reordered.')
    metadata = {}
    for key, c in columns.items():
        period = norm(table[3][c])
        years = norm(table[4][c])
        match = re.fullmatch(r'(\d{4})[~〜～](\d{4})', period)
        if period == '///' and years == '0':
            metadata[key] = dict(statistical_period=None, sample_years=0)
            continue
        if not match or not re.fullmatch(r'\d{1,2}', years): changed('Invalid climate statistical period/sample years.')
        start, end, count = int(match[1]), int(match[2]), int(years)
        if not 1800 <= start <= end <= dt.datetime.now(JST).year or not 1 <= count <= end-start+1 <= 30:
            changed('Inconsistent climate statistical period/sample years.')
        metadata[key] = dict(statistical_period={'from_year':start, 'to_year':end}, sample_years=count)
    result = []
    for month in months:
        metrics = {key: {**numeric(table[month+4][c]), **metadata[key]} for key,c in columns.items()}
        if any(v['value'] is not None and v['value'] < 0 for key,v in metrics.items()
               if key not in ('mean_temperature_c', 'mean_daily_high_c', 'mean_daily_low_c')):
            changed('Negative climate quantity outside temperature fields.')
        if any(v['value'] is not None and not v['sample_years'] for v in metrics.values()): changed('Climate value has no statistical samples.')
        available = [v for v in metrics.values() if v['value'] is not None]
        status = 'ok' if len(available) == len(metrics) and all(v['quality'] == 'normal' for v in available) else 'partial' if available else 'unavailable'
        result.append({'month': month, 'status': status, 'metrics': metrics})
    return result


def add_parsers(sub):
    sub.add_parser('climate-regions', help='Live JMA climate region names/codes')
    stations_parser = sub.add_parser('climate-stations', help='Live surface-station catalog for one exact JMA climate region')
    stations_parser.add_argument('--prefecture', required=True, help='Exact native JMA region name, e.g. 石川県; use climate-regions')
    query_parser = sub.add_parser('climate', help='Live monthly station climate normals, never a trip-date forecast')
    query_parser.add_argument('--prefecture', required=True, help='Exact native JMA region name')
    query_parser.add_argument('--station', required=True, help='Exact native surface-station name; use climate-stations')
    query_parser.add_argument('--month', type=int, choices=range(1,13), action='append', help='Repeat for up to 12 months; default all months')
    query_parser.add_argument('--prec-no', help='Previously discovered two-digit region code; requires --block-no')
    query_parser.add_argument('--block-no', help='Previously discovered five-digit surface-station code; requires --prec-no')


def main(args):
    client = Client()
    try:
        if args.command == 'climate':
            if args.month and len(args.month) > 12: raise WeatherError('invalid_options', 'Supply at most twelve --month values.')
            if bool(args.prec_no) != bool(args.block_no): raise WeatherError('invalid_options', '--prec-no and --block-no must be supplied together.')
            if args.prec_no and not allowed_url(url('view/nml_sfc_ym.php', args.prec_no, args.block_no)):
                raise WeatherError('invalid_options', 'Use a two-digit Japanese region and five-digit surface-station code from climate-stations.')
        for name in ('prefecture', 'station'):
            text = getattr(args,name,None)
            if text is not None and (not text.strip() or len(text)>100 or any(ord(c)<32 for c in text)):
                raise WeatherError('invalid_options', 'Use a nonempty native climate name of at most 100 printable characters.')
        sources = []
        if args.command == 'climate' and args.prec_no:
            station = dict(prec_no=args.prec_no, block_no=args.block_no, name_ja=args.prefecture,
                           station_name_ja=args.station, station_kind='surface')
        else:
            address = url('select/prefecture00.php')
            rows = regions(client.read(address))
            sources.append(address)
            if args.command == 'climate-regions':
                result = {'status':'ok', 'regions':rows}
            else:
                region = select(args.prefecture, rows, 'name_ja')
                address = url('select/prefecture.php',region['prec_no'])
                rows = stations(client.read(address),region)
                sources.append(address)
                if args.command == 'climate-stations':
                    result = {'status':'ok','stations':rows,'coverage':'Live surface-station discovery only; AMeDAS tables are not integrated. No climate value was queried.'}
                else:
                    station = select(args.station,rows,'station_name_ja')
        if args.command == 'climate':
            months = sorted(set(args.month or range(1,13)))
            address = url('view/nml_sfc_ym.php',station['prec_no'],station['block_no'])
            values = monthly(client.read(address),station,months)
            sources.append(address)
            status = 'ok' if all(v['status']=='ok' for v in values) else 'unavailable' if all(v['status']=='unavailable' for v in values) else 'partial'
            result = {'status':status, 'kind':'climate_normals', 'station':station,'requested_months':months,'months':values,
                      'metric_definitions':{key:{'label':label,'unit':unit,'source_header_ja':path} for key,(path,label,unit) in FIELDS.items()}, 'warnings':WARNINGS}
        result['source'] = {'publisher':'気象庁', 'urls':sources,'retrieved_at':dt.datetime.now(JST).isoformat(), 'issued_at':None,
                            'note':'Normalized from JMA HTML by japan-travel-skills. Live retrieval time is not publication time. Statistical periods/sample years are retained per metric.'}
        result['usage'] = client.usage()
        print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
        return 0
    except WeatherError as error:
        problem = {'code':error.code,'message':str(error),**error.details}
    except (KeyError, TypeError, ValueError, IndexError, AttributeError, OverflowError, RecursionError):
        problem = {'code':'source_schema_changed','message':'Unexpected JMA climate structure; no climate values were guessed.'}
    print(json.dumps({'status':'error','climate_state':'unknown','error':problem,'manual_check_url':BASE+'index.php','usage':client.usage()},ensure_ascii=False,separators=(',',':')))
    return 2
