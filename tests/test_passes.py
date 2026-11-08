"""Offline contracts for official pass catalogs, product boundaries and transport."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch
import urllib.error

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/japan-passes/scripts'
sys.path.insert(0, str(SCRIPTS))
import pass_source as s
import pass_providers as p
import passes


def page(title, body):
    return ('<html><head><title>' + title + '</title></head><body><main>' + body + '</main></body></html>').encode()


WEST = p.WEST + 'jrwest-rail-pass/'
WEST_PRODUCT = WEST + 'kansai/'
WEST_CARD = ('<li class="item"><h2>Kansai Area Pass<span class="note">Sales ended as of September 30, 2026.</span></h2>'
             '<a href="' + WEST_PRODUCT + '">Information</a><a href="/global/en/ticket/pass/reservation_form/kansai/">Book</a></li>')


class FakeClient:
    def __init__(self, documents):
        self.documents = documents
        self.calls = []
        self.last_source = None

    def read(self, url, transport='python'):
        self.calls.append((url, transport))
        self.last_source = {'url': url, 'retrieved_at': 'test', 'publisher_updated_at': None}
        value = self.documents[url]
        if isinstance(value, Exception):
            raise value
        return value, self.last_source


def args(provider, url, **overrides):
    values = dict(provider=provider, url=url, expect=None, section=[], outline=False, max_blocks=120)
    values.update(overrides)
    return argparse.Namespace(**values)


class CatalogTests(unittest.TestCase):
    def test_west_native_name_notice_and_information_link(self):
        records = p.discover('jr-west', s.Page(page('JR-WEST Rail Pass', WEST_CARD)), WEST)
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]['name'], 'Kansai Area Pass')
        self.assertEqual(records[0]['url'], WEST_PRODUCT)
        self.assertEqual(records[0]['sales_status']['state'], 'ended_or_suspended')

    def test_central_catalog_skips_booking_link(self):
        raw = page('Tourist Pass', '<section id="touristpass"><div class="item other"><h3>Mt. Fuji-Shizuoka Area</h3>'
                   '<a class="btn-detail" href="/en/fuji_shizuoka/">Details</a><a href="#otr">Book</a></div></section>')
        result = p.discover('jr-central', s.Page(raw), p.PROVIDERS['jr-central']['catalogs'][0])
        self.assertEqual(result[0]['name'], 'Mt. Fuji-Shizuoka Area Tourist Pass')
        self.assertEqual(result[0]['url'], 'https://touristpass.jp/en/fuji_shizuoka/')

    def test_hokkaido_catalog_native_fragments(self):
        raw = page('Hokkaido Rail Pass', '<div><h3>Hokkaido Rail Pass</h3><a href="railpass/index.html#hrp">Details</a></div>')
        result = p.discover('jr-hokkaido', s.Page(raw), p.PROVIDERS['jr-hokkaido']['catalogs'][0])
        self.assertTrue(result[0]['url'].endswith('#hrp'))

    def test_shikoku_suspended_sale_retains_exception(self):
        raw = page('SHIKOKU', '<a href="?pref=all">ALL SHIKOKU Rail Pass</a><a href="?pref=kagawa">KAGAWA Mini Rail &amp; Ferry Pass</a>'
                   '<p class="c-note-highlight pass-status-note -kagawa">This pass is no longer available for purchase. '
                   'Passes purchased on or before September 30 may still be used until they expire.</p>')
        records = p.discover('jr-shikoku', s.Page(raw), p.PROVIDERS['jr-shikoku']['catalogs'][0])
        self.assertEqual(records[0]['sales_status']['state'], 'unknown')
        self.assertIn('September 30', records[1]['sales_status']['evidence'])
        self.assertEqual(records[1]['sales_status']['state'], 'ended_or_suspended')

    def test_missing_or_conflicting_catalog_unknown(self):
        for body in ('<p>No cards</p>', WEST_CARD + WEST_CARD.replace('Kansai Area Pass', 'Different Pass')):
            with self.subTest(body=body[:20]), self.assertRaises(s.Error):
                p.discover('jr-west', s.Page(page('JR-WEST', body)), WEST)

    def test_nationwide_is_family_not_one_normalized_price(self):
        result = p.discover('jr-group', s.Page(page('JAPAN RAIL PASS', '<h1>JAPAN RAIL PASS prices</h1>')), p.PROVIDERS['jr-group']['catalogs'][0])
        self.assertEqual(result[0]['kind'], 'pass_family')
        self.assertNotIn('price', result[0])

    def test_reference_only_providers_make_no_request(self):
        client = FakeClient({})
        result = passes.catalog(client, argparse.Namespace(provider='jr-east', limit=50, query=None))
        self.assertEqual(result['status'], 'unavailable')
        self.assertEqual(result['entries'], [])
        self.assertEqual(client.calls, [])
        self.assertIsNone(result['provider_coverage'][0]['source'])

    def test_bad_options_are_checked_before_network(self):
        client = FakeClient({})
        for options in ({'expect': ' '}, {'section': [' ']}, {'max_blocks': 0}):
            with self.subTest(options=options), self.assertRaises(s.Error):
                passes.show(client, args('jr-west', WEST_PRODUCT, **options))
        with self.assertRaises(s.Error):
            passes.catalog(client, argparse.Namespace(provider='all', limit=50, query=' '))
        self.assertEqual(client.calls, [])

    def test_all_providers_keep_other_successes(self):
        def catalog(client, provider):
            if provider != 'jr-group':
                raise s.Error('unavailable', 'Not readable')
            return [{'name': 'JAPAN RAIL PASS', 'region_hints': []}], [{'url': 'test'}]
        with patch.object(p, 'catalog', side_effect=catalog):
            result = passes.catalog(FakeClient({}), argparse.Namespace(provider='all', limit=50, query='JAPAN'))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['returned_count'], 1)
        self.assertEqual(len(result['provider_coverage']), 7)

    def test_url_boundary_rejects_transactions_credentials_and_foreign_hosts(self):
        for url in ('https://evil.example/en/fuji_shizuoka/', 'https://touristpass.jp/en/fuji_shizuoka/?book=1',
                    ('https://user:pass' + '@' + 'touristpass.jp/en/fuji_shizuoka/'), 'http://touristpass.jp/en/fuji_shizuoka/',
                    'https://touristpass.jp:443/en/fuji_shizuoka/',
                    'https://www.westjr.co.jp/global/en/ticket/pass/reservation_form/kansai/'):
            with self.subTest(url=url):
                self.assertFalse(p.allowed(url))


class ProductTests(unittest.TestCase):
    def test_live_binding_rejects_uncatalogued_information_page(self):
        client = FakeClient({WEST: page('JR-WEST', WEST_CARD), p.WEST + 'other/': page('JR-WEST', WEST_CARD)})
        with self.assertRaises(s.Error):
            passes.show(client, args('jr-west', WEST + 'arbitrary/'))
        self.assertEqual(len(client.calls), 2)

    def test_hokkaido_selected_pass_and_common_conditions_only(self):
        url = p.PROVIDERS['jr-hokkaido']['catalogs'][0]
        product = url + 'railpass/index.html#hrp'
        client = FakeClient({url: page('Hokkaido', '<div><h3>Hokkaido Rail Pass</h3><a href="railpass/index.html#hrp">Details</a></div>'),
                             product: page('Hokkaido', '<section id="hrp"><h2>Hokkaido Rail Pass</h2><p>Hokkaido price</p></section>'
                             '<section id="furano"><h2>Furano Pass</h2><p>Different price</p></section>'
                             '<section id="reserve"><h2>Reservation</h2><p>Common reservations</p></section>'
                             '<section id="use"><p>All non-Japanese passport holders</p></section>'
                             '<section id="other"><h2>Other</h2><p>Green car requires additional charges</p></section>')})
        value = passes.show(client, args('jr-hokkaido', product))
        serialized = json.dumps(value['documents'])
        self.assertNotIn('Different price', serialized)
        self.assertIn('Common reservations', serialized)
        self.assertEqual(value['status'], 'ok')
        self.assertIn('Green car requires additional charges', serialized)
        self.assertIn('All non-Japanese passport holders', serialized)
        self.assertEqual(value['interpretation']['eligibility_decision'], 'not_evaluated')

    def test_missing_hokkaido_common_terms_stay_partial(self):
        url = p.PROVIDERS['jr-hokkaido']['catalogs'][0]
        product = url + 'railpass/index.html#hrp'
        client = FakeClient({url: page('Hokkaido', '<div><h3>Hokkaido Rail Pass</h3><a href="railpass/index.html#hrp">Details</a></div>'),
                             product: page('Hokkaido', '<section id="hrp"><h2>Hokkaido Rail Pass</h2><p>Product price</p></section>')})
        result = passes.show(client, args('jr-hokkaido', product))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual({e['section'] for e in result['conditions_errors']}, {'reserve', 'use', 'other'})
        self.assertIn('Product price', json.dumps(result['documents']))

    def test_shikoku_variant_scope_does_not_mix_hidden_product(self):
        doc = s.Page(page('SHIKOKU', '<div class="js-toggle-content -all"><h1>ALL SHIKOKU</h1></div>'
                         '<div class="js-toggle-content -kagawa"><h1>KAGAWA</h1></div>'))
        selected = p.scope('jr-shikoku', doc, p.PROVIDERS['jr-shikoku']['catalogs'][0] + '?pref=all')
        self.assertEqual(selected.text(), 'ALL SHIKOKU')

    def test_central_conditions_are_product_scoped(self):
        doc = s.Page(page('Tourist Pass', '<section id="conditions_for_use"><p>Temporary Visitor</p></section>'
                         '<section id="important_notes"><p>Common note</p></section>'
                         '<div class="guide_takayama"><p>Takayama only</p></div><div class="guide_alpine"><p>Alpine only</p></div>'))
        selected = p.conditions('jr-central', doc, 'https://touristpass.jp/en/takayama_hokuriku/')
        self.assertEqual([n.text() for _, n in selected], ['Temporary Visitor', 'Takayama only', 'Common note'])

    def test_supplement_failure_preserves_nationwide_prices(self):
        provider = p.PROVIDERS['jr-group']
        url = provider['catalogs'][0]
        client = FakeClient({url: page('JAPAN RAIL PASS', '<h1>JAPAN RAIL PASS prices</h1><p>7 days price</p>'),
                             **{u: s.Error('http_error', 'Denied') for u in provider['conditions']}})
        value = passes.show(client, args('jr-group', url))
        self.assertEqual(value['status'], 'partial')
        self.assertEqual(len(value['conditions_errors']), 2)
        self.assertIn('7 days price', json.dumps(value['documents']))

    def test_filters_and_output_limit_retain_dated_notices(self):
        url = p.PROVIDERS['jr-group']['catalogs'][0]
        doc = page('JAPAN RAIL PASS', '<h1>JAPAN RAIL PASS</h1><h2>Conditions</h2>'
                   '<p>From October 1, 2026 eligibility changes.</p><h2>Prices</h2><p>Online price</p><p>Agency price</p>')
        client = FakeClient({url: doc, **{u: page('JAPAN RAIL PASS', '<p>Common conditions</p>') for u in p.PROVIDERS['jr-group']['conditions']}})
        result = passes.show(client, args('jr-group', url, section=['Prices'], max_blocks=1))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['returned_blocks'], 1)
        self.assertIn('October 1', result['documents'][0]['notices'][0]['text'])
        self.assertNotIn('Common conditions', json.dumps([d['sections'] for d in result['documents']]))

    def test_outline_retains_heading_paths_without_content(self):
        url = p.PROVIDERS['jr-group']['catalogs'][0]
        client = FakeClient({url: page('JAPAN RAIL PASS', '<h1>JAPAN RAIL PASS</h1><h2>Online prices</h2><p>Price</p>'),
                             **{u: page('JAPAN RAIL PASS', '<h2>Conditions</h2><p>Terms</p>') for u in p.PROVIDERS['jr-group']['conditions']}})
        result = passes.show(client, args('jr-group', url, outline=True))
        self.assertEqual(result['returned_blocks'], 0)
        self.assertTrue(any('Online prices' in r['heading_path'] for r in result['outline']))
        self.assertTrue(all(not d['sections'] for d in result['documents']))

    def test_filtered_map_does_not_hide_that_service_terms_were_omitted(self):
        url = p.PROVIDERS['jr-group']['catalogs'][0]
        doc = page('JAPAN RAIL PASS', '<h1>JAPAN RAIL PASS</h1>'
                   '<h2>Valid routes</h2><p>See map.</p>'
                   '<h2>Valid services</h2><p>Airport Connector is included.</p>'
                   '<h2>Exceptions</h2><p>Premium seating requires another ticket.</p>')
        client = FakeClient({url: doc, **{u: page('JAPAN RAIL PASS', '<h2>Eligibility</h2><p>Visitor conditions</p>')
                                        for u in p.PROVIDERS['jr-group']['conditions']}})
        filtered = passes.show(client, args('jr-group', url, section=['Valid routes']))
        self.assertEqual(filtered['status'], 'ok')
        self.assertNotIn('Airport Connector', json.dumps(filtered['documents']))
        selection = filtered['section_selection']
        self.assertEqual(selection['scope'], 'filtered_view_not_complete_terms')
        self.assertEqual(selection['unmatched_filters'], [])
        omitted = [v['heading_path'][-1] for v in selection['omitted_sections']]
        self.assertIn('Valid services', omitted)
        self.assertIn('Exceptions', omitted)
        self.assertIn('Eligibility', omitted)
        self.assertTrue(any(v['document'] > 0 for v in selection['omitted_sections']))
        complete = passes.show(client, args('jr-group', url))
        self.assertIsNone(complete['section_selection'])
        self.assertIn('Airport Connector is included', json.dumps(complete['documents']))
        self.assertIn('Premium seating requires another ticket', json.dumps(complete['documents']))

    def test_unmatched_filter_is_partial_even_when_another_filter_matches(self):
        url = p.PROVIDERS['jr-group']['catalogs'][0]
        client = FakeClient({url: page('JAPAN RAIL PASS', '<h1>JAPAN RAIL PASS</h1><h2>Prices</h2><p>Price</p>'),
                             **{u: page('JAPAN RAIL PASS', '<h2>Conditions</h2><p>Terms</p>')
                                for u in p.PROVIDERS['jr-group']['conditions']}})
        result = passes.show(client, args('jr-group', url, section=['Prices', 'Covered routes']))
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['section_selection']['unmatched_filters'], ['Covered routes'])
        self.assertIn('Price', json.dumps(result['documents']))
        self.assertFalse(result['output_truncated'])

    def test_identity_mismatch_fails(self):
        doc = s.Page(page('JR-WEST', '<h1>Some other pass</h1>'))
        with self.assertRaises(s.Error):
            p.check_product('jr-west', {'name': 'Kansai Area Pass'}, doc.main, doc)


class ExtractionTests(unittest.TestCase):
    def test_price_channels_spans_and_symbols_are_not_flattened(self):
        doc = s.Page(page('JAPAN RAIL PASS', '<h1>Types and prices</h1><h2>Online</h2><table>'
                         '<tr><th rowspan="2">Green</th><th colspan="2">7 days</th></tr>'
                         '<tr><td>Adult 100</td><td>Child 50<img src="/symbol.svg" alt="Eligible"></td></tr></table>'
                         '<h2>Overseas agency</h2><table><tr><th>Adult</th><td>110</td></tr></table>'))
        records = s.sections(doc.main, 'https://japanrailpass.net/en/purchase/price/')
        self.assertEqual([r['heading_path'][-1] for r in records], ['Online', 'Overseas agency'])
        table = records[0]['blocks'][0]['value']
        self.assertEqual(table[0][0]['rowspan'], 2)
        self.assertEqual(table[0][1]['colspan'], 2)
        self.assertEqual(table[1][1]['images'][0]['alt'], 'Eligible')
        self.assertEqual(table[1][1]['images'][0]['state'], 'reference_only_not_ocr')

    def test_stop_marketing_does_not_swallow_later_terms(self):
        doc = s.Page(page('JR-WEST', '<h2>Prices</h2><p>Price</p><h2>Destinations</h2><div><p>Advertisement</p></div>'
                         '<section><h2>Eligibility</h2><p>Temporary Visitor</p></section>'))
        result = json.dumps(s.sections(doc.main, WEST))
        self.assertNotIn('Advertisement', result)
        self.assertIn('Temporary Visitor', result)

    def test_unknown_page_identity_and_encoding(self):
        for raw in (b'not html', page('Access denied', '<p>Blocked</p>'), b'\xff'):
            with self.subTest(raw=raw[:20]), self.assertRaises(s.Error):
                s.Page(raw)

    def test_commented_old_prices_and_scripts_are_not_published_facts(self):
        doc = s.Page(page('SHIKOKU', '<h2>Eligibility</h2><p>Active terms</p>'
                         '<!-- <h2>Pricing</h2><p>Old 6,000 yen</p> -->'
                         '<script>var oldPrice = 6000;</script>'))
        result = json.dumps(s.sections(doc.main, 'https://shikoku-railwaytrip.com/pass-information/'))
        self.assertIn('Active terms', result)
        self.assertNotIn('6,000', result)
        self.assertNotIn('6000', result)

    def test_invalid_table_span_fails(self):
        doc = s.Page(page('JR-WEST', '<table><tr><td colspan="999">Price</td></tr></table>'))
        with self.assertRaises(s.Error):
            s.sections(doc.main, WEST)


class TransportTests(unittest.TestCase):
    def response(self, body=b'<html/>', status=200):
        result = unittest.mock.MagicMock()
        response = result.__enter__.return_value
        response.status = status
        response.headers = {}
        response.read.return_value = body
        return result

    def test_cache_fragments_budget_and_pacing(self):
        client = s.Client(lambda u: True, budget=2)
        with patch.object(client.opener, 'open', return_value=self.response()) as op, patch.object(s.time, 'sleep') as sleep:
            client.read('https://example.com/a#one')
            client.read('https://example.com/a#two')
            client.read('https://example.com/b')
            with self.assertRaises(s.Error) as error:
                client.read('https://example.com/c')
        self.assertEqual(error.exception.code, 'request_budget_exhausted')
        self.assertEqual(op.call_count, 2)
        self.assertEqual(sleep.call_count, 1)
        self.assertEqual(client.usage()['http_requests'], 2)
        request = op.call_args[0][0]
        self.assertNotIn('Cookie', request.headers)
        self.assertEqual(op.call_args[1]['timeout'], 15)

    def test_denied_host_stops_without_retry_or_alternate_client(self):
        client = s.Client(lambda u: True)
        with patch.object(client.opener, 'open', side_effect=urllib.error.HTTPError('u', 403, 'Denied', {}, None)) as op:
            for url in ('https://example.com/a', 'https://example.com/b'):
                with self.assertRaises(s.Error):
                    client.read(url)
        self.assertEqual(op.call_count, 1)
        self.assertEqual(client.usage()['http_requests'], 1)

    def test_size_and_redirect_fail_closed(self):
        client = s.Client(lambda u: True)
        with patch.object(client.opener, 'open', return_value=self.response(b'x' * (s.LIMIT + 1))):
            with self.assertRaises(s.Error) as error:
                client.read('https://example.com/a')
        self.assertEqual(error.exception.code, 'response_too_large')
        with self.assertRaises(s.Error) as error:
            s.RejectRedirect().redirect_request(None, None, 302, '', {}, 'https://elsewhere.example/')
        self.assertEqual(error.exception.code, 'unexpected_redirect')

    def test_unsupported_url_never_reaches_network(self):
        client = s.Client(lambda u: False)
        with patch.object(client.opener, 'open') as op, self.assertRaises(s.Error):
            client.read('https://example.com/')
        op.assert_not_called()
        self.assertEqual(client.requests, 0)

    def test_curl_explicit_tls_no_config_redirect_or_cookies(self):
        client = s.Client(lambda u: True)
        def run(command, **kwargs):
            self.assertEqual(command[:3], ['curl', '-q', '--proto'])
            self.assertIn('--max-filesize', command)
            self.assertIn('--tlsv1.2', command)
            self.assertNotIn('--location', command)
            self.assertNotIn('-L', command)
            self.assertNotIn('--cookie', command)
            self.assertEqual(kwargs['timeout'], 25)
            Path(command[command.index('--output') + 1]).write_bytes(b'ok')
            Path(command[command.index('--dump-header') + 1]).write_text('HTTP/2 200\nLast-Modified: native-date\n')
            return subprocess.CompletedProcess(command, 0, b'200', b'')
        with patch.object(s.subprocess, 'run', side_effect=run), patch.object(s.shutil, 'which', return_value='/usr/bin/curl'):
            body, meta = client.read('https://example.com/', 'curl')
        self.assertEqual(body, b'ok')
        self.assertEqual(meta['http_last_modified_raw'], 'native-date')
        self.assertIsNone(meta['publisher_updated_at'])

    def test_curl_failure_is_unknown_without_stderr_leak(self):
        client = s.Client(lambda u: True)
        with patch.object(s.subprocess, 'run', return_value=subprocess.CompletedProcess([], 35, b'000', b'sensitive transport diagnostic')):
            with self.assertRaises(s.Error) as error:
                client.curl('https://example.com/')
        self.assertNotIn('sensitive', str(error.exception))
        self.assertEqual(error.exception.code, 'transport_error')


if __name__ == '__main__':
    unittest.main()
