"""Network-free behavior tests, including recorded inventories for two restaurants."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import math
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from urllib.parse import urlsplit, parse_qs
from unittest.mock import patch

import httpx
from tabelog_client.cli import run
from tabelog_client.core import (CliError, calendar_decision, distance, meal_schedule, month_ago,
                              point_value, public_url, review_window)
from tabelog_client.parsers import parse_map, parse_detail, parse_cards, parse_reviews, parse_review_read, parse_awards, matching_awards
from tabelog_client.service import Tabelog
from tabelog_client.transport import Client, RequestPacer, retry_after, request_headers

ROOT = 'https://tabelog.com'
RESTAURANT = ROOT+'/ishikawa/A1701/A170101/17005534/'
MAP = '<markers><srchinfo cnt="2" nextpg=""/><marker id="17005534" rstname="演示居酒屋" rsturl="/ishikawa/A1701/A170101/17005534/" score="3.64" rvwcnt="80" rstcat="居酒屋、日本料理" lat="36.5751" lng="136.6520"/><marker id="17005535" rstname="未知评分" rsturl="/ishikawa/A1701/A170101/17005535/" rstcat="寿司" lat="36.58" lng="136.66"/></markers>'
DETAIL = '''<script type="application/ld+json">{"@type":"Restaurant","name":"演示店","aggregateRating":{"ratingValue":"3.7","ratingCount":"12"},"servesCuisine":"Sushi","geo":{"latitude":36.5751,"longitude":136.652}}</script>
<table class="rstinfo-table"><tr><th>Business hours</th><td><ul class="rstinfo-table__business-list"><li class="rstinfo-table__business-item"><p class="rstinfo-table__business-title">Mon - Fri</p><p class="rstinfo-table__business-dtl-text">12:00 - 14:00</p><p class="rstinfo-table__business-dtl-text">18:00 - 22:00</p></li><li class="rstinfo-table__business-item"><p class="rstinfo-table__business-title">Sun</p><p class="rstinfo-table__business-dtl-text">Closed</p></li></ul><p>Lunch service is not available on Thursdays.</p></td></tr><tr><th>Reservation availability</th><td>Reservations available</td></tr></table>'''
REVIEW = '''<div class="rvw-item js-rvw-item-clickable-area" data-detail-url="/en/ishikawa/A1701/A170101/17005534/dtlrvwlst/B1234/">
<a class="rvw-item__rvwr-name">Test Reviewer<span class="rstdtl-rvw-country">Japan</span></a>
<p class="rvw-item__ratings-total"><span class="c-rating-v3__val">4.0</span></p>
<p class="rvw-item__payment-amount-delimiter">￥10,000～￥14,999</p><div class="rvw-item__date-inner"><span>Visited on October, 2026</span></div><div class="rvw-item__rvw-comment"><p>Great fish<br>Good service.</p></div></div>'''


def response(body, url, status=200, **kwargs):
    return {'body': body if isinstance(body, str) else json.dumps(body), 'url': url, 'http_status': status, 'version': 'test', **kwargs}


def client(reader, **kwargs):
    return Client(reader=reader, delay_min_ms=0, delay_max_ms=0, **kwargs)


def slot_body(date, times=None, people=2):
    y, m, d = map(int, date.split('-'))
    return {'base_date': {'year': y, 'month': m, 'day': d}, 'members': people,
            'selection': {str(i): {'time': t} for i, t in enumerate(['18:00'] if times is None else times)}}


def requested_date(url):
    value = parse_qs(urlsplit(url).query)['svd'][0]
    return value[:4]+'-'+value[4:6]+'-'+value[6:]


class Clock:
    def __init__(self):
        self.current, self.waits = 0, []
    def now(self):
        return self.current
    def sleep(self, seconds):
        self.waits.append(seconds)
        self.current += seconds


class ParsingTests(unittest.TestCase):
    def test_geographic_reference_distances(self):
        def measure(lat1, lon1, lat2, lon2):
            return distance(point_value([lat1, lon1]), point_value([lat2, lon2]))
        self.assertAlmostEqual(measure(0, 0, 1, 0), 111195.08, delta=.1)
        self.assertAlmostEqual(measure(0, 179.9, 0, -179.9), 22239.02, delta=.1)
        self.assertAlmostEqual(measure(90, 0, -90, 180), 20015114.44, delta=.1)

    def test_recorded_detail_matches_previous_implementation(self):
        folder = Path(__file__).parent / 'fixtures'
        expected = json.loads((folder / 'ebitei-detail-expected.json').read_text())
        actual = parse_detail((folder / 'ebitei-detail.html').read_text(), {'id': expected['id']}, expected['url'])
        self.assertEqual({key: actual[key] for key in expected}, expected)
        self.assertEqual(len(actual['info']), 26)

    def test_recorded_review_links_inside_cards(self):
        body = (Path(__file__).parent / 'fixtures/yumeri-review-cards.html').read_text()
        cards = parse_reviews(body, 1)['items']
        self.assertEqual(len(cards), 2)
        self.assertIn('/B537776950/', cards[0]['url'])
        self.assertEqual(cards[0]['rating'], 4.5)

    def test_map_missing_rating_and_security(self):
        parsed = parse_map(MAP, 'source')
        self.assertIsNone(parsed['items'][1]['rating'])
        for value in ['<html/>', '<!DOCTYPE markers><markers><srchinfo cnt="0"/></markers>', '<markers><srchinfo cnt="1"/><marker/></markers>']:
            with self.assertRaises(CliError):
                parse_map(value, 'source')

    def test_nul_encoded_map_xml_is_rejected(self):
        body = '<markers><srchinfo cnt="0"/></markers>'
        with self.assertRaises(CliError):
            parse_map(body.encode('utf-16-le').decode('utf-8'), 'source')

    def test_coordinate_validation_and_exact_radius(self):
        for value in ['1,', [None, 10], [True, 10], 'nan,1', '91,0']:
            with self.assertRaises(CliError):
                point_value(value)
        a = point_value('36.5751,136.6520')
        self.assertEqual(distance(a, a), 0)
        self.assertGreater(distance(a, {'latitude':36.585, 'longitude':136.652}), 1000)

    def test_detail_hours_notes_and_coordinates(self):
        item = parse_detail(DETAIL, {'id':'17005534'}, RESTAURANT)
        self.assertEqual(item['hours'][0]['dayList'], [1,2,3,4,5])
        self.assertTrue(item['hours'][1]['closed'])
        self.assertEqual(item['rating'], 3.7)
        self.assertEqual(item['latitude'], 36.5751)
        check = meal_schedule(item, 'lunch')
        self.assertEqual(check['status'], 'confirmed_regular_schedule')
        self.assertIn('Thursdays', check['notes'][0]['value'])
        self.assertEqual(meal_schedule({'cuisines':[]},'lunch')['status'],'unknown')
        self.assertEqual(meal_schedule({**item,'cuisines':['Japanese sweets']},'lunch')['status'],'retail_only')

    def test_detail_missing_identity_is_unknown(self):
        with self.assertRaises(CliError):
            parse_detail('<html/>', {'id':'1'}, RESTAURANT)

    def test_awards_scope_dedup_and_latest(self):
        def badge(category, year):
            return f'<a href="https://award.tabelog.com/hyakumeiten/{category}/{year}/"><span class="c-badge-hyakumeiten"><i>百名店 {year}</i></span></a>'
        records = parse_awards('<table class="rstinfo-table">'+badge('izakaya_west',2026)*2+'</table>'+badge('sushi',2026)+'<span class="c-badge-award"><i>Gold 2026</i></span>', 'source')
        self.assertEqual(len(records),1)
        self.assertEqual(len(matching_awards(records,latest={'izakaya_west':2026})),1)
        self.assertEqual(matching_awards(records,latest={'izakaya_west':2027}),[])

    def test_reviews_dom_and_detail_visits(self):
        record = parse_reviews(REVIEW, 1)['items'][0]
        self.assertEqual(record['reviewer'],'Test Reviewer')
        self.assertEqual(record['rating'],4)
        self.assertIn('Good service.',record['text'])
        visit = REVIEW.replace('rvw-item js-rvw-item-clickable-area','rvw-item__review-contents js-review').replace('rvw-item__ratings-total','rvw-item__single-ratings-total')
        detail = parse_review_read(visit)
        self.assertEqual(len(detail['visits']),1)
        with self.assertRaises(CliError):
            parse_review_read('<html/>')

    def test_review_window_precision(self):
        self.assertEqual(review_window('Visited on October, 2026','2026-09-29','2026-10-29','2026-10-29')['window'],'in_window')
        self.assertEqual(review_window('2026/09','2026-09-29','2026-10-29','2026-10-29')['window'],'boundary_uncertain')
        self.assertEqual(review_window('2026/11','2026-09-29','2026-10-29','2026-10-29')['window'],'future_anomaly')
        self.assertEqual(review_window('2026/02/30','2026-01-01','2026-10-29','2026-10-29')['window'],'undated')
        self.assertEqual(month_ago('2024-03-31'),'2024-02-29')

    def test_card_fields_and_pagination(self):
        body = '''<div class="list-rst" data-rst-id="17005534" data-detail-url="/ishikawa/A1701/A170101/17005534/"><a class="list-rst__rst-name-target">Test Sushi</a><span class="list-rst__area-genre">Kanazawa / Sushi, Seafood</span><span class="list-rst__rating-val">3.6</span><span class="list-rst__rvw-count-num">1,234</span></div><p class="c-page-count__num"><strong>1</strong><strong>20</strong><strong>123</strong></p><span class="c-pagination__num is-current">1</span><a class="c-pagination__num">7</a>'''
        parsed = parse_cards(body)
        self.assertEqual(parsed['items'][0]['cuisines'],['Sushi','Seafood'])
        self.assertEqual(parsed['items'][0]['review_count'],1234)
        self.assertEqual(parsed['count']['total'],123)
        self.assertEqual(parsed['pagination']['last'],7)


class TransportTests(unittest.TestCase):
    def test_pacing_shared_bucket_and_independent_gsi(self):
        clock = Clock()
        pacer = RequestPacer(1000,2500,clock.now,clock.sleep,lambda:.5)
        pacer.before(ROOT)
        pacer.after(ROOT)
        pacer.before('https://award.tabelog.com/hyakumeiten/')
        self.assertEqual(clock.waits,[1.75])
        pacer.after(ROOT)
        pacer.before('https://msearch.gsi.go.jp/')
        self.assertEqual(len(clock.waits),1)
        clock.current += 3
        pacer.before(ROOT)
        self.assertEqual(len(clock.waits),1)

    def test_parallel_serialization_and_cache(self):
        clock = Clock()
        active, peak = 0, 0
        def read(url):
            nonlocal active, peak
            active += 1
            peak = max(peak,active)
            clock.current += .02
            active -= 1
            return response({},url,metrics={'network_requests_started':1,'response_body_bytes':2,'connection_reuses':0})
        c = Client(reader=read,now=clock.now,sleep=clock.sleep,delay_min_ms=1000,delay_max_ms=1000)
        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(lambda u:c.read(u,'json'),[ROOT+'/a',ROOT+'/a',ROOT+'/b']))
        self.assertEqual(peak,1)
        self.assertEqual(c.usage()['cache_hits'],1)
        self.assertEqual(c.usage()['transport_attempts'],2)
        self.assertEqual(c.usage()['throttle_wait_ms'],1000)

    def test_endpoint_headers(self):
        api = request_headers(ROOT+'/en/booking/calendar/find_vacancy/')
        page = request_headers(RESTAURANT)
        self.assertEqual(api['X-Requested-With'],'XMLHttpRequest')
        self.assertNotIn('X-Requested-With',page)
        self.assertNotIn('Sec-CH-UA',page)
        self.assertIn('application/json',api['Accept'])

    def test_retry_after(self):
        now = datetime(2026,10,29,tzinfo=timezone.utc).timestamp()
        self.assertEqual(retry_after('120',now)['retry_after_seconds'],120)
        self.assertEqual(retry_after('Thu, 29 Oct 2026 00:01:00 GMT',now)['retry_after_seconds'],60)
        for value in [None,'-1','nonsense','99999999999999999999999']:
            self.assertEqual(retry_after(value,now),{})

    def test_denials_block_client_and_preserve_cooldown(self):
        for status in [401,403,429,503]:
            calls = []
            c = client(lambda url: calls.append(url) or response('denied',url,status,retry_after='120'))
            for url in [ROOT, ROOT+'/next']:
                with self.assertRaises(CliError) as raised:
                    c.read(url)
                self.assertEqual(raised.exception.details['retry_after_seconds'],120)
            self.assertEqual(len(calls),1)

    def test_challenge_is_not_data(self):
        c = client(lambda url:response('<title>Just a moment...</title>',url))
        with self.assertRaises(CliError) as raised:
            c.read(ROOT)
        self.assertEqual(raised.exception.code,'verification_required')

    def test_network_failure_has_no_transport_fanout(self):
        calls = []
        c = client(lambda url:calls.append(url) or {'error':'network_error','message':'test'})
        with self.assertRaises(CliError):
            c.read(ROOT)
        self.assertEqual(len(calls),1)

    def test_budget(self):
        c = client(lambda url:response({},url),max_requests=1)
        c.read(ROOT)
        with self.assertRaises(CliError) as raised:
            c.read(ROOT+'/another')
        self.assertEqual(raised.exception.code,'request_budget')

    def test_parse_failure_cache_and_metrics(self):
        c = client(lambda url:response({'ok':True},url,metrics={'network_requests_started':2,'response_body_bytes':11}))
        def parse(*_):
            raise CliError('parse_error','test')
        with self.assertRaises(CliError):
            c.read(ROOT,'json',parse)
        self.assertEqual(c.read(ROOT,'json'),{'ok':True})
        self.assertEqual(c.usage()['network_requests_started'],2)
        self.assertEqual(c.usage()['cache_hits'],1)
        self.assertIsNone(c.usage()['connection_reuses'])
        unknown = client(lambda url:response({},url))
        unknown.read(ROOT)
        self.assertFalse(unknown.usage()['metrics_complete'])

    def test_invalid_json_never_becomes_empty_or_nonfinite_data(self):
        for body in ['<html/>', '{"score":NaN}']:
            with self.assertRaises(CliError) as raised:
                client(lambda url: response(body, url)).read(ROOT, 'json')
            self.assertEqual(raised.exception.code, 'unexpected_response')

    def test_httpx_redirects_and_cookie_session(self):
        clock, seen = Clock(), []
        def handle(request):
            seen.append(request)
            if request.url.path == '/a':
                return httpx.Response(302,headers={'location':'/b','set-cookie':'anonymous=1; Path=/'})
            return httpx.Response(200,json={'ok':True})
        c = Client(session=httpx.Client(transport=httpx.MockTransport(handle)),now=clock.now,sleep=clock.sleep,delay_min_ms=1000,delay_max_ms=1000)
        self.assertEqual(c.read(ROOT+'/a','json'),{'ok':True})
        self.assertEqual(c.usage()['network_requests_started'],2)
        self.assertEqual(c.usage()['throttle_wait_ms'],1000)
        self.assertIn('anonymous=1',seen[1].headers['cookie'])
        self.assertEqual(c.read(ROOT+'/b','json'),{'ok':True})
        self.assertEqual(c.usage()['cache_hits'],1)
        c.close()

    def test_redirect_host_allowlist(self):
        c = client(lambda url:response('ok','https://example.com/'))
        with self.assertRaises(CliError):
            c.read(ROOT)
        for u in ['http://tabelog.com/','https://tabelog.com.evil/',('https://user:pass' + '@' + 'tabelog.com/'),'https://tabelog.com:444/','https://tblg.k-img.com/private']:
            with self.assertRaises(CliError):
                public_url(u)

    def test_official_award_research_sources_stay_read_only_and_narrow(self):
        for u in ['https://selection.tabelog.com/rstLst/?chk_hyakumeiten_genres%5B%5D=212',
                  'https://selection.tabelog.com/tokyo/rstLst/1/', 'https://s.tabelog.com/en/TopRestaurants/',
                  'https://s.tabelog.com/en/TopRestaurants/rstLst/?PG=2&pal=japan',
                  'https://s.tabelog.com/en/TopRestaurants/ishikawa/rstLst/']:
            self.assertEqual(public_url(u), u)
        for u in ['https://selection.tabelog.com/admin/', 'https://s.tabelog.com/account/',
                  'https://s.tabelog.com/en/TopRestaurants/admin/',
                  'https://selection.tabelog.com.evil/rstLst/', 'https://s.tabelog.com.evil/en/TopRestaurants/']:
            with self.assertRaises(CliError):
                public_url(u)

    def test_source_prime_keeps_anonymous_cookies_in_one_measured_session(self):
        calls = []
        home = 'https://s.tabelog.com/en/TopRestaurants/'
        target = home + 'ishikawa/rstLst/'
        def handler(request):
            calls.append(str(request.url))
            if str(request.url) == home:
                return httpx.Response(200, text='home', headers={'Set-Cookie': 'anonymous_test=one; Path=/'})
            self.assertIn('anonymous_test=one', request.headers.get('Cookie', ''))
            return httpx.Response(200, text='filtered source')
        result = run(['source', target, '--prime', home], create_client=lambda **_:
                     Client(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0))
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(calls, [home, target])
        self.assertEqual(result['output']['data']['body'], 'filtered source')
        self.assertEqual(result['output']['usage']['network_requests_started'], 2)

    def test_source_prime_stops_on_denial_budget_or_invalid_target(self):
        home = 'https://s.tabelog.com/en/TopRestaurants/'
        for status, args, expected in [(403, [], 1), (200, ['--max-requests', '1'], 1)]:
            calls = []
            result = run(['source', home + 'ishikawa/rstLst/', '--prime', home] + args,
                         create_client=lambda **kw: Client(reader=lambda url: calls.append(url) or response('home', url, status),
                                      **{**kw, 'delay_min_ms': 0, 'delay_max_ms': 0}))
            self.assertEqual(result['exit_code'], 1)
            self.assertEqual(len(calls), expected)
        for args in (['source', 'https://example.com/', '--prime', home], ['search', '--near', '0,0', '--prime', home]):
            result = run(args, create_client=lambda **_: client(lambda _: self.fail('No request for invalid flags/target')))
            self.assertEqual(result['exit_code'], 1)


class WorkflowTests(unittest.TestCase):
    def test_radius_does_not_round_outside_candidate_in(self):
        latitude = math.degrees(1000.01 / 6371008.8)
        xml = f'<markers><srchinfo cnt="1" nextpg=""/><marker id="17005534" rstname="Outside" rsturl="/ishikawa/A1701/A170101/17005534/" lat="{latitude}" lng="0"/></markers>'
        app = Tabelog(client(lambda url: response(xml, url)))
        self.assertEqual(app.search(near='0,0', radius=1000)['items'], [])

    def test_nearby_no_detail_fanout(self):
        calls=[]
        app = Tabelog(client(lambda url:calls.append(url) or response(MAP,url)))
        r=app.search(near='36.5751,136.6520',min_rating=3.5,cuisines=['居酒屋'],pages=1)
        self.assertEqual([x['id'] for x in r['items']],['17005534'])
        self.assertEqual(r['items'][0]['distance_m'],0)
        self.assertEqual(len(calls),1)
        self.assertIn('/xml/rstmap',calls[0])

    def test_station_gsi_exact_match_and_discrepancy(self):
        def read(url):
            raw = [{'properties':{'title':'金沢駅'},'geometry':{'type':'Point','coordinates':[136.648590739167,36.5780767488889]}}] if 'gsi.go.jp' in url else {'suggestResult':[{'name':'金沢駅','type':'RailroadStation','typeId':123,'latitude':36.58,'longitude':136.652}]}
            return response(raw,url)
        r=Tabelog(client(read)).station('金沢')
        self.assertEqual(r['latitude'],36.5780767488889)
        self.assertGreater(r['source_discrepancy_m'],100)
        self.assertIn('GSI',r['note'])

    def test_station_ambiguity_fails(self):
        app=Tabelog(client(lambda url:response({'suggestResult':[]},url)))
        with self.assertRaises(CliError) as raised:
            app.station('unknown')
        self.assertEqual(raised.exception.code,'station_not_found')

    def test_numeric_detail_redirect_cache(self):
        calls=[]
        app=Tabelog(client(lambda url:calls.append(url) or response(DETAIL,ROOT+'/en/ishikawa/A1701/A170101/17005534/')))
        self.assertEqual(app.detail('17005534')['rating'],3.7)
        app.detail(RESTAURANT)
        self.assertEqual(len(calls),1)

    def test_latest_retired_category(self):
        def badge(c,y):
            return f'<a href="https://award.tabelog.com/hyakumeiten/{c}/{y}/"><span class="c-badge-hyakumeiten"><i>百名店 {y}</i></span></a>'
        body=DETAIL.replace('</table>',badge('izakaya_west',2026)+badge('izakaya',2022)+'</table>')
        calls=[]
        def read(url):
            calls.append(url)
            return response('<a href="/hyakumeiten/izakaya_west">WEST</a>' if url.endswith('/hyakumeiten/') else '<title>WEST 百名店 2026</title>' if url.endswith('/izakaya_west/') else body,url)
        r=Tabelog(client(read)).awards(RESTAURANT)
        self.assertEqual(len(r['matches']),1)
        self.assertNotIn('https://award.tabelog.com/hyakumeiten/izakaya/',calls)
        self.assertIsNone(r['latest_by_category']['izakaya'])

    def test_meal_search_skips_retail_and_stops_at_limit(self):
        xml='<markers><srchinfo cnt="4" nextpg=""/>'+''.join(f'<marker id="1700553{n}" rstname="店{n}" rsturl="/ishikawa/A1701/A170101/1700553{n}/" score="3.6" rstcat="{"和菓子" if n==1 else "寿司"}" lat="36.575{n}" lng="136.6520"/>' for n in range(1,5))+'</markers>'
        app=Tabelog(client(lambda url:response(xml,url)))
        checked=[]
        def detail(url):
            checked.append(url)
            return {'rating':3.6,'name':'Test','cuisines':['Sushi'],'hours':[{'dayList':[1],'closed':False,'rangeList':[{'open':720,'close':810}]}],'info':[]}
        app.detail=detail
        r=app.search(near='36.5751,136.6520',meal='lunch',limit=1,pages=1)
        self.assertEqual(r['items'][0]['id'],'17005532')
        self.assertEqual(len(checked),1)
        self.assertEqual(r['meta']['meal_check']['excluded'][0]['reason'],'retail_only')

    def test_reviews_dates_and_full_text(self):
        visit=REVIEW.replace('rvw-item js-rvw-item-clickable-area','rvw-item__review-contents js-review').replace('rvw-item__ratings-total','rvw-item__single-ratings-total')
        app=Tabelog(client(lambda url:response(visit if '/B1234/' in url else REVIEW,url)))
        with patch('tabelog_client.service.today_japan',return_value='2026-10-29'),patch('tabelog_client.core.today_japan',return_value='2026-10-29'):
            r=app.reviews(RESTAURANT,since='2026-09-29',pages=1,full=True)
            self.assertEqual(r['items'][0]['window'],'in_window')
            self.assertEqual(r['items'][0]['content_level'],'detail')
            self.assertEqual(r['items'][0]['visits'][0]['window'],'in_window')

    def test_reviews_unrecognized_not_empty(self):
        app=Tabelog(client(lambda url:response('<html/>',url)))
        with self.assertRaises(CliError):
            app.reviews(RESTAURANT,since='2026-01-01')


class AvailabilityTests(unittest.TestCase):
    def make_app(self, overview, times=None, fail_status=None):
        urls=[]
        def read(url):
            urls.append(url)
            if 'date_with_status' in url:
                return response({'list':overview},url)
            return response('limited',url,fail_status) if fail_status else response(slot_body(requested_date(url),times),url)
        return Tabelog(client(read)),urls

    def test_only_known_nonselectable_codes_pruned(self):
        overview=[{'year':2099,'month':1,'day':i+1,'available':code} for i,code in enumerate([0,1,2,3,4,99])]
        app,urls=self.make_app(overview,['12:00'])
        r=app.availability('16010357',start='2099-01-01',end='2099-01-07',people=2,after='17:00')
        self.assertEqual(len(urls),5)
        self.assertEqual(r['query_plan']['calendar_excluded_dates'],3)
        self.assertEqual(r['query_plan']['slot_verified_dates'],4)
        self.assertEqual(r['coverage'],'complete')
        self.assertIsNone(r['dates'][0]['offered_times'])
        self.assertEqual(r['dates'][1]['matching_times'],[])
        self.assertFalse(calendar_decision(True)['skip_online_slots'])

    def test_duplicate_calendar_falls_back_conservatively(self):
        overview=[{'year':2099,'month':1,'day':1,'available':code} for code in [0,2]]
        app,urls=self.make_app(overview)
        r=app.availability('16010357',start='2099-01-01',end='2099-01-03',people=2)
        self.assertEqual(len(urls),4)
        self.assertEqual(r['coverage'],'partial')
        self.assertEqual(r['query_plan']['calendar_error']['code'],'unexpected_response')
        self.assertEqual(r['query_plan']['slot_verified_dates'], 3)
        self.assertEqual(r['errors'][0]['scope'], 'calendar')

    def test_recovered_calendar_failure_still_returns_nonzero_with_known_slots(self):
        overview = [{'year': 2099, 'month': 1, 'day': 1, 'available': code} for code in (0, 2)]
        app, urls = self.make_app(overview, ['18:00'])
        result = run(['availability', '16010357', '--date', '2099-01-01', '--people', '2'],
                     create_client=lambda **_: app.client)
        self.assertEqual(result['exit_code'], 3)
        self.assertEqual(result['output']['status'], 'partial')
        self.assertEqual(result['output']['data']['dates'][0]['offered_times'], ['18:00'])
        self.assertEqual(result['output']['errors'][0]['code'], 'unexpected_response')

    def test_empty_calendar_queries_all_dates(self):
        app,urls=self.make_app([])
        r=app.availability('16010357',start='2099-01-01',end='2099-01-03',people=2)
        self.assertEqual(len(urls),4)
        self.assertEqual(r['query_plan']['calendar_excluded_dates'],0)

    def test_calendar_denial_stops_all_dates_unknown(self):
        for status in [403,429,503]:
            calls=[]
            app=Tabelog(client(lambda url:calls.append(url) or response('denied',url,status)))
            r=app.availability('16010357',start='2099-01-01',end='2099-01-03',people=2)
            self.assertEqual(len(calls),1)
            self.assertEqual(r['coverage'],'partial')
            self.assertTrue(all(d['matching_times'] is None for d in r['dates']))

    def test_slot_failure_preserves_exclusions_and_unknowns(self):
        app,urls=self.make_app([{'year':2099,'month':1,'day':i+1,'available':s} for i,s in enumerate([0,2,0,2])],fail_status=429)
        r=app.availability('16010357',start='2099-01-01',end='2099-01-04',people=2)
        self.assertEqual(len(urls),2)
        self.assertEqual(r['query_plan']['unknown_dates'],2)
        self.assertEqual(r['query_plan']['calendar_excluded_dates'],2)
        self.assertEqual(r['dates'][3]['verification'],'not_queried')

    def test_single_date_verifies_contradiction(self):
        app,urls=self.make_app([{'year':2099,'month':1,'day':1,'available':0}])
        r=app.availability('16010357',start='2099-01-01',people=2)
        self.assertEqual(len(urls),2)
        self.assertEqual(r['query_plan']['calendar_slot_contradictions'],['2099-01-01'])

    def test_slots_party_echo_must_match(self):
        app,_=self.make_app([])
        with self.assertRaises(CliError):
            app.slots('16010357','2099-01-01',3,'19:00')

    def test_recorded_inventories_match_daily_oracle(self):
        for filename,counts,dinner_count in [('ebitei-calendar-2026-10-29.json',(6,32),4),('ecoutieres-calendar-2026-10-29.json',(27,31),22)]:
            fixture=json.loads((Path(__file__).parent/'fixtures'/filename).read_text())
            days=[{**d,'date':d['date'].replace('2026','2099',1)} for d in fixture['days']]
            outputs=[]
            for mode in ('calendar','oracle'):
                calls=[]
                def read(url):
                    calls.append(url)
                    if 'date_with_status' in url:
                        raw={'list':[dict(zip(('year','month','day'),map(int,d['date'].split('-'))),available=d['raw_status']) for d in days]}
                    else:
                        date=requested_date(url)
                        raw=slot_body(date,next(d['offered_times'] for d in days if d['date']==date))
                    return response(raw,url)
                app=Tabelog(client(read))
                if mode=='calendar':
                    r=app.availability(fixture['restaurant_id'],start=days[0]['date'],end=days[-1]['date'],people=2,after='17:00')
                    outputs.append([(d['date'],d['matching_times']) for d in r['dates']])
                else:
                    app.calendar(fixture['restaurant_id'])
                    outputs.append([(d['date'],[t for t in app.slots(fixture['restaurant_id'],d['date'],2,'19:00') if t>='17:00']) for d in days])
                self.assertEqual(len(calls),counts[mode=='oracle'])
                self.assertEqual(sum(bool(times) for _,times in outputs[-1]),dinner_count)
            self.assertEqual(*outputs)


class CliTests(unittest.TestCase):
    def test_structured_invalid_args(self):
        for args in [ ['availability','1','--date','2099-02-30','--people','2'], ['search','--min-rating','NaN'], ['search','--unknown'], ['doctor','--delay-min-ms','0'], ['doctor','--delay-min-ms','2000','--delay-max-ms','1000'], ['availability','1','--date','2099-01-01','--people','2','--strategy','daily'], ['doctor','--transport','http'], ['reviews',RESTAURANT,'--basis','published'], ['compare-availability','old.json','daily.json'] ]:
            with self.subTest(args=args):
                r=run(args)
                self.assertEqual(r['exit_code'],1)
                self.assertEqual(r['output']['status'],'error')

    def test_numeric_fixed_party_slots_single_request(self):
        calls=[]
        def create(**kwargs):
            kwargs.update(delay_min_ms=0,delay_max_ms=0)
            return Client(reader=lambda url:calls.append(url) or response(slot_body('2099-12-01'),url),**kwargs)
        r=run(['slots','16010357','--date','2099-12-01','--people','2'],create)
        self.assertEqual(r['exit_code'],0)
        self.assertEqual(len(calls),1)

    def test_usage_offline_unknown_metrics_and_duplicate(self):
        with tempfile.TemporaryDirectory() as folder:
            paths=[str(Path(folder)/f'{n}.json') for n in range(2)]
            for n,p in enumerate(paths):
                Path(p).write_text(json.dumps({'status':'ok','command':'slots','usage':{'elapsed_ms':10,'transport_attempts':1,'network_requests_started':None if n else 2,'browser_launches':0,'response_body_bytes':20,'cache_hits':0,'metrics_complete':not n,'dependencies':[]}}))
            r=run(['usage',*paths])
            self.assertEqual(r['output']['data']['totals']['transport_attempts'],2)
            self.assertEqual(r['output']['data']['totals']['summed_command_elapsed_ms'],20)
            self.assertIsNone(r['output']['data']['totals']['network_requests_started'])
            self.assertEqual(r['output']['usage']['transport_attempts'],0)
            self.assertEqual(run(['usage',paths[0],paths[0]])['exit_code'],1)

    def test_doctor_offline_and_help(self):
        self.assertIn('help',run(['--help']))
        r=run(['doctor'])
        self.assertEqual(r['exit_code'],0)
        self.assertFalse(r['output']['data']['browser_required'])
        self.assertEqual(r['output']['usage']['transport_attempts'],0)


if __name__ == '__main__':
    unittest.main()
