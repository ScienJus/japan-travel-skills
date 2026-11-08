"""Offline geographic scope, geometry and failure behavior for hotel radius queries."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/japan-hotels/scripts'))
import hotel_geo as geo
import hotels
import jalan
from test_hotels import DIRECTORY, NAME, card, encoded, search_html


def native_list():
    return search_html().replace(b'<input name="displayKencd"', b'<input name="lrgCd" value="192000"><input name="smlCd" value="192002"><input name="displayKencd"')


def args(*extra):
    return hotels.parser().parse_args(['search', '--directory', DIRECTORY, '--expect', 'JR金沢駅', *extra])


def station(lat='36.5', name='ＪＲ金沢駅', canonical=None):
    url = canonical or geo.landmark_url(DIRECTORY)
    return encoded(f'<script>var location = {{"kenCd":"190000"}};</script><link rel="canonical" href="{url}"><div id="detailMap-canvas" data-name="{name}" data-lat="{lat}" data-lng="136.5"></div>')


def map_html(total=1, name=NAME, hotel_id='123456', lat='36.5', filters=()):
    params = geo.map_params(native_list(), DIRECTORY, filters)
    inputs = ''.join(f'<input name="{k}" value="{v}">' for k,v in params.items())
    records = f"name = '{name}'; id = '{hotel_id}'; no = 1; content = 'reference'; markerData = new Jmap.MarkerData({lat}, 136.5, id, name, content, \"A\" + no); markerArray.push(markerData);" if total else ''
    return encoded(f'''<form name="pagingForm">{inputs}</form><script>
function initMap() {{
Jmap.count = parseInt({total}); Jmap.pageLimit = parseInt(30); Jmap.idx = parseInt(0);
Jmap.screenId = "UWW1701";
{records}
}}
function renderPageCtrl() {{ }}
</script>''')


def map_xml(hotel_id='234567', name='別のホテル', lat='36.6', total=31, index=30):
    return f'''<?xml version="1.0" encoding="UTF-8"?><searchResult count="{total}" pageLimit="30" idx="{index}">
<userDataArray><userData id="{hotel_id}" name="{name}" y="{lat}" x="136.5" type="YAD"/></userDataArray>
<searchResultYadList><searchResultYad yadNo="{hotel_id}" yadName="{name}" y="{lat}" x="136.5"/></searchResultYadList>
</searchResult>'''.encode()


def result(items=None):
    return {'page':1, 'hotels': items or [{'hotel_id':'123456','name_ja':NAME}], 'source_cards_on_page':1}


def lookup(): return {'errors':[]}


class GeometryTests(unittest.TestCase):
    def test_zero_symmetry_and_known_angular_distance(self):
        a,b = geo.coordinates(0,0),geo.coordinates(0,1)
        self.assertEqual(geo.distance_m(a,a),0)
        self.assertAlmostEqual(geo.distance_m(a,b),111195.08,places=2)
        self.assertEqual(geo.distance_m(a,b),geo.distance_m(b,a))

    def test_dateline_and_antipodal_stability(self):
        self.assertAlmostEqual(geo.distance_m(geo.coordinates(0,179.9),geo.coordinates(0,-179.9)),22239.016,places=2)
        self.assertTrue(math.isfinite(geo.distance_m(geo.coordinates(90,0),geo.coordinates(-90,180))))

    def test_invalid_coordinate_numbers(self):
        for lat,lon in [(math.nan,130),(36,math.inf),(91,130),(36,-181),(True,130),(None,130)]:
            with self.subTest(lat=lat,lon=lon),self.assertRaises(jalan.SourceError):geo.coordinates(lat,lon)
        with self.assertRaises(jalan.SourceError):geo.publisher_point(35,1390)

    def test_radius_options_fail_before_network(self):
        for options in [('--radius-m','nan'),('--radius-m','0'),('--radius-m','20001'),('--center-lat','36'),
                        ('--radius-m','1000','--center-lat','36','--center-lon','136'),
                        ('--radius-m','1000','--center-lat','inf','--center-lon','136','--center-name','point')]:
            with patch.object(jalan.Client,'read') as read,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(hotels.main(['search','--directory',DIRECTORY,'--expect','JR金沢駅',*options]),2)
                read.assert_not_called()

    def test_user_center_is_explicit_not_geocoded(self):
        center=geo.validate_options(args('--radius-m','1000','--center-lat','36.5','--center-lon','136.5','--center-name','指定点'))
        self.assertEqual(center['kind'],'user_supplied_coordinates')
        self.assertIsNone(center['source'])


class SourceTests(unittest.TestCase):
    def test_landmark_identity_and_point(self):
        point=geo.parse_landmark(station(),geo.landmark_url(DIRECTORY),'JR金沢駅')
        self.assertEqual((point['latitude'],point['longitude']),(36.5,136.5))
        self.assertEqual(point['kind'],'jalan_landmark_reference')
        for raw in [station(name='JR長野駅'),station(lat='NaN'),station(canonical='https://www.jalan.net/kankou/spt_guide000000192025/')]:
            with self.assertRaises(jalan.SourceError):geo.parse_landmark(raw,geo.landmark_url(DIRECTORY),'JR金沢駅')

    def test_map_region_from_source_not_hardcoded_city_catalog(self):
        p=geo.map_params(native_list(),DIRECTORY,['bath'])
        self.assertEqual((p['lrgCd'],p['smlCd'],p['careBath']),('192000','192002','1'))
        with self.assertRaises(jalan.SourceError):geo.map_params(search_html(),DIRECTORY,[])

    def test_map_point_binding_and_escaped_name(self):
        params=geo.map_params(native_list(),DIRECTORY,[])
        points,total=geo.parse_map(map_html(name=r"テスト\u3000ホテル\'金沢"),params)
        self.assertEqual(total,1)
        self.assertEqual(points['123456']['name_ja'],"テスト ホテル'金沢".replace(' ', '\u3000'))
        self.assertEqual(points['123456']['latitude'],36.5)

    def test_map_scope_filter_count_and_duplicates_fail(self):
        params=geo.map_params(native_list(),DIRECTORY,['bath'])
        for raw in [map_html(),map_html(total=2,filters=['bath']),map_html(filters=['bath']).replace(b'192002',b'192001'),map_html(filters=['bath']).replace(b'36.5, 136.5',b'136.5, 36.5')]:
            with self.assertRaises(jalan.SourceError):geo.parse_map(raw,params)

    def test_xml_marker_and_property_identity(self):
        points=geo.parse_map_page(map_xml(name=r'別の\u3000ホテル'),31,30)
        self.assertEqual(points['234567']['name_ja'],'別の\u3000ホテル')
        for raw in [map_xml(total=32),map_xml(index=0),map_xml().replace(b'yadNo="234567"',b'yadNo="111111"'),
                    map_xml().replace(b'type="YAD"',b'type="SPOT"'),map_xml().replace(b'<searchResultYad yadNo',b'<searchResultYad y="37" yadNo')]:
            with self.assertRaises(jalan.SourceError):geo.parse_map_page(raw,31,30)

    def test_xml_dtd_and_unknown_point_rejected(self):
        for raw in [b'<!DOCTYPE foo><searchResult/>',map_xml(lat=''),map_xml(lat='nan')]:
            with self.assertRaises(jalan.SourceError):geo.parse_map_page(raw,31,30)

    def test_nul_encoded_xml_is_rejected_even_for_an_otherwise_valid_empty_page(self):
        raw = ('<searchResult count="0" idx="0" pageLimit="30">'
               '<userDataArray/><searchResultYadList/></searchResult>').encode('utf-16-le')
        with self.assertRaises(jalan.SourceError):
            geo.parse_map_page(raw, 0, 0)

    def test_fixed_route_allowlist(self):
        p=geo.map_params(native_list(),DIRECTORY,[])
        self.assertTrue(jalan.allowed(geo.map_url(p)))
        self.assertTrue(jalan.allowed(geo.map_url({**p,'idx':'30'},True)))
        self.assertTrue(jalan.allowed(geo.landmark_url(DIRECTORY)))
        for url in [geo.map_url({**p,'idx':'60'},True),geo.map_url({**p,'callback':'secret'}),geo.map_url({**p,'careOnsen':'1'}),geo.map_url(p)+'&spotId=guide000000192025',geo.landmark_url(DIRECTORY)+'?x=1']:
            self.assertFalse(jalan.allowed(url),url)


class FilteringTests(unittest.TestCase):
    def test_boundary_uses_unrounded_distance(self):
        v=result();point={**geo.coordinates(36.5,136.5),'name_ja':NAME}
        with patch.object(geo,'distance_m',return_value=1000.04):
            geo.apply_radius(v,{'123456':point},point,1000,lookup())
        self.assertEqual(v['hotels'],[])
        self.assertEqual(v['radius_filter']['outside_on_page'],1)
        with patch.object(geo,'distance_m',return_value=1000):
            v=result();geo.apply_radius(v,{'123456':point},point,1000,lookup())
        self.assertTrue(v['hotels'][0]['distance']['near_boundary'])

    def test_missing_or_mismatched_points_are_not_outside(self):
        for points in [{},{'123456':{'name_ja':'別館',**geo.coordinates(36.5,136.5)}}]:
            v=result();self.assertTrue(geo.apply_radius(v,points,geo.coordinates(36.5,136.5),1000,lookup()))
            self.assertEqual(v['hotels'],[])
            self.assertEqual(v['radius_filter']['outside_on_page'],0)
            self.assertEqual(v['distance_unknown_hotels'][0]['distance']['state'],'unknown')

    def test_no_time_to_distance_inference(self):
        review=jalan.walking_review('金沢駅より徒歩5分。距離400m。徒歩約1.2km。',[])
        self.assertEqual(review['claims'][0]['minutes_min'],5)
        self.assertEqual(len(review['distance_claims']),1)
        self.assertEqual(review['distance_claims'][0]['metres_min'],1200)
        self.assertEqual(jalan.walking_review('駅から500m、徒歩7分。',[])['distance_claims'],[])

    def test_map_failure_preserves_unknown_candidates(self):
        client=Mock();client.last_source={'url':'map','retrieved_at':None}
        client.read.side_effect=[(station(),{'url':'station'}),(native_list(),{'url':'list'}),jalan.SourceError('http_error','Denied',http_status=403)]
        v=hotels.query(client,args('--radius-m','20000'))
        self.assertEqual(v['status'],'partial')
        self.assertEqual(v['source']['url'],'list')
        self.assertEqual(v['hotels'],[])
        self.assertEqual(v['distance_unknown_hotels'][0]['name_ja'],NAME)
        self.assertEqual(v['radius_filter']['coordinate_lookup']['errors'][0]['http_status'],403)
        self.assertEqual(client.read.call_count,3)

    def test_second_map_failure_preserves_first_map_matches(self):
        client=Mock();client.last_source={'url':'map-page2','retrieved_at':None}
        client.read.side_effect=[(station(),{'url':'station'}),(native_list(),{'url':'list'}),
                                 (map_html(),{'url':'map'}),jalan.SourceError('network_error','Unavailable')]
        points={'123456':{'name_ja':NAME,**geo.coordinates(36.5,136.5)}}
        with patch.object(geo,'parse_map',return_value=(points,31)):
            v=hotels.query(client,args('--radius-m','20000'))
        self.assertEqual(v['status'],'partial')
        self.assertEqual(v['hotels'][0]['distance']['metres'],0)
        self.assertEqual(v['hotels'][0]['coordinates']['source']['url'],'map')
        self.assertEqual(client.read.call_count,4)

    def test_radius_budget_stops_fifth_read(self):
        client=jalan.Client(request_limit=4);client.requests=4;client.opener=Mock()
        with self.assertRaises(jalan.SourceError) as error:client.read(jalan.hotel_url('123456'))
        self.assertEqual(error.exception.code,'request_budget_exhausted')
        client.opener.open.assert_not_called()

    def test_native_name_escape_is_data_not_code(self):
        self.assertEqual(geo.literal("hotel'; malicious(); //"),"hotel'; malicious(); //")
        for value in [r'\x41',r'\ud800']:
            with self.assertRaises(jalan.SourceError):geo.literal(value)
        with self.assertRaises(jalan.SourceError):geo.decode_name(r'\ud800')



if __name__=='__main__': unittest.main()
