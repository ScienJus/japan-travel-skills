"""Offline buffered-candidate coverage, identity, paging and query-budget checks."""
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'skills/japan-hotels/scripts'))
import hotel_geo as geo
import hotel_viewport as view
import hotels
import jalan
from test_hotels import DIRECTORY, NAME, encoded
from test_hotel_geo import args, station

CENTER = geo.coordinates(36.5, 136.5)


def native(cards=None, total=None, filters=(), center=CENTER, radius=1000):
    cards = cards if cards is not None else [('123456', NAME, 36.5, 136.5)]
    total = len(cards) if total is None else total
    params = view.params(DIRECTORY, filters, center, view.plan(center, radius)['zoom'])
    inputs = ''.join(f'<input name="{k}" value="{v}">' for k,v in params.items())
    records, html = [], []
    for index,(identity,name,lat,lon) in enumerate(cards,1):
        records.append(f"name = '{name}'; id = '{identity}'; no = {index}; content = 'data'; markerData = new Jmap.MarkerData({lat}, {lon}, id, name, content, \"A\" + no); markerArray.push(markerData);")
        html.append(f'''<div class="pack" id="listresult-{index}"><p class="name"><a href="javascript:openYadoSyosai('{identity}')">{name}</a></p><p class="exp">紹介。駅から徒歩5分。</p><p class="price">99,999円</p></div>''')
    return encoded(f'''<form name="pagingForm">{inputs}</form><script>
function initMap() {{
Jmap.count = parseInt({total}); Jmap.pageLimit = parseInt(30); Jmap.idx = parseInt(0);
Jmap.screenId = "UWW1701"; Jmap.reShFlg = "1";
Jmap.initialize1({center['longitude']}, {center['latitude']}, {params['zoomLevel']});
{''.join(records)}
}}
function renderPageCtrl() {{ }}
</script>{''.join(html)}''')


def xml(total=31, index=30, zoom=14, name='別のホテル'):
    return f'''<?xml version="1.0" encoding="UTF-8"?><searchResult count="{total}" pageLimit="30" idx="{index}" zoomLevel="{zoom}">
<userDataArray><userData id="234567" name="{name}" y="36.5" x="136.5" type="YAD"/></userDataArray>
<searchResultYadList><searchResultYad yadNo="234567" yadName="{name}" y="36.5" x="136.5" yadCopy="館内紹介。" yadPrice="99,999円"/></searchResultYadList></searchResult>'''.encode()


def first_thirty():
    return [(str(100000+i), 'ホテル'+str(i), 36.5,136.5) for i in range(30)]


class PlanTests(unittest.TestCase):
    def test_combined_margin_at_small_and_large_radii(self):
        for radius, buffered in [(1,1.5),(500,750),(1000,1500),(2000,3000),(5000,6000),(10000,11000),(20000,21000)]:
            with self.subTest(radius=radius):
                plan=view.plan(CENTER,radius)
                self.assertEqual(plan['radius_m'],buffered)
                self.assertFalse(plan['coverage_guaranteed'])
        self.assertEqual(view.plan(CENTER,1000)['zoom'],14)
        self.assertFalse(view.plan(CENTER,20000)['supported'])

    def test_outward_zoom_fits_buffered_circle_in_policy_envelope(self):
        for lat in (20,26,36.5,43,46):
            for radius in (1,50,500,1000,2000,5000,10000,11000,14000,20000):
                center=geo.coordinates(lat,136)
                plan=view.plan(center,radius)
                angle=plan['radius_m']/geo.EARTH_RADIUS_M
                factor=2**(14-plan['zoom'])
                self.assertLessEqual(math.degrees(angle), view.HALF_LATITUDE_AT_Z14*factor+1e-12)
                longitude=math.degrees(math.asin(math.sin(angle)/math.cos(math.radians(lat))))
                self.assertLessEqual(longitude,view.HALF_LONGITUDE_AT_Z14*factor+1e-12)

    def test_allowlist_accepts_only_bounded_native_search_and_paging(self):
        p=view.params(DIRECTORY,['bath'],CENTER,14)
        self.assertTrue(jalan.allowed(geo.map_url(p)))
        paging={**p,'screenId':'UWW1701','idx':'0','nowPage':'2','searchResultYadCount':'31'}
        self.assertTrue(jalan.allowed(geo.map_url(paging,True)))
        for extra in [{'zoomLevel':'10','resetZoomLevel':'10'},{'centerPosY':'nan'},{'centerPosY':'80'},
                      {'careOnsen':'1'},{'genreTypeSpot':'1'},{'dateUndecided':'0'}, {'zoomLevel':'014','resetZoomLevel':'014'}]:
            self.assertFalse(jalan.allowed(geo.map_url({**p,**extra})))
        for extra in [{'idx':'30'},{'nowPage':'11'},{'searchResultYadCount':'9001'},{'screenId':'other'}]:
            self.assertFalse(jalan.allowed(geo.map_url({**paging,**extra},True)))
        self.assertFalse(jalan.allowed(geo.map_url(p)+'&spotId=guide000000192025'))


class SourceTests(unittest.TestCase):
    def test_native_cards_are_bound_to_markers_and_undated_prices_omitted(self):
        p=view.params(DIRECTORY,['bath'],CENTER,14)
        cards,points,total=view.parse_first(native(filters=['bath']),p,['bath'])
        self.assertEqual(total,1)
        self.assertEqual(cards[0]['hotel_id'],'123456')
        self.assertEqual(points['123456']['latitude'],36.5)
        self.assertEqual(cards[0]['introduction_ja'],'紹介。駅から徒歩5分。')
        self.assertIsNone(cards[0]['access_ja'])
        self.assertEqual(cards[0]['walking_review']['claims'],[])
        self.assertNotIn('99,999',str(cards))

    def test_changed_native_scope_and_card_identity_fail(self):
        p=view.params(DIRECTORY,[],CENTER,14)
        raw=native()
        for bad in [raw.replace(b'Jmap.reShFlg = "1"',b'Jmap.reShFlg = "0"'),
                    raw.replace(b'Jmap.initialize1(136.5',b'Jmap.initialize1(136.6'),
                    raw.replace(b"openYadoSyosai('123456')",b"openYadoSyosai('111111')"),
                    raw.replace(b'<form name="pagingForm">',b'<form name="pagingForm"><input name="careOnsen" value="1">'),
                    raw.replace(b'<form name="pagingForm">',b'<form name="pagingForm"><input name="genreTypeSpot" value="1">')]:
            with self.assertRaises(jalan.SourceError):view.parse_first(bad,p,[])

    def test_native_marker_html_entities_match_card_text_once(self):
        params=view.params(DIRECTORY,[],CENTER,14)
        for published,expected in [('ホテル Comic&amp;Books','ホテル Comic&Books'),
                                   ('ホテル &#38; Books','ホテル & Books'),
                                   ('ホテル &quot;本館&quot;','ホテル "本館"'),
                                   ('ホテル &amp;amp; Books','ホテル &amp; Books')]:
            with self.subTest(published=published):
                cards,points,total=view.parse_first(native(cards=[('123456',published,36.5,136.5)]),params,[])
                self.assertEqual(total,1)
                self.assertEqual(cards[0]['name_ja'],expected)
                self.assertEqual(points['123456']['name_ja'],expected)
                result={'hotels':cards,'page':1}
                geo.apply_radius(result,points,CENTER,1000,{'errors':[]})
                self.assertEqual(result['radius_filter']['matched_on_page'],1)
                self.assertEqual(result['radius_filter']['unknown_on_page'],0)

        raw=native(cards=[('123456','ホテル Comic&amp;Books',36.5,136.5)])
        escaped=raw.replace(b'Comic&amp;Books',b'Comic\\u0026amp;Books',1)
        cards,points,_=view.parse_first(escaped,params,[])
        self.assertEqual(cards[0]['name_ja'],'ホテル Comic&Books')
        self.assertEqual(points['123456']['name_ja'],'ホテル Comic&Books')
        # Equivalent escaping must not permit a different name or a mismatched ID.
        for bad in [raw.replace(b'Comic&amp;Books</a>',b'Other&amp;Books</a>'),
                    raw.replace(b"openYadoSyosai('123456')",b"openYadoSyosai('111111')"),
                    raw.replace(b'Comic&amp;Books</a>',b'Comic&amp;amp;Books</a>')]:
            with self.assertRaises(jalan.SourceError):view.parse_first(bad,params,[])

    def test_validated_zero_keeps_source_scope(self):
        cards,points,total=view.parse_first(native(cards=[]),view.params(DIRECTORY,[],CENTER,14),[])
        self.assertEqual((cards,points,total),([],{},0))
        with self.assertRaises(jalan.SourceError):view.parse_first(native(cards=[],total=1),view.params(DIRECTORY,[],CENTER,14),[])

    def test_xml_preserves_introduction_and_rejects_changed_zoom_count_and_page(self):
        cards,points=view.parse_page(xml(),31,2,14,[])
        self.assertEqual(cards[0]['introduction_ja'],'館内紹介。')
        self.assertEqual(cards[0]['hotel_id'],'234567')
        self.assertNotIn('99,999',str(cards))
        for bad in [xml(zoom=13),xml(total=32),xml(index=0),xml(name='')]:
            with self.assertRaises(jalan.SourceError):view.parse_page(bad,31,2,14,[])


class QueryTests(unittest.TestCase):
    def client(self, *responses):
        client=Mock();client.last_source=None;client.read.side_effect=responses
        return client

    def test_first_page_skips_large_directory_and_filters_before_limit(self):
        cards=[('111111','遠いホテル',36.52,136.5),('123456',NAME,36.5,136.5)]
        client=self.client((station(),{'url':'landmark'}),(native(cards),{'url':'map'}))
        value=hotels.query(client,args('--radius-m','1000','--limit','1'))
        self.assertEqual(client.read.call_count,2)
        self.assertEqual(value['status'],'ok')
        self.assertEqual([h['hotel_id'] for h in value['hotels']],['123456'])
        self.assertEqual(value['source_total'],2)
        self.assertEqual(value['source_total_scope'],'buffered_map_viewport')
        self.assertEqual(value['radius_filter']['outside_on_page'],1)
        self.assertEqual(value['hotels'][0]['source_rank'],2)
        self.assertFalse(value['output_truncated'])
        self.assertEqual(value['radius_filter']['prefilter']['radius_m'],1500)
        self.assertEqual(value['hotels'][0]['coordinates']['source']['url'],'map')
        for call in client.read.call_args_list:self.assertNotIn('/190000/',call.args[0])

    def test_unread_source_pages_mark_partial_and_totals_stay_unfiltered(self):
        client=self.client((station(),{'url':'landmark'}),(native(first_thirty(),total=31),{'url':'map'}))
        value=hotels.query(client,args('--radius-m','1000'))
        self.assertEqual(value['status'],'partial')
        self.assertTrue(value['has_next_page'])
        self.assertEqual(value['source_total'],31)
        self.assertTrue(value['radius_filter']['coordinate_lookup']['publisher_map_truncated'])
        self.assertEqual(client.read.call_count,2)

    def test_requested_native_second_page_only_is_returned(self):
        client=self.client((station(),{'url':'landmark'}),(native(first_thirty(),total=31),{'url':'map'}),(xml(),{'url':'page2'}))
        value=hotels.query(client,args('--radius-m','1000','--page','2'))
        self.assertEqual(value['status'],'partial')
        self.assertEqual(value['page'],2)
        self.assertEqual(value['source_cards_on_page'],1)
        self.assertEqual(value['hotels'][0]['hotel_id'],'234567')
        self.assertEqual(value['hotels'][0]['source_rank'],31)
        self.assertEqual(value['source']['url'],'page2')
        fields=dict(urllib.parse.parse_qsl(urllib.parse.urlsplit(client.read.call_args.args[0]).query))
        self.assertEqual((fields['nowPage'],fields['idx'],fields['searchResultYadCount']),('2','0','31'))
        self.assertEqual(client.read.call_count,3)

    def test_out_of_range_page_does_not_fetch_or_return_other_page(self):
        client=self.client((station(),{'url':'landmark'}),(native(),{'url':'map'}))
        with self.assertRaises(jalan.SourceError) as error:hotels.query(client,args('--radius-m','1000','--page','2'))
        self.assertEqual(error.exception.code,'page_out_of_range')
        self.assertEqual(client.read.call_count,2)

    def test_custom_center_still_verifies_landmark_identity(self):
        client=self.client((station(),{'url':'landmark'}),(native(),{'url':'map'}))
        value=hotels.query(client,args('--radius-m','1000','--center-lat','36.5','--center-lon','136.5','--center-name','指定点'))
        self.assertEqual(value['radius_filter']['center']['kind'],'user_supplied_coordinates')
        self.assertIsNone(value['radius_filter']['center']['source'])
        self.assertEqual(client.read.call_count,2)
        client=self.client((station(name='JR長野駅'),{'url':'landmark'}))
        with self.assertRaises(jalan.SourceError):hotels.query(client,args('--radius-m','1000','--center-lat','36.5','--center-lon','136.5','--center-name','指定点'))
        self.assertEqual(client.read.call_count,1)

    def test_source_denial_stops_without_retry_or_region_fallback(self):
        client=self.client((station(),{'url':'landmark'}),jalan.SourceError('http_error','Denied',http_status=403))
        with self.assertRaises(jalan.SourceError):hotels.query(client,args('--radius-m','1000'))
        self.assertEqual(client.read.call_count,2)

    def test_wrong_landmark_prefecture_stops_before_candidate_search(self):
        client=self.client((station().replace(b'"190000"',b'"160000"'),{'url':'landmark'}))
        with self.assertRaises(jalan.SourceError):hotels.query(client,args('--radius-m','1000'))
        self.assertEqual(client.read.call_count,1)

    def test_unsupported_zoom_uses_bounded_region_lookup_instead_of_native_empty(self):
        from test_hotel_geo import native_list,map_html
        client=self.client((station(),{'url':'landmark'}),(native_list(),{'url':'directory'}),(map_html(),{'url':'region'}))
        value=hotels.query(client,args('--radius-m','20000'))
        self.assertEqual(value['status'],'ok')
        self.assertEqual(value['radius_filter']['prefilter']['mode'],'regional_coordinate_lookup')
        self.assertEqual(value['source_total_scope'],'landmark_directory')
        self.assertEqual(client.read.call_count,3)
        for call in client.read.call_args_list:self.assertNotIn('reShFlg=1',call.args[0])


if __name__=='__main__':unittest.main()
