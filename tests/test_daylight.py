"""Offline checks for the NAOJ daylight integration."""
import contextlib
import datetime as dt
import http.client
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.parse

SCRIPT = Path(__file__).resolve().parents[1] / "skills/japan-daylight/scripts/daylight.py"
spec = importlib.util.spec_from_file_location("japan_daylight", SCRIPT)
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


def catalog(years=range(2016, 2037)):
    return ('<html><form><select name="year">' + ''.join('<option value="{0}">{0}</option>'.format(y) for y in years) +
            '</select><select name="NAO_id">' + ''.join('<option value="{}">{}</option>'.format(code, name) for code, name in
              [('17', '富山(富山県)'), ('18', '金沢(石川県)'), ('19', '福井(福井県)'),
               ('21', '長野(長野県)'), ('50', '富士山頂(日本)'), ('51', 'すばる望遠鏡(ハワイ)'),
               ('52', 'ALMA観測所(チリ)')]) + '</select></form></html>')


# Selected cells observed in the official result; no runtime calendar fixture.
ROWS = [
    ['2026/11/21', '6:37', '114.3', '11:39:10', '33.6', '16:41', '245.6', '10:05'],
    ['2026/11/22', '6:38', '114.6', '11:39:25', '33.3', '16:41', '245.3', '10:03'],
    ['2026/11/23', '6:39', '114.9', '11:39:41', '33.1', '16:41', '245.0', '10:02'],
]
HEADERS = ['年月日', '出', '方位[°]', '南中', '高度[°]', '入り', '方位[°]', '長さ']


def result(rows=None, label='金沢(石川県): Kanazawa', coordinates=None):
    rows = ROWS if rows is None else rows
    coordinates = coordinates or '緯度:36.5667° 経度:136.6500° 標高:   0.0 m 標準時:UT+9<sup>h</sup>'
    return ('<html><meta charset="EUC-JP"/><div id="skipr"><h2>結果</h2><h3>日の出入り</h3>'
            '<div>' + label + '</div><div>' + coordinates + '</div><table class="result" border="1">' +
            '<tr>' + ''.join('<th scope="col">' + c + '</th>' for c in HEADERS) + '</tr>' +
            ''.join('<tr>' + ''.join('<td>' + c + '</td>' for c in row) + '</tr>' for row in rows) +
            '</table><hr/><h3>ご利用にあたって</h3><ul><li>予告なく変更することがあります (ver.2.1h)。</li></ul></div></html>')


POINTS, YEARS = d.parse_catalog(catalog())
POINT = d.resolve(POINTS, '金沢')
START, END = dt.date(2026, 11, 21), dt.date(2026, 11, 23)


class CatalogTests(unittest.TestCase):
    def test_domestic_locations_and_live_years(self):
        self.assertEqual(len(POINTS), 5)
        self.assertNotIn('51', [p['code'] for p in POINTS])
        self.assertEqual(YEARS, list(range(2016, 2037)))
        _, years = d.parse_catalog(catalog(range(2017, 2038)))
        self.assertEqual(years[-1], 2037)

    def test_exact_aliases_and_fullwidth_labels(self):
        for query in ('金沢', '金泽', 'Kanazawa', '金沢市', '金沢（石川県）'):
            with self.subTest(query=query):
                self.assertEqual(d.resolve(POINTS, query)['code'], '18')
        self.assertEqual(d.resolve(POINTS, 'Nagano')['code'], '21')

    def test_partial_and_prefecture_names_return_candidates_without_substitution(self):
        for query in ('金', '石川県', '高山'):
            with self.subTest(query=query), self.assertRaises(d.DaylightError) as cm:
                d.resolve(POINTS, query)
            self.assertEqual(cm.exception.code, 'city_not_found')
        self.assertEqual(d.search_points(POINTS, '石川県'), [POINT])

    def test_ambiguous_native_names_are_not_selected(self):
        points = POINTS + [{**POINT, 'code': '99', 'region_ja': 'test', 'label_ja': '金沢(test)'}]
        with self.assertRaises(d.DaylightError) as cm:
            d.resolve(points, '金沢')
        self.assertEqual(cm.exception.code, 'ambiguous_city')

    def test_bad_or_missing_menu_is_not_empty_catalog(self):
        for page in ('<html>denied</html>', catalog().replace('NAO_id', 'changed'),
                     catalog().replace('value="19"', 'value="18"'), catalog([2027, 2026]), catalog([2026, 2026])):
            with self.subTest(page=page[:60]), self.assertRaises(d.DaylightError) as cm:
                d.parse_catalog(page)
            self.assertEqual(cm.exception.code, 'source_schema_changed')


class ResultTests(unittest.TestCase):
    def parse(self, text=None, detail=False):
        return d.parse_result(result() if text is None else text, POINT, START, END, detail)

    def test_native_rounding_preserved_and_jst_timestamps(self):
        location, days, version = self.parse()
        self.assertEqual((location['latitude'], location['longitude'], location['elevation_m']), (36.5667, 136.65, 0))
        self.assertEqual(days[0], {'date': '2026-11-21', 'sunrise': '2026-11-21T06:37+09:00',
                                  'sunset': '2026-11-21T16:41+09:00', 'daylight_minutes': 605})
        # Rounded 16:41 minus 06:37 is 604, but the source's 長さ is 605.
        self.assertEqual(version, '2.1h')

    def test_detail_retains_transit_seconds_and_angles(self):
        _, days, _ = self.parse(detail=True)
        self.assertEqual(days[0]['solar_noon'], '2026-11-21T11:39:10+09:00')
        self.assertEqual(days[0]['sunset_azimuth_deg'], 245.6)

    def test_cross_year_dates_are_exact(self):
        rows = [
            ['2026/12/31', '6:59', '118.6', '11:50:03', '30.3', '16:41', '241.5', '9:42'],
            ['2027/01/01', '6:59', '118.5', '11:50:32', '30.3', '16:42', '241.6', '9:42'],
            ['2027/01/02', '7:00', '118.4', '11:51:00', '30.4', '16:43', '241.7', '9:43'],
        ]
        point = d.resolve(POINTS, '長野')
        _, days, _ = d.parse_result(result(rows, '長野(長野県): Nagano'), point, dt.date(2026, 12, 31), dt.date(2027, 1, 2))
        self.assertEqual(days[1]['date'], '2027-01-01')
        self.assertEqual(days[1]['daylight_minutes'], 582)

    def test_fuji_elevation_not_forced_to_sea_level(self):
        rows = [['2026/06/21', '4:18', '58.3', '11:46:49', '78.1', '19:16', '301.7', '14:58']]
        text = result(rows, '富士山頂(日本): Mt. Fuji', '緯度:35.3608° 経度:138.7275° 標高:3776.0 m 標準時:UT+9<sup>h</sup>')
        point = d.resolve(POINTS, '富士山頂')
        loc, days, _ = d.parse_result(text, point, dt.date(2026, 6, 21), dt.date(2026, 6, 21))
        self.assertEqual(loc['elevation_m'], 3776)
        self.assertEqual(days[0]['daylight_minutes'], 898)

    def test_missing_extra_duplicate_and_wrong_dates_fail(self):
        for rows in (ROWS[:-1], ROWS + [ROWS[-1]], [ROWS[0], ROWS[0], ROWS[2]],
                     [[*ROWS[0]], ['2026/11/24'] + ROWS[1][1:], ROWS[2]]):
            with self.subTest(rows=rows), self.assertRaises(d.DaylightError):
                self.parse(result(rows))

    def test_wrong_location_timezone_or_columns_fail(self):
        pages = [result(label='富山(富山県): Toyama'), result().replace('UT+9', 'UT+8'),
                 result().replace('日の出入り</h3>', '月の出入り</h3>'), result().replace('長さ</th>', 'changed</th>'),
                 result().replace('id="skipr"', 'id="gone"')]
        for page in pages:
            with self.subTest(page=page[:80]), self.assertRaises(d.DaylightError):
                self.parse(page)

    def test_invalid_clocks_duration_and_numbers_fail(self):
        for column, value in [(1, '24:01'), (1, '--:--'), (3, '11:99:10'), (5, '05:00'),
                              (7, '10:10'), (2, 'nan'), (4, '-10'), (6, '361')]:
            rows = [list(r) for r in ROWS]
            rows[0][column] = value
            with self.subTest(column=column, value=value), self.assertRaises(d.DaylightError):
                self.parse(result(rows))

    def test_negative_rounding_difference_is_also_valid(self):
        rows = [list(r) for r in ROWS]
        rows[0][7] = '10:03'
        self.assertEqual(self.parse(result(rows))[1][0]['daylight_minutes'], 603)


class CliTests(unittest.TestCase):
    def test_excessively_nested_source_html_returns_structured_unknown(self):
        raw = '<div>'*1100+'source layout changed'+'</div>'*1100
        with patch.object(d.Client, 'read', return_value=raw), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(d.main(['cities', '金沢']), 2)
        value = json.loads(out.getvalue())
        self.assertEqual(value['error']['code'], 'source_schema_changed')
        self.assertEqual(value['source_url'], d.BASE)

    def invoke(self, argv, pages=None):
        with patch.object(d.Client, 'read', side_effect=pages or [catalog(), result()]) as read, \
                contextlib.redirect_stdout(io.StringIO()) as out:
            code = d.main(argv)
        return code, json.loads(out.getvalue()), read

    def test_query_uses_two_reads_and_one_batched_daily_calculation(self):
        code, data, read = self.invoke(['query', '--city', '金泽', '--from', '2026-11-21', '--to', '2026-11-23'])
        self.assertEqual((code, data['status'], len(data['days'])), (0, 'ok', 3))
        self.assertEqual(read.call_count, 2)
        url = read.call_args[0][0]
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(url).query)
        for key, value in {'NAO_id': '18', 'lst': '9', 'len': '3', 'div': '1', 'divu': '3', 'lenu': '3', 'btn00': 'Go', 'drtn': '1'}.items():
            self.assertEqual(params[key], [value])
        self.assertEqual(data['source']['url'], url)

    def test_city_catalog_read_once_and_no_matches_is_not_found(self):
        for term, status, count in [('石川県', 'ok', 1), ('高山', 'not_found', 0)]:
            code, data, read = self.invoke(['cities', term], [catalog()])
            self.assertEqual((code, data['status'], len(data['locations'])), (0, status, count))
            read.assert_called_once_with(d.BASE)

    def test_outside_menu_years_does_not_submit_calculation(self):
        for argv in (['--date', '2040-01-01'], ['--from', '2036-12-31', '--to', '2037-01-01']):
            code, data, read = self.invoke(['query', '--city', '金沢'] + argv, [catalog()])
            self.assertEqual((code, data['status'], data['days']), (0, 'unavailable', []))
            read.assert_called_once()

    def test_unknown_city_has_candidates_and_no_calculation(self):
        code, data, read = self.invoke(['query', '--city', '金'], [catalog()])
        self.assertEqual((code, data['error']['code']), (2, 'city_not_found'))
        self.assertEqual(data['error']['candidates'], [POINT])
        read.assert_called_once()

    def test_new_menu_year_is_automatically_usable(self):
        rows = [['2037/11/21'] + ROWS[0][1:]]
        code, data, read = self.invoke(['query', '--city', '金沢', '--date', '2037-11-21'],
                                       [catalog(range(2017, 2038)), result(rows)])
        self.assertEqual((code, data['status']), (0, 'ok'))
        self.assertEqual(read.call_count, 2)

    def test_doctor_has_no_client_or_network(self):
        with patch.object(d, 'Client', side_effect=AssertionError('network')), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(d.main(['doctor']), 0)
        self.assertIs(json.loads(out.getvalue())['network_checked'], False)

    def test_default_date_is_jst(self):
        args = Mock(start=None, end=None, date=None)
        date, _ = d.date_range(args, Mock(), dt.datetime(2026, 11, 1, 16, tzinfo=dt.timezone.utc))
        self.assertEqual(date, dt.date(2026, 11, 2))

    def test_argument_errors_make_no_network_calls(self):
        cases = [['--date', '2026-02-30'], ['--date', '2026-1-1'], ['--from', '2026-11-01'],
                 ['--to', '2026-11-01'], ['--date', '2026-11-01', '--to', '2026-11-02'],
                 ['--date', '2026-11-01', '--from', '2026-11-01'],
                 ['--from', '2026-11-01', '--to', '2026-10-31'],
                 ['--from', '2026-11-01', '--to', '2026-12-02']]
        for argv in cases:
            with self.subTest(argv=argv), patch.object(d, 'Client', side_effect=AssertionError('network')), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                d.main(['query', '--city', '金沢'] + argv)
            self.assertEqual(cm.exception.code, 2)


class ClientTests(unittest.TestCase):
    def response(self, text=None, raw=None, status=200, headers=None):
        raw = (text or catalog()).encode('euc_jp') if raw is None else raw
        response = Mock(status=status, headers=headers or {'Content-Length': str(len(raw))})
        response.read.return_value = raw
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_success_eucjp_bytes_and_budget(self):
        response = self.response()
        with patch.object(d.urllib.request, 'build_opener') as factory, patch.object(d.time, 'sleep'):
            factory.return_value.open.return_value = response
            client = d.Client()
            self.assertEqual(client.read(d.BASE), catalog())
            self.assertEqual(client.read(d.BASE + '?x=1'), catalog())
            self.assertEqual(client.usage()['http_requests'], 2)
            self.assertEqual(client.usage()['response_body_bytes'], len(catalog().encode('euc_jp')) * 2)
            with self.assertRaises(d.DaylightError) as cm:
                client.read(d.BASE)
            self.assertEqual(cm.exception.code, 'request_budget_exhausted')
            self.assertEqual(factory.return_value.open.call_count, 2)
            self.assertEqual(factory.return_value.open.call_args.kwargs['timeout'], 15)

    def test_paces_request_starts(self):
        with patch.object(d.urllib.request, 'build_opener') as factory, patch.object(d.time, 'monotonic', return_value=0), \
                patch.object(d.time, 'sleep') as sleep:
            factory.return_value.open.return_value = self.response()
            client = d.Client()
            client.read(d.BASE)
            client.read(d.BASE + '?x=1')
            sleep.assert_called_once_with(1)
            self.assertEqual(client.usage()['pacing_ms'], 1000)

    def test_http_network_and_read_errors_are_structured_without_retry(self):
        errors = [(urllib.error.HTTPError(d.BASE, 429, 'busy', {}, None), 'http_error'),
                  (urllib.error.URLError('failed'), 'network_error'),
                  (http.client.BadStatusLine('bad'), 'network_error'),
                  (http.client.IncompleteRead(b'partial'), 'network_error'), (TimeoutError(), 'network_error')]
        for error, expected in errors:
            with self.subTest(error=type(error).__name__), patch.object(d.urllib.request, 'build_opener') as factory:
                response = self.response()
                response.read.side_effect = error
                factory.return_value.open.return_value = response
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = d.main(['query', '--city', '金沢'])
                data = json.loads(out.getvalue())
                self.assertEqual((code, data['error']['code']), (2, expected))
                factory.return_value.open.assert_called_once()

    def test_size_status_encoding_and_content_length_checks(self):
        cases = [(self.response(raw=b'x' * (d.MAX_BYTES + 1)), 'response_too_large'),
                 (self.response(status=206), 'unexpected_status'),
                 (self.response(headers={'Content-Length': '999999'}), 'incomplete_response'),
                 (self.response(raw=b'\xff'), 'source_schema_changed')]
        for response, expected in cases:
            with self.subTest(expected=expected), patch.object(d.urllib.request, 'build_opener') as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(d.DaylightError) as cm:
                    d.Client().read(d.BASE)
                self.assertEqual(cm.exception.code, expected)

    def test_redirect_and_unconfigured_urls_rejected(self):
        with self.assertRaises(d.DaylightError) as cm:
            d.RejectRedirect().redirect_request(None, None, 302, 'moved', {}, 'https://example.com')
        self.assertEqual(cm.exception.code, 'unexpected_redirect')
        with self.assertRaises(d.DaylightError) as cm:
            d.Client().read(d.BASE + '/unexpected')
        self.assertEqual(cm.exception.code, 'unsupported_url')


if __name__ == '__main__':
    unittest.main()
