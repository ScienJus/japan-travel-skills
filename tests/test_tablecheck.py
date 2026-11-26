"""Offline behavioral checks for batched dates, scoped inventory and bounded reads."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
from datetime import datetime, timedelta, timezone
import json
import shlex
import unittest
from unittest.mock import patch

import httpx

from tablecheck_client.cli import run
from tablecheck_client.service import TableCheck, slug_value
from tablecheck_client.transport import Client, CliError


SHOP = {'_id': '1'*24, 'slug': 'sample-restaurant', 'time_zone': 'Asia/Tokyo', 'currency': 'JPY', 'booking_page_mode': 'v1',
        'name_translations': [{'locale': 'ja', 'translation': '例示店'}], 'geocode': {'lat': 36.5, 'lon': 136.5},
        'service_categories': [{'id': 'private', 'name_translations': [{'locale': 'en', 'translation': 'Private'}]}]}
V2_SHOP = {**SHOP, 'slug': 'himawarishokudo2', 'booking_page_mode': 'v2',
           'tc_input_service_category': 'required', 'service_categories': []}
COURSE = {'id': '2'*24, 'price': '55000.0', 'is_active': True, 'is_group_order': True, 'meals': ['dinner'],
          'service_category_ids': ['private'], 'valid_date_ranges': [{'start_date': '2026-12-01', 'end_date': '2026-12-31'}]}


def client(handler, budget=20):
    return Client(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0, max_requests=budget)


def response(value):
    return httpx.Response(200, json=value)


def calendar(day, available=False):
    start = datetime.fromisoformat(day+'T08:00:00+00:00')
    return {(start+timedelta(minutes=i*30)).isoformat(): {'is_available': available and i == 2} for i in range(9)}


class TableCheckTests(unittest.TestCase):
    def setUp(self):
        clock = patch('tablecheck_client.service.datetime', wraps=datetime)
        frozen = clock.start()
        frozen.now.return_value = datetime.fromisoformat('2026-10-31T12:00:00+09:00')
        self.addCleanup(clock.stop)

    def test_calendar_reuses_one_response_for_a_month_and_filters_alternatives(self):
        def handler(request):
            if '/shops/' in request.url.path:
                return response({'shops': [SHOP]})
            data = {f'2026-12-{day:02}': calendar(f'2026-12-{day:02}', day == 2) for day in range(1, 31)}
            return response({'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo', 'data': data,
                'closed_dates': [], 'alternate_timeslots': {'2026-12-01': ['2026-12-01T03:00:00Z']}}})
        transport = client(handler)
        result = TableCheck(transport).availability(SHOP['slug'], '2026-12-01', '2026-12-30', 2, '17:00', '21:00')
        self.assertEqual(transport.requests, 2)
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['days'][1]['offered_times'], ['18:00'])
        self.assertEqual(result['days'][0]['offered_times'], [])
        transport.close()

    def test_v2_dates_and_party_return_venue_start_times(self):
        first, second = '2099-12-02', '2099-12-03'
        grid = {}
        for day in (first, second):
            grid[day] = {
                f'{day}T{hour:02}:{minute:02}:00+09:00': {'is_available': day == first and hour == 18}
                for hour in range(24) for minute in (0, 30)
            }

        def handler(request):
            if request.url.path == '/v2/shops/' + V2_SHOP['slug']:
                return response({'shops': [V2_SHOP]})
            self.assertEqual(request.url.path, '/v2/hub/availability_calendar_v2')
            self.assertEqual(json.loads(request.content)['num_people'], 2)
            return response({'availability_calendar': {
                'type': 'success', 'time_zone': 'Asia/Tokyo', 'data': grid}})

        result = run(['availability', V2_SHOP['slug'], '--from', first, '--to', second, '--people', '2'],
                     create_client=lambda **_: client(handler))
        self.assertEqual(result['exit_code'], 0)
        data = result['output']['data']
        self.assertEqual(data['scope'], 'venue')
        self.assertEqual(data['people'], 2)
        self.assertIs(data['course_linked'], False)
        self.assertIs(data['seat_linked'], False)
        self.assertEqual(data['coverage'], 'complete')
        self.assertEqual([(day['date'], day['complete'], day['offered_times']) for day in data['days']],
                         [(first, True, ['18:00', '18:30']), (second, True, [])])

    def test_v2_unverifiable_seat_returns_only_a_separate_venue_command(self):
        def handler(request):
            self.assertEqual(request.url.path, '/v2/shops/' + V2_SHOP['slug'])
            return response({'shops': [V2_SHOP]})

        venue_args = ['availability', V2_SHOP['slug'], '--from', '2099-12-02', '--to', '2099-12-03',
                      '--people', '2', '--meal', 'dinner', '--after', '18:00', '--max-requests', '5']
        launcher = ['/path with spaces/python', '/installed skill/scripts/tablecheck.py']
        for filters in (['--seat=Counter'], ['--seat', 'Private Room', '--course=' + COURSE['id']]):
            with self.subTest(filters=filters):
                result = run(venue_args + filters, create_client=lambda **_: client(handler), launcher=launcher)
                self.assertEqual(result['exit_code'], 1)
                output = result['output']
                self.assertNotIn('data', output)
                self.assertEqual(output['usage']['network_requests_started'], 1)
                error = output['error']
                self.assertEqual(error['code'], 'unsupported_scope')
                self.assertEqual(error['booking_page_mode'], 'v2')
                self.assertIn('Course and seat remain unverified', error['message'])
                self.assertEqual(shlex.split(error['venue_query_command']), launcher + venue_args)

    def test_v2_reports_only_filtered_grid_evidence(self):
        day = '2099-12-02'
        shop = {**V2_SHOP, 'service_categories': SHOP['service_categories']}
        for args, group, seats, result_state in (
            (['--course', COURSE['id']], True, ['private'], 'available'),
            (['--seat', 'Private'], False, ['private'], 'available'),
            (['--seat', 'Private', '--course', COURSE['id']], False, ['private'], 'available'),
            (['--seat', 'Private'], False, ['private'], 'wrong_seat'),
            (['--course', COURSE['id']], True, ['private'], 'rejected'),
            (['--course', COURSE['id']], True, ['private'], 'other_experience'),
            (['--course', COURSE['id']], True, ['private'], 'invalid_flag'),
            (['--course', COURSE['id']], True, ['private'], 'denied'),
        ):
            with self.subTest(args=args, result_state=result_state):
                def handler(request):
                    path = request.url.path
                    if path.startswith('/v2/shops/'):
                        return response({'shops': [shop]})
                    if path.endswith('/menu_items'):
                        self.assertIn('--course', args)
                        return response({'menu_items': [{**COURSE, 'valid_date_ranges': [], 'is_group_order': group}]})
                    if path.endswith('/availability_calendar_v2'):
                        self.assertEqual(result_state, 'available')
                        return response({'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo',
                                                                  'data': {day: calendar(day, True)}}})
                    self.assertEqual(str(request.url), 'https://production-booking.tablecheck.com/v2/booking/availability_v5/grid')
                    self.assertEqual(request.method, 'POST')
                    params = json.loads(request.content)
                    self.assertEqual(params['shop_id'], shop['slug'])
                    self.assertEqual(params['pax_adult'], 2)
                    self.assertEqual(params['start_at'], day + 'T18:00:00+09:00')
                    self.assertEqual(params['service_category_ids'], seats)
                    self.assertEqual(params['orders'], [{'menu_item_id': COURSE['id'], 'is_group_order': group,
                                                         'qty': 1 if group else 2}] if '--course' in args else [])
                    if result_state == 'denied':
                        return httpx.Response(403)
                    if result_state == 'rejected':
                        return response({'availability_grid': {'code': 'failure', 'data': {'menu_item_ids': [COURSE['id']]}}})
                    if result_state == 'other_experience':
                        return response({'availability_grid': {'code': 'success', 'data': [
                            {'t': day + 'T09:00:00Z', 'a': True, 'exp': 'other'}]}})
                    seat = 'other' if result_state == 'wrong_seat' else 'private'
                    # The venue offered 18:00. The filtered grid can reject that start and offer a different one.
                    return response({'availability_grid': {'code': 'success', 'data': [
                        {'t': day + 'T09:00:00Z', 'a': False, 'sc': seat},
                        {'t': day + 'T09:15:00Z', 'a': 'true' if result_state == 'invalid_flag' else True, 'sc': seat}]}})

                times = ['--meal', 'dinner'] if result_state == 'available' else ['--time', '18:00']
                result = run(['availability', shop['slug'], '--date', day, '--people', '2', *times, *args],
                             create_client=lambda **_: client(handler))
                data = result['output']['data']
                row, = data['days']
                if result_state == 'available':
                    self.assertEqual(result['exit_code'], 0)
                    self.assertEqual(row['offered_times'], ['18:15'])
                    self.assertEqual(row['slots'][0]['course_id'], COURSE['id'] if '--course' in args else None)
                    self.assertEqual(row['slots'][0]['seat_category_id'], 'private' if '--seat' in args else None)
                    self.assertEqual(data['seat_linked'], '--seat' in args)
                    self.assertEqual(data['course_linked'], '--course' in args)
                else:
                    self.assertEqual(result['exit_code'], 3)
                    self.assertEqual((row['complete'], row['status'], row['offered_times']), (False, 'unknown', []))

    def test_missing_calendar_dates_remain_unknown_without_daily_sweep(self):
        def handler(request):
            return response({'shops': [SHOP]}) if '/shops/' in request.url.path else response(
                {'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo', 'data': {'2026-12-01': calendar('2026-12-01')}, 'closed_dates': []}})
        transport = client(handler)
        result = TableCheck(transport).availability(SHOP['slug'], '2026-12-01', '2026-12-30', 2, '17:00', '21:00')
        self.assertEqual(transport.requests, 3)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['days'][-1]['status'], 'unknown')
        self.assertEqual(result['errors'][-1]['code'], 'incomplete_coverage')
        transport.close()

    def test_complete_calendar_with_no_slots_is_success(self):
        def handler(request):
            return response({'shops': [SHOP]}) if '/shops/' in request.url.path else response({
                'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo',
                    'data': {'2099-12-01': calendar('2099-12-01')}, 'closed_dates': []}})
        transport = client(handler)
        result = run(['availability', SHOP['slug'], '--date', '2099-12-01', '--people', '2', '--meal', 'dinner'],
                     create_client=lambda **_: transport)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['output']['status'], 'ok')
        self.assertEqual(result['output']['data']['days'][0]['status'], 'unavailable')

    def test_invalid_alternate_time_and_missing_dates_are_nonzero_at_cli_boundary(self):
        for alternates in ({'2099-12-01': ['not-a-timestamp']}, {}):
            with self.subTest(alternates=alternates):
                def handler(request):
                    return response({'shops': [SHOP]}) if '/shops/' in request.url.path else response({
                        'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo',
                            'data': {'2099-12-01': calendar('2099-12-01')}, 'closed_dates': [],
                            'alternate_timeslots': alternates}})
                transport = client(handler)
                result = run(['availability', SHOP['slug'], '--from', '2099-12-01', '--to', '2099-12-02',
                              '--people', '2', '--meal', 'dinner'], create_client=lambda **_: transport)
                self.assertEqual(result['exit_code'], 3)
                self.assertEqual(result['output']['status'], 'partial')
                codes = {error['code'] for error in result['output']['errors']}
                self.assertIn('incomplete_coverage', codes)
                if alternates:
                    self.assertIn('unexpected_response', codes)

    def test_search_reports_skipped_unknown_filters_and_keeps_matches_when_menus_fail(self):
        for invalid, flags, code in (
            ({'geocode': None}, [], 'unverified_distance'),
            ({'budget_dinner_avg': None}, ['--budget-max', '30000'], 'unverified_budget'),
            ({}, ['--with-courses'], 'access_denied'),
        ):
            with self.subTest(code=code):
                def handler(request):
                    if request.url.path.endswith('/menu_items'):
                        return httpx.Response(403)
                    return response({'shops': [{**SHOP, **invalid}], 'meta': {'last_page': True}})
                transport = client(handler)
                result = run(['search', '--near', '36.5,136.5', *flags], create_client=lambda **_: transport)
                self.assertEqual(result['exit_code'], 3)
                self.assertEqual(result['output']['status'], 'partial')
                self.assertEqual(result['output']['errors'][0]['code'], code)
                if code == 'access_denied':
                    item = result['output']['data']['items'][0]
                    self.assertEqual(item['slug'], SHOP['slug'])
                    self.assertIsNone(item['courses'])

    def test_invalid_course_eligibility_is_not_reported_as_an_empty_menu(self):
        for change in ({'days': ['new-code']}, {'valid_date_ranges': [{'start_date': 'not-a-date'}]}, {'meals': 'invalid'}):
            with self.subTest(change=change):
                transport = client(lambda request: response({'shops': [SHOP]}) if '/shops/' in request.url.path else
                                   response({'menu_items': [{**COURSE, **change}]}))
                result = run(['courses', SHOP['slug'], '--date', '2099-12-01', '--meal', 'dinner'],
                             create_client=lambda **_: transport)
                self.assertEqual(result['exit_code'], 1)
                self.assertEqual(result['output']['error']['code'], 'unexpected_response')

    def test_filtered_course_uses_form_index_and_batches_dates_then_confirms(self):
        seen = []
        def handler(request):
            seen.append(request)
            path = request.url.path
            if '/v2/shops/' in path:
                return response({'shops': [SHOP]})
            if path.endswith('/menu_items'):
                return response({'menu_items': [COURSE]})
            if path.endswith('/reserve'):
                return httpx.Response(200, text='<input name="reservation[service_category]" value="private">'
                    '<input name="reservation[orders_attributes][7][menu_item_id]" value="'+COURSE['id']+'">'
                    '<input name="reservation[orders_attributes][7][is_group_order]" value="true">')
            self.assertEqual(request.url.params['reservation[orders_attributes][7][menu_item_id]'], COURSE['id'])
            self.assertEqual(request.url.params['reservation[service_category]'], 'private')
            if path.endswith('/timetable'):
                return response({'queried_date': '2026-12-01', 'data': {'slots': {
                    day: {str(int(datetime.fromisoformat(day+'T09:00:00+00:00').timestamp())): {'available': True}}
                    for day in ('2026-12-01', '2026-12-02')}}})
            return response({'status': 'success'})
        transport = client(handler)
        result = TableCheck(transport).availability(SHOP['slug'], '2026-12-01', '2026-12-02', 2, '17:00', '21:00', COURSE['id'], 'Private')
        self.assertEqual(transport.requests, 6)
        self.assertEqual(sum(r.url.path.endswith('/timetable') for r in seen), 1)
        self.assertTrue(result['course_linked'] and result['seat_linked'])
        self.assertTrue(all(day['offered_times'] == ['18:00'] for day in result['days']))
        transport.close()

    def test_sparse_v1_timetable_uses_only_explicit_venue_closures(self):
        first, second = '2026-12-01', '2026-12-02'
        shop = {**SHOP, 'slug': 'sushi-ikuta', 'tc_input_service_category': 'required'}
        for seat, closed, budget, calendar_denied in (
            (None, [first, second], 20, False),
            ('Private', [first], 20, False),
            (None, [], 20, False),
            ('Private', [first, second], 4, False),
            (None, [first, second], 20, True),
        ):
            with self.subTest(seat=seat, closed=closed, budget=budget, denied=calendar_denied):
                def handler(request):
                    path = request.url.path
                    if '/v2/shops/' in path:
                        return response({'shops': [shop]})
                    if path.endswith('/menu_items'):
                        return response({'menu_items': [COURSE]})
                    if path.endswith('/reserve'):
                        return httpx.Response(200, text='<input name="reservation[service_category]" value="private">'
                            '<input name="reservation[orders_attributes][0][menu_item_id]" value="' + COURSE['id'] + '">'
                            '<input name="reservation[orders_attributes][0][is_group_order]" value="true">')
                    if path.endswith('/timetable'):
                        # The first day is absent; the second has an explicit empty grid.
                        return response({'queried_date': first, 'data': {'slots': {second: {}}}})
                    self.assertEqual(path, '/v2/hub/availability_calendar_v2')
                    body = json.loads(request.content)
                    self.assertEqual((body['shop_id'], body['num_people']), (shop['_id'], 2))
                    if calendar_denied:
                        return httpx.Response(403)
                    return response({'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo',
                        'data': {day: calendar(day, day not in closed) for day in (first, second)},
                        'closed_dates': closed}})

                transport = client(handler, budget)
                result = TableCheck(transport).availability(shop['slug'], first, second, 2, '17:00', '21:00',
                                                            course=COURSE['id'], seat=seat)
                verified = closed if budget > 4 and not calendar_denied else []
                for row in result['days']:
                    is_closed = row['date'] in verified
                    self.assertEqual(row['status'], 'closed' if is_closed else 'unknown')
                    self.assertEqual(row['complete'], is_closed)
                    self.assertEqual(row['offered_times'], [])
                    if is_closed:
                        self.assertEqual(row['source'], 'venue_calendar_closed_dates')
                self.assertEqual(result['coverage'], 'complete' if len(verified) == 2 else 'partial')
                missing = [day for day in (first, second) if day not in verified]
                self.assertEqual([e['dates'] for e in result['errors'] if e['code'] == 'incomplete_coverage'],
                                 [missing] if missing else [])
                self.assertEqual(transport.requests, min(budget, 5))
                transport.close()

    def test_denial_stops_further_requests_and_reports_no_empty_inventory(self):
        class DeniedBody(httpx.SyncByteStream):
            def __iter__(self):
                raise AssertionError('A denial must stop the command before consuming its body.')
        transport = client(lambda request: httpx.Response(429, headers={'Retry-After': '120'}, stream=DeniedBody()))
        for _ in range(2):
            with self.assertRaises(CliError) as caught:
                transport.read('GET', '/v2/cuisines')
            self.assertEqual(caught.exception.code, 'rate_limited')
        self.assertEqual(transport.requests, 1)
        self.assertEqual(transport.trace[0]['http_status'], 429)
        transport.close()

    def test_unconfirmed_filtered_slot_remains_partial_at_budget_limit(self):
        def handler(request):
            if '/v2/shops/' in request.url.path:
                return response({'shops': [SHOP]})
            if request.url.path.endswith('/reserve'):
                return httpx.Response(200, text='<input name="reservation[service_category]" value="private">')
            return response({'queried_date': '2026-12-01', 'data': {'slots': {'2026-12-01': {'1796115600': {'available': True}}}}})
        transport = client(handler, budget=3)
        result = TableCheck(transport).availability(SHOP['slug'], '2026-12-01', '2026-12-01', 2, '17:00', '21:00', seat='Private')
        self.assertEqual(result['coverage'], 'partial')
        self.assertFalse(result['days'][0]['complete'])
        self.assertEqual(result['days'][0]['offered_times'], [])
        transport.close()

    def test_unrelated_parameters_and_implicit_party_sizes_are_rejected_offline(self):
        for args in (['availability', SHOP['slug'], '--date', '2099-12-01'], ['detail', SHOP['slug'], '--near', '36,136'],
                     ['availability', SHOP['slug'], '--date', '2099-12-01', '--people', '2', '--course='],
                     ['availability', SHOP['slug'], '--date', '2099-12-01', '--people', '2', '--seat='],
                     ['search', '--near', '36,136', '--people', '2'], ['detail', SHOP['slug'], '--no-courses', '--date', '2099-12-01']):
            result = run(args)
            self.assertEqual(result['output']['status'], 'error')
            self.assertIsNone(result['output']['usage'])

    def test_course_dates_and_money_preserve_source_conditions(self):
        def handler(request):
            return response({'shops': [SHOP]}) if '/shops/' in request.url.path else response({'menu_items': [COURSE]})
        transport = client(handler)
        result = run(['detail', SHOP['slug'], '--from', '2026-11-30', '--to', '2026-12-02', '--meal', 'dinner'],
                     create_client=lambda **_: transport)
        self.assertEqual(result['output']['status'], 'ok')
        item = result['output']['data']['courses'][0]
        self.assertEqual(item['price'], '55000.0')
        self.assertEqual(item['eligible_dates'], {'2026-11-30': False, '2026-12-01': True, '2026-12-02': True})
        self.assertIsNone(item['computed_total'])
        transport.close()

    def test_course_only_query_checks_required_seats_and_keeps_the_actual_category(self):
        shop = {**SHOP, 'tc_input_service_category': 'required', 'service_categories': [
            *SHOP['service_categories'], {'id': 'counter', 'name_translations': [{'locale': 'en', 'translation': 'Counter'}]}]}
        def handler(request):
            path = request.url.path
            if '/v2/shops/' in path:
                return response({'shops': [shop]})
            if path.endswith('/menu_items'):
                return response({'menu_items': [{**COURSE, 'service_category_ids': ['private', 'counter']}]})
            if path.endswith('/reserve'):
                return httpx.Response(200, text='<input name="reservation[service_category]" value="private">'
                    '<input name="reservation[service_category]" value="counter">'
                    '<input name="reservation[orders_attributes][2][menu_item_id]" value="'+COURSE['id']+'">'
                    '<input name="reservation[orders_attributes][2][is_group_order]" value="true">')
            if path.endswith('/timetable'):
                return response({'queried_date': '2026-12-01', 'data': {'slots': {'2026-12-01': {
                    '1796115600': {'available': request.url.params['reservation[service_category]'] == 'private'}}}}})
            return response({'status': 'success'})
        transport = client(handler)
        result = TableCheck(transport).availability(shop['slug'], '2026-12-01', '2026-12-01', 2, '17:00', '21:00', course=COURSE['id'])
        self.assertEqual(result['coverage'], 'complete')
        self.assertEqual(result['days'][0]['offered_times'], ['18:00'])
        self.assertEqual(result['days'][0]['slots'][0]['seat_category_id'], 'private')
        self.assertEqual(transport.requests, 6)
        transport.close()

    def test_required_seat_flag_without_api_categories_or_form_controls_checks_course_only(self):
        shop = {**SHOP, 'tc_input_service_category': 'required', 'service_categories': []}
        seen = []
        def handler(request):
            seen.append(request)
            path = request.url.path
            if '/v2/shops/' in path:
                return response({'shops': [shop]})
            if path.endswith('/menu_items'):
                return response({'menu_items': [{**COURSE, 'service_category_ids': []}]})
            if path.endswith('/reserve'):
                return httpx.Response(200, text=
                    '<input name="reservation[orders_attributes][0][menu_item_id]" value="'+COURSE['id']+'">'
                    '<input name="reservation[orders_attributes][0][is_group_order]" value="true">')
            self.assertNotIn('reservation[service_category]', request.url.params)
            self.assertEqual(request.url.params['reservation[orders_attributes][0][menu_item_id]'], COURSE['id'])
            if path.endswith('/timetable'):
                return response({'queried_date': '2026-12-01', 'data': {'slots': {
                    day: {str(int(datetime.fromisoformat(day+'T09:00:00+00:00').timestamp())): {'available': True}}
                    for day in ('2026-12-01', '2026-12-02')}}})
            return response({'status': 'success'})
        transport = client(handler)
        result = TableCheck(transport).availability(shop['slug'], '2026-12-01', '2026-12-02', 2, '17:00', '21:00', course=COURSE['id'])
        self.assertEqual(result['coverage'], 'complete')
        self.assertTrue(result['course_linked'])
        self.assertFalse(result['seat_linked'])
        self.assertIsNone(result['seat_category_id'])
        self.assertTrue(all(day['offered_times'] == ['18:00'] for day in result['days']))
        self.assertEqual(sum(r.url.path.endswith('/timetable') for r in seen), 1)
        self.assertEqual(transport.requests, 6)
        self.assertIn('seat type remains unverified', result['note'])
        transport.close()

    def test_missing_api_categories_never_silently_drops_a_form_or_course_seat_requirement(self):
        shop = {**SHOP, 'tc_input_service_category': 'required', 'service_categories': []}
        for allowed in ([], ['private']):
            with self.subTest(allowed=allowed):
                def handler(request):
                    path = request.url.path
                    if '/v2/shops/' in path:
                        return response({'shops': [shop]})
                    if path.endswith('/menu_items'):
                        return response({'menu_items': [{**COURSE, 'service_category_ids': allowed}]})
                    self.assertTrue(path.endswith('/reserve'))
                    return httpx.Response(200, text='<input name="reservation[service_category]" value="private">')
                transport = client(handler)
                with self.assertRaises(CliError) as caught:
                    TableCheck(transport).availability(shop['slug'], '2026-12-01', '2026-12-02', 2, course=COURSE['id'])
                self.assertEqual(caught.exception.code, 'unsupported_scope')
                self.assertLessEqual(transport.requests, 3)
                transport.close()

        transport = client(lambda request: response({'shops': [shop]}))
        with self.assertRaises(CliError) as caught:
            TableCheck(transport).availability(shop['slug'], '2026-12-01', '2026-12-02', 2, seat='Counter')
        self.assertEqual(caught.exception.code, 'invalid_argument')
        self.assertEqual(transport.requests, 1)
        transport.close()

    def test_source_returns_html_without_treating_it_as_a_result_object(self):
        transport = client(lambda request: httpx.Response(200, text='<title>Reservation form</title>'))
        result = run(['source', '/en/shops/sample-restaurant/reserve'], create_client=lambda **_: transport)
        self.assertEqual(result['exit_code'], 0)
        self.assertEqual(result['output']['data'], '<title>Reservation form</title>')
        self.assertEqual(result['output']['usage']['network_requests_started'], 1)

    def test_search_verifies_candidates_and_stops_after_enough_available_results(self):
        shops = [{**SHOP, 'slug': name, '_id': str(index)*24} for index, name in enumerate(('first', 'second', 'third'), 1)]
        queried = []
        def handler(request):
            queried.append(request.url.path)
            if request.url.path.endswith('/shop_search'):
                return response({'shops': shops, 'meta': {'last_page': True}})
            if '/v2/shops/' in request.url.path:
                return response({'shops': [next(shop for shop in shops if request.url.path.endswith('/'+shop['slug']))]})
            if request.url.path.endswith('/menu_items'):
                return response({'menu_items': [COURSE]})
            body = json.loads(request.content)
            return response({'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo',
                'data': {day: calendar(day, body['shop_id'] != '1'*24) for day in ('2026-12-01', '2026-12-02')}, 'closed_dates': []}})
        transport = client(handler)
        result = TableCheck(transport).search((36.5, 136.5), 1000, [], None, None, 2, 1,
            '2026-12-01', '2026-12-02', 2, '17:00', '21:00', True, 'dinner')
        self.assertEqual([item['slug'] for item in result['items']], ['second'])
        self.assertTrue(result['limit_reached'])
        self.assertNotIn('/v2/shops/third', queried)
        self.assertEqual(transport.requests, 6)
        transport.close()

    def test_native_search_reuses_quarter_hour_index_and_only_fetches_selected_menus(self):
        shops = [{**SHOP, 'slug': name, '_id': str(index)*24,
                  'availability': [] if index == 1 else ['2026-12-01T18:15:00+09:00']}
                 for index, name in enumerate(('first', 'second', 'third'), 1)]
        def handler(request):
            if request.url.path.endswith('/shop_search'):
                self.assertEqual(request.url.params['date'], '2026-12-01')
                self.assertEqual(request.url.params['num_people'], '2')
                self.assertNotIn('time', request.url.params)
                return response({'shops': shops, 'meta': {'last_page': True}})
            self.assertTrue(request.url.path.endswith('/menu_items'))
            self.assertEqual(json.loads(request.content)['shop_id'], '2'*24)
            return response({'menu_items': [COURSE]})
        transport = client(handler)
        result = TableCheck(transport).search((36.5, 136.5), 1000, [], None, None, 2, 1,
            '2026-12-01', '2026-12-01', 2, '17:00', '21:00', True, 'dinner')
        self.assertEqual([item['slug'] for item in result['items']], ['second'])
        self.assertEqual(result['items'][0]['availability']['days'][0]['offered_times'], ['18:15'])
        self.assertEqual(result['availability_verification'], 'search_index_only')
        self.assertEqual(transport.requests, 2)
        transport.close()

    def test_city_search_resolves_native_city_and_keeps_exact_time_and_radius_scope(self):
        def location(kind, name):
            return {'text_translations': [{'locale': 'ja', 'translation': name}],
                    'payload': {'location_type': kind, 'term': name, 'geo': {'lat': 36.5, 'lon': 136.5}}}
        def handler(request):
            if request.url.path.endswith('/autocomplete'):
                return response({'shops': [], 'locations': [location('city', '金沢市'), location('ward', '金沢区')]})
            self.assertEqual(request.url.params['geo_distance'], '10000')
            return response({'shops': [{**SHOP, 'availability': ['2099-12-01T12:15:00+09:00']}], 'meta': {'last_page': True}})
        transport = client(handler)
        result = run(['search', '--area', '金沢', '--date', '2099-12-01', '--people', '2', '--time', '12:15'],
                     create_client=lambda **_: transport)
        self.assertEqual(result['output']['status'], 'ok')
        data = result['output']['data']
        self.assertEqual(data['location']['term'], '金沢市')
        self.assertEqual(data['geographic_scope'], 'center_radius_not_administrative_boundary')
        self.assertEqual(data['items'][0]['availability']['days'][0]['offered_times'], ['12:15'])
        self.assertEqual(transport.requests, 2)

    def test_native_search_never_promotes_wrong_date_index_to_available(self):
        transport = client(lambda request: response({'shops': [{**SHOP, 'availability': ['2026-12-02T18:00:00+09:00']}],
                                                    'meta': {'last_page': True}}))
        result = TableCheck(transport).search((36.5, 136.5), 1000, [], None, None, 1, 5, '2026-12-01', '2026-12-01', 2)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['items'], [])
        self.assertEqual(result['errors'][0]['code'], 'unexpected_response')
        transport.close()

    def test_known_matches_do_not_hide_partial_candidate_inventory(self):
        transport = client(lambda request: response({'shops': [SHOP], 'meta': {'last_page': True}}))
        app = TableCheck(transport)
        inventory = {'coverage': 'partial', 'days': [{'date': '2026-12-01', 'offered_times': ['18:00']}],
                     'errors': [{'code': 'request_budget'}]}
        with patch.object(app, 'availability', return_value=inventory):
            result = app.search((36.5, 136.5), 1000, [], None, None, 1, 1, '2026-12-01', '2026-12-02', 2)
        self.assertEqual(len(result['items']), 1)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['errors'][0]['code'], 'partial_inventory')
        transport.close()

    def test_elapsed_today_slots_are_filtered_from_index_calendar_and_form(self):
        def handler(request):
            if '/v2/shops/' in request.url.path:
                return response({'shops': [SHOP]})
            if request.url.path.endswith('/reserve'):
                return httpx.Response(200, text='<input name="reservation[service_category]" value="private">')
            if request.url.path.endswith('/timetable'):
                return response({'queried_date': '2026-12-01', 'data': {'slots': {'2026-12-01': {
                    '1796115600': {'available': True}, '1796117400': {'available': True}}}}})
            if request.url.path.endswith('/available'):
                self.assertEqual(request.url.params['reservation[start_at_epoch]'], '1796117400')
                return response({'status': 'success'})
            values = calendar('2026-12-01', True)
            values['2026-12-01T09:30:00+00:00']['is_available'] = True
            return response({'availability_calendar': {'type': 'success', 'time_zone': 'Asia/Tokyo',
                'data': {'2026-12-01': values}, 'closed_dates': []}})
        transport = client(handler)
        app = TableCheck(transport)
        with patch('tablecheck_client.service.datetime', wraps=datetime) as clock:
            clock.now.return_value = datetime.fromisoformat('2026-12-01T18:05:00+09:00')
            shop = {**SHOP, 'availability': ['2026-12-01T18:00:00+09:00', '2026-12-01T18:30:00+09:00']}
            results = [app.indexed_availability(shop, '2026-12-01', 2, '17:00', '21:00'),
                       app.availability(SHOP['slug'], '2026-12-01', '2026-12-01', 2, '17:00', '21:00'),
                       app.availability(SHOP['slug'], '2026-12-01', '2026-12-01', 2, '17:00', '21:00', seat='Private')]
        for result in results:
            self.assertEqual(result['days'][0]['offered_times'], ['18:30'])
        transport.close()

    def test_foreign_urls_and_write_routes_are_rejected_without_network(self):
        with self.assertRaises(CliError):
            slug_value('https://example.org/en/shops/sample-restaurant/reserve')
        transport = client(lambda request: self.fail('unexpected network request'))
        with self.assertRaises(CliError):
            transport.read('POST', '/v2/hub/reservations', body={})
        self.assertEqual(transport.requests, 0)
        transport.close()
