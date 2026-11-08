"""Offline inventory contracts: calendar hints, party bounds, booking modes and failures."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
from copy import deepcopy
from datetime import datetime
import json
import unittest
from unittest.mock import Mock, patch

import httpx

from pocket_concierge_client.cli import run
from pocket_concierge_client.service import PocketConcierge, restaurant_id
from pocket_concierge_client.transport import Client, CliError

VENUE = {'id': '123456', 'name': '例示店', 'realTimeBooking': True, 'area': {'id': '20', 'name': '北陸'},
         'cuisines': [{'id': '1', 'name': '和食'}], 'priceRanges': []}
COURSE = {'id': '123', 'name': '夕食コース', 'costPerGuest': 20000, 'fixedPrice': None,
          'serviceType': 'DINNER', 'summary': 'Tax included; service fee specified separately.', 'supplementaryInformation': ''}


def slot(day='2099-12-02', **changes):
    return {'__typename': 'ReservableAvailability', 'id': '700', 'course': deepcopy(COURSE),
            'startTime': day+'T18:00:00+09:00', 'endTime': day+'T18:00:00+09:00',
            'seatingType': 'COUNTER', 'minPartySize': 2, 'maxPartySize': 6, **changes}


def client(handler, budget=20):
    def respond(request):
        value = handler(json.loads(request.content), request)
        return value if isinstance(value, httpx.Response) else httpx.Response(200, json={'data': value})
    return Client(session=httpx.Client(transport=httpx.MockTransport(respond)), max_requests=budget,
                  delay_min_ms=0, delay_max_ms=0)


def inventory(slots, venue=None):
    return {'venue': {**(VENUE if venue is None else venue), 'courses': [COURSE, {**COURSE, 'id': '124'}]}, 'availabilitySearch': slots}


class PocketConciergeTests(unittest.TestCase):
    def test_explicit_empty_sessions_are_success(self):
        transport = client(lambda body, request: inventory([]))
        result = run(['slots', VENUE['id'], '--date', '2099-12-02'], create_client=lambda **_: transport)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['output']['status'], 'ok')
        self.assertEqual(result['output']['data']['status'], 'no_matching_session')

    def test_slots_preserve_course_session_identity_and_party_ranges_without_enumeration(self):
        def handler(body, request):
            self.assertEqual(request.headers['X-Auth-Origin'], 'GUEST_ORIGIN')
            self.assertNotIn('authorization', request.headers)
            self.assertNotIn('cookie', request.headers)
            self.assertEqual(body['variables'], {'id': VENUE['id'], 'date': '2099-12-02'})
            return inventory([slot(), slot(course={**COURSE, 'id': '124'}), slot()])
        transport = client(handler)
        result = PocketConcierge(transport).slots(VENUE['id'], '2099-12-02')
        self.assertEqual(len(result['slots']), 2)
        self.assertEqual({s['course_id'] for s in result['slots']}, {'123', '124'})
        self.assertTrue(all((s['min_people'], s['max_people']) == (2, 6) for s in result['slots']))
        self.assertEqual(result['status'], 'available')
        self.assertEqual(transport.requests, 1)
        transport.close()

    def test_waitlists_and_request_booking_never_become_instant_confirmation(self):
        waiting = slot(__typename='WaitlistableAvailability')
        waiting.pop('id')
        waiting.pop('seatingType')
        transport = client(lambda body, request: inventory([waiting]))
        result = PocketConcierge(transport).slots(VENUE['id'], '2099-12-02', people=2)
        self.assertEqual(result['status'], 'waitlist_only')
        self.assertEqual(result['slots'], [])
        self.assertIsNone(result['waitlist'][0]['session_id'])
        transport.close()
        transport = client(lambda body, request: inventory([slot()], {**VENUE, 'realTimeBooking': False}))
        result = PocketConcierge(transport).slots(VENUE['id'], '2099-12-02', people=2)
        self.assertEqual(result['status'], 'requestable')
        self.assertEqual(result['slots'][0]['status'], 'reservation_request')
        transport.close()

    def test_unknown_party_bounds_and_missing_seats_are_not_confirmed_matches(self):
        for change, filters in (({'maxPartySize': None}, {'people': 2}), ({'seatingType': None}, {'seat': 'COUNTER'})):
            with self.subTest(change=change):
                transport = client(lambda body, request: inventory([slot(**change)]))
                result = PocketConcierge(transport).slots(VENUE['id'], '2099-12-02', **filters)
                self.assertEqual(result['slots'], [])
                self.assertEqual(result['status'], 'unknown')
                self.assertEqual(result['coverage'], 'partial')
                self.assertEqual(len(result['unverified']), 1)
                transport.close()

    def test_mismatched_dates_and_bad_slots_keep_known_matches_partial(self):
        transport = client(lambda body, request: inventory([
            slot(), slot(day='2099-12-03'), slot(__typename='NewAvailability'),
            slot(startTime=None), slot(startTime=123), slot(endTime=123),
        ]))
        result = PocketConcierge(transport).slots(VENUE['id'], '2099-12-02', people=2)
        self.assertEqual(len(result['slots']), 1)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(len(result['errors']), 5)
        transport.close()

    def test_waitlist_with_unknown_requested_filters_is_partial(self):
        waiting = slot(__typename='WaitlistableAvailability')
        waiting.pop('id')
        waiting.pop('seatingType')
        transport = client(lambda body, request: inventory([waiting]))
        result = run(['slots', VENUE['id'], '--date', '2099-12-02', '--people', '2', '--seat', 'COUNTER'],
                     create_client=lambda **_: transport)
        self.assertEqual(result['exit_code'], 3)
        data = result['output']['data']
        self.assertEqual(data['status'], 'unknown')
        self.assertEqual(data['coverage'], 'partial')
        self.assertEqual(data['slots'], [])
        self.assertEqual(data['waitlist'][0]['unknown'], ['seat'])
        self.assertEqual(result['output']['errors'][0]['code'], 'unverified_session')

    def test_network_failures_include_safe_exception_type_in_cli_and_trace(self):
        def handler(body, request):
            raise httpx.ReadTimeout('private source detail must not be echoed')
        transport = client(handler)
        result = run(['slots', VENUE['id'], '--date', '2099-12-02'], create_client=lambda **_: transport)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['output']['error']['exception_type'], 'ReadTimeout')
        self.assertEqual(result['output']['trace'][-1]['error']['exception_type'], 'ReadTimeout')
        self.assertNotIn('private source detail', json.dumps(result))

    def test_malformed_detail_faq_is_an_error_instead_of_silently_missing_policy(self):
        transport = client(lambda body, request: {'venue': {**VENUE, 'frequentlyAskedQuestions': ['invalid']}})
        result = run(['detail', VENUE['id'], '--no-courses'], create_client=lambda **_: transport)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['output']['error']['code'], 'unexpected_response')

    def test_people_meal_course_seat_and_reported_start_filters_compose(self):
        transport = client(lambda body, request: inventory([slot(), slot(course={**COURSE, 'id': '124', 'serviceType': 'LUNCH'}), slot(id='701', minPartySize=4)]))
        result = PocketConcierge(transport).slots(VENUE['id'], '2099-12-02', people=2, meal='dinner', course='123', seat='COUNTER', after='18:00', before='18:00')
        self.assertEqual([s['session_id'] for s in result['slots']], ['700'])
        self.assertEqual(result['slots'][0]['course']['price']['all_in_total'], None)
        transport.close()

    def test_elapsed_starts_are_omitted_without_inventing_intermediate_times(self):
        transport = client(lambda body, request: inventory([slot(day='2026-12-02'), slot(day='2026-12-02', id='701', startTime='2026-12-02T19:00:00+09:00', endTime='2026-12-02T20:00:00+09:00')]))
        with patch('pocket_concierge_client.service.now_japan', return_value=datetime.fromisoformat('2026-12-02T18:05:00+09:00')):
            result = PocketConcierge(transport).slots(VENUE['id'], '2026-12-02')
        self.assertEqual([s['start_time'] for s in result['slots']], ['2026-12-02T19:00:00+09:00'])
        self.assertEqual(result['slots'][0]['end_time'], '2026-12-02T20:00:00+09:00')
        transport.close()

    def test_range_uses_calendar_screening_and_marks_exclusions_as_hints(self):
        def handler(body, request):
            if body['query'].startswith('query Calendar'):
                return {'venue': {**VENUE, 'availabilityCalendar': {'reservationDates': ['2099-12-02', '2099-12-04'], 'waitlistDates': ['2099-12-03']}}}
            return inventory([slot(day=body['variables']['date'])])
        transport = client(handler)
        result = PocketConcierge(transport).availability(VENUE['id'], '2099-12-01', '2099-12-05', people=2)
        self.assertEqual(transport.requests, 3)
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['days'][2]['status'], 'calendar_waitlist_hint')
        self.assertIsNone(result['days'][2]['slots'])
        self.assertEqual(result['days'][1]['status'], 'available')
        transport.close()
        transport = client(handler, budget=2)
        result = PocketConcierge(transport).availability(VENUE['id'], '2099-12-01', '2099-12-05', people=2)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['days'][1]['status'], 'available')
        self.assertEqual(result['days'][3]['status'], 'unknown')
        self.assertEqual(transport.requests, 2)
        transport.close()

    def test_range_stops_when_the_course_is_not_listed_for_the_restaurant(self):
        def handler(body, request):
            if body['query'].startswith('query Calendar'):
                return {'venue': {**VENUE, 'availabilityCalendar': {
                    'reservationDates': ['2099-12-02', '2099-12-03', '2099-12-04'], 'waitlistDates': [],
                }}}
            return inventory([slot(day=body['variables']['date'])])
        transport = client(handler)
        result = PocketConcierge(transport).availability(VENUE['id'], '2099-12-02', '2099-12-04', course='999')
        self.assertEqual(transport.requests, 2)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual([error['code'] for error in result['errors']], ['not_found'])
        self.assertEqual([row['verification'] for row in result['days']], ['failed', 'not_queried', 'not_queried'])
        self.assertTrue(all(row['status'] == 'unknown' for row in result['days']))
        transport.close()

    def test_partial_graphql_data_is_an_error_and_denials_stop_before_body_reads(self):
        transport = client(lambda body, request: httpx.Response(200, json={'data': {'availabilitySearch': []}, 'errors': [{'message': 'query failed'}]}))
        with self.assertRaises(CliError) as caught:
            transport.read('slots', {'id': VENUE['id'], 'date': '2099-12-02'})
        self.assertEqual(caught.exception.code, 'graphql_error')
        with self.assertRaises(CliError):
            transport.read('filters')
        self.assertEqual(transport.requests, 1)
        transport.close()
        class DeniedBody(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError('Denied bodies must not be consumed.')
        transport = client(lambda body, request: httpx.Response(429, stream=DeniedBody(), headers={'Retry-After': '120'}))
        for _ in range(2):
            with self.assertRaises(CliError) as caught:
                transport.read('filters')
            self.assertEqual(caught.exception.code, 'rate_limited')
        self.assertEqual(transport.requests, 1)
        transport.close()

    def test_search_resolves_native_labels_once_and_stops_early(self):
        def handler(body, request):
            if body['query'].startswith('query Filters'):
                return {'areas': [VENUE['area']], 'cuisines': VENUE['cuisines']}
            variables = body['variables']
            self.assertEqual(variables['areas'], ['20'])
            self.assertEqual(variables['cuisines'], ['1'])
            self.assertEqual(variables['people'], 2)
            return {'venuesSearch': {'collection': [VENUE], 'metadata': {'currentPage': 1, 'limitValue': 10, 'totalCount': 20, 'totalPages': 2}}}
        transport = client(handler)
        result = PocketConcierge(transport).search(area='北陸', cuisines=['和食'], day='2099-12-02', people=2, limit=1)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(transport.requests, 2)
        self.assertEqual(result['verification'], 'search_results_only')
        self.assertTrue(result['limit_reached'])
        self.assertEqual(result['coverage'], 'limited')
        transport.close()

    def test_repeated_page_and_identity_mismatch_never_claim_complete_coverage(self):
        transport = client(lambda body, request: {'venuesSearch': {'collection': [VENUE], 'metadata': {'currentPage': 1, 'limitValue': 10, 'totalCount': 20, 'totalPages': 2}}})
        result = PocketConcierge(transport).search(limit=5)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(len(result['items']), 1)
        transport.close()
        transport = client(lambda body, request: inventory([slot()], {**VENUE, 'id': '654321'}))
        result = run(['slots', VENUE['id'], '--date', '2099-12-02'], create_client=lambda **_: transport)
        self.assertEqual(result['output']['status'], 'error')
        self.assertEqual(result['output']['error']['code'], 'unexpected_response')

    def test_invalid_parameters_and_write_queries_are_rejected_before_requests(self):
        create = Mock(side_effect=AssertionError('Invalid arguments must not create a client.'))
        for args in (['calendar', VENUE['id'], '--people', '2'], ['search', '--people', '2'],
                     ['detail', VENUE['id'], '--no-courses', '--meal', 'lunch'],
                     ['availability', VENUE['id'], '--from', '2099-12-02'],
                     ['slots', VENUE['id'], '--date', '2099-12-02', '--time', '18:00', '--after', '17:00'],
                     ['slots', 'https://example.org/restaurants/123456', '--date', '2099-12-02']):
            with self.subTest(args=args):
                result = run(args, create_client=create)
                self.assertEqual(result['output']['status'], 'error')
                self.assertIsNone(result['output']['usage'])
        create.assert_not_called()
        transport = client(lambda body, request: self.fail('Write/query injection must not reach HTTP.'))
        with self.assertRaises(CliError):
            transport.read('mutation Reserve')
        self.assertEqual(transport.requests, 0)
        transport.close()
        self.assertEqual(restaurant_id('https://www.pocket-concierge.jp/en/restaurants/123456?utm_source=example'), VENUE['id'])

    def test_offline_doctor_and_request_cache_need_no_extra_reads(self):
        create = Mock(side_effect=AssertionError('Doctor must not create a network client.'))
        result = run(['doctor'], create_client=create)
        self.assertEqual(result['output']['usage']['network_requests_started'], 0)
        transport = client(lambda body, request: {'areas': [], 'cuisines': []})
        first = transport.read('filters')
        first['areas'].append('local modification')
        self.assertEqual(transport.read('filters')['areas'], [])
        self.assertEqual(transport.requests, 1)
        self.assertEqual(transport.hits, 1)
        transport.close()
