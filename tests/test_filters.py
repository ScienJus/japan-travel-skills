"""Budget, dated hours, and published course behavior; no live requests."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import json
from pathlib import Path
import unittest

from tabelog_client.cli import run
from tabelog_client.core import CliError
from tabelog_client.filters import budget_range, budget_check, opening_check
from tabelog_client.parsers import parse_cards, parse_courses, parse_detail, parse_map
from tabelog_client.service import Tabelog
from tabelog_client.transport import Client


ROOT = 'https://tabelog.com'
URL = ROOT+'/ishikawa/A1701/A170101/17013984/'
REF = {'id': '17013984', 'path': 'ishikawa/A1701/A170101/17013984'}
FIXTURES = Path(__file__).parent/'fixtures'


def rule(days, start=660, end=840, closed=False, **kwargs):
    return {'dayList': days, 'closed': closed, 'rangeList': [] if closed else [{'open': start, 'close': end}], **kwargs}


def client(read):
    return Client(reader=lambda u: {'body': read(u), 'url': u, 'http_status': 200, 'version': 'test'}, delay_min_ms=0, delay_max_ms=0)


class FilterTests(unittest.TestCase):
    def test_dated_opening_rule_exposes_nonofficial_local_calendar_basis(self):
        result = opening_check({'hours': [rule([0, 1, 2, 3, 4, 5, 6])]},
                               day='2026-11-03', at='12:00')
        self.assertEqual(result['holiday_calendar'],
                         {'name': 'jpholiday', 'basis': 'third_party_local_rules',
                          'official_feed_checked': False})

    def test_budget_without_meal_matches_either_band_and_reports_which(self):
        item = {'budgets': {'lunch': '￥1,000～￥1,999', 'dinner': '￥8,000～￥9,999'}}
        self.assertEqual(budget_check(item, None, maximum=2000)['matching_meals'], ['lunch'])
        self.assertEqual(budget_check(item, None, maximum=10000)['matching_meals'], ['lunch', 'dinner'])
        self.assertEqual(budget_check(item, None, maximum=500)['status'], 'outside_budget')
        item['budgets']['lunch'] = None
        self.assertEqual(budget_check(item, None, maximum=2000)['status'], 'unknown')
        self.assertEqual(budget_check(item, None, minimum=8000)['matching_meals'], ['dinner'])
        item['budgets']['dinner'] = '￥1,000～￥2,999'
        self.assertEqual(budget_check(item, None, maximum=2000)['status'], 'boundary_uncertain')

    def test_weekly_time_filter_reports_days_without_choosing_a_date(self):
        item = {'hours': [rule([1, 2, 3, 4, 5]), rule([0, 6], closed=True)]}
        result = opening_check(item, at='12:00')
        self.assertEqual(result['matching_weekdays'], [1, 2, 3, 4, 5])
        self.assertEqual(result['unknown_weekdays'], [])
        self.assertEqual(result['basis'], 'regular_weekdays')
        self.assertIsNone(result['date'])
        self.assertEqual(opening_check(item, at='14:00')['status'], 'outside_regular_hours')
        self.assertEqual(opening_check(item, at='13:00', until='15:00')['status'], 'outside_regular_hours')

    def test_weekly_rules_preserve_holiday_exceptions_without_applying_them(self):
        item = {'hours': [rule([1, 2, 3, 4, 5]), rule([0, 6], closed=True),
                          rule([], closed=True, day_types=['holiday'])]}
        weekly = opening_check(item, at='12:00')
        self.assertEqual(weekly['matching_weekdays'], [1, 2, 3, 4, 5])
        self.assertEqual(len(weekly['special_rules']), 1)
        self.assertEqual(opening_check(item, '2026-11-03', '12:00')['status'], 'outside_regular_hours')

    def test_weekly_overnight_stays_carry_between_adjacent_weekdays(self):
        item = {'hours': [rule([1], 1320, 1440), rule([2], 0, 120), rule([0, 3, 4, 5, 6], closed=True)]}
        self.assertEqual(opening_check(item, at='23:00', until='01:00')['matching_weekdays'], [1])
        self.assertEqual(opening_check(item, at='01:00')['matching_weekdays'], [2])
        self.assertEqual(opening_check(item, at='02:00')['status'], 'outside_regular_hours')

    def test_weekly_missing_and_uncertain_schedules_remain_unknown(self):
        self.assertEqual(opening_check({'hours': []}, at='12:00')['unknown_weekdays'], list(range(7)))
        item = {'hours': [rule([4])], 'info': [{'label': 'Business hours', 'value': 'Reservations required'}]}
        self.assertEqual(opening_check(item, at='12:00')['status'], 'unknown')
        item = {'hours': [rule([4])], 'info': []}
        result = opening_check(item, at='12:00')
        self.assertEqual(result['matching_weekdays'], [4])
        self.assertEqual(result['unknown_weekdays'], [0, 1, 2, 3, 5, 6])

    def test_budget_bands_unknown_open_ended_and_boundary(self):
        for text, expected in [('￥1,000～￥1,999', (1000, 1999)), ('～￥999', (0, 999)), ('￥100,000～', (100000, None))]:
            b = budget_range(text)
            self.assertEqual((b['min_yen'], b['max_yen']), expected)
        for text in ['－', None, '￥10,000', '￥2,000～￥1,000']:
            self.assertIsNone(budget_range(text))
        item = {'budgets': {'lunch': '￥4,000～￥4,999', 'dinner': '￥10,000～'}}
        self.assertEqual(budget_check(item, 'lunch', maximum=5000)['status'], 'matches_list_budget')
        self.assertEqual(budget_check(item, 'lunch', maximum=4500)['status'], 'boundary_uncertain')
        self.assertEqual(budget_check(item, 'lunch', minimum=5000)['status'], 'outside_budget')
        self.assertEqual(budget_check(item, 'dinner', maximum=15000)['status'], 'boundary_uncertain')
        self.assertEqual(budget_check(item, 'dinner', minimum=10000)['status'], 'matches_list_budget')

    def test_english_jpy_budget_bands_preserve_raw_and_boundaries(self):
        for raw, expected in [('JPY 5,000 - JPY 5,999', (5000, 5999)),
                              ('- JPY 999', (0, 999)), ('JPY 100,000 -', (100000, None))]:
            with self.subTest(raw=raw):
                parsed = budget_range(raw)
                self.assertEqual((parsed['min_yen'], parsed['max_yen']), expected)
        raw = 'JPY 5,000 - JPY 5,999'
        result = budget_check({'budgets': {'dinner': raw}}, 'dinner', minimum=5000, maximum=8000)
        self.assertEqual(result['status'], 'matches_list_budget')
        self.assertEqual(result['raw'], raw)
        self.assertEqual(budget_check({'budgets': {'dinner': raw}}, 'dinner', maximum=5500)['status'],
                         'boundary_uncertain')
        self.assertEqual(budget_check({'budgets': {'dinner': 'JPY 100,000 -'}}, 'dinner', maximum=8000)['status'],
                         'outside_budget')

    def test_english_budget_does_not_guess_missing_foreign_or_malformed_values(self):
        for raw in ['-', 'USD 5,000 - USD 5,999', 'JPY 5,000 - USD 5,999',
                    'JPY 5,000 - 5,999', '5,000 - 5,999', 'JPY -5,000 - JPY 5,999',
                    'JPY 50.5 - JPY 60.5', 'JPY 5,00 - JPY 5,999', 'JPY 5,999 - JPY 5,000']:
            with self.subTest(raw=raw):
                self.assertIsNone(budget_range(raw))
                self.assertEqual(budget_check({'budgets': {'dinner': raw}}, 'dinner', maximum=8000)['status'],
                                 'unknown')

    def test_english_list_card_budget_can_match_exclude_or_remain_at_boundary(self):
        cards = ''.join(f'''<div class="list-rst" data-rst-id="{ident}" data-detail-url="/en/kyoto/A2601/A260101/{ident}/">
<a class="list-rst__rst-name-target">店{ident}</a><span class="list-rst__area-genre">Kyoto / Japanese Cuisine</span>
<i class="c-rating-v3__time--dinner"></i><span class="c-rating-v3__val">{raw}</span></div>'''
                        for ident, raw in [('26000001', 'JPY 5,000 - JPY 5,999'),
                                           ('26000002', 'JPY 50,000 - JPY 59,999'),
                                           ('26000003', 'JPY 6,000 - JPY 8,999')])
        items = parse_cards(cards)['items']
        self.assertEqual([budget_check(item, 'dinner', minimum=5000, maximum=8000)['status'] for item in items],
                         ['matches_list_budget', 'outside_budget', 'boundary_uncertain'])

    def test_weekday_date_split_sessions_and_closing_boundary(self):
        item = {'hours': [rule([1,2,3,4,5]), rule([1,2,3,4,5], 1080, 1320), rule([0,6], closed=True)]}
        for at, until, expected in [('12:00', None, 'matches_regular_hours'), ('14:00', None, 'outside_regular_hours'),
                                    ('13:00', '19:00', 'outside_regular_hours'), ('18:00', '22:00', 'matches_regular_hours')]:
            self.assertEqual(opening_check(item, '2026-10-29', at, until)['status'], expected)
        self.assertEqual(opening_check(item, '2026-11-01', '12:00')['status'], 'outside_regular_hours')
        self.assertEqual(opening_check({'hours': []}, '2026-10-29', '12:00')['status'], 'unknown')

    def test_public_holiday_and_eve_override_weekday(self):
        item = {'hours': [rule([1,2,3,4,5]), rule([], closed=True, day_types=['holiday']),
                          rule([], 1080, 1380, day_types=['before_holiday'])]}
        holiday = opening_check(item, '2026-11-03', '12:00')
        self.assertEqual(holiday['holiday'], '文化の日')
        self.assertEqual(holiday['status'], 'outside_regular_hours')
        self.assertEqual(opening_check(item, '2026-11-02', '21:00')['status'], 'matches_regular_hours')
        self.assertEqual(opening_check(item, '2026-11-02', '12:00')['status'], 'outside_regular_hours')

    def test_overnight_carry_and_cross_midnight_stay(self):
        item = {'hours': [rule([1], 1080, 1560), rule([2], closed=True)]}
        self.assertEqual(opening_check(item, '2026-10-26', '23:00', '01:00')['status'], 'matches_regular_hours')
        self.assertEqual(opening_check(item, '2026-10-27', '01:00')['status'], 'matches_regular_hours')
        self.assertEqual(opening_check(item, '2026-10-27', '02:00')['status'], 'outside_regular_hours')
        split = {'hours': [rule([1], 1320, 1440), rule([2], 0, 120)]}
        self.assertEqual(opening_check(split, '2026-10-26', '23:00', '01:00')['status'], 'matches_regular_hours')

    def test_irregular_reservation_and_meal_exception_remain_unknown(self):
        for note in ['Irregular holidays; temporary closures may occur.', 'Lunch service is not available on Thursdays.',
                     '完全予約制', '祝日は休業する場合があります']:
            item = {'hours': [rule([4])], 'info': [{'label': 'Business hours', 'value': note}]}
            self.assertEqual(opening_check(item, '2026-10-29', '12:00')['status'], 'unknown')
        conflict = {'hours': [rule([4]), rule([4], closed=True)]}
        self.assertEqual(opening_check(conflict, '2026-10-29', '12:00')['status'], 'unknown')

    def test_last_order_before_and_after(self):
        item = {'hours': [rule([4], 1080, 1320)]}
        item['hours'][0]['rangeList'][0]['lastOrder'] = '21:00'
        self.assertEqual(opening_check(item, '2026-10-29', '20:00')['status'], 'matches_regular_hours')
        self.assertEqual(opening_check(item, '2026-10-29', '21:30')['status'], 'unknown')

    def test_written_ordinal_weekday_exceptions_do_not_confirm_a_visit_date(self):
        for note in ['Closed on the first and third Tuesdays of each month.',
                     'The second & fourth Tuesdays are closed.', 'Closed on the last Tuesday.']:
            item = {'hours': [rule([2], 1020, 1380)],
                    'info': [{'label': 'Business hours', 'value': note}]}
            with self.subTest(note=note):
                result = opening_check(item, '2026-12-01', meal='dinner')
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['notes'][0]['value'], note)
                self.assertEqual(opening_check(item, meal='dinner')['matching_weekdays'], [])

    def test_ordinal_words_without_weekday_exception_do_not_hide_regular_hours(self):
        item = {'hours': [rule([2], 1020, 1380)],
                'info': [{'label': 'Business hours', 'value': 'First course 18:00. Last order 21:00.'}]}
        self.assertEqual(opening_check(item, '2026-12-01', meal='dinner')['status'], 'matches_regular_hours')

    def test_english_last_order_and_generic_disclaimer_are_not_special_closures(self):
        item = {'hours': [rule([4])], 'info': [{'label': 'Business hours', 'value': 'Hours and closed days may change, so please check with the restaurant before visiting.'},
                                             {'label': 'Remarks', 'value': 'July 2014: Store renovation.'}]}
        item['hours'][0]['rangeList'][0]['lastOrder'] = 'Food 1:30 PM'
        self.assertEqual(opening_check(item, '2026-10-29', '12:30')['status'], 'matches_regular_hours')
        self.assertEqual(opening_check(item, '2026-10-29', '13:45')['status'], 'unknown')

    def test_date_and_meal_must_match_same_day(self):
        item = {'hours': [rule([1]), rule([4], 1080, 1320)]}
        self.assertEqual(opening_check(item, '2026-10-29', meal='lunch')['status'], 'outside_regular_hours')
        self.assertEqual(opening_check(item, '2026-10-29', meal='dinner')['status'], 'matches_regular_hours')

    def test_invalid_search_flags_are_rejected_before_network(self):
        for flags in [['--open-until','13:00'], ['--open-date','2026-02-30'], ['--open-date','2026-11-01','--open-until','13:00'],
                      ['--open-date','2026-11-01','--open-at','12:00','--open-until','12:00'],
                      ['--budget-meal','lunch'], ['--budget-meal','lunch','--budget-min','6000','--budget-max','5000'],
                      ['--budget-meal','breakfast','--budget-max','5000'], ['--budget-meal','lunch','--budget-max','NaN']]:
            result = run(['search','--near','0,0',*flags], create_client=lambda **kw: client(lambda u: self.fail('Unexpected network read')))
            self.assertEqual(result['output']['error']['code'], 'invalid_argument', flags)

    def test_list_budget_search_does_not_read_details(self):
        rows = ''.join(f'<marker id="1700000{n}" rstname="店{n}" rsturl="/ishikawa/A1701/A170101/1700000{n}/" score="{4.5-n/10}" rstcat="寿司" lat="0" lng="0" price_range1="{budget}" price_range2="￥10,000～￥14,999"/>'
                       for n, budget in [(1,'－'), (2,'￥5,000～￥5,999'), (3,'￥4,000～￥4,999'), (4,'￥3,000～￥3,999')])
        calls = []
        def read(url):
            calls.append(url)
            return '<markers><srchinfo cnt="60" nextpg="2"/>'+rows+'</markers>'
        result = run(['search','--near','0,0','--budget-meal','lunch','--budget-max','5000','--limit','1','--pages','10'],
                     create_client=lambda **kw: client(read))
        self.assertEqual(result['output']['status'], 'partial')
        self.assertEqual(result['exit_code'], 3)
        self.assertEqual(result['output']['errors'][0]['code'], 'unverified_candidates')
        data = result['output']['data']
        self.assertEqual([r['id'] for r in data['items']], ['17000003'])
        self.assertEqual(len(data['unverified']), 2)
        self.assertEqual(len(calls), 1)
        self.assertIn('/xml/rstmap', calls[0])

    def test_search_without_budget_meal_uses_both_bands_without_detail_reads(self):
        calls = []
        body = '<markers><srchinfo cnt="1" nextpg=""/><marker id="17013984" rstname="店" rsturl="/ishikawa/A1701/A170101/17013984/" score="4" rstcat="寿司" lat="0" lng="0" price_range1="￥1,000～￥1,999" price_range2="￥9,000～￥9,999"/></markers>'
        r = run(['search', '--near', '0,0', '--budget-max', '2000'],
                create_client=lambda **_: client(lambda url: calls.append(url) or body))
        data = r['output']['data']
        self.assertEqual(r['exit_code'], 0)
        self.assertEqual(data['items'][0]['budget_filter']['matching_meals'], ['lunch'])
        self.assertEqual(data['meta']['filters']['budget_meal'], 'any')
        self.assertEqual(len(calls), 1)

    def test_weekly_search_fetches_details_once_and_meal_inherits_budget_scope(self):
        calls = []
        def read(url):
            calls.append(url)
            if '/xml/' in url:
                return '<markers><srchinfo cnt="1" nextpg=""/><marker id="17013984" rstname="店" rsturl="/ishikawa/A1701/A170101/17013984/" score="4" rstcat="寿司" lat="0" lng="0" price_range1="￥1,000～￥1,999" price_range2="￥9,000～￥9,999"/></markers>'
            self.assertNotIn('/party/', url)
            return '<script type="application/ld+json">{"@type":"Restaurant","name":"店","servesCuisine":"Sushi"}</script><ul class="rstinfo-table__business-list"><li class="rstinfo-table__business-item"><p class="rstinfo-table__business-title">Mon - Fri</p><p class="rstinfo-table__business-dtl-text">12:00 - 14:00</p></li></ul>'
        r = run(['search', '--near', '0,0', '--budget-max', '2000', '--meal', 'lunch', '--open-at', '12:30'],
                create_client=lambda **_: client(read))
        item = r['output']['data']['items'][0]
        self.assertEqual(item['opening_filter']['matching_weekdays'], [1, 2, 3, 4, 5])
        self.assertIsNone(item['opening_filter']['date'])
        self.assertEqual(item['meal_service']['status'], 'confirmed_regular_schedule_on_weekdays')
        self.assertEqual(item['budget_filter']['meal'], 'lunch')
        self.assertEqual(len(calls), 2)

    def test_detail_translation_does_not_discard_a_matching_list_cuisine(self):
        calls = []
        def read(url):
            calls.append(url)
            if '/xml/' in url:
                return '<markers><srchinfo cnt="1" nextpg=""/><marker id="17013210" rstname="店" rsturl="/ishikawa/A1701/A170101/17013210/" score="3" rstcat="ハンバーガー" lat="0" lng="0"/></markers>'
            return '<script type="application/ld+json">{"@type":"Restaurant","name":"Restaurant","servesCuisine":"Hamburger"}</script><ul class="rstinfo-table__business-list"><li class="rstinfo-table__business-item"><p class="rstinfo-table__business-title">Mon - Sun</p><p class="rstinfo-table__business-dtl-text">7:00 AM - 10:00 PM</p></li></ul>'
        result = run(['search', '--near', '0,0', '--cuisine', 'ハンバーガー', '--open-at', '12:30'],
                     create_client=lambda **_: client(read))
        item = result['output']['data']['items'][0]
        self.assertEqual(item['cuisines'], ['ハンバーガー'])
        self.assertEqual(item['localized_cuisines'], ['Hamburger'])
        self.assertEqual(item['opening_filter']['matching_weekdays'], list(range(7)))
        self.assertEqual(len(calls), 2)

    def test_dated_search_checks_hours_without_fetching_courses(self):
        calls = []
        def read(url):
            calls.append(url)
            if '/xml/' in url:
                return '<markers><srchinfo cnt="1" nextpg=""/><marker id="17013984" rstname="店" rsturl="/ishikawa/A1701/A170101/17013984/" score="4" rstcat="寿司" lat="0" lng="0"/></markers>'
            self.assertNotIn('/party/', url)
            return '<script type="application/ld+json">{"@type":"Restaurant","name":"店","servesCuisine":"Sushi"}</script><ul class="rstinfo-table__business-list"><li class="rstinfo-table__business-item"><p class="rstinfo-table__business-title">Thu</p><p class="rstinfo-table__business-dtl-text">12:00 - 14:00</p></li></ul>'
        r = Tabelog(client(read)).search(near='0,0', open_date='2026-10-29', open_at='12:30')
        self.assertEqual(len(r['items']), 1)
        self.assertEqual(r['items'][0]['opening_filter']['status'], 'matches_regular_hours')
        self.assertEqual(len(calls), 2)

    def test_search_meal_honors_holiday_only_opening(self):
        def read(url):
            if '/xml/' in url:
                return '<markers><srchinfo cnt="1" nextpg=""/><marker id="17013984" rstname="店" rsturl="/ishikawa/A1701/A170101/17013984/" score="4" rstcat="寿司" lat="0" lng="0"/></markers>'
            return '<script type="application/ld+json">{"@type":"Restaurant","name":"店","servesCuisine":"Sushi"}</script><ul class="rstinfo-table__business-list"><li class="rstinfo-table__business-item"><p class="rstinfo-table__business-title">Public Holiday</p><p class="rstinfo-table__business-dtl-text">12:00 - 14:00</p></li></ul>'
        r = Tabelog(client(read)).search(near='0,0', meal='lunch', open_date='2026-11-03')
        self.assertEqual(len(r['items']), 1)
        self.assertEqual(r['items'][0]['meal_service']['status'], 'confirmed_regular_schedule_on_date')


class CourseTests(unittest.TestCase):
    def test_recorded_courses_prices_and_constraints(self):
        data = parse_courses((FIXTURES/'ecoutieres-courses.html').read_text(), REF, URL+'party/')
        self.assertEqual(len(data['items']), 7)
        self.assertEqual(data['coverage'], 'listed_courses')
        first = data['items'][0]
        self.assertEqual(first['id'], '301304296')
        self.assertEqual(first['price_yen'], 29700)
        self.assertIn('税込', first['tax'])
        self.assertIn('12/24', first['name'])
        self.assertIn('1～5名様', first['rules'][0]['value'])
        self.assertIn('/party/301304296', first['url'])

    def test_missing_course_data_is_not_confirmed_empty(self):
        for body in ['<html>bad gateway</html>', '<link rel="canonical" href="https://tabelog.com/toyama/A1601/A160101/16010357/party/">']:
            with self.assertRaises(CliError):
                parse_courses(body, REF, URL+'party/')
        body = f'<link rel="canonical" href="{URL}party/">'
        self.assertEqual(parse_courses(body, REF, URL+'party/')['coverage'], 'not_listed')
        self.assertEqual(parse_courses(body+'コースはありません', REF, URL+'party/')['coverage'], 'explicit_empty')

    def test_detail_fetches_course_catalog_once_without_inventory_calls(self):
        calls = []
        def read(url):
            calls.append(url)
            return ((FIXTURES/'ecoutieres-courses.html').read_text() if '/party/' in url else
                    '<script type="application/ld+json">{"@type":"Restaurant","name":"店"}</script>')
        app = Tabelog(client(read))
        self.assertNotIn('courses', app.detail(URL))
        self.assertEqual(len(app.detail(URL, include_courses=True)['courses']['items']), 7)
        app.detail(URL, include_courses=True)
        self.assertEqual(len(calls), 2)
        self.assertFalse(any('/booking/' in u for u in calls))

    def test_course_failure_preserves_detail_and_reports_partial(self):
        def read(url):
            if '/party/' in url:
                raise CliError('access_denied', '403')
            return '<script type="application/ld+json">{"@type":"Restaurant","name":"店"}</script>'
        r = run(['detail', URL], create_client=lambda **kw: client(read))
        self.assertEqual(r['exit_code'], 3)
        self.assertEqual(r['output']['data']['name'], '店')
        self.assertEqual(r['output']['data']['courses']['coverage'], 'unknown')
        self.assertIsNone(r['output']['data']['courses']['items'])
        self.assertEqual(r['output']['errors'][0]['scope'], 'courses')

    def test_missing_course_markup_and_unread_course_pages_are_explicit_failures(self):
        for course_body, code in [
            (f'<link rel="canonical" href="{URL}party/">', 'unverified_courses'),
            ((FIXTURES/'ecoutieres-courses.html').read_text()+'<a class="c-pagination__num">2</a>', 'incomplete_courses'),
        ]:
            with self.subTest(code=code):
                def read(url):
                    return course_body if '/party/' in url else '<script type="application/ld+json">{"@type":"Restaurant","name":"店"}</script>'
                result = run(['detail', URL], create_client=lambda **_: client(read))
                self.assertEqual(result['exit_code'], 3)
                self.assertEqual(result['output']['status'], 'partial')
                self.assertEqual(result['output']['errors'][0]['code'], code)
                self.assertEqual(result['output']['data']['name'], '店')
