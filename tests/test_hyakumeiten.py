"""Native Hyakumeiten switch: all live categories, no category/year search input.
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.

Fixture source and redaction notes are in fixtures/README.md; no local captures required.
"""
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from tabelog_client.cli import run
from tabelog_client.core import CliError
from tabelog_client.hyakumeiten import CATALOG_URL, FILTER_KEY, parse_categories
from tabelog_client.service import Tabelog
from tabelog_client.transport import Client
from test_search import make_client, map_page, marker

FIXTURES = Path(__file__).parent / 'fixtures'
CATALOG = (FIXTURES / 'hyakumeiten-categories.json').read_text()
CURRENT_IDS = [str(row['id']) for row in json.loads(CATALOG)['hyakumeitenCategoryList']]
ORIGIN = '36.5780767488889,136.648590739167'


class NativeCategoryTests(unittest.TestCase):
    def test_recorded_catalog_retains_ids_and_names_without_year_inference(self):
        result = parse_categories(json.loads(CATALOG), CATALOG_URL)
        self.assertEqual(result['meta']['count'], 71)
        self.assertIsNone(result['meta']['year'])
        self.assertEqual([str(row['id']) for row in result['items']], CURRENT_IDS)
        self.assertEqual(set(result['items'][0]), {'id', 'name'})

    def test_catalog_accepts_new_names_and_dynamic_ids(self):
        catalog = parse_categories({'hyakumeitenCategoryList': [{'id': 991, 'name': '寿司 WEST'},
                                    {'id': 992, 'name': '新ジャンル NORTH'}]}, 'source')
        self.assertEqual(catalog['items'], [{'id': 991, 'name': '寿司 WEST'},
                                           {'id': 992, 'name': '新ジャンル NORTH'}])

    def test_malformed_empty_and_duplicate_catalogs_fail_closed(self):
        for raw in ([], {}, {'hyakumeitenCategoryList': []}, {'hyakumeitenCategoryList': {}},
                    *({'hyakumeitenCategoryList': rows} for rows in ([None], [{'id': True, 'name': 'sushi'}],
                       [{'id': '212', 'name': 'sushi'}], [{'id': 0, 'name': 'sushi'}], [{'id': 1, 'name': ' '}],
                       [{'id': 1, 'name': None}], [{'id': 1, 'name': 'a'}, {'id': 1, 'name': 'b'}],
                       [{'id': 1, 'name': 'a'}, {'id': 2, 'name': ' a '}]))):
            with self.subTest(raw=raw), self.assertRaises(CliError):
                parse_categories(raw, 'source')


class NativeSearchTests(unittest.TestCase):
    def app(self, reader):
        app = Tabelog(make_client(reader))
        app.detail = lambda _: self.fail('Native awards alone must not fetch details')
        app.latest_awards = lambda _: self.fail('Native search must not fetch edition HTML')
        return app

    def test_cli_all_current_categories_uses_two_reads_and_stops_at_limit(self):
        calls = []
        def reader(url):
            calls.append(url)
            return CATALOG if url == CATALOG_URL else (FIXTURES / 'hyakumeiten-map.xml').read_text()
        result = run(['search', '--near', ORIGIN, '--hyakumeiten', '--pages', '10', '--limit', '5'],
                     create_client=lambda **_: make_client(reader))
        self.assertEqual(result['exit_code'], 0)
        data = result['output']['data']
        self.assertEqual(len(calls), 2)
        query = parse_qs(urlsplit(calls[-1]).query)
        self.assertEqual(query[FILTER_KEY], CURRENT_IDS)
        self.assertEqual(query['SrtT'], ['rt'])
        self.assertEqual([r['id'] for r in data['items']], ['17010524', '17001005', '17010028', '17012178', '17009093'])
        self.assertEqual(data['meta']['stop_reason'], 'limit_reached')
        self.assertEqual(data['meta']['hyakumeiten_filter']['method'], 'native_current_categories')
        self.assertNotIn('year', data['meta']['filters'])
        self.assertNotIn('category', data['meta']['filters'])
        self.assertTrue(all('matched_awards' not in r for r in data['items']))

    def test_cuisine_filter_reuses_all_dynamic_categories_in_one_search(self):
        calls = []
        def reader(url):
            calls.append(url)
            return json.dumps({'hyakumeitenCategoryList': [{'id': 991, 'name': '寿司 WEST'},
                               {'id': 992, 'name': '新ジャンル NORTH'}]}) if url == CATALOG_URL else (
                                   map_page(marker(1, 4.5, cuisine='ラーメン'), marker(2, 4.0, cuisine='寿司')))
        result = run(['search', '--near', '0,0', '--hyakumeiten', '--cuisine', '寿司', '--limit', '1'],
                     create_client=lambda **_: make_client(reader))
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlsplit(calls[-1]).query)[FILTER_KEY], ['991', '992'])
        self.assertEqual([r['id'] for r in result['output']['data']['items']], ['17000002'])

    def test_legitimate_positive_and_zero_results(self):
        for filename, expected in [('hyakumeiten-sushi-west.xml', 2), ('hyakumeiten-empty.xml', 0)]:
            calls = []
            def reader(url):
                calls.append(url)
                return CATALOG if url == CATALOG_URL else (FIXTURES / filename).read_text()
            result = self.app(reader).search(near=ORIGIN, hyakumeiten=True)
            self.assertEqual(len(result['items']), expected)
            self.assertEqual(len(calls), 2)
            self.assertEqual(result['meta']['stop_reason'], 'source_exhausted')

    def test_invalid_catalog_or_block_stops_before_search(self):
        for body, status in [('{}', 200), ('{"hyakumeitenCategoryList":[]}', 200), ('denied', 403)]:
            calls = []
            def reader(url):
                calls.append(url)
                return {'body': body, 'url': url, 'http_status': status}
            app = Tabelog(Client(reader=reader, delay_min_ms=0, delay_max_ms=0))
            with self.assertRaises(CliError):
                app.search(near='0,0', area='金沢', hyakumeiten=True)
            self.assertEqual(calls, [CATALOG_URL])

    def test_filters_and_pagination_preserved_and_catalog_cached(self):
        calls = []
        def reader(url):
            calls.append(url)
            if url == CATALOG_URL:
                return CATALOG
            query = parse_qs(urlsplit(url).query)
            self.assertEqual(query[FILTER_KEY], CURRENT_IDS)
            return (map_page(marker(1, 4.5, .009, .009), marker(2, 4.4, cuisine='ラーメン')) if query['pg'] == ['1']
                    else map_page(marker(3, 4.0), marker(4, 3.4), more=False, total=4))
        app = self.app(reader)
        result = app.search(near='0,0', hyakumeiten=True, cuisines=['寿司'], min_rating=3.5, pages=10, limit=1)
        self.assertEqual([r['id'] for r in result['items']], ['17000003'])
        self.assertEqual(len(calls), 3)
        app.hyakumeiten_categories()
        self.assertEqual(len(calls), 3)

    def test_native_meal_checks_only_cheap_matches_without_edition_requests(self):
        calls, details = [], []
        app = self.app(lambda url: calls.append(url) or (CATALOG if url == CATALOG_URL else
                            map_page(marker(1, 4.5, .009, .009), marker(2, 4.4), marker(3, 4.3))))
        def detail(url):
            details.append(url)
            return {'name': '店', 'cuisines': ['寿司'], 'hours': [{'closed': False, 'dayList': [1],
                    'rangeList': [{'open': 720, 'close': 840}]}]}
        app.detail = detail
        result = app.search(near='0,0', hyakumeiten=True, meal='lunch', limit=1)
        self.assertEqual([r['id'] for r in result['items']], ['17000002'])
        self.assertEqual(len(details), 1)
        self.assertEqual(len(calls), 2)

    def test_native_list_budget_needs_no_detail_requests(self):
        calls = []
        app = self.app(lambda url: calls.append(url) or (CATALOG if url == CATALOG_URL else
                                        (FIXTURES / 'hyakumeiten-sushi-west.xml').read_text()))
        result = app.search(near=ORIGIN, hyakumeiten=True, budget_meal='lunch', budget_min=10000, budget_max=14999)
        self.assertEqual(len(result['items']), 2)
        self.assertTrue(all(r['budget_filter']['status'] == 'matches_list_budget' for r in result['items']))
        self.assertEqual(len(calls), 2)

    def test_area_pagination_and_explicit_fallback_retain_native_filter(self):
        for use_map in (False, True):
            calls = []
            def reader(url):
                calls.append(url)
                if url == CATALOG_URL:
                    return CATALOG
                self.assertEqual(parse_qs(urlsplit(url).query)[FILTER_KEY], CURRENT_IDS)
                if '/xml/' in url:
                    raise CliError('unexpected_response', 'malformed map')
                page = 2 if '/rstLst/2/' in url else 1
                return (f'<span class="c-pagination__num is-current">{page}</span>'
                        f'<span class="c-page-count__num"><strong>{1 if page == 1 else 21}</strong>'
                        '<strong>40</strong><strong>60</strong></span>'
                        f'<div class="list-rst js-list-item" data-rst-id="1700000{page}" '
                        f'data-detail-url="/ishikawa/A1701/A170101/1700000{page}/">'
                        '<a class="list-rst__rst-name-target">店</a>'
                        f'<span class="list-rst__rating-val">{3.4 if page == 1 else 3.8}</span></div>')
            app = self.app(reader)
            app.suggest = lambda _: [{'name': '金沢', 'kind': 'area', 'datatype': 'Area2', 'exact_match': True}]
            if use_map:
                app.detail = lambda _: {'name': '店', 'cuisines': [], 'latitude': 0, 'longitude': 0}
            result = app.search(near='0,0' if use_map else None, area='金沢', hyakumeiten=True,
                                min_rating=3.5, limit=1, pages=10)
            self.assertEqual(len(result['items']), 1)
            self.assertEqual(len(calls), 4 if use_map else 3)
            self.assertEqual(result['meta']['source'], 'area_suggest_api_then_html')

    def test_access_block_after_catalog_never_falls_back(self):
        for status in (403, 429, 503):
            calls = []
            def reader(url):
                calls.append(url)
                return {'body': CATALOG if url == CATALOG_URL else 'blocked', 'url': url,
                        'http_status': 200 if url == CATALOG_URL else status}
            app = Tabelog(Client(reader=reader, delay_min_ms=0, delay_max_ms=0))
            app.suggest = lambda _: self.fail('No area fallback after block')
            with self.assertRaises(CliError):
                app.search(near='0,0', area='金沢', hyakumeiten=True)
            self.assertEqual(len(calls), 2)

    def test_search_without_award_switch_never_loads_catalog(self):
        calls = []
        def reader(url):
            calls.append(url)
            self.assertIn('/xml/rstmap', url)
            self.assertNotIn(FILTER_KEY, parse_qs(urlsplit(url).query))
            return map_page(marker(1))
        result = self.app(reader).search(near='0,0', limit=1)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(len(calls), 1)

    def test_catalog_diagnostics_and_removed_search_options(self):
        result = run(['hyakumeiten-categories'], lambda **_: make_client(lambda _: CATALOG))
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(len(result['output']['data']['items']), 71)
        for args in (['hyakumeiten-categories', '--year', '2026'], ['hyakumeiten-categories', 'extra'],
                     ['search', '--near', '0,0', '--hyakumeiten', '--category', 'sushi_west'],
                     ['search', '--near', '0,0', '--hyakumeiten', '--year', '2026'],
                     ['awards', '17005534', '--category', 'sushi_west', '--category', 'izakaya_west']):
            result = run(args, lambda **_: make_client(lambda _: self.fail('Invalid arguments must not request')))
            self.assertEqual(result['exit_code'], 1)


if __name__ == '__main__':
    unittest.main()
