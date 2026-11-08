"""Forward-geocoding contracts, ambiguity and shared CLI access rules."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import json
import unittest
from urllib.parse import parse_qs, urlsplit

from tabelog_client.cli import run
from tabelog_client.core import CliError, public_url
from tabelog_client.geo import geocode, parse_locations
from tabelog_client.transport import Client, request_headers


SOURCE = 'https://photon.komoot.io/api/?q=test'


def feature(name='Hyatt Centric Kanazawa', lon=136.6477005, lat=36.5800589, **properties):
    return {'type': 'Feature', 'geometry': {'type': 'Point', 'coordinates': [lon, lat]},
            'properties': {'name': name, 'countrycode': 'JP', 'city': 'Kanazawa', 'osm_type': 'W',
                           'osm_id': 123, 'osm_key': 'tourism', 'osm_value': 'hotel', **properties}}


def collection(*features):
    return {'type': 'FeatureCollection', 'features': list(features)}


def client(read):
    return Client(reader=lambda u: {'body': json.dumps(read(u)), 'url': u, 'http_status': 200,
                                   'version': 'test'}, delay_min_ms=0, delay_max_ms=0)


class GeoTests(unittest.TestCase):
    def test_wgs84_order_identity_attribution_and_precise_source(self):
        r = parse_locations(collection(feature()), 'photon', SOURCE, 5)
        item = r['items'][0]
        self.assertEqual(item['latitude'], 36.5800589)
        self.assertEqual(item['longitude'], 136.6477005)
        self.assertEqual(item['near'], '36.5800589,136.6477005')
        self.assertEqual(item['address']['city'], 'Kanazawa')
        self.assertEqual(item['provider_id'], 'W:123')
        self.assertEqual(item['coordinate_source'], SOURCE)
        self.assertIn('OpenStreetMap', r['attribution'])
        self.assertIn('not verified', item['precision'])

    def test_homonyms_not_automatically_selected_and_duplicates_collapsed(self):
        wrong = feature('HYATT CENTRIC SAPPORO', lon=141.3489134, lat=43.0626174, city='Sapporo', osm_id=456)
        r = parse_locations(collection(wrong, feature(), feature()), 'photon', SOURCE, 5)
        self.assertEqual(len(r['items']), 2)
        self.assertEqual(r['items'][0]['address']['city'], 'Sapporo')
        self.assertNotIn('selected', r)

    def test_outside_japan_and_malformed_response_distinguished_from_empty(self):
        outside = feature('Paris', countrycode='FR')
        r = parse_locations(collection(outside), 'photon', SOURCE, 5)
        self.assertEqual(r['items'], [])
        self.assertEqual(r['outside_japan_records'], 1)
        self.assertEqual(parse_locations(collection(), 'photon', SOURCE, 5)['items'], [])
        for raw in [{}, [], collection(feature(lat=91)), collection({'type': 'Feature'})]:
            with self.assertRaises(CliError):
                parse_locations(raw, 'photon', SOURCE, 5)

    def test_bad_row_is_disclosed_and_limit_does_not_hide_ambiguity(self):
        r = parse_locations(collection(feature(), feature('Other Hotel', osm_id=456), {}), 'photon', SOURCE, 1)
        self.assertEqual(len(r['items']), 1)
        self.assertEqual(r['coverage'], 'partial')
        self.assertEqual(r['invalid_records'], 1)

    def test_gsi_address_candidates_keep_provider_titles(self):
        f = {'geometry': {'type': 'Point', 'coordinates': [136.64, 36.58]}, 'properties': {'title': '石川県金沢市広岡一丁目'}}
        r = parse_locations([f, f], 'gsi', 'https://msearch.gsi.go.jp/address-search/AddressSearch?q=test', 5)
        self.assertEqual(len(r['items']), 1)
        self.assertEqual(r['items'][0]['name'], '石川県金沢市広岡一丁目')
        self.assertEqual(r['items'][0]['latitude'], 36.58)
        self.assertIn('国土地理院', r['attribution'])

    def test_cli_encapsulates_one_get_and_retains_command_cache(self):
        calls = []
        def read(url):
            calls.append(url)
            self.assertEqual(urlsplit(url).hostname, 'photon.komoot.io')
            self.assertEqual(parse_qs(urlsplit(url).query)['countrycode'], ['JP'])
            self.assertEqual(parse_qs(urlsplit(url).query)['q'], ['Hyatt Centric Kanazawa'])
            return collection(feature())
        r = run(['geocode', 'Hyatt Centric Kanazawa', '--provider', 'photon', '--limit', '3'], create_client=lambda **kw: client(read))
        self.assertEqual(r['output']['status'], 'ok')
        self.assertEqual(len(calls), 1)
        c = client(lambda url: collection(feature()))
        geocode(c, 'Test', provider='photon'); geocode(c, 'Test', provider='photon')
        self.assertEqual(c.usage()['cache_hits'], 1)

    def test_default_official_geocoder_preserves_candidates_without_fallback(self):
        calls = []
        def read(url):
            calls.append(url)
            self.assertEqual(urlsplit(url).hostname, 'msearch.gsi.go.jp')
            self.assertEqual(parse_qs(urlsplit(url).query)['q'], ['東京都千代田区丸の内'])
            return []
        result = run(['geocode', '東京都千代田区丸の内'], create_client=lambda **kw: client(read))
        self.assertEqual(result['output']['data']['provider'], 'gsi')
        self.assertEqual(result['output']['data']['items'], [])
        self.assertEqual(len(calls), 1)

    def test_endpoint_scope_and_json_headers(self):
        self.assertEqual(public_url(SOURCE), SOURCE)
        self.assertIn('application/json', request_headers(SOURCE)['Accept'])
        for url in ['https://photon.komoot.io/update', 'https://photon.komoot.io/reverse?lat=1',
                    'http://photon.komoot.io/api/', 'https://photon.komoot.io.evil/api/']:
            with self.assertRaises(CliError):
                public_url(url)

    def test_invalid_args_or_denial_never_trigger_provider_rotation(self):
        for args in [['geocode', ''], ['geocode', 'Test', '--provider', 'unknown'],
                     ['doctor', '--provider', 'photon']]:
            r = run(args, create_client=lambda **kw: client(lambda u: self.fail('Unexpected HTTP read')))
            self.assertEqual(r['output']['error']['code'], 'invalid_argument')
        calls = []
        def read(url):
            calls.append(url)
            raise CliError('access_denied', '403')
        r = run(['geocode', 'Test'], create_client=lambda **kw: client(read))
        self.assertEqual(r['output']['error']['code'], 'access_denied')
        self.assertEqual(len(calls), 1)
