"""Meal-filtered reviews keep per-visit meal evidence and server query semantics."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import unittest
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from bs4 import BeautifulSoup

from tabelog_client.cli import run
from tabelog_client.parsers import parse_reviews, parse_review_read
from tabelog_client.service import Tabelog
from tabelog_client.transport import Client


URL = 'https://tabelog.com/ishikawa/A1701/A170101/17005534/'


def row(ident=1, meal='dinner', detail=False):
    icon = f'<i class="c-rating-v3__time--{meal}"></i>' if meal else ''
    return (f'<div class="{"rvw-item__review-contents js-review" if detail else "rvw-item js-rvw-item-clickable-area"}" '
            f'data-detail-url="/en/ishikawa/A1701/A170101/17005534/dtlrvwlst/B{ident}/">'
            f'<p class="{"rvw-item__single-ratings-total" if detail else "rvw-item__ratings-total"}">{icon}'
            '<b class="c-rating-v3__val">4.0</b></p>'
            '<div class="rvw-item__date-inner"><span>Visited on October, 2020</span></div>'
            f'<div class="rvw-item__rvw-comment"><p>{meal or "unknown"} visit</p></div></div>')


def client(reader):
    return Client(reader=lambda u: {'body': reader(u), 'url': u, 'http_status': 200, 'version': 'test'},
                  delay_min_ms=0, delay_max_ms=0)


class ReviewMealTests(unittest.TestCase):
    def test_parser_labels_each_list_and_full_visit_meal(self):
        self.assertEqual([r['meal'] for r in parse_reviews(row(meal='lunch')+row(2, 'dinner')+row(3, None), 1)['items']],
                         ['lunch', 'dinner', None])
        self.assertEqual([r['meal'] for r in parse_review_read(row(meal='lunch', detail=True)+row(2, 'dinner', detail=True))['visits']],
                         ['lunch', 'dinner'])

    def test_cli_sends_meal_filter_without_more_requests(self):
        # Derive the oracle from recorded real navigation, not from the implementation.
        doc = BeautifulSoup((Path(__file__).parent/'fixtures/review-meal-links.html').read_text(), 'html.parser')
        cases = [(a.get_text().split()[0].lower(), parse_qs(urlsplit(a['href']).query)['use_type'][0]) for a in doc.select('a')]
        for meal, code in cases+[('all', '0'), (None, '0')]:
            calls = []
            def read(url):
                calls.append(url)
                self.assertEqual(parse_qs(urlsplit(url).query)['use_type'], [code])
                return row(meal=meal if meal in ('lunch', 'dinner') else 'dinner')
            args = ['reviews', URL, '--since', '2020-10-01', '--until', '2020-10-31', '--pages', '1']
            if meal:
                args += ['--meal', meal]
            result = run(args, create_client=lambda **kw: client(read))
            self.assertEqual(result['output']['status'], 'ok')
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['output']['data']['meta']['meal'], meal or 'all')
            self.assertEqual(len(result['output']['data']['items']), 1)

    def test_wrong_review_page_is_an_error_instead_of_source_exhaustion(self):
        body = row()+'<b class="c-pagination__num is-current">1</b><a class="c-pagination__num">2</a>'
        result = run(['reviews', URL, '--since', '2020-10-01', '--until', '2020-10-31', '--pages', '2'],
                     create_client=lambda **_: client(lambda _url: body))
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['output']['status'], 'error')
        self.assertEqual(result['output']['error']['code'], 'unexpected_response')

    def test_mismatched_or_unknown_list_meal_never_counts_as_matching(self):
        app = Tabelog(client(lambda u: row(meal='dinner')+row(2, None)+row(3, 'lunch')))
        result = app.reviews(URL, '2020-10-01', '2020-10-29', pages=1, meal='lunch')
        self.assertEqual([r['review_id'] for r in result['items']], ['B3'])
        self.assertEqual(result['unverified'][0]['meal'], None)
        self.assertEqual(result['meta']['meal_check']['excluded_list_records'], 1)
        self.assertEqual(result['meta']['meal_check']['unknown_list_records'], 1)

    def test_mismatched_duplicate_does_not_hide_matching_review(self):
        app = Tabelog(client(lambda u: row(meal='dinner')+row(meal='lunch')))
        result = app.reviews(URL, '2020-10-01', '2020-10-29', pages=1, meal='lunch')
        self.assertEqual([r['review_id'] for r in result['items']], ['B1'])
        self.assertEqual(result['items'][0]['meal'], 'lunch')

    def test_full_text_excludes_other_meals_and_separates_unknown_visits(self):
        def read(url):
            return (row(meal='lunch', detail=True)+row(2, 'dinner', detail=True)+row(3, None, detail=True)
                    if '/B1/' in url else row(meal='lunch'))
        result = Tabelog(client(read)).reviews(URL, '2020-10-01', '2020-10-29', pages=1, meal='lunch', full=True)
        item = result['items'][0]
        self.assertEqual([v['meal'] for v in item['visits']], ['lunch'])
        self.assertEqual([v['meal'] for v in item['unverified_visits']], [None])
        self.assertEqual(result['meta']['meal_check']['excluded_full_visits'], 1)
        self.assertEqual(result['meta']['meal_check']['unknown_full_visits'], 1)
        self.assertNotIn('text', item)

    def test_full_text_without_matching_visit_is_unverified_not_confirmed(self):
        app = Tabelog(client(lambda u: row(meal='dinner', detail=True) if '/B1/' in u else row(meal='lunch')))
        result = app.reviews(URL, '2020-10-01', '2020-10-29', pages=1, meal='lunch', full=True)
        self.assertEqual(result['items'], [])
        self.assertEqual(len(result['unverified']), 1)

    def test_default_all_and_standalone_review_read_keep_all_visit_meals(self):
        body = row(meal='lunch', detail=True)+row(2, 'dinner', detail=True)+row(3, None, detail=True)
        app = Tabelog(client(lambda u: body if '/B1/' in u else row(meal='lunch')))
        result = app.reviews(URL, '2020-10-01', '2020-10-29', pages=1, full=True)
        self.assertEqual(len(result['items'][0]['visits']), 3)
        self.assertEqual([v['meal'] for v in app.review_read(URL+'dtlrvwlst/B1/')['visits']], ['lunch', 'dinner', None])

    def test_invalid_meal_is_rejected_before_resolving_numeric_id(self):
        result = run(['reviews', '17005534', '--meal', 'breakfast'],
                     create_client=lambda **kw: client(lambda u: self.fail('Unexpected HTTP read')))
        self.assertEqual(result['output']['error']['code'], 'invalid_argument')
        result = run(['review-read', URL+'dtlrvwlst/B1/', '--meal', 'dinner'],
                     create_client=lambda **kw: client(lambda u: self.fail('Unexpected HTTP read')))
        self.assertEqual(result['output']['error']['code'], 'invalid_argument')
