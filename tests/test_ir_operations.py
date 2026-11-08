"""Synthetic IR source contracts; no copied operator bulletins or captures."""
from http_test_support import Response
import copy
import datetime as dt
import importlib.util
import io
import json
from pathlib import Path
import sys
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/japan-transit/scripts'
sys.path.insert(0,str(SCRIPTS))
import rail_operations as o
SPEC=importlib.util.spec_from_file_location('transit_ir_test',SCRIPTS/'transit.py')
t=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)
NOW=dt.datetime(2026,11,1,14,30,tzinfo=o.JST)


def summary():
    return [{'@type':'odpt:TrainInformation','@id':'synthetic:1',
             'dc:date':(NOW-dt.timedelta(seconds=60)).isoformat(),
             'dct:valid':(NOW+dt.timedelta(minutes=4)).isoformat(),
             'odpt:timeOfOrgin':'2026-10-01T08:00:00+09:00',
             'odpt:operator':o.IR_OPERATOR,'odpt:railway':o.IR_RAILWAY,
             'odpt:trainInformationText':'Synthetic summary; no actual operation assertion.'},
            {'@type':'odpt:Railway',o.IR_RAILWAY:'ＩＲいしかわ線'},
            {'@type':'odpt:Operator',o.IR_OPERATOR:'ＩＲいしかわ鉄道'}]


def complete():
    return {'operation_information':[{'dc:date':'2026-10-01T08:00:00+09:00',
            'odpt:trainInformationText':'Synthetic long-running section restriction and direction; not an actual report.'}]}


def supplemental():
    return {'operation_news':{'title':'Synthetic extra notice. Its issue time is unknown.'}}


def encoded(value):
    return json.dumps(value,ensure_ascii=False).encode()


class IRTests(unittest.TestCase):
    def run_ir(self,products=None,checked_at=NOW,retrieved_at=NOW):
        products=products if products is not None else [summary(),complete(),supplemental()]
        reader=[(encoded(value),retrieved_at) for value in products]
        with patch.object(o.Client,'read',side_effect=reader) as read, patch.object(o,'now_jst',return_value=checked_at), redirect_stdout(io.StringIO()) as out:
            code=t.main(['operations','--operator','ir-ishikawa','--line','IRいしかわ鉄道線'])
        return code,json.loads(out.getvalue()),read

    def test_catalog_is_operator_qualified_and_aliases_deduplicate(self):
        row,=o.candidates(operator='ir-ishikawa')
        self.assertEqual(row['operator_section_reference'],{'from_ja':'大聖寺','to_ja':'倶利伽羅'})
        self.assertEqual(row['operator_ja'],'IRいしかわ鉄道')
        selected=o.select_lines(['ＩＲいしかわ線','IR石川铁道线','IRいしかわ鉄道線'],'ir-ishikawa')
        self.assertEqual(len(selected),1)
        for line,operator in [('IRいしかわ鉄道線','jr-west'),('七尾線','ir-ishikawa'),('IR','ir-ishikawa')]:
            with self.assertRaises(o.OperationsError): o.select_lines([line],operator)

    def test_three_products_preserve_full_notices_and_separate_time_scopes(self):
        code,value,read=self.run_ir()
        self.assertEqual((code,read.call_count),(0,3))
        self.assertEqual([call.args[0] for call in read.call_args_list],o.IR_DATA)
        source=value['sources'][0]
        report=value['reports'][0]
        self.assertEqual(source['valid_until'],(NOW+dt.timedelta(minutes=4)).isoformat())
        self.assertEqual(report['bulletins'],[summary()[0]])
        self.assertEqual(report['context']['operation_information'],complete()['operation_information'])
        self.assertEqual(report['context']['supplemental_notice'],supplemental()['operation_news'])
        self.assertIsNone(report['context']['supplemental_notice_snapshot_at'])
        self.assertEqual(report['state'],'reports_listed')
        self.assertNotIn('is_operating',report)

    def test_multiple_conditions_and_old_origin_times_are_retained(self):
        data=summary()
        row=copy.deepcopy(data[0]); row['@id']='synthetic:2'
        row['odpt:trainInformationText']='Synthetic second section condition.'
        data.insert(1,row)
        detail=complete()
        detail['operation_information'].append({'dc:date':NOW.isoformat(),'odpt:trainInformationText':'Synthetic planned work; effective date is in prose.'})
        code,value,read=self.run_ir([data,detail,supplemental()])
        self.assertEqual((code,len(value['reports'][0]['bulletins'])),(0,2))
        self.assertEqual(len(value['reports'][0]['context']['operation_information']),2)

    def test_stale_future_and_expired_summary_stop_before_context_reads(self):
        for key,value in [('dc:date',(NOW-dt.timedelta(seconds=601)).isoformat()),
                          ('dc:date',(NOW+dt.timedelta(seconds=1)).isoformat()),
                          ('dct:valid',NOW.isoformat()), ('dct:valid','2026-01-01T00:00:00+09:00')]:
            data=summary(); data[0][key]=value
            with self.subTest(key=key,value=value):
                code,result,read=self.run_ir([data])
                self.assertEqual((code,read.call_count,result['report_state']),(2,1,'unknown'))
                self.assertNotIn('reports',result)

    def test_expiry_during_context_reads_is_checked_again(self):
        code,value,read=self.run_ir(checked_at=NOW+dt.timedelta(minutes=5))
        self.assertEqual((code,read.call_count,value['report_state']),(2,3,'unknown'))

    def test_wrong_operator_line_native_names_and_future_origin_fail(self):
        variants=[]
        for key,value in [('odpt:operator','odpt.Operator:JRWest'),('odpt:railway','other'),
                          ('odpt:timeOfOrgin',(NOW+dt.timedelta(minutes=1)).isoformat()),
                          ('odpt:trainInformationText','')]:
            data=summary(); data[0][key]=value; variants.append(data)
        data=summary(); data[1][o.IR_RAILWAY]='別の路線'; variants.append(data)
        data=summary(); data[2][o.IR_OPERATOR]='別の会社'; variants.append(data)
        for data in variants:
            with self.assertRaises(o.OperationsError): o.ir_summary(data,NOW)

    def test_missing_duplicate_and_unsupported_summary_records_fail(self):
        variants=[summary()[1:],summary()[:-1],summary()+[copy.deepcopy(summary()[0])],
                  summary()+[{'@type':'new:Unknown'}],{}]
        for data in variants:
            with self.assertRaises(o.OperationsError): o.ir_summary(data,NOW)

    def test_missing_or_incomplete_context_cannot_become_no_reports(self):
        for details,notice in [({},supplemental()),({'operation_information':[]},supplemental()),
                               (complete(),{}),(complete(),{'operation_news':{'title':''}})]:
            code,value,read=self.run_ir([summary(),details,notice])
            self.assertEqual((code,value['report_state']),(2,'unknown'))
            self.assertNotIn('reports',value)
            self.assertEqual(value['official_pages'],[o.IR_PAGE])

    def test_future_complete_notice_fails_but_old_issue_time_is_not_snapshot_age(self):
        details=complete(); details['operation_information'][0]['dc:date']=(NOW+dt.timedelta(minutes=1)).isoformat()
        code,value,read=self.run_ir([summary(),details,supplemental()])
        self.assertEqual((code,value['report_state']),(2,'unknown'))

    def test_source_denial_has_no_partial_reports_or_operator_fallback(self):
        with patch.object(o.Client,'read',side_effect=o.OperationsError('http_error','Synthetic denial',http_status=403)) as read, redirect_stdout(io.StringIO()) as out:
            code=t.main(['operations','--operator','ir-ishikawa','--line','IRいしかわ鉄道線'])
        self.assertEqual((code,read.call_count),(2,1))
        result=json.loads(out.getvalue())
        self.assertEqual(result['report_state'],'unknown')
        self.assertNotIn('reports',result)

    def test_unsupported_pair_is_rejected_without_network(self):
        with patch.object(o.Client,'read',side_effect=AssertionError('network')) as read, redirect_stdout(io.StringIO()) as out:
            code=t.main(['operations','--operator','ir-ishikawa','--line','北陸線'])
        self.assertEqual((code,read.call_count),(2,0))

    def test_no_invented_fixed_jr_west_hours_are_applied_to_ir(self):
        # Runtime availability is established by the native summary deadline;
        # an arbitrary JR West service window must not replace that evidence.
        early=NOW.replace(hour=3)
        data=summary()
        data[0]['dc:date']=(early-dt.timedelta(minutes=1)).isoformat()
        data[0]['dct:valid']=(early+dt.timedelta(minutes=4)).isoformat()
        code,value,read=self.run_ir([data,complete(),supplemental()],checked_at=early,retrieved_at=early)
        self.assertEqual((code,read.call_count),(0,3))
        self.assertIsNone(value['sources'][0]['reporting_hours_jst'])


class IRClientTests(unittest.TestCase):
    def test_operator_url_and_request_budgets_remain_separate(self):
        client=o.Client(operator='ir-ishikawa')
        with patch.object(client.opener,'open',return_value=Response(b'{}')):
            self.assertEqual(client.read(o.IR_DATA[0])[0],b'{}')
        with self.assertRaises(o.OperationsError): client.read(o.WEST_DATA)
        with self.assertRaises(o.OperationsError): o.Client().read(o.IR_DATA[0])
        client.requests=3
        with self.assertRaises(o.OperationsError): client.read(o.IR_DATA[1])

    def test_ir_reads_are_serial_and_paced(self):
        client=o.Client(operator='ir-ishikawa')
        # Use a separate context-managed response for each request.
        with patch.object(client.opener,'open',side_effect=[Response(b'{}'),Response(b'{}')]) as read, patch.object(o.time,'monotonic',return_value=100), patch.object(o.time,'sleep') as sleep:
            client.read(o.IR_DATA[0]); client.read(o.IR_DATA[1])
        self.assertEqual(read.call_count,2)
        sleep.assert_called_once_with(1)
        self.assertEqual(client.pacing_ms,1000)


if __name__=='__main__': unittest.main()
