"""Synthetic interface fixtures for independently attributed seasonal sources."""
from http_test_support import Response
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

SCRIPTS=Path(__file__).resolve().parents[1]/'skills/japan-seasons/scripts'
sys.path.insert(0,str(SCRIPTS))
import season_common as c
import wn_seasons as wn
import jmc_seasons as jmc
SPEC=importlib.util.spec_from_file_location('seasons_test',SCRIPTS/'seasons.py')
s=importlib.util.module_from_spec(SPEC);SPEC.loader.exec_module(s)
NOW=dt.datetime(2026,11,1,15,tzinfo=c.JST)


def nuxt(objects):
    values=[]
    for obj in objects:
        row={}
        for key,value in obj.items():
            row[key]=len(values)
            values.append(value)
        values.append(row)
    return '<script id="__NUXT_DATA__" type="application/json">'+json.dumps(values,ensure_ascii=False)+'</script>'


def wn_page(season='foliage',year=2026,ended=False,hidden=False):
    path=c.wn_url(season,'spot','123')
    meta={'spotid':'123','cityname':'テスト県テスト市','contact':'Synthetic agency','kind':'テスト品種',
          'name':'テスト公園','prefname':'テスト','reinennomigoro':'11月頃'}
    if season=='foliage':
        state={'obs':'10月30日時点','rankText':'色づき','migoro':'11月20日','rakuyoStart':'12月3日',
               'showContent':not hidden,'showMigoroPrediction':True,'showRakuyoStartPrediction':True}
        content='''<div class="statusInfo__content"><h3 class="statusInfo__state">色づき</h3><p class="statusInfo__date">10月30日時点</p></div>
<div class="statusInfo__content"><h3 class="statusInfo__state">見頃</h3><p class="statusInfo__date">11月20日頃〜</p></div>
<div class="statusInfo__content"><h3 class="statusInfo__state">落葉はじめ</h3><p class="statusInfo__date">12月3日頃〜</p></div>'''
    else:
        meta={**meta,'spotname':meta.pop('name'),'pref':'テスト','reinen':'4月頃','fcst_tree_kind':'予測対象品種'}
        state={'obsday':'4/12','obsrank':9,'prediction':False,'shuzai':'','kaika':'','mankai':'','gobu':'','fubuki':''}
        content='<p class="kaikaStatus__date">最終取材日：4月12日</p><h3 class="kaikaStatus__title">葉桜</h3>'
        if ended:content+='{}年の桜開花情報の更新は終了しました。'.format(year)
    return ('<title>テスト公園の'+('紅葉' if season=='foliage' else '桜')+'情報【'+str(year)+'】</title><meta property="og:url" content="'+path+'"><h1>テスト公園</h1>'+content+nuxt([meta,state])).encode()


def active_sakura(rank=1,estimated=False,shown=('kaika','gobu','mankai','fubuki')):
    body=wn_page('sakura').decode()
    values=json.loads(body.split('<script id="__NUXT_DATA__" type="application/json">')[1].split('</script>')[0])
    state=next(o for o in values if isinstance(o,dict) and 'prediction' in o)
    values[state['prediction']]=True
    values[state['obsday']]='3/1'
    values[state['obsrank']]=rank
    values[state['shuzai']]='data' if estimated else ''
    labels={'kaika':('開花予想日','3/20'),'gobu':('五分咲き','3/24'),
            'mankai':('満開','3/27'),'fubuki':('桜吹雪','4/1')}
    for key,(_,date) in labels.items():values[state[key]]=date
    content='<p class="kaikaStatus__date">'+('3月1日の推定状況' if estimated else '最終取材日：3月1日')+'</p><h3 class="kaikaStatus__title">'+wn.SAKURA_STAGES.get(rank,'Unknown')+'</h3><dl class="kaikaList">'
    for key in shown:
        label,date=labels[key]
        content+='<div class="kaikaList__item"><dt class="kaikaList__title">'+label+'</dt><dd class="kaikaList__content">'+date.replace('/','月')+'日</dd></div>'
    content+='</dl>'
    head=body.split('<p class="kaikaStatus__date">')[0]
    return (head+content+'<script id="__NUXT_DATA__" type="application/json">'+json.dumps(values,ensure_ascii=False)+'</script>').encode()


def jmc_page(season='foliage',year=2026,ended=False):
    product='紅葉・黄葉見頃予想' if season=='foliage' else '桜の開花・満開予想'
    content='<div class="title">{}年{}（第2回）を発表</div><div class="date">{}年10月1日</div>'.format(year,product,year)
    if season=='foliage':
        for key,marker,date,species in [('red_leaves','autumn01','11/30','カエデ'),('yellow_leaves','autumn02','10/26','イチョウ')]:
            content+='<table><tr>'+''.join('<th>'+h+'</th>' for h in jmc.HEADERS[key])+'</tr><tr><th>テスト市</th><td class="'+marker+'">'+date+'</td><td>0日</td><td>11/24</td><td>'+species+'</td></tr></table>'
    else:
        content+='<table><tr>'+''.join('<th>'+h+'</th>' for h in jmc.HEADERS['sakura'])+'</tr><tr><th>テスト市</th><td class="sakura02">3/29開花</td><td>-1日</td><td class="sakura02">4/3満開</td><td>-1日</td><td>3/30</td></tr></table>'
        if ended:content+='今シーズンの桜開花予想の発表は、今回で最後となります。'
    return (content+'<div>実況値</div>').encode()


def directory(season='foliage'):
    if season=='foliage':
        row={'spotid':'123','pointname':'テスト公園','prefname':'テスト','cityname':'テスト県テスト市','address':'Synthetic address'}
    else:row={'lcid':'123','name':'テスト公園','pref_jp':'テスト','pref_en':'test','cityname':'テスト県テスト市'}
    prefix='/koyo/' if season=='foliage' else '/sakura/'
    return ('<title>テストの'+('紅葉' if season=='foliage' else '桜')+'情報【2026】</title><meta property="og:url" content="'+c.wn_url(season,'area','test')+'"><a href="'+prefix+'spot/123/">テスト公園</a>'+nuxt([row])).encode()


def regional_directory(area='test-region'):
    children=[('first','架空県'),('second','別県')]
    nav='<ul class="searchArea type03">'+''.join('<li><a href="#'+slug+'">'+name[:-1]+'</a></li>' for slug,name in reversed(children))+'</ul>'
    blocks=''.join('<div><article class="block" id="'+slug+'"><section class="card"><h2 class="title04">'+name+'</h2><a href="/koyo/spot/123/?fm=area">人気スポット</a><p class="buttonRight"><a href="/koyo/area/'+slug+'/">'+name+'の紅葉名所をもっと見る </a></p></section></article></div>' for slug,name in children)
    return ('<title>広域の紅葉情報【2026】</title><meta property="og:url" content="'+c.wn_url('foliage','area',area)+'"><main class="main"><div class="templateRoot">'+nav+blocks+'</div><div class="templateRoot"><article class="block"><a href="/koyo/area/unrelated/">別地域</a></article></div></main>'+nuxt([{'spotid':'123','name':'人気スポット','reinen':'例年の時期'}])).encode()


class WeathernewsTests(unittest.TestCase):
    def parse(self,raw=None,season='foliage',year=2026):
        return wn.parse(raw if raw is not None else wn_page(season),season,'123','テスト公園',year,NOW)

    def test_spot_predictions_keep_approximation_and_separate_condition_time(self):
        value=self.parse()
        self.assertEqual(value['status'],'ok')
        self.assertEqual([e['date'] for e in value['events']],['2026-11-20','2026-12-03'])
        self.assertTrue(all(e['approximate'] and e['relation']=='around_then_onward' for e in value['events']))
        self.assertEqual(value['condition']['as_of'],'2026-10-30')
        self.assertEqual(value['condition']['age_days'],2)
        self.assertIsNone(value['issued_at'])
        self.assertEqual(value['scope']['kind'],'spot')

    def test_wrong_canonical_id_name_and_directory_identity_are_rejected(self):
        body=wn_page().decode()
        for before,after in [('spot/123','spot/124'), ('<h1>テスト公園','<h1>別公園'), ('"123"','"124"')]:
            with self.subTest(change=before),self.assertRaises(c.SourceError):self.parse(body.replace(before,after).encode())
        expected={'name_ja':'テスト公園','city_ja':'別県別市','prefecture_ja':'テスト'}
        with self.assertRaises(c.SourceError):wn.parse(wn_page(),'foliage','123','テスト公園',2026,NOW,expected)

    def test_missing_year_source_shell_and_nuxt_reference_fail(self):
        for raw in [b'<html>Maintenance</html>',wn_page().replace('【2026】'.encode(),b''),
                    wn_page().replace(b'"showContent":',b'"missingContent":')]:
            with self.assertRaises(c.SourceError):self.parse(raw)

    def test_future_conditions_and_visible_data_disagreement_fail(self):
        for before,after in [('10月30日','11月30日'), ('11月20日頃〜','11月21日頃〜'),('頃〜','')]:
            with self.subTest(change=before),self.assertRaises(c.SourceError):
                self.parse(wn_page().decode().replace(before,after).encode())

    def test_hidden_source_content_exposes_no_forecast(self):
        result=self.parse(wn_page(hidden=True))
        self.assertEqual((result['status'],result['events']),('unavailable',[]))

    def test_requested_new_year_never_inherits_old_dates(self):
        value=self.parse(year=2027)
        self.assertEqual((value['status'],value['reason'],value['events']),('unavailable','requested_year_not_on_source',[]))
        self.assertIsNone(value['condition'])

    def test_ended_sakura_is_archived_with_old_condition_not_future_prediction(self):
        value=self.parse(wn_page('sakura',ended=True),'sakura')
        self.assertEqual(value['status'],'archived')
        self.assertEqual(value['condition']['as_of'],'2026-04-12')
        self.assertTrue(all(e['date'] is None for e in value['events']))

    def test_visible_active_sakura_milestones_preserve_kind_and_forecast_species(self):
        value=self.parse(active_sakura(),'sakura')
        self.assertEqual(value['status'],'ok')
        self.assertEqual([e['milestone'] for e in value['events']],['flowering','half_bloom','full_bloom','petal_blizzard'])
        self.assertEqual([e['date'] for e in value['events']],['2026-03-20','2026-03-24','2026-03-27','2026-04-01'])
        self.assertTrue(all(e['kind']=='forecast' and e['date_has_passed'] for e in value['events']))
        self.assertTrue(all(e['species_ja']=='予測対象品種' and e['issued_at'] is None for e in value['events']))
        self.assertEqual(value['condition']['kind'],'reported_condition')
        self.assertEqual(value['condition']['as_of'],'2026-03-01')

    def test_estimated_sakura_condition_is_not_reported_observation(self):
        value=self.parse(active_sakura(estimated=True),'sakura')
        self.assertEqual(value['condition']['kind'],'estimated_condition')
        self.assertEqual(value['condition']['raw_date'],'3月1日の推定状況')
        with self.assertRaises(c.SourceError):self.parse(active_sakura().replace('最終取材日：3月1日'.encode(),'3月1日の推定状況'.encode()),'sakura')

    def test_sakura_hidden_dates_are_not_recovered_after_stage_passes(self):
        value=self.parse(active_sakura(rank=7,shown=('fubuki',)),'sakura')
        self.assertEqual([e['kind'] for e in value['events']],['unavailable','unavailable','unavailable','forecast'])
        self.assertTrue(all(e['date'] is None for e in value['events'][:3]))
        value=self.parse(active_sakura(shown=()),'sakura')
        self.assertTrue(all(e['kind']=='unavailable' for e in value['events']))

    def test_sakura_visible_dates_need_prediction_marker_and_exact_data_match(self):
        body=active_sakura()
        for before,after in [('true','false'),('3月20日','3月21日'),('開花予想日','開花実績日')]:
            with self.subTest(change=before),self.assertRaises(c.SourceError):
                self.parse(body.decode().replace(before,after).encode(),'sakura')
        with self.assertRaises(c.SourceError):self.parse(active_sakura(rank=7),'sakura')

    def test_sakura_ended_notice_overrides_lingering_forecast_fields(self):
        body=active_sakura()+'2026年の桜開花情報の更新は終了しました。'.encode()
        value=self.parse(body,'sakura')
        self.assertEqual(value['status'],'archived')
        self.assertTrue(all(e['kind']=='unavailable' for e in value['events']))

    def test_sakura_unknown_rank_duplicate_milestone_and_condition_mismatch_fail(self):
        with self.assertRaises(c.SourceError):self.parse(active_sakura(rank=25),'sakura')
        body=active_sakura().decode()
        a=body.index('<div class="kaikaList__item">');b=body.index('</div>',a)+6
        for invalid in [body+body[a:b],body.replace('>つぼみ</h3>','>葉桜</h3>'),body.replace('最終取材日：3月1日','最終取材日：3月2日')]:
            with self.assertRaises(c.SourceError):self.parse(invalid.encode(),'sakura')

    def test_new_spring_does_not_inherit_current_sakura_dates(self):
        value=self.parse(active_sakura(),'sakura',2027)
        self.assertEqual((value['status'],value['events'],value['condition']),('unavailable',[],None))

    def test_live_directory_is_exact_for_selection_and_season_specific(self):
        for season in ('foliage','sakura'):
            rows=wn.spots(directory(season),season,'test','テスト')['spots']
            self.assertEqual((len(rows),rows[0]['spot_id']),(1,'123'))
            client=c.Client()
            with patch.object(client,'read',return_value=(directory(season),NOW)):
                self.assertEqual(wn.selected_spot(client,season,'test','テスト公園')['spot_id'],'123')
                with self.assertRaises(c.SourceError):wn.selected_spot(client,season,'test','テスト')

    def test_live_area_links_and_empty_directory_fail_closed(self):
        raw=b'<title>\xe7\xb4\x85\xe8\x91\x89\xe6\x83\x85\xe5\xa0\xb1\xe3\x80\x902026\xe3\x80\x91</title><meta property="og:url" content="https://weathernews.jp/koyo/"><a href="/koyo/area/test/">Test</a>'
        self.assertEqual(wn.area_list(raw,'foliage')['areas'][0]['area'],'test')
        with self.assertRaises(c.SourceError):wn.spots(raw,'foliage','test')

    def test_foliage_regional_overview_requests_native_prefecture_selection(self):
        for area in ('test-region','another-region'):
            with self.subTest(area=area),self.assertRaises(c.SourceError) as caught:
                wn.spots(regional_directory(area),'foliage',area,'人気')
            self.assertEqual(caught.exception.code,'unsupported_area')
            details=caught.exception.details
            self.assertEqual(details['directory_kind'],'regional_overview')
            self.assertEqual(details['source_year'],2026)
            self.assertEqual(details['candidate_areas'],[
                {'area':'first','name_ja':'架空県','url':c.wn_url('foliage','area','first')},
                {'area':'second','name_ja':'別県','url':c.wn_url('foliage','area','second')}])
            self.assertNotIn('spots',details)
            self.assertNotIn('events',details)

    def test_malformed_regional_blocks_still_fail_schema_instead_of_partial_selection(self):
        text=regional_directory().decode()
        invalid=[text.replace('id="second"',''),
                 text.replace('id="second"','id="first"'),
                 text.replace('href="#second"','href="#missing"'),
                 text.replace('/area/second/','/area/first/'),
                 text.replace('/area/second/','https://example.org/area/second/'),
                 text.replace('別県の紅葉名所をもっと見る','異なる県の紅葉名所をもっと見る'),
                 text.replace('別県','架空県').replace('href="#second">別</a>','href="#second">架空</a>'),
                 text.replace('id="second"','id="test-region"').replace('href="#second"','href="#test-region"').replace('/area/second/','/area/test-region/'),
                 text.replace('<div><article class="block" id="second">','<div><article class="changed" id="second">')]
        for body in invalid:
            with self.subTest(body=body[:80]),self.assertRaises(c.SourceError) as caught:
                wn.spots(body.encode(),'foliage','test-region')
            self.assertEqual(caught.exception.code,'source_schema_changed')

        sakura=text.replace('/koyo/','/sakura/').replace('紅葉','桜')
        with self.assertRaises(c.SourceError) as caught:wn.spots(sakura.encode(),'sakura','test-region')
        self.assertEqual(caught.exception.code,'source_schema_changed')


class JMCTests(unittest.TestCase):
    def parse(self,raw=None,season='foliage',year=2026):return jmc.parse(raw or jmc_page(season),season,'テスト市',year,NOW)

    def test_same_table_keeps_forecast_and_observation_and_species(self):
        value=self.parse()
        self.assertEqual([e['kind'] for e in value['events']],['forecast','observed'])
        self.assertEqual([e['species_ja'] for e in value['events']],['カエデ','イチョウ'])
        self.assertEqual(value['release']['release_published_on'],'2026-10-01')
        self.assertIsNone(value['release']['cell_updated_at'])
        self.assertEqual(value['events'][1]['date'],'2026-10-26')

    def test_observed_after_release_is_valid_but_future_observation_fails(self):
        body=jmc_page().decode()
        self.assertEqual(self.parse()['events'][1]['kind'],'observed')
        with self.assertRaises(c.SourceError):self.parse(body.replace('10/26','11/26').encode())

    def test_passed_forecast_does_not_automatically_become_observed(self):
        result=self.parse(jmc_page().replace(b'11/30',b'10/30'))
        self.assertEqual(result['events'][0]['kind'],'forecast')
        self.assertTrue(result['events'][0]['date_has_passed'])

    def test_malformed_class_header_and_missing_table_fail(self):
        for before,after in [('autumn01','newClass'),('紅葉予想日','別の指標'),('実況値','')]:
            with self.subTest(change=before),self.assertRaises(c.SourceError):
                self.parse(jmc_page().decode().replace(before,after).encode())

    def test_source_year_rollover_and_ended_sakura_are_explicit(self):
        self.assertEqual(self.parse(year=2027)['events'],[])
        result=self.parse(jmc_page('sakura',ended=True),'sakura')
        self.assertEqual((result['status'],[e['kind'] for e in result['events']]),('archived',['observed','observed']))

    def test_sakura_opening_observation_and_full_bloom_forecast_can_coexist(self):
        body=jmc_page('sakura').decode().replace('class="sakura02">4/3満開','class="sakura01">4/3')
        result=self.parse(body.encode(),'sakura')
        self.assertEqual([e['kind'] for e in result['events']],['observed','forecast'])
        self.assertEqual([e['milestone'] for e in result['events']],['flowering','full_bloom'])
        self.assertTrue(result['events'][1]['date_has_passed'])

    def test_unknown_city_is_not_substituted(self):
        with self.assertRaises(c.SourceError):jmc.parse(jmc_page(),'foliage','テスト',2026,NOW)
        rows=jmc.cities(jmc_page(),'foliage',NOW)
        self.assertEqual(rows['cities'][0]['name_ja'],'テスト市')

    def test_duplicate_city_or_table_is_not_silently_chosen(self):
        body=jmc_page().decode()
        start=body.index('<table>');end=body.index('</table>')+8
        with self.assertRaises(c.SourceError):self.parse((body+body[start:end]).encode())


class CommandTests(unittest.TestCase):
    ARGS=['query','--season','foliage','--year','2026','--city','テスト市','--spot','テスト公園','--spot-id','123']
    def run_query(self,reads,args=None):
        def reader(url):
            value=reads[url]
            if isinstance(value,Exception):raise value
            return value,NOW
        with patch.object(c.Client,'read',side_effect=reader) as read,patch.object(s,'now_jst',return_value=NOW),contextlib.redirect_stdout(io.StringIO()) as out:
            code=s.main(args or self.ARGS)
        return code,json.loads(out.getvalue()),read

    def test_query_always_has_two_unmerged_sources_with_distinct_metric_scope(self):
        code,value,read=self.run_query({c.wn_url('foliage','spot','123'):wn_page(),c.jmc_url('foliage'):jmc_page()})
        self.assertEqual((code,read.call_count),(0,2))
        self.assertEqual([p['provider'] for p in value['providers']],['weathernews','jmc'])
        self.assertFalse(value['comparison']['same_location_and_metric'])
        self.assertNotIn('consensus_date',value)
        self.assertNotEqual(value['providers'][0]['events'][0]['date'],value['providers'][1]['events'][0]['date'])

    def test_failure_is_displayed_beside_other_provider_not_hidden(self):
        for bad in ('wn','jmc'):
            reads={c.wn_url('foliage','spot','123'):wn_page(),c.jmc_url('foliage'):jmc_page()}
            reads[c.wn_url('foliage','spot','123') if bad=='wn' else c.jmc_url('foliage')]=c.SourceError('http_error','Synthetic 403',http_status=403)
            code,value,read=self.run_query(reads)
            self.assertEqual((code,read.call_count,value['status']),(0,2,'partial'))
            self.assertEqual(sorted(p['status'] for p in value['providers']),['error','ok'])
            self.assertEqual(len(value['providers']),2)

    def test_both_failures_remain_unknown_and_exit_two(self):
        error=c.SourceError('network_error','Synthetic source outage')
        code,value,read=self.run_query({c.wn_url('foliage','spot','123'):error,c.jmc_url('foliage'):error})
        self.assertEqual((code,value['status']),(2,'error'))
        self.assertEqual([p['state'] for p in value['providers']],['unknown','unknown'])

    def test_named_spot_adds_only_one_directory_read(self):
        args=self.ARGS[:-2]+['--area','test']
        code,value,read=self.run_query({c.wn_url('foliage','spot','123'):wn_page(),c.wn_url('foliage','area','test'):directory(),c.jmc_url('foliage'):jmc_page()},args)
        self.assertEqual((code,read.call_count),(0,3))

    def test_regional_discovery_returns_selection_and_source_after_only_one_read(self):
        raw=regional_directory();client=c.Client()
        with patch.object(s,'Client',return_value=client),patch.object(c,'now_jst',return_value=NOW),patch.object(client.opener,'open',return_value=Response(raw)) as read,contextlib.redirect_stdout(io.StringIO()) as out:
            code=s.main(['spots','--season','foliage','--area','test-region','人気'])
        value=json.loads(out.getvalue())
        self.assertEqual((code,read.call_count,value['provider'],value['state']),(2,1,'weathernews','unknown'))
        self.assertEqual(value['error']['code'],'unsupported_area')
        self.assertEqual(value['source'],{'url':c.wn_url('foliage','area','test-region'),'retrieved_at':NOW.isoformat()})
        self.assertEqual(value['usage']['http_requests'],1)
        self.assertEqual(value['usage']['response_body_bytes'],len(raw))
        self.assertNotIn('spots',value)
        self.assertEqual(len(value['error']['candidate_areas']),2)

    def test_regional_query_preserves_independent_jmc_without_following_child_links(self):
        args=self.ARGS[:-2]+['--area','test-region']
        code,value,read=self.run_query({c.wn_url('foliage','area','test-region'):regional_directory(),c.jmc_url('foliage'):jmc_page()},args)
        self.assertEqual((code,read.call_count,value['status']),(0,2,'partial'))
        self.assertEqual([call.args[0] for call in read.call_args_list],[c.wn_url('foliage','area','test-region'),c.jmc_url('foliage')])
        self.assertEqual(value['providers'][0]['error']['code'],'unsupported_area')
        self.assertEqual(value['providers'][1]['status'],'ok')
        self.assertEqual(len(value['providers'][0]['error']['candidate_areas']),2)

    def test_discovery_schema_and_transport_errors_keep_real_provider_and_source_scope(self):
        for command,provider,url in [(['areas','--season','foliage'],'weathernews',c.wn_url('foliage')),
                                     (['cities','--season','foliage'],'jmc',c.jmc_url('foliage'))]:
            for transport_failure in (False,True):
                client=c.Client()
                response={'side_effect':urllib.error.URLError(TimeoutError())} if transport_failure else {'return_value':Response(b'<html>Unknown</html>')}
                with self.subTest(provider=provider,transport=transport_failure),patch.object(s,'Client',return_value=client),patch.object(c,'now_jst',return_value=NOW),patch.object(client.opener,'open',**response) as read,contextlib.redirect_stdout(io.StringIO()) as out:
                    code=s.main(command)
                value=json.loads(out.getvalue())
                self.assertEqual((code,read.call_count,value['provider']),(2,1,provider))
                self.assertEqual(value['source'],{'url':url,'retrieved_at':None if transport_failure else NOW.isoformat()})
                self.assertEqual(value['usage']['http_requests'],1)
                self.assertEqual(value['error']['code'],'network_error' if transport_failure else 'source_schema_changed')

        with patch.object(c.Client,'read',side_effect=AssertionError('network')) as read,contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(s.main(['spots','--season','foliage','--area','../invalid']),2)
        read.assert_not_called()
        self.assertNotIn('source',json.loads(out.getvalue()))

    def test_invalid_options_and_doctor_are_offline(self):
        for args,expected in [(['doctor'],0),(self.ARGS[:-1]+['../123'],2), (self.ARGS[:4]+['1800']+self.ARGS[5:],2)]:
            with patch.object(c.Client,'read',side_effect=AssertionError('network')) as read,contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(s.main(args),expected)
            read.assert_not_called()


class ClientTests(unittest.TestCase):
    def test_allowlist_denials_and_redirects_never_switch_clients(self):
        client=c.Client()
        for url in ['https://example.org/','https://weathernews.jp/koyo/spot/123/?x=1','https://weathernews.jp/sakura/report/123/']:
            with self.assertRaises(c.SourceError):client.read(url)
        with self.assertRaises(c.SourceError):c.RejectRedirect().redirect_request(None,None,302,'',{},'https://example.org/')
        error=urllib.error.HTTPError(c.jmc_url('foliage'),429,'Throttled',{'Retry-After':'60'},None)
        with patch.object(client.opener,'open',side_effect=error) as read,self.assertRaises(c.SourceError) as caught:
            client.read(c.jmc_url('foliage'))
        self.assertEqual((read.call_count,caught.exception.details['retry_after']),(1,'60'))

    def test_cache_and_independent_provider_budgets_are_measured(self):
        client=c.Client()
        with patch.object(client.opener,'open',return_value=Response(b'page')) as read:
            self.assertEqual(client.read(c.jmc_url('foliage')),client.read(c.jmc_url('foliage')))
        self.assertEqual((read.call_count,client.requests,client.response_bytes,client.cache_hits),(1,1,4,1))
        with self.assertRaises(c.SourceError):client.read(c.jmc_url('sakura'))
        client=c.Client();client.requests=3
        with self.assertRaises(c.SourceError):client.read(c.jmc_url('foliage'))

    def test_truncated_and_oversized_responses_are_errors(self):
        client=c.Client()
        with patch.object(client.opener,'open',side_effect=http.client.IncompleteRead(b'x')),self.assertRaises(c.SourceError):client.read(c.jmc_url('foliage'))
        client=c.Client()
        with patch.object(client.opener,'open',return_value=Response(b'x'*(2*1024*1024+1))),self.assertRaises(c.SourceError):client.read(c.jmc_url('foliage'))


if __name__=='__main__':unittest.main()
