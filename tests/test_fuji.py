"""Synthetic Fuji-source checks; never contact the publisher from unit tests."""
import contextlib
import datetime as dt
import http.client
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
import urllib.error
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1]/'skills/japan-fuji/scripts'
sys.path.insert(0,str(SCRIPTS))
import fuji_source as f
SPEC = importlib.util.spec_from_file_location('fuji_test',SCRIPTS/'fuji.py')
cli = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(cli)
NOW = dt.datetime(2026,11,1,22,tzinfo=f.JST)
INITIAL = NOW.replace(hour=9)
DATES = [dt.date(2026,11,2)+dt.timedelta(days=i) for i in range(7)]
SCRIPT = f.HOME+'lib/t24.js?202601010000'


def panel():
    days = '<td colspan="2">-</td>'*7
    periods = '<td>午前</td><td>午後</td>'*7
    body = '<title>富士見予報</title><script src="./lib/t24.js?202601010000"></script><table class="table01">'
    body += '<tr><td>富士見指数<br>1～10</td>'+days+'</tr><tr>'+periods+'</tr>'
    for side,cls in [('north','ne'),('south','s')]:
        body += '<tr><td>'+f.LABELS[side]+'</td>'+('<td class="findexv_'+cls+'">-</td>')*14+'</tr>'
        body += '<tr>'+('<td>-</td>')*14+'</tr>'
    return (body+'</table>').encode()


def script():
    body = ''
    for code,row in [('N',2),('S',4)]:
        body += "n_file_"+code+" = './data/fdata_"+code+".csv?' + sendTime;\n"
        body += ('var setValue_'+code+' = function(my_data, my_col) {\n'
                 'var findex = Math.ceil(my_data[1] / 10) + 1;\n'
                 'if (findex > 10) { findex = 10 }\n'
                 "$('.table01 tr').eq("+str(row)+").children('td').eq(my_col).html(findex);\n}\n")
    return body.encode()


def data(initial=INITIAL,count=21,values=None):
    rows = [initial.strftime('%Y/%m/%d %H:%M:%S')+',JST']
    for i in range(count):
        reference = dt.datetime.combine(initial.date()+dt.timedelta(days=1+i//2),dt.time(9 if i%2==0 else 15))
        raw = str(values[i%len(values)]) if values is not None else '70'
        rows.append(reference.strftime('%Y/%m/%d %H:%M:%S')+','+raw)
    return ('\r\n'.join(rows)+'\r\n').encode()


class SourceTests(unittest.TestCase):
    def parse(self,body=None,dates=DATES,now=NOW): return f.parse_csv(body if body is not None else data(),'north',dates,now)

    def test_published_panel_and_formula_contracts(self):
        self.assertEqual(f.panel_contract(panel()),SCRIPT)
        self.assertEqual(f.script_contract(script())['visible_days'],7)
        for before,after in [('Math.ceil','Math.floor'),('/ 10','/ 20'),('fdata_N.csv','another.csv'),('eq(4)','eq(2)'),('.table01 tr','.table01tr')]:
            with self.subTest(change=before),self.assertRaises(f.SourceError):f.script_contract(script().decode().replace(before,after).encode())

    def test_contract_ignores_comments_and_rejects_missing_active_formula(self):
        commented=b'// '+script().replace(b'\n',b'\n// ')
        with self.assertRaises(f.SourceError): f.script_contract(commented)

    def test_unknown_page_scale_direction_period_or_script_returns_unknown(self):
        for before,after in [('1～10','1～100'),('午前','朝'),('北からの眺め','東からの眺め'),('t24.js','other.js')]:
            with self.subTest(change=before),self.assertRaises(f.SourceError):f.panel_contract(panel().decode().replace(before,after).encode())
        with self.assertRaises(f.SourceError):f.panel_contract(b'<html>Maintenance</html>')

    def test_page_day_columns_must_remain_seven(self):
        with self.assertRaises(f.SourceError):f.panel_contract(panel().replace(b'<td colspan="2">-</td>',b'',1))

    def test_ui_index_is_not_raw_value_or_percent(self):
        result = self.parse(data(values=[0,1,10,11,90,91,100]))
        actual = [p['index'] for d in result['days'] for p in d['periods']]
        self.assertEqual(actual[:7],[1,2,2,3,10,10,10])
        self.assertTrue(all(1 <= i <= 10 for i in actual))
        self.assertEqual(result['scope']['specific_viewpoint'],None)
        self.assertIsNone(result['issued_at'])
        self.assertEqual(result['source_initialization_time'],'2026-11-01T09:00:00+09:00')

    def test_backend_extra_dates_are_outside_public_panel(self):
        dates = [DATES[0],DATES[-1],DATES[-1]+dt.timedelta(days=1)]
        result = self.parse(dates=dates)
        self.assertEqual(result['status'],'partial')
        self.assertEqual([d['status'] for d in result['days']],['ok','ok','unavailable'])
        self.assertTrue(all(p['index'] is None for p in result['days'][-1]['periods']))

    def test_missing_value_is_unavailable_but_zero_is_lowest_index(self):
        result = self.parse(data(values=['',0]))
        self.assertEqual(result['status'],'partial')
        self.assertEqual([p['index'] for p in result['days'][0]['periods']],[None,1])
        self.assertEqual(result['days'][0]['periods'][0]['reason'],'publisher_value_missing')

    def test_invalid_values_row_width_and_unknown_timezone_fail(self):
        for value in ['101','-1','nan','Infinity','unknown','7.5']:
            with self.subTest(value=value),self.assertRaises(f.SourceError):self.parse(data(values=[value]))
        for body in [data().replace(b',JST',b',UTC'),data().replace(b',70',b',70,extra',1),data(count=13)]:
            with self.assertRaises(f.SourceError):self.parse(body)

    def test_reordered_duplicate_missing_or_invalid_dates_fail(self):
        rows = data().splitlines()
        for body in [b'\n'.join([rows[0],rows[2],rows[1]]+rows[3:]),
                     b'\n'.join(rows[:2]+[rows[1]]+rows[3:]),
                     data().replace(b'2026/11/02',b'2026/11/31'),
                     data().replace(b'15:00:00',b'18:00:00')]:
            with self.assertRaises(f.SourceError): self.parse(body)

    def test_stale_and_future_initialization_are_unknown(self):
        for now in [INITIAL-dt.timedelta(seconds=1),INITIAL+dt.timedelta(hours=36,seconds=1)]:
            with self.assertRaises(f.SourceError):self.parse(now=now)
        self.assertEqual(self.parse(now=INITIAL+dt.timedelta(hours=36))['status'],'ok')

    def test_new_year_is_bound_to_full_source_dates(self):
        initial = dt.datetime(2026,12,31,9,tzinfo=f.JST)
        dates = [dt.date(2027,1,1)]
        result = self.parse(data(initial=initial),dates=dates,now=initial+dt.timedelta(hours=12))
        self.assertEqual(result['days'][0]['periods'][0]['source_reference_at'],'2027-01-01T09:00:00+09:00')

    def test_passed_forecast_reference_never_becomes_observation(self):
        result = self.parse(now=dt.datetime(2026,11,2,12,tzinfo=f.JST))
        period = result['days'][0]['periods'][0]
        self.assertEqual((period['kind'],period['reference_time_has_passed']),('forecast',True))


class CommandTests(unittest.TestCase):
    def run_cli(self,args,changed=None,clock=None):
        reads = []
        fixtures = {f.HOME:panel(),SCRIPT:script(),f.DATA['north']:data(),f.DATA['south']:data()}
        fixtures.update(changed or {})
        def read(client,url):
            reads.append(url)
            value = fixtures[url]
            if isinstance(value,Exception): raise value
            return value,{'url':url,'retrieved_at':NOW.isoformat(),'http_last_modified_raw':None}
        out = io.StringIO()
        with patch.object(f.Client,'read',read),patch.object(f,'now_jst',side_effect=clock if clock else None,return_value=NOW),contextlib.redirect_stdout(out):
            code = cli.main(args)
        return code,json.loads(out.getvalue()),reads

    def test_both_directions_share_contract_and_remain_independent(self):
        code,result,reads = self.run_cli(['forecast'])
        self.assertEqual((code,result['status'],len(reads)),(0,'ok',4))
        self.assertEqual([r['scope']['side'] for r in result['records']],['north','south'])
        self.assertTrue(result['comparison']['same_initialization'])

    def test_single_direction_reads_only_its_own_csv(self):
        code,result,reads = self.run_cli(['forecast','--side','south','--date','2026-11-03'])
        self.assertEqual((code,len(reads)),(0,3))
        self.assertNotIn(f.DATA['north'],reads)
        self.assertEqual(len(result['records'][0]['days']),1)

    def test_one_direction_error_stays_visible_beside_the_other(self):
        code,result,reads = self.run_cli(['forecast'],{f.DATA['north']:f.SourceError('http_error','Denied',http_status=403)})
        self.assertEqual((code,result['status'],len(reads)),(0,'partial',4))
        self.assertEqual([r['status'] for r in result['records']],['error','ok'])
        self.assertEqual(result['records'][0]['state'],'unknown')
        self.assertFalse(result['comparison']['same_initialization'])

    def test_both_errors_and_bad_contract_exit_two_without_fabricated_indices(self):
        changes = {u:b'maintenance' for u in f.DATA.values()}
        code,result,reads = self.run_cli(['forecast'],changes)
        self.assertEqual((code,result['status']),(2,'error'))
        self.assertTrue(all(r['days']==[] for r in result['records']))
        code,result,reads = self.run_cli(['forecast'],{SCRIPT:b'unsupported'})
        self.assertEqual((code,len(reads)),(2,2))

    def test_initialization_is_rechecked_after_all_reads(self):
        later = INITIAL+dt.timedelta(hours=37)
        code,result,_ = self.run_cli(['forecast'],clock=[NOW,NOW,NOW,later])
        self.assertEqual(code,2)
        self.assertTrue(all(r['error']['code']=='stale_initialization' for r in result['records']))

    def test_invalid_options_are_rejected_before_network(self):
        for args in [['--days','8'],['--from','2026-11-02'],['--to','2026-11-03'],
                     ['--date','2026-02-30'],['--date','20261102'],
                     ['--from','2026-11-02','--to','2026-11-09']]:
            with self.subTest(args=args):
                code,result,reads = self.run_cli(['forecast']+args)
                self.assertEqual((code,reads),(2,[]))

    def test_different_source_runs_are_not_compared_as_one_snapshot(self):
        code,result,_ = self.run_cli(['forecast','--date','2026-11-03'],
                                    {f.DATA['south']:data(initial=INITIAL.replace(hour=6))})
        self.assertEqual((code,result['status']),(0,'partial'))
        self.assertFalse(result['comparison']['same_initialization'])
        self.assertEqual([r['status'] for r in result['records']],['ok','ok'])

    def test_distant_date_is_unavailable_not_extrapolated(self):
        code,result,_ = self.run_cli(['forecast','--date','2027-04-01'])
        self.assertEqual((code,result['status']),(0,'unavailable'))
        self.assertTrue(all(p['index'] is None for r in result['records'] for d in r['days'] for p in d['periods']))

    def test_doctor_is_offline(self):
        code,result,reads = self.run_cli(['doctor'])
        self.assertEqual((code,result['network_checked'],reads),(0,False,[]))


class Response(io.BytesIO):
    status = 200
    def __init__(self,body): super().__init__(body); self.headers = {'Last-Modified':'Sun, 01 Nov 2026 06:51:20 GMT'}
    def __enter__(self): return self
    def __exit__(self,*args): self.close()


class HTTPTests(unittest.TestCase):
    def test_routes_budget_memory_cache_and_request_controls(self):
        client = f.Client()
        with patch.object(client.opener,'open',side_effect=lambda *a,**kw:Response(b'checked')) as opened,patch.object(f.time,'sleep'):
            for url in [f.HOME,SCRIPT,*f.DATA.values()]: client.read(url)
            client.read(f.HOME)
            with self.assertRaises(f.SourceError):client.read(f.HOME+'lib/t24.js?202602020000')
            self.assertEqual((opened.call_count,client.usage()['memory_cache_hits']),(4,1))
            self.assertTrue(all(c.kwargs['timeout']==15 for c in opened.call_args_list))
            self.assertEqual(client.usage()['response_body_bytes'],28)
        for url in ['http://www.fuji-san.info/',f.HOME+'lib/listimg.php',f.HOME+'data/fdata_E.csv',f.HOME+'?x=1','https://other.test/data/fdata_N.csv']:
            with self.subTest(url=url),self.assertRaises(f.SourceError):client.read(url)

    def test_denial_and_network_failures_are_not_retried(self):
        for error in [urllib.error.HTTPError(f.HOME,429,'Busy',{'Retry-After':'60'},None),http.client.RemoteDisconnected('closed')]:
            client = f.Client()
            with patch.object(client.opener,'open',side_effect=error) as opened:
                with self.assertRaises(f.SourceError):client.read(f.HOME)
            self.assertEqual(opened.call_count,1)
            self.assertEqual(client.usage()['http_requests'],1)

    def test_response_limit_and_redirect_rejection(self):
        client = f.Client()
        with patch.object(client.opener,'open',return_value=Response(b'x'*(f.BODY_LIMIT+1))):
            with self.assertRaises(f.SourceError):client.read(f.HOME)
        with self.assertRaises(f.SourceError):f.RejectRedirect().redirect_request(None,None,302,'Moved',{},'https://other.test/')


if __name__=='__main__': unittest.main()
