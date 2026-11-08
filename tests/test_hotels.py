"""Synthetic offline source contracts, scope checks and request limits for hotels."""
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import MagicMock, Mock, patch
import urllib.error

SCRIPTS = Path(__file__).resolve().parents[1] / 'skills/japan-hotels/scripts'
sys.path.insert(0, str(SCRIPTS))
import jalan
import hotels

DIRECTORY = 'https://www.jalan.net/190000/spt_guide000000183832/'
TODAY = dt.date(2026, 11, 2)
NAME = 'テストホテル金沢'


def encoded(html):
    return ('<html><head><title>宿・ホテル - じゃらんnet</title></head><body>' + html + '</body></html>').encode('cp932')


def card(hotel_id='123456', name=NAME, access='金沢駅西口から徒歩約7分。コンビニ徒歩1分。'):
    return f'''<a class="jlnpc-yadoCassette__link" href="/yad{hotel_id}/?adultNum=2">
<h2>{name}</h2><p class="p-searchResultItem__description">ホテル紹介。大浴場あり。</p>
<dd class="p-searchResultItem__accessValue">{access}</dd>
<dl class="p-searchResultItem__lowestPrice">大人2名 5,000円～</dl></a>'''


def search_html(cards=None, total=1, page=1, filters=(), landmark='ＪＲ金沢駅'):
    if cards is None: cards = card()
    checks = ''.join(f'<input name="{field}" value="1" {"checked" if key in filters else ""}>' for key, (field, label) in jalan.FILTERS.items())
    heading = landmark + '周辺のホテル・旅館・宿泊施設' + (f'({page}/7)' if page > 1 else '')
    return encoded(f'''<h1>{heading}</h1><form id="jalan_form"><input name="spotId" value="guide000000183832">
<input name="displayKencd" value="190000">{checks}</form>
<script>var vars = {{"currentPage":"{page}"}}</script><span class="jlnpc-listInformation--count">{total}</span>
{cards}<a href="/yad999999/"><h2>Related recommendation</h2></a>''')


def detail_html(name=NAME, hotel_id='123456', room_link=True):
    return encoded(f'''<h1 class="jlnpc-styleguide-scope jlnpc-yado__subTitle">{name}の施設概要</h1><input name="yadNo" value="{hotel_id}">
<div class="facility-overview-text">旅の参考紹介</div>
<table class="jlnpc-shisetsu-accessparking-table"><tr><th>住所</th><td>石川県金沢市</td></tr></table>
<table class="shisetsu-bath_body"><tr><th>温泉</th><td>無し</td></tr><tr><th>風呂利用条件</th><td>宿泊者無料</td></tr></table>
<table class="shisetsu-roomsetsubi_body"><tr><td><table><tr><th>ツイン</th></tr><tr><td>16～23m2</td></tr></table></td></tr></table>
{f'<a href="/yad{hotel_id}/room/?foo=bar">部屋</a>' if room_link else ''}''')


def rooms_html(area='12.5㎡', name=NAME, hotel_id='123456'):
    return encoded(f'''<h1 class="jlnpc-styleguide-scope jlnpc-yado__subTitle">{name}の部屋</h1><input name="yadNo" value="{hotel_id}">
<table><tr><td>部屋タイプ</td><td>室数</td><td>広さ</td><td>通常料金（消費税込み）</td></tr>
<tr><td>ダブル</td><td>12室</td><td>{area}</td><td>99,000円～</td></tr></table>
<table><tr><td>部屋設備補足事項</td><td></td><td>冷暖房切替不可</td></tr></table>''')


class ParserTests(unittest.TestCase):
    def parse(self, raw=None, page=1, filters=()):
        return jalan.parse_search(raw or search_html(), DIRECTORY, 'JR金沢駅', page, filters, TODAY)

    def test_main_results_only_and_no_undated_prices(self):
        value = self.parse()
        self.assertEqual([h['hotel_id'] for h in value['hotels']], ['123456'])
        self.assertEqual(value['source_total'], 1)
        self.assertNotIn('5,000', json.dumps(value, ensure_ascii=False))
        self.assertEqual(value['hotels'][0]['name_ja'], NAME)

    def test_source_filter_conflict_is_exposed(self):
        value = self.parse(search_html(filters=('bath', 'station5')), filters=('bath', 'station5'))
        review = value['hotels'][0]['walking_review']
        self.assertEqual(review['station5_assessment'], 'potential_conflict')
        self.assertEqual([c['minutes_max'] for c in review['claims']], [7, 1])

    def test_short_walk_is_not_independent_verification(self):
        value = self.parse(search_html(cards=card(access='金沢駅より徒歩3分'), filters=('station5',)), filters=('station5',))
        self.assertEqual(value['hotels'][0]['walking_review']['station5_assessment'], 'needs_access_review')

    def test_reflected_filters_required(self):
        with self.assertRaises(jalan.SourceError): self.parse(filters=('bath',))
        with self.assertRaises(jalan.SourceError): self.parse(search_html(filters=('bath',)))

    def test_location_and_native_id_mismatch(self):
        for raw in (search_html(landmark='ＪＲ長野駅'), search_html().replace(b'guide000000183832', b'guide000000192025')):
            with self.subTest(raw=raw[:30]), self.assertRaises(jalan.SourceError): self.parse(raw)

    def test_pagination_identity_and_count(self):
        value = self.parse(search_html(total=61, page=2), page=2)
        self.assertTrue(value['has_next_page'])
        with self.assertRaises(jalan.SourceError): self.parse(search_html(total=61), page=2)
        with self.assertRaises(jalan.SourceError): self.parse(search_html(total=1, page=2), page=2)

    def test_duplicate_cards_and_missing_results_are_unknown(self):
        for raw in (search_html(cards=card()+card()), search_html(cards='', total=10), encoded('<h1>challenge</h1>')):
            with self.assertRaises(jalan.SourceError): self.parse(raw)

    def test_validated_zero_is_distinct_from_failure(self):
        value = self.parse(search_html(cards='', total=0))
        self.assertEqual(value['hotels'], [])
        self.assertEqual(value['source_total'], 0)

    def test_future_opening_is_not_current_operation(self):
        value = self.parse(search_html(cards=card(name='新ホテル（2027年1月25日新規開業）')))
        self.assertEqual(value['hotels'][0]['operating_status']['opening_date'], '2027-01-25')
        self.assertEqual(self.parse()['hotels'][0]['operating_status']['state'], 'unknown')
        self.assertEqual(jalan.opening_notice('2020年1月1日開業', None, TODAY)['state'], 'unknown')

    def test_missing_access_is_unknown(self):
        value = self.parse(search_html(cards=card().replace('p-searchResultItem__accessValue', 'unrecognized')))
        self.assertIsNone(value['hotels'][0]['access_ja'])
        self.assertEqual(value['hotels'][0]['walking_review']['claims'], [])

    def test_profile_preserves_onsen_absence_and_summary_scope(self):
        value = jalan.parse_detail(detail_html(), '123456', NAME, TODAY)
        bath = next(s for s in value['sections'] if s['section_ja'] == '温泉・風呂')
        self.assertEqual(bath['fields'][0], {'label_ja': '温泉', 'value_ja': '無し'})
        self.assertIn('16～23m2', json.dumps(value, ensure_ascii=False))
        self.assertTrue(value['rooms_link_published'])
        self.assertEqual(value['sections'][-1]['state'], 'unknown')

    def test_profile_exact_hotel_identity(self):
        for args in [(detail_html(hotel_id='111111'), '123456', NAME), (detail_html(), '123456', '違うホテル')]:
            with self.assertRaises(jalan.SourceError): jalan.parse_detail(*args, TODAY)
        with self.assertRaises(jalan.SourceError): jalan.parse_rooms(rooms_html(name='別館'), '123456', NAME)

    def test_native_profile_and_room_heading_exclude_embedded_news(self):
        news = (f'<h1 class="news-contents-title">別の施設の施設概要</h1>'
                f'<h1 class="news-contents-modal-title">{NAME}の部屋</h1>').encode('cp932')
        profile = detail_html().replace(b'</body>', news + b'</body>')
        rooms = rooms_html().replace(b'</body>', news + b'</body>')
        detail = jalan.parse_detail(profile, '123456', NAME, TODAY)
        self.assertEqual((detail['hotel_id'], detail['name_ja']), ('123456', NAME))
        self.assertEqual(detail['sections'][0]['fields'][0]['value_ja'], '石川県金沢市')
        self.assertEqual(jalan.parse_rooms(rooms, '123456', NAME)['room_types'][0]['area_m2_min'], 12.5)

    def test_missing_or_duplicate_native_heading_is_not_replaced_by_news(self):
        for raw, is_rooms in ((detail_html(), False), (rooms_html(), True)):
            for suffix in ('の施設概要', 'の部屋'):
                news = f'<h1 class="news-contents-title">{NAME}{suffix}</h1>'.encode('cp932')
                missing = raw.replace(b'jlnpc-yado__subTitle', b'other-jlnpc-yado__subTitle')
                duplicate = f'<h1 class="jlnpc-yado__subTitle">{NAME}{suffix}</h1>'.encode('cp932')
                for candidate in (missing, missing.replace(b'</body>', news + b'</body>'),
                                  raw.replace(b'</body>', duplicate + b'</body>')):
                    with self.subTest(suffix=suffix, raw=candidate[:120]):
                        with self.assertRaises(jalan.SourceError) as error:
                            jalan.profile_page(candidate, '123456', NAME, rooms=is_rooms)
                        self.assertEqual(error.exception.code, 'source_schema_changed')

    def test_news_cannot_rescue_wrong_native_name_id_or_page_mode(self):
        news = f'<h1 class="news-contents-title">{NAME}の施設概要</h1>'.encode('cp932')
        for raw, code in ((detail_html(name='別館'), 'hotel_mismatch'),
                          (detail_html(hotel_id='999999'), 'source_schema_changed'),
                          (rooms_html(), 'source_schema_changed')):
            with self.subTest(code=code), self.assertRaises(jalan.SourceError) as error:
                jalan.parse_detail(raw.replace(b'</body>', news + b'</body>'), '123456', NAME, TODAY)
            self.assertEqual(error.exception.code, code)

    def test_amenity_grid_does_not_include_accessibility_table_with_same_class(self):
        extra = '''<div class="shisetsu-amenityspec_body_wrap">
<table class="shisetsu-amenityspec_body"><tr><td>○</td><td>バスタオル</td></tr></table></div>
<div class="shisetsu-gnlspec_body_wrap">
<table class="shisetsu-amenityspec_body"><tr><td>×</td><td>大浴場に手すり</td></tr></table></div>'''
        raw = detail_html().replace(b'</body>', extra.encode('cp932') + b'</body>')
        value = jalan.parse_detail(raw, '123456', NAME, TODAY)
        grid = value['sections'][-1]
        self.assertEqual(grid['state'], 'published')
        self.assertEqual(grid['source_rows'][0][1]['label_ja'], 'バスタオル')
        self.assertNotIn('大浴場に手すり', json.dumps(grid, ensure_ascii=False))
        self.assertEqual(value['sections'][2]['fields'][0]['value_ja'], '無し')

    def test_real_duplicate_amenity_containers_or_tables_remain_errors(self):
        table = '<table class="shisetsu-amenityspec_body"><tr><td>○</td><td>タオル</td></tr></table>'
        wrapper = '<div class="shisetsu-amenityspec_body_wrap">{}</div>'
        for extra in (wrapper.format(table) * 2, wrapper.format(table * 2)):
            raw = detail_html().replace(b'</body>', extra.encode('cp932') + b'</body>')
            with self.subTest(extra=extra), self.assertRaises(jalan.SourceError):
                jalan.parse_detail(raw, '123456', NAME, TODAY)

    def test_unscoped_same_class_table_does_not_establish_amenity_grid(self):
        extra = '<table class="shisetsu-amenityspec_body"><tr><td>○</td><td>タオル</td></tr></table>'
        raw = detail_html().replace(b'</body>', extra.encode('cp932') + b'</body>')
        value = jalan.parse_detail(raw, '123456', NAME, TODAY)
        self.assertEqual(value['sections'][-1]['state'], 'unknown')
        self.assertEqual(value['sections'][-1]['source_rows'], [])

    def test_room_types_decimal_area_and_qualifications(self):
        value = jalan.parse_rooms(rooms_html(), '123456', NAME)
        room, = value['room_types']
        self.assertEqual((room['name_ja'], room['area_m2_min'], room['area_m2_max']), ('ダブル', 12.5, 12.5))
        self.assertEqual(room['published_room_count_ja'], '12室')
        self.assertNotIn('99,000', json.dumps(value, ensure_ascii=False))
        self.assertEqual(value['notes'][0]['value_ja'], '冷暖房切替不可')

    def test_area_range_and_unknown_units(self):
        for area, expected in [('16～23㎡', (16.0, 23.0)), ('和室8畳', (None, None))]:
            value = jalan.parse_rooms(rooms_html(area), '123456', NAME)['room_types'][0]
            self.assertEqual((value['area_m2_min'], value['area_m2_max']), expected)
            self.assertEqual(value['size_ja'], area)

    def test_missing_room_table_unknown_changed_columns_error(self):
        value = jalan.parse_rooms(encoded(f'<h1 class="jlnpc-yado__subTitle">{NAME}の部屋</h1><input name="yadNo" value="123456"><p>写真のみ 広さ20㎡</p>'), '123456', NAME)
        self.assertEqual(value['state'], 'unknown')
        raw = rooms_html().decode('cp932').replace('通常料金（消費税込み）', '新料金')
        with self.assertRaises(jalan.SourceError): jalan.parse_rooms(raw.encode('cp932'), '123456', NAME)


class CliTests(unittest.TestCase):
    def test_invalid_input_does_not_read_network(self):
        for arguments in [['search', '--directory', 'https://evil.test/', '--expect', 'JR金沢駅'],
                          ['search', '--directory', DIRECTORY, '--expect', 'JR金沢駅', '--limit', '31'],
                          ['detail', '../secret']]:
            with patch.object(jalan.Client, 'read') as read, contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(hotels.main(arguments), 2)
                read.assert_not_called()
                self.assertEqual(json.loads(out.getvalue())['usage']['http_requests'], 0)

    def test_doctor_is_offline(self):
        with patch.object(jalan.Client, 'read') as read, contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(hotels.main(['doctor']), 0)
            self.assertFalse(json.loads(out.getvalue())['network_checked'])
            read.assert_not_called()

    def test_limit_retains_page_coverage(self):
        client = Mock()
        client.read.return_value = search_html(cards=card()+card('234567'), total=2), {'url': DIRECTORY}
        args = hotels.parser().parse_args(['search', '--directory', DIRECTORY, '--expect', 'JR金沢駅', '--limit', '1'])
        value = hotels.query(client, args)
        self.assertEqual((value['source_cards_on_page'], value['returned_count'], value['output_truncated']), (2, 1, True))
        client.read.assert_called_once()

    def test_room_failure_preserves_profile_and_error(self):
        client = Mock()
        client.read.side_effect = [(detail_html(), {'url': 'profile'}), jalan.SourceError('http_error', 'denied', http_status=403)]
        value = hotels.query(client, hotels.parser().parse_args(['detail', '123456', '--rooms']))
        self.assertEqual(value['status'], 'partial')
        self.assertEqual(value['name_ja'], NAME)
        self.assertEqual(value['rooms']['error']['http_status'], 403)
        self.assertEqual(client.read.call_count, 2)

    def test_detail_embedded_news_preserves_source_without_additional_reads(self):
        news = '<h1 class="news-contents-title">宿の紹介記事</h1>'.encode('cp932')
        client = Mock()
        client.read.return_value = (detail_html().replace(b'</body>', news + b'</body>'),
                                    {'url': 'https://www.jalan.net/yad123456/?dateUndecided=1'})
        args = hotels.parser().parse_args(['detail', '123456', '--expect', NAME])
        value = hotels.query(client, args)
        self.assertEqual(value['status'], 'ok')
        self.assertEqual(value['name_ja'], NAME)
        self.assertEqual(value['source']['url'], client.read.return_value[1]['url'])
        self.assertEqual(value['rooms']['state'], 'not_requested')
        client.read.assert_called_once_with(jalan.hotel_url('123456'))

    def test_unexpected_room_layout_preserves_profile(self):
        client = Mock()
        client.read.side_effect = [(detail_html(), {'url': 'profile'}), (rooms_html(), {'url': 'room'})]
        with patch.object(jalan, 'parse_rooms', side_effect=ValueError('changed layout')):
            value = hotels.query(client, hotels.parser().parse_args(['detail', '123456', '--rooms']))
        self.assertEqual(value['status'], 'partial')
        self.assertEqual(value['rooms']['source']['url'], 'room')
        self.assertEqual(value['rooms']['error']['code'], 'source_schema_changed')

    def test_source_failure_retains_attempted_url(self):
        url = jalan.hotel_url('123456')
        def denied(client, requested):
            client.last_source = {'url': requested, 'retrieved_at': None}
            raise jalan.SourceError('http_error', 'Denied', http_status=403)
        with patch.object(jalan.Client, 'read', denied), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(hotels.main(['detail', '123456']), 2)
        self.assertEqual(json.loads(out.getvalue())['source']['url'], url)

    def test_no_room_link_no_speculative_request(self):
        client = Mock()
        client.read.return_value = detail_html(room_link=False), {}
        value = hotels.query(client, hotels.parser().parse_args(['detail', '123456', '--rooms']))
        self.assertEqual(value['rooms']['state'], 'unknown')
        client.read.assert_called_once()


class RequestTests(unittest.TestCase):
    def test_allowlist_rejects_credentials_queries_and_transaction_paths(self):
        good = jalan.directory_url(DIRECTORY, 2, ['bath', 'station5'])
        self.assertTrue(jalan.allowed(good))
        self.assertTrue(jalan.allowed(jalan.hotel_url('123456', True)))
        for url in [good.replace('www.jalan.net', 'www.jalan.net.evil.test'), good+'&adultNum=2', good+'&dateUndecided=1',
                    good.replace('https:', 'http:'), good+'#fragment', 'https://www.jalan.net/yad123456/plan/?dateUndecided=1',
                    good.replace('www.jalan.net', ('user:pass' + '@' + 'www.jalan.net')), good.replace('page2', 'page11')]:
            with self.subTest(url=url): self.assertFalse(jalan.allowed(url))
        for url in [DIRECTORY+'?dateUndecided=1', DIRECTORY+'#foo', DIRECTORY.replace('spt_guide', 'STA_')]:
            with self.assertRaises(jalan.SourceError): jalan.directory_url(url)

    def test_http_denial_no_retry_or_cookies(self):
        client = jalan.Client()
        client.opener = Mock()
        client.opener.open.side_effect = urllib.error.HTTPError(jalan.hotel_url('123456'), 429, 'Slow down', {'Retry-After': '120'}, None)
        with self.assertRaises(jalan.SourceError) as error: client.read(jalan.hotel_url('123456'))
        self.assertEqual(error.exception.details['retry_after'], '120')
        self.assertEqual(client.requests, 1)
        client.opener.open.assert_called_once()
        self.assertNotIn('Cookie', dict(client.opener.open.call_args[0][0].header_items()))

    def test_body_cap_and_budget(self):
        client = jalan.Client()
        client.opener = MagicMock()
        response = client.opener.open.return_value.__enter__.return_value
        response.status = 200
        response.headers = {}
        response.read.return_value = b'x' * 9
        with patch.object(jalan, 'BODY_LIMIT', 8):
            with self.assertRaises(jalan.SourceError) as error: client.read(jalan.hotel_url('123456'))
        self.assertEqual(error.exception.code, 'response_too_large')
        client.requests = 2
        with self.assertRaises(jalan.SourceError): client.read(jalan.hotel_url('123456'))
        self.assertEqual(client.opener.open.call_count, 1)

    def test_redirect_is_rejected(self):
        with self.assertRaises(jalan.SourceError): jalan.RejectRedirect().redirect_request(None, None, 302, '', {}, 'https://evil.test')


if __name__ == '__main__': unittest.main()
