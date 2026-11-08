"""Published policies remain distinct from slot, child and checkout eligibility."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import json
from pathlib import Path
import unittest

import httpx

from tabelog_client.parsers import parse_detail
from tablecheck_client.service import TableCheck
from tablecheck_client.cli import run as tablecheck_run
from tablecheck_client.transport import Client as TableCheckClient
from pocket_concierge_client.service import PocketConcierge
from pocket_concierge_client.transport import Client as PocketClient


class DetailInfoTests(unittest.TestCase):
    def test_tabelog_recorded_details_expose_policies_and_website_without_inventory(self):
        path = Path(__file__).parent/'fixtures/ebitei-detail.html'
        url = 'https://tabelog.com/en/toyama/A1601/A160101/16010357/'
        detail = parse_detail(path.read_text(), {'id': '16010357'}, url)
        info = detail['practical_info']
        self.assertIs(info['reservation']['accepted'], True)
        self.assertIs(info['reservation']['required'], True)
        self.assertIs(info['reservation']['availability_checked'], False)
        self.assertIs(info['payment']['credit_cards_accepted'], True)
        self.assertIs(info['payment']['electronic_money_accepted'], False)
        self.assertIs(info['payment']['qr_payments_accepted'], False)
        self.assertIs(info['payment']['cash_only'], False)
        self.assertIn('Children aged 12', info['children']['evidence'][0]['text'])
        self.assertFalse(info['children']['eligibility_checked'])
        self.assertIn('https://ebitei-bekkan.com/', [link['url'] for link in info['links'] if link['kind'] == 'website'])
        self.assertEqual(info['payment']['evidence'][0]['source_url'], url)

    def test_tabelog_negative_conditional_and_absent_flags_remain_distinct(self):
        def parse(reservation='', payment='', remarks=''):
            body = '<script type="application/ld+json">{"@type":"Restaurant","name":"例示店"}</script>'
            body += '<table class="rstinfo-table"><tr><th>予約可否</th><td>'+reservation+'</td></tr>'
            body += '<tr><th>支払い方法</th><td>'+payment+'</td></tr>'
            body += '<tr><th>備考</th><td>'+remarks+'</td></tr></table>'
            return parse_detail(body, {'id': '12345678'}, 'https://tabelog.com/tokyo/A1301/A130101/12345678/')['practical_info']
        self.assertIs(parse('予約不可')['reservation']['accepted'], False)
        self.assertIsNone(parse('予約可')['reservation']['required'])
        self.assertIsNone(parse('条件により受付')['reservation']['accepted'])
        self.assertIs(parse(payment='現金のみ')['payment']['cash_only'], True)
        value = parse(payment='カード不可<br>電子マネー可<br>QRコード決済不可')['payment']
        self.assertIs(value['credit_cards_accepted'], False)
        self.assertIs(value['electronic_money_accepted'], True)
        self.assertIs(value['cash_only'], False)
        value = parse(payment='Credit card accepted for dinner only')['payment']
        self.assertIsNone(value['credit_cards_accepted'])
        self.assertIsNone(value['cash_only'])
        value = parse(payment='カード不可')['payment']
        self.assertIsNone(value['cash_only'])
        value = parse(payment='カード可', remarks='ランチは現金のみ、ディナーはカード可。')['payment']
        self.assertIsNone(value['credit_cards_accepted'])
        self.assertIsNone(value['cash_only'])
        self.assertEqual(len(value['evidence']), 2)
        self.assertEqual(parse()['payment']['evidence'], [])

    def test_missing_policies_remain_unknown_across_platforms(self):
        from tablecheck_client.detail_info import practical_info as tablecheck_info
        from pocket_concierge_client.detail_info import practical_info as pocket_info
        body = '<script type="application/ld+json">{"@type":"Restaurant","name":"例示店"}</script>'
        values = [parse_detail(body, {'id': '12345678'}, 'https://tabelog.com/tokyo/A1301/A130101/12345678/')['practical_info'],
                  tablecheck_info({'slug': 'sample'}, None), pocket_info({}, 'https://www.pocket-concierge.jp/ja/restaurants/123456')]
        for info in values:
            self.assertIsNone(info['reservation']['accepted'])
            self.assertEqual(info['reservation']['evidence'], [])
            self.assertIsNone(info['payment']['cash_only'])
            self.assertIsNone(info['payment']['credit_cards_accepted'])
            self.assertEqual(info['payment']['evidence'], [])
            self.assertEqual(info['children']['evidence'], [])
            self.assertFalse(info['children']['eligibility_checked'])

    def test_tabelog_links_preserve_explicit_targets_without_guessing_or_following(self):
        body = '''<script type="application/ld+json">{"@type":"Restaurant","name":"例示店"}</script>
          <table class="rstinfo-table"><tr><th>ホームページ</th><td>
          <a href="https://example.com/">公式サイト</a>
          <a href="https://www.tablecheck.com/ja/shops/sample/reserve">予約</a>
          <a href="https://www.pocket-concierge.jp/ja/restaurants/123456">PC</a>
          <a href="javascript:alert(1)">invalid</a>
          <a href="https://example.com/?session=example-private">session</a>
          </td></tr></table>'''
        info = parse_detail(body, {'id': '12345678'}, 'https://tabelog.com/tokyo/A1301/A130101/12345678/')['practical_info']
        self.assertEqual(len(info['links']), 4)
        channels = [link for link in info['links'] if link['kind'] == 'booking_entry']
        self.assertEqual({link['platform'] for link in channels}, {'tablecheck', 'pocket_concierge'})
        self.assertTrue(all(link['verification'] == 'listed_link' for link in channels))

    def test_tablecheck_detail_uses_one_existing_read_and_keeps_payment_scope_unknown(self):
        shop = {'_id': '1'*24, 'slug': 'sample', 'booking_page_mode': 'v1',
                'url': 'https://example.com/', 'name_translations': [],
                'request_policy_translations': [{'locale': 'ja', 'translation':
                    '<p>予約時はクレジットカードの登録が必要です。現地のお支払いは現金のみ。</p>'
                    '<p>お子様は12歳以上で同じコースを召し上がる方のみ。</p>'}]}
        requests = []
        def handler(request):
            requests.append(request)
            self.assertEqual(request.url.path, '/v2/shops/sample')
            return httpx.Response(200, json={'shops': [shop]})
        transport = TableCheckClient(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0)
        self.addCleanup(transport.close)
        detail = TableCheck(transport).detail('sample', '2099-12-01', '2099-12-02', include_courses=False)
        info = detail['practical_info']
        self.assertEqual(len(requests), 1)
        self.assertIsNone(info['payment']['credit_cards_accepted'])
        self.assertIsNone(info['payment']['cash_only'])
        self.assertIn('現地のお支払いは現金のみ', info['payment']['evidence'][0]['text'])
        self.assertIn('12歳以上', info['children']['evidence'][0]['text'])
        self.assertEqual(detail['policy_ja'], shop['request_policy_translations'][0]['translation'])
        self.assertEqual(info['links'][0]['kind'], 'booking_entry')
        self.assertFalse(info['reservation']['availability_checked'])

    def test_pocket_detail_groups_terms_and_faq_without_interpreting_transaction_flags(self):
        venue = {'id': '123456', 'name': '例示店', 'realTimeBooking': True, 'transactionsAllowed': True,
                 'reservationTerms': 'ご予約はオンラインでお願いします。\n\nお子様は12歳以上のみ。',
                 'frequentlyAskedQuestions': [{'question': '支払い方法は？', 'answer': '現金のみです。'},
                                              {'question': '子供のコースは？', 'answer': '大人と同じコースです。'}]}
        def handler(request):
            query = json.loads(request.content)['query']
            self.assertIn('reservationTerms', query)
            self.assertNotIn('availabilitySearch', query)
            return httpx.Response(200, json={'data': {'venue': venue}})
        transport = PocketClient(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0)
        self.addCleanup(transport.close)
        detail = PocketConcierge(transport).detail('123456', include_courses=False)
        info = detail['practical_info']
        self.assertEqual(transport.requests, 1)
        self.assertIsNone(info['payment']['credit_cards_accepted'])
        self.assertIsNone(info['payment']['cash_only'])
        self.assertEqual(info['payment']['evidence'][0]['text'], '支払い方法は？\n現金のみです。')
        self.assertEqual(len(info['children']['evidence']), 2)
        self.assertFalse(info['children']['eligibility_checked'])
        self.assertTrue(detail['transactions_allowed'])
        self.assertEqual(info['links'][0]['platform'], 'pocket_concierge')

    def test_tablecheck_missing_api_notices_read_the_public_notice_once(self):
        shop = {'_id': '1'*24, 'slug': 'sample', 'booking_page_mode': 'v1', 'name_translations': []}
        def handler(request):
            if request.url.path == '/v2/shops/sample':
                return httpx.Response(200, json={'shops': [shop]})
            self.assertEqual(request.url.path, '/en/shops/sample/reserve')
            return httpx.Response(200, text='<div class="reserveform-bookingpolicy-text">'
                '完全予約制<br><br>お子様は12歳以上のみ。<br><br>現金のみ。<br></div>'
                '<input name="authenticity_token" value="example-private">')
        transport = TableCheckClient(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0)
        self.addCleanup(transport.close)
        result = TableCheck(transport).detail('sample', '2099-12-01', '2099-12-02', include_courses=False)
        self.assertEqual(transport.requests, 2)
        info = result['practical_info']
        self.assertEqual(info['children']['evidence'][0]['field'], 'public_form.notice')
        self.assertIn('12歳以上', info['children']['evidence'][0]['text'])
        self.assertIn('現金のみ', info['payment']['evidence'][0]['text'])
        self.assertNotIn('example-private', json.dumps(result))
        self.assertIsNone(info['payment']['credit_cards_accepted'])

    def test_tablecheck_notice_denial_keeps_details_partial_and_stops_further_reads(self):
        shop = {'_id': '1'*24, 'slug': 'sample', 'booking_page_mode': 'v1', 'name_translations': []}
        def handler(request):
            if request.url.path == '/v2/shops/sample':
                return httpx.Response(200, json={'shops': [shop]})
            self.assertTrue(request.url.path.endswith('/reserve'))
            return httpx.Response(403)
        transport = TableCheckClient(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0)
        self.addCleanup(transport.close)
        result = TableCheck(transport).detail('sample', '2099-12-01', '2099-12-02')
        self.assertEqual(transport.requests, 2)
        self.assertEqual(result['coverage'], 'partial')
        self.assertEqual(result['errors'][0]['code'], 'access_denied')
        self.assertIsNone(result['courses'])
        self.assertEqual(result['slug'], 'sample')

    def test_tablecheck_menu_failures_keep_known_details_and_safe_error_types(self):
        shop = {'_id': '1'*24, 'slug': 'sample', 'booking_page_mode': 'v1', 'name_translations': [], 'time_zone': 'Asia/Tokyo'}
        for denied in (False, True):
            with self.subTest(denied=denied):
                def handler(request):
                    if request.url.path == '/v2/shops/sample':
                        return httpx.Response(200, json={'shops': [shop]})
                    if request.url.path.endswith('/reserve'):
                        return httpx.Response(200, text='<div class="reserveform-bookingpolicy-text">Closed Sundays.</div>')
                    self.assertEqual(request.url.path, '/v2/hub/menu_items')
                    if denied:
                        return httpx.Response(403)
                    raise httpx.ReadTimeout('example-private-transport-message', request=request)
                transport = TableCheckClient(session=httpx.Client(transport=httpx.MockTransport(handler)), delay_min_ms=0, delay_max_ms=0)
                result = tablecheck_run(['detail', 'sample', '--from', '2099-12-01', '--to', '2099-12-02'],
                                        create_client=lambda **_: transport)
                self.assertEqual(result['exit_code'], 3)
                output = result['output']
                self.assertEqual(output['status'], 'partial')
                self.assertEqual(output['data']['slug'], 'sample')
                self.assertIsNone(output['data']['courses'])
                self.assertEqual(output['data']['errors'][0]['scope'], 'courses')
                self.assertIn('Closed Sundays.', output['data']['practical_info']['reservation']['evidence'][0]['text'])
                self.assertEqual(output['usage']['network_requests_started'], 3)
                self.assertNotIn('example-private-transport-message', json.dumps(output))
                if not denied:
                    self.assertEqual(output['data']['errors'][0]['exception_type'], 'ReadTimeout')
                    self.assertEqual(output['trace'][-1]['error']['exception_type'], 'ReadTimeout')
                else:
                    self.assertEqual(output['data']['errors'][0]['code'], 'access_denied')
