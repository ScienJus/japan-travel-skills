"""Read AMECS's public Fuji-view panel and its page-owned CSVs, without JS execution."""
import socket
import ssl
import csv
import datetime as dt
import http.client
import io
import math
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

JST = dt.timezone(dt.timedelta(hours=9), 'Asia/Tokyo')
HOME = 'https://www.fuji-san.info/'
DATA = {side: HOME+'data/fdata_'+code+'.csv' for side,code in [('north','N'),('south','S')]}
LABELS = {'north':'北からの眺め','south':'南からの眺め'}
PUBLISHER = '株式会社応用気象エンジニアリング'
MAX_AGE_HOURS = 36
BODY_LIMIT = 128 * 1024


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


def norm(value):
    return re.sub(r'\s+', '', unicodedata.normalize('NFKC', value))


def allowed(url):
    if url in (HOME,*DATA.values()): return True
    p = urllib.parse.urlsplit(url)
    return (p.scheme == 'https' and p.netloc == 'www.fuji-san.info' and p.path == '/lib/t24.js'
            and not p.fragment and bool(re.fullmatch(r'\d{12}',p.query)))


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise SourceError('unexpected_redirect','Source redirect rejected; no alternate client was used.',http_status=code)


class Client:
    def __init__(self):
        self.started = time.monotonic()
        self.requests = self.bytes = self.cache_hits = self.pacing_ms = 0
        self.cache, self.last = {}, None
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self,url):
        if not allowed(url): raise SourceError('unsupported_url','Only configured public AMECS Fuji routes are allowed.')
        if url in self.cache:
            self.cache_hits += 1
            return self.cache[url]
        if self.requests >= 4: raise SourceError('request_budget_exhausted','Stopped at four anonymous reads.')
        delay = max(0,1-(time.monotonic()-self.last)) if self.last is not None else 0
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay*1000)
        self.last = time.monotonic()
        self.requests += 1
        try:
            request = urllib.request.Request(url,headers={'User-Agent':'japan-travel-skills (anonymous Fuji reader)',
                                                         'Accept':'text/html,text/plain,text/csv,application/javascript',
                                                         'Cache-Control':'no-cache'})
            with self.opener.open(request,timeout=15) as response:
                if response.status != 200:
                    raise SourceError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(BODY_LIMIT+1)
                self.bytes += len(raw)
                if len(raw) > BODY_LIMIT:
                    raise SourceError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise SourceError("incomplete_response", "Body size does not match Content-Length.")
                modified = response.headers.get('Last-Modified')
        except urllib.error.HTTPError as error:
            details = {'http_status':error.code}
            if error.headers and error.headers.get('Retry-After'): details['retry_after'] = error.headers['Retry-After']
            raise SourceError('http_error','Source request failed; no retry was attempted.',**details) from None
        except (urllib.error.URLError,http.client.HTTPException,OSError,TimeoutError) as error:
            if isinstance(error, http.client.IncompleteRead):
                self.bytes += len(error.partial)
            raise SourceError('network_error','Source could not be read; no retry was attempted.',exception_type=type(error).__name__, network_reason=network_reason(error)) from None
        value = raw,{'url':url,'retrieved_at':now_jst().isoformat(),'http_last_modified_raw':modified}
        self.cache[url] = value
        return value

    def usage(self):
        return {'http_requests':self.requests,'response_body_bytes':self.bytes,'memory_cache_hits':self.cache_hits,
                'pacing_ms':self.pacing_ms,'elapsed_ms':round((time.monotonic()-self.started)*1000),
                'scope':'This invocation; body bytes exclude HTTP/TLS overhead. No token or monetary estimate.'}


class Panel(HTMLParser):
    """Only the original page's forecast table, title and script references."""
    def __init__(self,raw):
        super().__init__(convert_charrefs=True)
        self.title, self.scripts, self.rows = '', [], []
        self.in_title = self.in_table = False
        self.cell, self.tables = None, 0
        try: self.feed(raw.decode('utf-8-sig')); self.close()
        except UnicodeError: fail('Fuji source page is not UTF-8.')

    def handle_starttag(self,tag,attrs):
        attrs = dict(attrs)
        if tag == 'title': self.in_title = True
        if tag == 'script' and attrs.get('src'): self.scripts.append(attrs['src'])
        if tag == 'table' and 'table01' in attrs.get('class','').split():
            self.in_table = True
            self.tables += 1
        if self.in_table and tag == 'tr': self.rows.append([])
        if self.in_table and tag == 'td':
            if not self.rows: fail('Fuji table cell has no row.')
            self.cell = {'attrs':attrs,'text':''}
            self.rows[-1].append(self.cell)

    def handle_data(self,data):
        if self.in_title: self.title += data
        if self.cell is not None: self.cell['text'] += data

    def handle_endtag(self,tag):
        if tag == 'title': self.in_title = False
        if tag == 'td': self.cell = None
        if tag == 'table': self.in_table = False


def panel_contract(raw):
    p = Panel(raw)
    if norm(p.title) != '富士見予報' or p.tables != 1 or [len(r) for r in p.rows] != [8,14,15,14,15,14]:
        fail('Fuji page identity or seven-day forecast table changed.')
    if norm(p.rows[0][0]['text']) != '富士見指数1~10': fail('Fuji index scale changed.')
    if any(c['attrs'].get('colspan') != '2' for c in p.rows[0][1:]): fail('Fuji day/period columns changed.')
    if [norm(c['text']) for c in p.rows[1]] != ['午前','午後']*7: fail('Fuji morning/afternoon order changed.')
    for row,side,cls in [(2,'north','findexv_ne'),(4,'south','findexv_s')]:
        if norm(p.rows[row][0]['text']) != LABELS[side] or any(cls not in c['attrs'].get('class','').split() for c in p.rows[row][1:]):
            fail('Fuji north/south table scope changed.')
    urls = [urllib.parse.urljoin(HOME,u) for u in p.scripts if re.fullmatch(r'\./lib/t24\.js\?\d{12}',u)]
    if len(urls) != 1 or not allowed(urls[0]): fail('Verified Fuji page-owned data script is missing/duplicated.')
    return urls[0]


def script_contract(raw):
    try: text = raw.decode('utf-8-sig')
    except UnicodeError: fail('Fuji page-owned script is not UTF-8.')
    # Inspect text only. A changed route, formula or row mapping needs re-audit.
    # Preserve spaces inside selectors/URLs. Stripping all whitespace would
    # incorrectly equate '.table01 tr' and '.table01tr'. Never evaluate code.
    tokens = re.finditer(r'''(?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')|(?P<comment>//[^\n]*|/\*[\s\S]*?\*/)|(?P<space>\s+)|(?P<other>.)''',text)
    compact = ''.join(t.group() for t in tokens if t.lastgroup in ('string','other'))
    for code,row in [('N',2),('S',4)]:
        route = "n_file_"+code+"='./data/fdata_"+code+".csv?'+sendTime;"
        if compact.count(route) != 1: fail('Fuji CSV route contract changed.')
        # The declaration through the first DOM write must be exactly the known computation.
        prefix = ('varsetValue_'+code+'=function(my_data,my_col){varfindex=Math.ceil(my_data[1]/10)+1;'
                  'if(findex>10){findex=10}'+"$('.table01 tr').eq("+str(row)+").children('td').eq(my_col).html(findex);")
        if compact.count(prefix) != 1: fail('Fuji published index formula or side-row mapping changed.')
    return {'visible_days':7,'periods':['am','pm'],'index_min':1,'index_max':10,
            'normalization':'Publisher UI: min(10, ceil(raw_value / 10) + 1); not a percentage.'}


def initialization_time(raw):
    if not re.fullmatch(r'\d{4}/\d{2}/\d{2} \d{2}:\d{2}:\d{2}',raw): fail('Unsupported Fuji initialization timestamp.')
    try: return dt.datetime.strptime(raw,'%Y/%m/%d %H:%M:%S').replace(tzinfo=JST)
    except ValueError: fail('Invalid Fuji source date.')


def check_fresh(initial,now):
    age = (now-initial).total_seconds()
    if age < 0: raise SourceError('future_initialization','Fuji source initialization is in the future; forecast state is unknown.')
    if age > MAX_AGE_HOURS*3600:
        raise SourceError('stale_initialization','Fuji source exceeds the fixed 36-hour initialization-age policy; forecast state is unknown.')


def parse_csv(raw,side,dates,now):
    if side not in DATA: raise SourceError('invalid_options','Use north or south.')
    try: rows = list(csv.reader(io.StringIO(raw.decode('ascii')),strict=True))
    except (UnicodeError,csv.Error): fail('Fuji CSV is not the checked ASCII date/value product.')
    if not rows or len(rows[0]) != 2 or rows[0][1] != 'JST':
        fail('Fuji initialization timezone is not the verified JST contract.')
    initial = initialization_time(rows[0][0])
    check_fresh(initial,now)
    records = rows[1:]
    if not 14 <= len(records) <= 64 or any(len(r) != 2 for r in records): fail('Incomplete/unsupported Fuji forecast rows.')
    values = []
    for i,row in enumerate(records):
        reference = initialization_time(row[0])
        expected = dt.datetime.combine(initial.date()+dt.timedelta(days=1+i//2),dt.time(9 if i%2==0 else 15),JST)
        if reference != expected: fail('Fuji forecast dates, AM/PM order or initialization scope disagree.')
        if row[1] in ('','-'): value = None
        elif re.fullmatch(r'\d{1,3}',row[1]) and 0 <= int(row[1]) <= 100: value = int(row[1])
        else: fail('Invalid/missing-marker-unknown Fuji index input.')
        values.append((reference,value))
    # The checked page has only fourteen slots. Extra backend rows are not public-panel coverage.
    visible = {ref.date():[] for ref,_ in values[:14]}
    for i,(reference,value) in enumerate(values[:14]):
        period = {'period':'am' if i%2==0 else 'pm','period_label_ja':'午前' if i%2==0 else '午後',
                                         'kind':'forecast' if value is not None else 'unavailable',
                                         'index':min(10,math.ceil(value/10)+1) if value is not None else None,
                                         'source_reference_at':reference.isoformat(),
                                         'reference_time_has_passed':reference<now}
        if value is None: period['reason'] = 'publisher_value_missing'
        visible[reference.date()].append(period)
    days = []
    for date in dates:
        periods = visible.get(date,[{'period':p,'period_label_ja':label,'kind':'unavailable','index':None,
                                   'reason':'outside_published_panel'} for p,label in [('am','午前'),('pm','午後')]])
        count = sum(p['kind']=='forecast' for p in periods)
        days.append({'date':date.isoformat(),'status':'ok' if count==2 else 'partial' if count else 'unavailable','periods':periods})
    states = [d['status'] for d in days]
    return {'provider':'amecs','publisher':PUBLISHER,'product':'富士見予報','status':states[0] if len(set(states))==1 else 'partial',
            'scope':{'side':side,'label_ja':LABELS[side],'kind':'broad_foothill_direction','specific_viewpoint':None},
            'source_initialization_time':initial.isoformat(),'issued_at':None,
            'freshness_policy':{'basis':'source_initialization_time','max_age_hours':MAX_AGE_HOURS},
            'coverage':{'from':min(visible).isoformat(),'through':max(visible).isoformat(),'visible_days':7},
            'index_scale':{'min':1,'max':10,'higher':'Greater viewing possibility according to the publisher; not a percentage or guarantee.'},
            'days':days}
