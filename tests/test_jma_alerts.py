"""Offline source-shaped checks for timestamped VPWS50 warning snapshots."""
import contextlib
import copy
import datetime as dt
import http.client
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import Mock, patch
import urllib.error
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weather_alert_test", ROOT / "skills/japan-weather/scripts/weather.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)
a = w.jma_alerts
NOW = a.instant("2026-11-01T12:00:00+09:00")
PUBLISHED = "2026-11-01T02:50:48Z"
SNAPSHOT = "2026-11-01T11:50:00+09:00"
URL = "https://www.data.jma.go.jp/developer/xml/data/20261101025050_0_VPWS50_010000.xml"
OTHER_URL = "https://www.data.jma.go.jp/developer/xml/data/20261101024059_0_VPWS50_010000.xml"
FULL_CATALOG = w.load_catalog()
CATALOG = copy.deepcopy(FULL_CATALOG)
CATALOG["areas"]["class20s"] = {k: v for k, v in CATALOG["areas"]["class20s"].items() if k in ("1720100", "0121400")}


def feed(entries=None):
    entries = entries or [(URL, PUBLISHED, a.TITLE)]
    text = '<feed xmlns="http://www.w3.org/2005/Atom"><updated>2026-11-01T12:00:00+09:00</updated>'
    for url, updated, title in entries:
        text += '<entry><title>{}</title><id>{}</id><updated>{}</updated><link type="application/xml" href="{}"/></entry>'.format(title, url, updated, url)
    return (text + '</feed>').encode()


def kind(name=None, code=None, status=a.NONE, issued="2026-11-01T08:01:00+09:00", extra=""):
    identity = '' if name is None else '<Name>{}</Name><Code>{}</Code>'.format(name, code)
    return '<Kind>{}<Status>{}</Status><DateTime type="発表時刻">{}</DateTime>{}</Kind>'.format(identity, status, issued, extra)


def item(code, name, kinds):
    return '<Item>{}<Area><Name>{}</Name><Code>{}</Code></Area></Item>'.format(kinds, name, code)


def snapshot(items=None):
    if items is None:
        items = [item('1720100', '金沢市', kind()),
                 item('0121400', '稚内市', kind('波浪注意報', '16', '継続', '2026-10-31T15:20:00+09:00'))]
    return ('''<?xml version="1.0" encoding="UTF-8"?>
<Report xmlns="http://xml.kishou.go.jp/jmaxml1/">
<Control><Title>気象警報・注意報（Ｒ０６）（集約通報）</Title><DateTime>2026-11-01T02:50:48Z</DateTime><Status>通常</Status><EditorialOffice>気象庁本庁</EditorialOffice><PublishingOffice>気象庁</PublishingOffice></Control>
<Head xmlns="http://xml.kishou.go.jp/jmaxml1/informationBasis1/"><Title>警戒・注意事項集約定時通報</Title><ReportDateTime>2026-11-01T11:50:00+09:00</ReportDateTime><TargetDateTime>2026-11-01T11:50:00+09:00</TargetDateTime><InfoType>発表</InfoType><InfoKind>気象警報・注意報</InfoKind><InfoKindVersion>1.5_0</InfoKindVersion><Headline><Information><Item><Kind><Code>99</Code></Kind></Item></Information></Headline></Head>
<Body xmlns="http://xml.kishou.go.jp/jmaxml1/body/meteorology1/"><Warning type="気象警報・注意報（市町村等）">''' + ''.join(items) + '</Warning></Body></Report>').encode()


def selected(raw=None, now=NOW):
    return a.select_entry(feed() if raw is None else raw, now)


def parse(raw=None, now=NOW, detail=False):
    return a.parse_snapshot(snapshot() if raw is None else raw, selected(), CATALOG['areas']['class20s'], now, detail)


def mutate(raw, path, value):
    root = ET.fromstring(raw)
    root.find(path).text = value
    return ET.tostring(root, encoding='utf-8')


class FeedTests(unittest.TestCase):
    def test_latest_control_time_selected_independent_of_order(self):
        for entries in ([(OTHER_URL, '2026-11-01T02:40:57Z', a.TITLE), (URL, PUBLISHED, a.TITLE)],
                        [(URL, PUBLISHED, a.TITLE), (OTHER_URL, '2026-11-01T02:40:57Z', a.TITLE)]):
            self.assertEqual(selected(feed(entries))['url'], URL)

    def test_identical_duplicate_entry_deduplicated_but_conflicts_rejected(self):
        self.assertEqual(selected(feed([(URL, PUBLISHED, a.TITLE)] * 2))['url'], URL)
        with self.assertRaises(w.WeatherError):
            selected(feed([(URL, PUBLISHED, a.TITLE), (URL, '2026-11-01T02:40:57Z', a.TITLE)]))
        with self.assertRaises(w.WeatherError):
            selected(feed([(URL, PUBLISHED, a.TITLE), (OTHER_URL, PUBLISHED, a.TITLE)]))

    def test_bad_latest_entry_cannot_fall_back_to_older_valid_one(self):
        for url, title in [('https://example.com/new_VPWS50_.xml', a.TITLE),
                           (URL, 'changed product')]:
            with self.subTest(url=url), self.assertRaises(w.WeatherError):
                selected(feed([(OTHER_URL, '2026-11-01T02:40:57Z', a.TITLE), (url, PUBLISHED, title)]))

    def test_missing_entry_and_mismatched_link_rejected(self):
        for raw in (b'<feed xmlns="http://www.w3.org/2005/Atom"><updated>2026-11-01T12:00:00+09:00</updated></feed>',
                    feed().replace(('href="' + URL).encode(), b'href="https://example.com/a')):
            with self.assertRaises(w.WeatherError):
                selected(raw)

    def test_stale_and_future_feed_snapshots_rejected(self):
        for now, expected in [(NOW + dt.timedelta(hours=1), 'stale_alert_snapshot'),
                              (NOW - dt.timedelta(hours=1), 'future_alert_snapshot')]:
            with self.subTest(expected=expected), self.assertRaises(w.WeatherError) as cm:
                selected(now=now)
            self.assertEqual(cm.exception.code, expected)

    def test_future_feed_header_is_not_hidden_by_valid_entry(self):
        raw = feed().replace(b'<updated>2026-11-01T12:00:00+09:00</updated>', b'<updated>2026-11-01T12:01:00+09:00</updated>')
        with self.assertRaises(w.WeatherError) as cm:
            selected(raw)
        self.assertEqual(cm.exception.code, 'future_alert_snapshot')

    def test_bad_xml_encoding_entities_namespace_and_timestamp_rejected(self):
        cases = [b'<feed>', b'\xff', feed().replace(b'2005/Atom', b'2005/Other'),
                 feed().replace(b'<feed ', b'<!DOCTYPE feed [<!ENTITY x "test">]><feed '),
                 feed().decode().encode('utf-16'), feed().replace(PUBLISHED.encode(), b'2026-11-01T02:50:48')]
        for raw in cases:
            with self.subTest(raw=raw[:30]), self.assertRaises(w.WeatherError):
                selected(raw)


class SnapshotTests(unittest.TestCase):
    def test_current_none_and_old_but_active_kind_are_distinct(self):
        areas, metadata = parse()
        self.assertEqual(areas['1720100']['alert_state'], 'none')
        self.assertIs(areas['1720100']['has_active_alerts'], False)
        self.assertEqual(areas['1720100']['no_alert_status']['status_ja'], a.NONE)
        self.assertEqual(areas['0121400']['alert_state'], 'active')
        self.assertEqual(areas['0121400']['alerts'][0]['issued_at'], '2026-10-31T15:20:00+09:00')
        self.assertEqual((metadata['snapshot_age_seconds'], metadata['max_snapshot_age_seconds']), (600, 1800))

    def test_downgrade_remains_active_and_previous_warning_is_context(self):
        extra = '<LastKind><Name>レベル３大雨警報</Name><Code>03</Code></LastKind><Condition>test condition</Condition><Addition><Note>突風</Note><Note>ひょう</Note></Addition>'
        raw = snapshot([item('1720100', '金沢市', kind('レベル２大雨注意報', '10', '警報から注意報', extra=extra)),
                        item('0121400', '稚内市', kind())])
        areas, _ = parse(raw, detail=True)
        alerts = areas['1720100']['alerts']
        self.assertEqual(len(alerts), 1)
        self.assertEqual(alerts[0]['code'], '10')
        self.assertEqual(alerts[0]['previous']['code'], '03')
        self.assertEqual(alerts[0]['notes_ja'], ['突風', 'ひょう'])
        self.assertEqual(alerts[0]['condition_ja'], 'test condition')
        self.assertIs(areas['1720100']['has_active_alerts'], True)

    def test_release_is_not_active_and_is_preserved(self):
        raw = snapshot([item('1720100', '金沢市', kind('雷注意報', '14', '解除')),
                        item('0121400', '稚内市', kind())])
        areas, _ = parse(raw)
        self.assertEqual(areas['1720100']['alert_state'], 'cleared')
        self.assertEqual(areas['1720100']['alerts'], [])
        self.assertEqual(areas['1720100']['released_alerts'][0]['code'], '14')

    def test_correction_is_a_valid_complete_snapshot(self):
        raw = mutate(snapshot(), './/' + a.HEAD + 'InfoType', '訂正')
        self.assertEqual(parse(raw)[1]['info_type_ja'], '訂正')

    def test_tests_training_other_product_and_version_fail(self):
        for path, value in [('./' + a.REPORT + 'Control/' + a.REPORT + 'Status', '試験'),
                            ('./' + a.REPORT + 'Control/' + a.REPORT + 'Status', '訓練'),
                            ('.//' + a.HEAD + 'InfoType', '取消'),
                            ('.//' + a.HEAD + 'InfoKindVersion', '2.0'),
                            ('.//' + a.HEAD + 'Title', 'other product')]:
            with self.subTest(value=value), self.assertRaises(w.WeatherError):
                parse(mutate(snapshot(), path, value))

    def test_feed_control_mismatch_and_target_report_mismatch_fail(self):
        for path, value in [('./' + a.REPORT + 'Control/' + a.REPORT + 'DateTime', '2026-11-01T02:50:49Z'),
                            ('.//' + a.HEAD + 'ReportDateTime', '2026-11-01T11:40:00+09:00')]:
            with self.subTest(path=path), self.assertRaises(w.WeatherError):
                parse(mutate(snapshot(), path, value))

    def test_fresh_control_cannot_hide_stale_target(self):
        root = ET.fromstring(snapshot())
        for tag in ('ReportDateTime', 'TargetDateTime'):
            root.find('.//' + a.HEAD + tag).text = '2026-11-01T11:00:00+09:00'
        with self.assertRaises(w.WeatherError) as cm:
            parse(ET.tostring(root))
        self.assertEqual(cm.exception.code, 'stale_alert_snapshot')

    def test_exact_age_boundary_and_future_are_enforced(self):
        self.assertEqual(parse(now=a.instant('2026-11-01T12:20:00+09:00'))[1]['snapshot_age_seconds'], 1800)
        for now in ('2026-11-01T12:20:01+09:00', '2026-11-01T11:49:00+09:00'):
            with self.assertRaises(w.WeatherError):
                parse(now=a.instant(now))

    def test_missing_extra_duplicate_and_empty_area_states_fail(self):
        cases = [snapshot([item('1720100', '金沢市', kind())]),
                 snapshot([item('1720100', '金沢市', kind()), item('0121400', '稚内市', kind()), item('9999999', 'new area', kind())]),
                 snapshot([item('1720100', '金沢市', kind()), item('1720100', '金沢市', kind())]),
                 snapshot([item('1720100', '金沢市', ''), item('0121400', '稚内市', kind())]),
                 snapshot([])]
        for raw in cases:
            with self.subTest(raw=raw[-120:]), self.assertRaises(w.WeatherError):
                parse(raw)

    def test_unknown_duplicate_mixed_and_malformed_kind_states_fail(self):
        bad = [kind(status='unknown'), kind() + kind('雷注意報', '14', '継続'),
               kind('雷注意報', '14', '継続') * 2, kind('雷注意報', '14', a.NONE),
               kind('雷注意報', '00', '継続'), kind('雷注意報', '14', '継続', '2026-11-01T11:51:00+09:00'),
               kind().replace('type="発表時刻"', 'type="other"'),
               kind('雷注意報', '14', '継続', extra='<Addition><Note/></Addition>')]
        for kinds in bad:
            raw = snapshot([item('1720100', '金沢市', kinds), item('0121400', '稚内市', kind())])
            with self.subTest(kinds=kinds[:70]), self.assertRaises(w.WeatherError):
                parse(raw)

    def test_missing_or_duplicate_section_and_truncation_fail(self):
        root = ET.fromstring(snapshot())
        body = root.find(a.BODY + 'Body')
        body.append(copy.deepcopy(body[0]))
        for raw in [ET.tostring(root), snapshot().replace(a.AREA_TYPE.encode(), 'other section'.encode()), snapshot()[:-20]]:
            with self.assertRaises(w.WeatherError):
                parse(raw)


class CliTests(unittest.TestCase):
    def response(self, raw):
        response = Mock(status=200, headers={'Content-Length': str(len(raw))})
        response.read.return_value = raw
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def invoke(self, argv, bodies=None, now=NOW):
        with patch.object(w, 'load_catalog', return_value=CATALOG), patch.object(w, 'now_jst', return_value=now), \
                patch.object(a.urllib.request, 'build_opener') as factory, patch.object(a.time, 'sleep'), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            factory.return_value.open.side_effect = [self.response(raw) for raw in (bodies or [feed(), snapshot()])]
            code = w.main(argv)
        return code, json.loads(output.getvalue()), factory.return_value.open

    def test_multiple_cities_share_one_feed_and_snapshot(self):
        code, data, opened = self.invoke(['alerts', '--city', '金泽', '--city', '稚内市'])
        self.assertEqual((code, data['status']), (0, 'ok'))
        self.assertEqual([c['alert_state'] for c in data['cities']], ['none', 'active'])
        self.assertEqual(data['source']['snapshot_at'], SNAPSHOT)
        self.assertEqual(data['usage']['http_requests'], 2)
        self.assertEqual(data['usage']['response_body_bytes'], len(feed()) + len(snapshot()))
        self.assertEqual([call.args[0].full_url for call in opened.call_args_list], [a.FEED_URL, URL])
        self.assertIn('separate river flood-warning products', data['scope']['excluded'])

    def test_stale_feed_never_requests_body_or_reports_no_alerts(self):
        code, data, opened = self.invoke(['alerts', '--city', '金泽'], now=NOW + dt.timedelta(hours=1))
        self.assertEqual((code, data['alert_state']), (2, 'unknown'))
        self.assertNotIn('cities', data)
        self.assertNotIn('alerts', data)
        self.assertEqual(data['manual_check_url'], a.PAGE_URL)
        opened.assert_called_once()

    def test_missing_area_causes_unknown_for_whole_command(self):
        code, data, _ = self.invoke(['alerts', '--city', '金泽'], [feed(), snapshot([item('0121400', '稚内市', kind())])])
        self.assertEqual((code, data['alert_state'], data['error']['code']), (2, 'unknown', 'alert_area_catalog_mismatch'))

    def test_bad_city_and_option_values_do_not_read_network(self):
        for argv in [['--city', 'not a city'], ['--city', '金泽', '--timeout', 'nan'],
                     ['--city', '金泽', '--timeout', '0'], ['--city', '金泽'] * 11]:
            with self.subTest(argv=argv):
                code, data, opened = self.invoke(['alerts'] + argv)
                self.assertEqual((code, data['alert_state']), (2, 'unknown'))
                opened.assert_not_called()

    def test_date_option_is_not_a_historical_or_future_warning_query(self):
        with patch.object(a.Client, 'read', side_effect=AssertionError('network')), contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
            w.main(['alerts', '--city', '金泽', '--date', '2026-12-01'])
        self.assertEqual(cm.exception.code, 2)

    def test_reference_aliases_require_explicit_scope(self):
        for query in ('东京', 'Tokyo', '東京', '富山', '富山市', '長野', '长野', '奈良', '横滨'):
            with self.subTest(query=query), self.assertRaises(w.WeatherError) as cm:
                w.resolve_alert_city(query, FULL_CATALOG)
            self.assertEqual(cm.exception.code, 'alert_scope_required')
            self.assertGreater(cm.exception.details['total_candidates'], 1)
        for query, code in [('金泽', '1720100'), ('千代田区', '1310100'), ('2020111', '2020111'), ('長野市鬼無里戸隠', '2020112')]:
            self.assertEqual(w.resolve_alert_city(query, FULL_CATALOG)['code'], code)
        # Existing forecast reference behavior remains available to forecasts.
        self.assertEqual(w.resolve_city('Tokyo', FULL_CATALOG)['code'], '1310100')


class ClientTests(unittest.TestCase):
    def response(self, raw=b'body', status=200, headers=None):
        response = Mock(status=status, headers=headers or {'Content-Length': str(len(raw))})
        response.read.return_value = raw
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def test_pacing_two_read_budget_and_usage(self):
        with patch.object(a.urllib.request, 'build_opener') as factory, patch.object(a.time, 'monotonic', return_value=0), patch.object(a.time, 'sleep') as sleep:
            factory.return_value.open.return_value = self.response()
            client = a.Client()
            client.read(a.FEED_URL)
            client.read(URL)
            sleep.assert_called_once_with(1)
            self.assertEqual(client.usage()['http_requests'], 2)
            self.assertEqual(client.usage()['response_body_bytes'], 8)
            with self.assertRaises(w.WeatherError):
                client.read(URL)
            self.assertEqual(factory.return_value.open.call_count, 2)

    def test_denial_protocol_and_read_errors_return_unknown_without_retry(self):
        failures = [urllib.error.HTTPError(a.FEED_URL, 429, 'busy', {'Retry-After': '60'}, None),
                    urllib.error.URLError('failed'), http.client.IncompleteRead(b'partial'), http.client.BadStatusLine('bad'), TimeoutError()]
        for failure in failures:
            with self.subTest(failure=type(failure).__name__), patch.object(a.urllib.request, 'build_opener') as factory, contextlib.redirect_stdout(io.StringIO()) as out:
                response = self.response()
                response.read.side_effect = failure
                factory.return_value.open.return_value = response
                code = w.main(['alerts', '--city', '金泽'])
                data = json.loads(out.getvalue())
                self.assertEqual((code, data['alert_state']), (2, 'unknown'))
                factory.return_value.open.assert_called_once()
                if isinstance(failure, urllib.error.HTTPError):
                    self.assertEqual(data['error']['retry_after'], '60')

    def test_status_length_size_and_redirect_limits(self):
        for response, error in [(self.response(status=206), 'unexpected_status'),
                                (self.response(headers={'Content-Length': '100'}), 'incomplete_response'),
                                (self.response(raw=b'x' * (a.MAX_BYTES + 1)), 'response_too_large')]:
            with self.subTest(error=error), patch.object(a.urllib.request, 'build_opener') as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(w.WeatherError) as cm:
                    a.Client().read(a.FEED_URL)
                self.assertEqual(cm.exception.code, error)
        with self.assertRaises(w.WeatherError) as cm:
            a.RejectRedirect().redirect_request(None, None, 302, 'moved', {}, a.FEED_URL)
        self.assertEqual(cm.exception.code, 'unexpected_redirect')

    def test_other_hosts_and_legacy_warning_json_never_requested(self):
        with patch.object(a.urllib.request, 'build_opener') as factory:
            for url in ('https://example.com/VPWS50.xml', 'https://www.jma.go.jp/bosai/warning/data/warning/170000.json', URL + '?extra=1'):
                with self.assertRaises(w.WeatherError):
                    a.Client().read(url)
            factory.return_value.open.assert_not_called()


if __name__ == '__main__':
    unittest.main()
