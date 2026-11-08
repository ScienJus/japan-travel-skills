"""Synthetic source-shaped HTML; no captured climate tables bundled in tests."""
import contextlib
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'skills/japan-weather/scripts'
sys.path.insert(0, str(SCRIPTS))
import jma_climate as c
SPEC = importlib.util.spec_from_file_location('weather_climate_test', SCRIPTS / 'weather.py')
w = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(w)
REGION = {'prec_no':'56', 'name_ja':'石川県'}
STATION = dict(REGION, station_name_ja='金沢', block_no='47605', station_kind='surface')


def menu():
    return b'''<map name="point"><area alt="\xe7\x9f\xb3\xe5\xb7\x9d\xe7\x9c\x8c" href="prefecture.php?prec_no=56&amp;block_no=&amp;year=&amp;month=&amp;day=&amp;view="></map>'''


def station_menu():
    # Duplicate map hotspots are normal. AMeDAS entries use another table schema.
    surface = '''<area alt="金沢" href="../index.php?prec_no=56&block_no=47605&year=&month=&day=&view=" onmouseover="javascript:viewPoint('s','47605','金沢','テスト');">'''
    amedas = surface.replace('金沢','山の観測所').replace('47605','0560').replace("('s'", "('a'")
    return ('<img alt="地点選択用石川県地図"><map name="point">' + surface*2 + amedas + '</map>').encode()


def monthly_page(overrides=None, period='1991～2020', samples='30'):
    # Eight selected quantities, including realistic rowspan/colspan headers.
    headers = '''<tr><th rowspan="3">要素</th><th colspan="3">気温</th><th>降水量</th><th>日照時間</th><th colspan="2">雪</th><th>大気現象</th></tr>
<tr><th rowspan="2">平均<br>(℃)</th><th rowspan="2">日最高<br>(℃)</th><th rowspan="2">日最低<br>(℃)</th><th rowspan="2">合計<br>(mm)</th><th rowspan="2">合計<br>(時)</th><th>降雪の深さ</th><th rowspan="2">最深積雪<br>(cm)</th><th rowspan="2">雪日数</th></tr>
<tr><th>合計<br>(cm)</th></tr>'''
    rows = ['<tr><th>統計期間</th>' + ('<td>'+period+'</td>')*8 + '</tr>',
            '<tr><th>資料年数</th>' + ('<td>'+samples+'</td>')*8 + '</tr>']
    values = ['7.2','12.4','-1.1','222.5','101.3','0','0','0.0']
    for month in range(1,13):
        cells = [str((overrides or {}).get((month,i),v)) for i,v in enumerate(values)]
        rows.append('<tr><th><a>'+str(month)+'月</a></th>'+''.join('<td>'+v+'</td>' for v in cells)+'</tr>')
    rows.append('<tr><th>年</th>'+'<td>0</td>'*8+'</tr>')
    return ('''<a href="../index.php?prec_no=56&block_no=47605&year=&month=&day=&view=">Station</a>
<h3>金沢（石川県)　平年値（年・月ごとの値）　主な要素</h3><table id="tablefix1">'''+headers+''.join(rows)+'</table>').encode()


class CatalogTests(unittest.TestCase):
    def test_live_map_discovery_keeps_exact_station_identity(self):
        self.assertEqual(c.regions(menu()), [REGION])
        self.assertEqual(c.stations(station_menu(),REGION), [STATION])

    def test_substrings_and_ambiguous_names_are_not_substituted(self):
        for query,rows in [('石川',[REGION]), ('石川県',[REGION,REGION])]:
            with self.assertRaises(c.WeatherError): c.select(query,rows,'name_ja')

    def test_station_region_name_and_code_mismatches_fail(self):
        for old,new in [('地点選択用石川県地図','地点選択用福井県地図'), ('prec_no=56','prec_no=57'),
                        ("'47605'","'47606'"), ("'金沢'","'別の観測所'")]:
            with self.subTest(change=old), self.assertRaises(c.WeatherError):
                c.stations(station_menu().decode().replace(old,new).encode(),REGION)

    def test_untrusted_menu_links_and_shell_fail(self):
        for body in [b'<html>Maintenance</html>', menu().replace(b'prefecture.php?',b'https://example.org/prefecture.php?')]:
            with self.assertRaises(c.WeatherError): c.regions(body)


class MonthlyTests(unittest.TestCase):
    def test_values_have_quantities_periods_samples_and_station_identity(self):
        result=c.monthly(monthly_page(),STATION,[11])[0]
        self.assertEqual(result['month'],11)
        self.assertEqual(result['status'],'ok')
        metric=result['metrics']['mean_daily_low_c']
        self.assertEqual(metric['value'],-1.1)
        self.assertEqual(metric['statistical_period'],{'from_year':1991,'to_year':2020})
        self.assertEqual(metric['sample_years'],30)
        self.assertEqual(result['metrics']['precipitation_total_mm']['value'],222.5)

    def test_quality_and_missing_markers_are_not_zero_or_normal(self):
        for marker,quality,value in [('---','no_phenomenon',None), ('///','missing_or_not_observed',None),
                                     ('','missing',None), ('×','missing',None), ('#','questionable',None),
                                     ('4.2 @','reference',4.2), ('4.2 )','quasi_normal',4.2), ('4.2 ]','insufficient',4.2)]:
            with self.subTest(marker=marker):
                row=c.monthly(monthly_page({(11,5):marker}),STATION,[11])[0]
                metric=row['metrics']['snowfall_total_cm']
                self.assertEqual((metric['value'],metric['quality'],metric['raw']),(value,quality,marker))
                self.assertEqual(row['status'],'partial')

    def test_actual_zero_is_preserved(self):
        self.assertEqual(c.monthly(monthly_page(),STATION,[11])[0]['metrics']['snowfall_total_cm']['value'],0)

    def test_unsupported_quality_nonfinite_and_negative_quantities_fail(self):
        for cell in ['N/A', '3.2 ?', 'NaN', '9'*400, '-2.0']:
            with self.subTest(cell=cell[:20]), self.assertRaises(c.WeatherError):
                c.monthly(monthly_page({(11,3):cell}),STATION,[11])

    def test_wrong_station_region_product_and_native_code_fail(self):
        body=monthly_page()
        for old,new in [('金沢','輪島'), ('石川県','富山県'), ('年・月ごとの値','日ごとの値'), ('block_no=47605','block_no=47600')]:
            with self.subTest(change=old), self.assertRaises(c.WeatherError):
                c.monthly(body.decode().replace(old,new).encode(),STATION,[11])

    def test_header_unit_changes_cannot_shift_columns(self):
        for old,new in [('(mm)','(cm)'), ('日最高','日最低'), ('合計<br>(時)','平均<br>(時)')]:
            with self.subTest(change=old), self.assertRaises(c.WeatherError):
                c.monthly(monthly_page().decode().replace(old,new).encode(),STATION,[11])

    def test_missing_duplicate_reordered_rows_and_tables_fail(self):
        body=monthly_page().decode()
        variants=[body.replace('11月','12月'),body.replace('資料年数','資料なし'),
                  body+body,body.rsplit('</td>',1)[0]]
        for variant in variants:
            with self.assertRaises(c.WeatherError): c.monthly(variant.encode(),STATION,[11])

    def test_statistical_period_is_read_not_pinned_to_old_normals(self):
        result=c.monthly(monthly_page(period='1995～2024'),STATION,[1])[0]
        self.assertEqual(result['metrics']['mean_temperature_c']['statistical_period']['to_year'],2024)
        for period,samples in [('1991～2020','31'), ('1991～2020','0'), ('2020～1991','30'), ('1991～2100','30')]:
            with self.assertRaises(c.WeatherError): c.monthly(monthly_page(period=period,samples=samples),STATION,[1])


class CommandTests(unittest.TestCase):
    def run_command(self,opts,bodies):
        with patch.object(c.Client,'read',side_effect=bodies) as read, contextlib.redirect_stdout(io.StringIO()) as out:
            code=w.main(opts)
        return code,json.loads(out.getvalue()),read

    def test_named_query_shares_one_annual_table_across_selected_months(self):
        code,value,read=self.run_command(['climate','--prefecture','石川県','--station','金沢','--month','11','--month','12','--month','11'],[menu(),station_menu(),monthly_page()])
        self.assertEqual((code,read.call_count,value['kind']),(0,3,'climate_normals'))
        self.assertEqual(value['requested_months'],[11,12])
        self.assertIsNone(value['source']['issued_at'])
        self.assertNotIn('forecasts',value)

    def test_verified_codes_skip_menus_but_require_native_page_identity(self):
        opts=['climate','--prefecture','石川県','--station','金沢','--prec-no','56','--block-no','47605']
        code,value,read=self.run_command(opts,[monthly_page()])
        self.assertEqual((code,read.call_count,len(value['months'])),(0,1,12))
        code,value,read=self.run_command(opts,[monthly_page().replace('金沢'.encode(),'輪島'.encode())])
        self.assertEqual((code,value['climate_state']),(2,'unknown'))
        self.assertNotIn('months',value)

    def test_invalid_code_pairs_stop_before_network(self):
        for flags in [['--prec-no','56'], ['--prec-no','56','--block-no','0560'], ['--prec-no','99','--block-no','89532']]:
            code,value,read=self.run_command(['climate','--prefecture','石川県','--station','金沢']+flags,[])
            self.assertEqual(code,2)
            read.assert_not_called()

    def test_unknown_station_stops_before_climate_table_request(self):
        code,value,read=self.run_command(['climate','--prefecture','石川県','--station','金'],[menu(),station_menu()])
        self.assertEqual((code,read.call_count,value['climate_state']),(2,2,'unknown'))

    def test_source_denial_has_no_partial_climate_result(self):
        code,value,read=self.run_command(['climate-regions'],c.WeatherError('http_error','Synthetic denial',http_status=403))
        self.assertEqual((code,read.call_count,value['climate_state']),(2,1,'unknown'))
        self.assertNotIn('regions',value)

    def test_discovery_is_online_and_keeps_native_names(self):
        code,value,read=self.run_command(['climate-stations','--prefecture','石川県'],[menu(),station_menu()])
        self.assertEqual((code,read.call_count,value['stations']),(0,2,[STATION]))


class ClientTests(unittest.TestCase):
    def test_allowlist_rejects_redirect_targets_extra_params_and_amedas(self):
        for address in [c.url('view/nml_sfc_ym.php','56','0560'), c.url('select/prefecture.php','56')+'&extra=1',
                        c.url('select/prefecture.php','56').replace('https:','http:'), 'https://example.org/']:
            with self.assertRaises(c.WeatherError): c.Client().read(address)
        with self.assertRaises(c.WeatherError): c.RejectRedirect().redirect_request(None,None,302,'',{},'https://example.org/')

    def test_cache_budget_size_and_protocol_failure_are_bounded(self):
        client=c.Client()
        address=c.url('select/prefecture00.php')
        with patch.object(client.opener,'open') as read:
            read.return_value.__enter__.return_value.status=200
            read.return_value.__enter__.return_value.headers={}
            read.return_value.__enter__.return_value.read.return_value=b'<html></html>'
            self.assertEqual(client.read(address),client.read(address))
            self.assertEqual((read.call_count,client.requests,client.cache_hits),(1,1,1))
        client=c.Client()
        client.requests=3
        with self.assertRaises(c.WeatherError): client.read(address)
        for failure in [http.client.IncompleteRead(b'x'), urllib.error.HTTPError(address,429,'Throttled',{'Retry-After':'60'},None)]:
            client=c.Client()
            with patch.object(client.opener,'open',side_effect=failure) as read, self.assertRaises(c.WeatherError):
                client.read(address)
            self.assertEqual(read.call_count,1)
        client=c.Client()
        with patch.object(client.opener,'open') as read:
            read.return_value.__enter__.return_value.status=200
            read.return_value.__enter__.return_value.headers={}
            read.return_value.__enter__.return_value.read.return_value=b'x'*(c.MAX_BYTES+1)
            with self.assertRaises(c.WeatherError): client.read(address)


if __name__=='__main__': unittest.main()
