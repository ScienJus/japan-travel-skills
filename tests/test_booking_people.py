"""Native party-size discovery and verified time-specific ranges, without network."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import json
from pathlib import Path
import unittest
from urllib.parse import parse_qs, urlsplit

from tabelog_client.cli import run
from tabelog_client.core import CliError
from tabelog_client.service import Tabelog
from tabelog_client.transport import Client


DAY = '2099-12-01'
MEMBERS = {'svpsOpts': [{'member_num': n, 'status': 2 if n in (1, 2, 4) else 0} for n in range(1, 6)]}


def overview(*statuses):
    return {'list': [{'year': 2099, 'month': 12, 'day': n, 'available': status}
                     for n, status in enumerate(statuses, 1)]}


def make_app(members=MEMBERS, dates=None, times=None, fail=None, max_requests=80):
    calls = []
    def read(url):
        calls.append(url)
        params = parse_qs(urlsplit(url).query)
        status = 200
        if 'date_with_status' in url:
            body = dates if dates is not None else overview(2)
        elif 'member_by_date' in url:
            body = members
        else:
            number = int(params['svps'][0])
            if fail == number:
                return {'body': 'rate limited', 'url': url, 'http_status': 429}
            date = params['svd'][0]
            body = {'base_date': {'year': int(date[:4]), 'month': int(date[4:6]), 'day': int(date[6:])},
                    'members': number, 'selection': {str(n): {'time': t} for n, t in enumerate((times or {}).get(number, []))}}
        return {'body': json.dumps(body), 'url': url, 'http_status': status}
    return Tabelog(Client(reader=read, delay_min_ms=0, delay_max_ms=0, max_requests=max_requests)), calls


class PartySizeTests(unittest.TestCase):
    def test_calendar_without_dates_returns_only_the_overview_in_one_read(self):
        app, calls = make_app(dates=overview(2, 0))
        result = run(['calendar', '17013984'], create_client=lambda **_: app.client)
        self.assertEqual(result['exit_code'], 0)
        data = result['output']['data']
        self.assertIsNone(data['requested_range'])
        self.assertEqual(data['coverage'], 'returned_overview')
        self.assertEqual(data['member_coverage'], 'not_queried')
        self.assertTrue(all(r['selectable_people'] is None for r in data['dates']))
        self.assertEqual(len(calls), 1)

    def test_slots_without_time_omits_svt_and_explicit_time_is_still_sent(self):
        app, calls = make_app(times={2: ['12:00', '18:30']})
        first = app.slots('17013984', DAY, 2)
        second = app.slots('17013984', DAY, 2, '12:00')
        self.assertEqual(first, second)
        self.assertNotIn('svt', parse_qs(urlsplit(calls[0]).query))
        self.assertEqual(parse_qs(urlsplit(calls[1]).query)['svt'], ['1200'])

    def test_availability_without_time_uses_default_upstream_anchor_and_filters_window(self):
        app, calls = make_app(times={2: ['12:00', '18:30']})
        r = run(['availability', '17013984', '--date', DAY, '--people', '2', '--after', '17:00'],
                create_client=lambda **_: app.client)
        self.assertEqual(r['exit_code'], 0)
        self.assertEqual(r['output']['data']['dates'][0]['matching_times'], ['18:30'])
        self.assertIsNone(r['output']['data']['requested_range']['anchor_time'])
        self.assertNotIn('svt', parse_qs(urlsplit(calls[-1]).query))

    def test_recorded_member_response_returns_one_to_four_without_probing_sizes(self):
        fixture = json.loads((Path(__file__).parent/'fixtures/ecoutieres-members.json').read_text())
        app, calls = make_app(members=fixture)
        result = app.member_options('17013984', DAY)
        self.assertEqual(result['selectable_people'], [1, 2, 3, 4])
        self.assertEqual(result['selectable_people_ranges'], [{'min': 1, 'max': 4}])
        self.assertEqual(len(calls), 1)
        self.assertNotIn('svps', parse_qs(urlsplit(calls[0]).query))

    def test_calendar_groups_disjoint_sizes_and_never_queries_slots(self):
        app, calls = make_app(dates=overview(2, 0, 4))
        result = app.calendar_query('17013984', DAY, '2099-12-03')
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['dates'][0]['selectable_people_ranges'], [{'min': 1, 'max': 2}, {'min': 4, 'max': 4}])
        self.assertEqual([r['status'] for r in result['dates']], ['member_options', 'calendar_excluded', 'calendar_excluded'])
        self.assertEqual(len(calls), 2)
        self.assertEqual(parse_qs(urlsplit(calls[0]).query), {'rst_id': ['17013984']})
        self.assertFalse(any('svps' in parse_qs(urlsplit(url).query) for url in calls))
        self.assertEqual(result['query_plan']['slot_queries'], 0)

    def test_calendar_people_marks_requested_size_without_filtering_other_options(self):
        app, _ = make_app()
        result = app.calendar_query('17013984', DAY, people=3)
        self.assertEqual(result['dates'][0]['requested_people_hint'], 'not_selectable')
        self.assertEqual(result['dates'][0]['selectable_people'], [1, 2, 4])

    def test_missing_calendar_dates_still_check_members(self):
        app, calls = make_app(dates={'list': []})
        result = app.calendar_query('17013984', DAY)
        self.assertEqual(result['dates'][0]['selectable_people'], [1, 2, 4])
        self.assertIsNone(result['dates'][0]['raw_status'])
        self.assertEqual(len(calls), 2)

    def test_unknown_member_codes_remain_partial_and_are_not_selectable(self):
        app, _ = make_app(members={'svpsOpts': [{'member_num': 1, 'status': 1}, {'member_num': 2, 'status': 2}]})
        result = app.calendar_query('17013984', DAY)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['dates'][0]['selectable_people'], [2])
        self.assertEqual(result['dates'][0]['unknown_people'], [1])

    def test_malformed_members_do_not_become_empty_availability(self):
        rows = MEMBERS['svpsOpts']
        for raw in ({}, {'svpsOpts': []}, {'svpsOpts': rows + rows[:1]},
                    {'svpsOpts': [{'member_num': True, 'status': 2}]},
                    {'svpsOpts': [{'member_num': 100, 'status': 2}]},
                    {'svpsOpts': [{'member_num': 1, 'status': '2'}]}):
            with self.subTest(raw=raw):
                app, _ = make_app(members=raw)
                with self.assertRaises(CliError):
                    app.member_options('17013984', DAY)

    def test_slot_ranges_are_per_time_and_do_not_assume_monotonic_capacity(self):
        app, calls = make_app(times={1: ['12:00', '18:00'], 2: ['18:00'], 4: ['12:00', '19:00']})
        result = app.all_party_slots('17013984', DAY, '19:00')
        self.assertEqual(result['available_people'], [1, 2, 4])
        by_time = {r['time']: r['people_ranges'] for r in result['time_options']}
        self.assertEqual(by_time['12:00'], [{'min': 1, 'max': 1}, {'min': 4, 'max': 4}])
        self.assertEqual(by_time['18:00'], [{'min': 1, 'max': 2}])
        self.assertEqual(by_time['19:00'], [{'min': 4, 'max': 4}])
        self.assertEqual(len(calls), 4)

    def test_unknown_sizes_never_trigger_speculative_slot_requests(self):
        app, calls = make_app(members={'svpsOpts': [{'member_num': 1, 'status': 0}, {'member_num': 2, 'status': 77}]})
        result = app.all_party_slots('17013984', DAY, '19:00')
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['available_people'], [])
        self.assertEqual(result['unknown_people'], [2])
        self.assertEqual(len(calls), 1)

    def test_slot_failure_preserves_verified_sizes_and_stops_further_requests(self):
        app, calls = make_app(times={1: ['18:00']}, fail=2)
        result = app.all_party_slots('17013984', DAY, '19:00')
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['available_people_ranges'], [{'min': 1, 'max': 1}])
        self.assertEqual(result['people_results'][-1]['error']['code'], 'not_queried')
        self.assertEqual(result['unknown_people'], [2, 4])
        self.assertEqual(result['error']['code'], 'rate_limited')
        self.assertEqual(len(calls), 3)

    def test_request_budget_keeps_unchecked_calendar_dates_unknown(self):
        app, calls = make_app(dates=overview(2, 2, 2), max_requests=2)
        result = app.calendar_query('17013984', DAY, '2099-12-03')
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['dates'][0]['status'], 'member_options')
        self.assertEqual(result['dates'][1]['error']['code'], 'request_budget')
        self.assertEqual(result['dates'][2]['status'], 'unknown')
        self.assertEqual(len(calls), 2)

    def test_omitted_people_availability_screens_dates_and_groups_dinner_sizes(self):
        app, calls = make_app(dates=overview(2, 0), times={1: ['12:00'], 2: ['18:00'], 4: ['18:00']})
        result = app.availability('17013984', DAY, end='2099-12-02', after='17:00')
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['dates'][0]['available_people'], [2, 4])
        self.assertEqual(result['dates'][0]['available_people_ranges'], [{'min': 2, 'max': 2}, {'min': 4, 'max': 4}])
        self.assertEqual(result['dates'][1]['status'], 'calendar_excluded')
        self.assertEqual(result['query_plan']['member_queries'], 1)
        self.assertEqual(result['query_plan']['slot_queries'], 3)
        self.assertEqual(len(calls), 5)

    def test_omitted_people_denial_stops_remaining_dates(self):
        app, calls = make_app(dates=overview(2, 2), fail=2)
        result = app.availability('17013984', DAY, end='2099-12-02')
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['dates'][1]['verification'], 'not_queried')
        self.assertEqual(len(calls), 4)

    def test_no_selectable_sizes_does_not_claim_slot_verification(self):
        app, calls = make_app(members={'svpsOpts': [{'member_num': 2, 'status': 0}]})
        result = app.availability('17013984', DAY)
        self.assertEqual(result['dates'][0]['available_people'], [])
        self.assertEqual(result['query_plan']['slot_verified_dates'], 0)
        self.assertEqual(len(calls), 2)

    def test_slot_budget_keeps_remaining_sizes_and_dates_unknown(self):
        app, calls = make_app(dates=overview(2, 2), times={1: ['18:00']}, max_requests=3)
        result = app.availability('17013984', DAY, end='2099-12-02')
        first = result['dates'][0]
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(first['available_people'], [1])
        self.assertEqual(first['unknown_people'], [2, 4])
        self.assertEqual(first['error']['code'], 'request_budget')
        self.assertEqual(result['dates'][1]['verification'], 'not_queried')
        self.assertEqual(len(calls), 3)

    def test_calendar_denial_never_queries_members(self):
        calls = []
        app = Tabelog(Client(reader=lambda url: calls.append(url) or
                             {'body': 'denied', 'url': url, 'http_status': 403}, delay_min_ms=0, delay_max_ms=0))
        result = app.calendar_query('17013984', DAY, '2099-12-03')
        self.assertEqual(result['coverage'], 'partial')
        self.assertTrue(all(r['error']['code'] == 'access_denied' for r in result['dates']))
        self.assertEqual(len(calls), 1)

    def test_cli_calendar_and_slots_accept_omitted_people(self):
        for command, expected in (('calendar', 2), ('slots', 4), ('availability', 5)):
            app, calls = make_app(times={2: ['18:00']})
            result = run([command, '17013984', '--date', DAY], create_client=lambda **_: app.client)
            self.assertEqual(result['exit_code'], 0, result)
            self.assertEqual(len(calls), expected)

    def test_invalid_windows_do_not_make_requests(self):
        for flags in (['--from', DAY], ['--to', DAY], ['--date', DAY, '--to', DAY],
                      ['--from', DAY, '--to', '2099-11-01'], ['--from', DAY, '--to', '2100-01-01']):
            app, calls = make_app()
            result = run(['calendar', '17013984', *flags], create_client=lambda **_: app.client)
            self.assertEqual(result['output']['error']['code'], 'invalid_argument')
            self.assertFalse(calls)


if __name__ == '__main__':
    unittest.main()
