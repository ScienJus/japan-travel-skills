"""Catalog scope, malformed responses and bounded directory reads; no network."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit, parse_qs

from tabelog_client.catalog import Catalog, parse_catalog, parse_neighborhoods
from tabelog_client.cli import run
from tabelog_client.core import CliError
from tabelog_client.service import Tabelog
from tabelog_client.transport import Client, request_headers

FIXTURES = Path(__file__).parent / 'fixtures'
CITY_URL = 'https://tabelog.com/ishikawa/C17201/rstLst/'
CITY = {'name':'Kanazawa City', 'datatype':'AddressMaster', 'id_in_datatype':48339,
        'exact_match':True, 'pal':'ishikawa', 'LstPrf':'C17201'}


def response(body, url):
    return {'body':body if isinstance(body,str) else json.dumps(body),'url':url,'http_status':200}


def client(reader, **kwargs):
    return Client(reader=reader, delay_min_ms=0, delay_max_ms=0, **kwargs)


class CatalogParsingTests(unittest.TestCase):
    def test_nul_encoded_xml_is_rejected_before_parsing(self):
        body = '<items><item name="fixture" optval="A1701"/></items>'
        disguised = body.encode('utf-16-le').decode('utf-8')
        with self.assertRaises(CliError):
            parse_catalog(disguised, 'area1', {'id': '17'}, 'source')

    def test_recorded_hierarchy_and_station_options(self):
        for filename, level, parent, count, first_id in [
            ('catalog-ishikawa-area1.xml','area1',{'id':'17'},4,'A1701'),
            ('catalog-kanazawa-area2.xml','area2',{'id':'A1701'},2,'A170101'),
            ('catalog-kanazawa-stations.xml','station',{'id':'A170101'},22,'11810'),
        ]:
            rows = parse_catalog((FIXTURES/filename).read_text(),level,parent,'source')
            self.assertEqual(len(rows),count)
            self.assertEqual(rows[0]['id'],first_id)
            self.assertNotIn('0',[r['id'] for r in rows])

    def test_malformed_empty_and_cross_parent_xml_unknown(self):
        for body in ['<html/>', '<items/>', '<items><item name="すべて" optval="0"/></items>',
                     '<!DOCTYPE items><items/>', '<items><item name="bad" optval="A1301"/></items>',
                     '<items><item name="bad" optval="17"/></items>',
                     '<items><item name="one" optval="A1701"/><item name="two" optval="A1701"/></items>']:
            with self.subTest(body=body),self.assertRaises(CliError):
                parse_catalog(body,'area1',{'id':'17'},'source')
        with self.assertRaises(CliError):
            parse_catalog('<items><item name="bad" optval="A170201"/></items>','area2',{'id':'A1701'},'source')

    def test_repeated_identical_options_deduplicate(self):
        row='<item name="金沢駅" optval="11810"/>'
        rows=parse_catalog('<items>'+row*2+'</items>','station',{'id':'A170101'},'source')
        self.assertEqual(len(rows),1)

    def test_municipal_nav_all_tabs_and_parent_boundaries(self):
        body='''<div id="js-leftnavi-area-scroll"><a href="/ishikawa/C17201/rstLst/">parent</a>
        <div id="tab-a"><a href="/ishikawa/C17201/C48340/rstLst/">青草町</a></div>
        <div id="tab-b" hidden><a href="/ishikawa/C17201/C48342/rstLst/">暁町</a></div>
        <a href="https://evil.example/ishikawa/C17201/C48343/rstLst/">external</a>
        <a href="/ishikawa/C17202/C100/rstLst/">different city</a>
        <a href="/ishikawa/A1701/A170101/R11800/rstLst/">search-area station</a></div>
        <a href="/ishikawa/C17201/C48344/rstLst/">sidebar recommendation</a>'''
        rows=parse_neighborhoods(body,'C17201','ishikawa',CITY_URL)
        self.assertEqual([r['name'] for r in rows],['青草町','暁町'])
        self.assertTrue(all(r['parent_id']=='C17201' for r in rows))
        with self.assertRaises(CliError):
            parse_neighborhoods('<html/>','C17201','ishikawa',CITY_URL)

    def test_recorded_municipal_directory_is_not_keyword_suggestions(self):
        rows=parse_neighborhoods((FIXTURES/'catalog-kanazawa-neighborhoods.html').read_text(),'C17201','ishikawa',CITY_URL)
        self.assertGreater(len(rows),300)
        self.assertIn('青草町',[r['name'] for r in rows])
        self.assertIn('駅西本町',[r['name'] for r in rows])
        self.assertEqual(len(rows),len({r['id'] for r in rows}))


class CatalogWorkflowTests(unittest.TestCase):
    def test_no_scope_lists_prefectures_offline_with_reusable_codes(self):
        c = client(lambda url: self.fail('Prefecture list must not make requests'))
        result = run(['areas'], create_client=lambda **_: c)
        self.assertEqual(result['exit_code'], 0)
        data = result['output']['data']
        self.assertEqual(len(data['items']), 47)
        self.assertEqual([r['id'] for r in data['items']], [str(n) for n in range(1, 48)])
        self.assertEqual(data['items'][16], {'id': '17', 'name': '石川県', 'type': 'prefecture'})
        self.assertEqual(data['items'][12]['name'], '東京都')
        self.assertEqual(data['items'][-1]['name'], '沖縄県')
        self.assertEqual(result['output']['usage']['network_requests_started'], 0)

    def test_numeric_parent_one_api_read_and_scope_reported(self):
        calls=[]
        body=(FIXTURES/'catalog-kanazawa-stations.xml').read_text()
        c=client(lambda url:calls.append(url) or response(body,url))
        result=Catalog(Tabelog(c)).stations('A170101')
        self.assertEqual(len(calls),1)
        self.assertEqual(urlsplit(calls[0]).path,'/xml/list_stations')
        self.assertEqual(parse_qs(urlsplit(calls[0]).query),{'type':['search'],'area2':['A170101']})
        self.assertEqual(result['meta']['relation'],'tabelog_search_hierarchy')
        self.assertEqual(result['meta']['administrative_completeness'],'not_verified')
        self.assertEqual(result['meta']['count'],22)
        self.assertIn('application/xml',request_headers(calls[0])['Accept'])

    def test_municipal_c_code_rejected_without_request(self):
        c=client(lambda url:self.fail('Must not query unsupported municipal scope'))
        with self.assertRaises(CliError):
            Catalog(Tabelog(c)).stations('C17201')
        self.assertEqual(c.usage()['transport_attempts'],0)

    def test_city_name_two_reads_no_per_neighborhood_fanout(self):
        calls=[]
        def read(url):
            calls.append(url)
            return response([CITY] if '/suggest/' in url else (FIXTURES/'catalog-kanazawa-neighborhoods.html').read_text(),url)
        result=Catalog(Tabelog(client(read))).areas(city='金沢市')
        self.assertEqual(len(calls),2)
        self.assertEqual(calls[-1],CITY_URL)
        self.assertEqual(result['parent']['id'],'C17201')
        self.assertEqual(result['parent']['suggestion_id'],'48339')
        self.assertEqual(result['meta']['relation'],'municipal_neighborhoods')
        self.assertGreater(result['meta']['count'],300)

    def test_prefecture_name_resolves_then_one_directory(self):
        calls=[]
        def read(url):
            calls.append(url)
            return response([{'name':'Ishikawa','datatype':'Prefecture','id_in_datatype':17,'exact_match':True}] if '/suggest/' in url else (FIXTURES/'catalog-ishikawa-area1.xml').read_text(),url)
        result=Catalog(Tabelog(client(read))).areas(prefecture='石川県')
        self.assertEqual(len(calls),2)
        self.assertEqual(result['parent']['id'],'17')
        self.assertEqual(result['meta']['count'],4)

    def test_city_ambiguity_and_redirect_cannot_change_municipality(self):
        app=Tabelog(client(lambda url:response([CITY,{**CITY,'name':'other','LstPrf':'C14108'}],url)))
        with self.assertRaises(CliError) as raised:
            Catalog(app).areas(city='金沢')
        self.assertEqual(raised.exception.code,'ambiguous_city')
        app=Tabelog(client(lambda url:response([CITY],url) if '/suggest/' in url else response((FIXTURES/'catalog-kanazawa-neighborhoods.html').read_text(),'https://tabelog.com/kanagawa/C14108/rstLst/')))
        with self.assertRaises(CliError):
            Catalog(app).areas(city='金沢市')

    def test_cli_named_commands_and_invalid_flags_are_structured(self):
        def create(**kwargs):
            kwargs.update(delay_min_ms=0,delay_max_ms=0)
            return Client(reader=lambda url:response((FIXTURES/'catalog-ishikawa-area1.xml').read_text(),url),**kwargs)
        result=run(['areas','--prefecture','17'],create)
        self.assertEqual(result['exit_code'],0)
        self.assertEqual(result['output']['data']['meta']['count'],4)
        for args in [['areas','--prefecture',''],['areas','--prefecture','48'],['areas','--prefecture','17','--city','金沢市'],
                     ['areas','--parent','C17201'],['stations','--area','C17201'],['stations','--city','金沢市']]:
            with self.subTest(args=args):
                r=run(args,create)
                self.assertEqual(r['exit_code'],1)
                usage = r['output']['usage']
                # Parser errors now occur before a client is created.
                if usage is not None:
                    self.assertEqual(usage['network_requests_started'], 0)
        result=run(['search','--station','金沢駅','--city','横浜市'],create)
        self.assertEqual(result['exit_code'],1)
        self.assertIsNone(result['output']['usage'])


if __name__=='__main__':
    unittest.main()
