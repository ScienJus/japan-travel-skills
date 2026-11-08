"""Offline observable invariants using synthetic website-shaped responses."""
from http_test_support import Response
import copy
import datetime as dt
import http.client
import importlib.util
import io
import json
import unittest
import urllib.error
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("japan_transit", Path(__file__).resolve().parents[1] / "skills/japan-transit/scripts/transit.py")
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)
import transit_source as source
import transit_transport as transport
import urllib.parse

ORIGIN = {"name": "テスト出発", "code": "10001"}
DEST = {"name": "テスト到着", "code": "10003"}


def edge(name, code, times, fare=None):
    return {"stationName": name, "stationCode": code, "timeInfo": times, "railName": "テスト線・到着行",
            "priceInfo": fare or {}, "accessInfo": {"type": 0},
            "ridingPositionInfo": {"departure": ["0", "番線"], "arrival": [None, "情報なし"]}}


def feature():
    repeated = {"price": "1,000", "expPrice": "500", "expType": "指定席", "edgeGroup": "0_1", "isExpDisplay": True, "isExpFirst": True}
    return {"summaryInfo": {"departureTime": "23:50", "arrivalTime": "00:30", "totalTime": "40分",
                            "totalPrice": "1,500", "totalPriceDetail": "（乗車券1,000円　特別料金500円）", "transferCount": "1",
                            "calendarData": {"startTime": "20261102T235000", "endTime": "20261103T003000"}},
            "edgeInfoList": [edge(ORIGIN["name"], ORIGIN["code"], [{"type": 3, "time": "23:50"}], repeated),
                             edge("テスト乗換", "10002", [{"type": 2, "time": "00:05"}, {"type": 1, "time": "00:15"}], repeated),
                             edge(DEST["name"], DEST["code"], [{"type": 3, "time": "00:30"}])]}


def args(*extra):
    return t.build_parser().parse_args(["route", "--from", ORIGIN["name"], "--to", DEST["name"], "--from-code", ORIGIN["code"],
                                       "--to-code", DEST["code"], "--date", "2026-11-02", "--time", "23:45", *extra])


def props():
    return {"queryState": {"year": "2026", "month": "11", "day": "02", "hour": "23", "minute": "45", "dateType": "1",
                            "ticket": "normal", "expKind": "1", "sort": "0", "useAirline": False, "useHighwayBus": False,
                            "useLocalBus": False, "useShip": False, "useShinkansen": True, "useLimitedExpress": True},
            "naviSearchParam": {"resultInfo": {"Status": 200, "ForceAverageSearch": "False", "Total": 6}, "featureInfoList": [feature()]},
            "kousyouResult": {"detail": {"jr": "Synthetic timetable version", "kousyou": "Synthetic<br>rights notice"}}}


def html(value):
    return ('<html><script id="__NEXT_DATA__" type="application/json">' + json.dumps({"props": {"pageProps": value}}) + '</script></html>').encode()


class Fake:
    def __init__(self, value):
        self.value = value
        self.urls = []

    def read(self, url):
        self.urls.append(url)
        return self.value


class RouteTests(unittest.TestCase):
    def test_cross_midnight_and_connection_wait(self):
        r = source.normalize_route(feature(), ORIGIN, DEST, 1)
        self.assertEqual(r["legs"][0]["arrival_at"], "2026-11-03T00:05:00+09:00")
        self.assertEqual(r["legs"][1]["departure_at"], "2026-11-03T00:15:00+09:00")
        self.assertEqual(r["connection_waits"][0]["minutes"], 10)
        self.assertEqual(r["fare"]["total_jpy"], 1500)  # Repeated fare displays are not summed.
        self.assertEqual(r["fare"]["priced_seat_labels_ja"], ["指定席"])
        self.assertEqual(r["legs"][0]["departure_platform_ja"], "0番線")
        self.assertIsNone(r["legs"][0]["arrival_platform_ja"])

    def test_overnight_wait_is_preserved(self):
        f = feature()
        f["edgeInfoList"][1]["timeInfo"][1]["time"] = "04:15"
        f["edgeInfoList"][2]["timeInfo"][0]["time"] = "04:30"
        f["summaryInfo"].update(arrivalTime="04:30", totalTime="4時間40分")
        f["summaryInfo"]["calendarData"]["endTime"] = "20261103T043000"
        r = source.normalize_route(f, ORIGIN, DEST, 1)
        self.assertEqual(r["connection_waits"][0]["minutes"], 250)

    def test_next_day_departure_uses_source_calendar(self):
        f = feature()
        f["summaryInfo"].update(departureTime="00:01", arrivalTime="00:30", totalTime="29分")
        f["summaryInfo"]["calendarData"]["startTime"] = "20261103T000100"
        f["edgeInfoList"][0]["timeInfo"][0]["time"] = "00:01"
        self.assertTrue(source.normalize_route(f, ORIGIN, DEST, 1)["departure_at"].startswith("2026-11-03"))

    def test_unknown_clock_or_time_kind_fails(self):
        for field, value in [("time", "--:--"), ("type", 99)]:
            with self.subTest(field=field):
                f = feature(); f["edgeInfoList"][1]["timeInfo"][0][field] = value
                with self.assertRaises(t.TransitError): source.normalize_route(f, ORIGIN, DEST, 1)

    def test_calendar_duration_and_intermediate_boundary_must_agree(self):
        for change in ["duration", "intermediate", "summary_clock"]:
            with self.subTest(change=change):
                f = feature()
                if change == "duration": f["summaryInfo"]["totalTime"] = "41分"
                if change == "intermediate": f["edgeInfoList"][1]["timeInfo"][1]["time"] = "00:45"
                if change == "summary_clock": f["summaryInfo"]["arrivalTime"] = "00:31"
                with self.assertRaises(t.TransitError): source.normalize_route(f, ORIGIN, DEST, 1)

    def test_endpoint_identity_checked_for_each_result(self):
        for field, value in [("stationCode", "99999"), ("stationName", "別の駅")]:
            f = feature(); f["edgeInfoList"][-1][field] = value
            with self.assertRaises(t.TransitError) as caught: source.normalize_route(f, ORIGIN, DEST, 1)
            self.assertEqual(caught.exception.code, "station_mismatch")

    def test_verified_source_operator_alias_is_scoped_to_native_code(self):
        selected = {"name": "羽田空港第3ターミナル(モノレール)", "code": "29671"}
        actual = {"name": "羽田空港第３ターミナル(東京モノレール)", "code": "29671"}
        self.assertTrue(source.same_station(selected, actual))
        self.assertFalse(source.same_station(selected, {**actual, "code": "29672"}))
        self.assertFalse(source.same_station(selected, {**actual, "name": "羽田空港第３ターミナル(京急)"}))
        self.assertFalse(source.same_station({**selected, "code": "10001"}, {**actual, "code": "10001"}))

    def test_kansai_native_name_variant_keeps_code_kind_and_qualifier_guards(self):
        selected = {"name": "関西空港駅(鉄道)", "code": "25891", "kind": "station"}
        actual = {"name": "関西空港(鉄道)", "code": "25891", "kind": "station"}
        self.assertTrue(source.same_station(selected, actual))
        self.assertTrue(source.same_station(actual, selected))
        for wrong in [
            {**actual, "code": "25892"},
            {**actual, "kind": "bus"},
            {**actual, "name": "関西空港(空路)"},
            {**actual, "name": "関西空港ポートターミナル(船)"},
            {**actual, "name": "関西空港"},
            {**actual, "name": "関西空港(別事業者)"},
        ]:
            with self.subTest(wrong=wrong):
                self.assertFalse(source.same_station(selected, wrong))
        self.assertFalse(source.same_station({**selected, "code": "10001"}, {**actual, "code": "10001"}))
        self.assertFalse(source.same_station({"name": "富山", "code": "10001"},
                                             {"name": "富山駅", "code": "10001"}))

    def test_synthetic_kansai_suggestion_to_route_handoff_needs_no_retry(self):
        # Synthetic native-shaped data, not a capture of any published journey.
        name = "関西空港駅(鉄道)"
        p = props()
        p["naviSearchParam"]["featureInfoList"][0]["edgeInfoList"][0].update(
            stationName="関西空港(鉄道)", stationCode="25891")
        def suggestion(query, code):
            return json.dumps({"@query": query, "Result": [
                {"Id": "st", "Code": code, "Suggest": query}]}).encode()
        responses = [Response(suggestion(name, "25891")), Response(suggestion(DEST["name"], DEST["code"])),
                     Response(html(p))]
        with patch.object(urllib.request.OpenerDirector, "open", side_effect=responses) as call, \
                patch.object(transport.time, "sleep"), redirect_stdout(io.StringIO()) as output:
            code = t.main(["route", "--from", name, "--to", DEST["name"],
                           "--date", "2026-11-02", "--time", "23:45", "--detail"])
        result = json.loads(output.getvalue())
        self.assertEqual((code, result["status"], result["returned_routes"]), (0, "ok", 1))
        self.assertEqual(result["usage"]["http_requests"], 3)
        self.assertEqual(call.call_count, 3)  # Two suggestions and one route, no retry.
        self.assertEqual(result["query"]["from"]["name"], name)
        self.assertEqual(result["routes"][0]["legs"][0]["from"]["name"], "関西空港(鉄道)")
        route_query = urllib.parse.parse_qs(urllib.parse.urlsplit(result["source"]["url"]).query)
        self.assertEqual((route_query["from"], route_query["flatlon"]), ([name], [",,25891"]))
        self.assertEqual(result["routes"][0]["fare"]["total_jpy"], 1500)

    def test_kansai_alias_does_not_hide_other_query_or_endpoint_damage(self):
        selected = {"name": "関西空港駅(鉄道)", "code": "25891", "kind": "station"}
        for change in ("date", "fare", "destination", "unknown_time"):
            with self.subTest(change=change):
                p = props()
                f = p["naviSearchParam"]["featureInfoList"][0]
                f["edgeInfoList"][0].update(stationName="関西空港(鉄道)", stationCode="25891")
                if change == "date": p["queryState"]["day"] = "03"
                if change == "fare": f["summaryInfo"]["totalPrice"] = "unexpected"
                if change == "destination": f["edgeInfoList"][-1]["stationCode"] = "99999"
                if change == "unknown_time": f["edgeInfoList"][1]["timeInfo"][0]["type"] = 99
                a = args(); a.origin = selected["name"]; a.from_code = selected["code"]
                client = Fake(html(p))
                with self.assertRaises(t.TransitError) as caught: t.search_route(client, a)
                self.assertEqual(caught.exception.code, "station_mismatch" if change == "destination" else "source_schema_changed")
                self.assertEqual(len(client.urls), 1)

    def test_page_json_does_not_execute_javascript(self):
        p = props()
        self.assertEqual(source.page_props(html(p)), p)
        for raw in [b'<script>location.href="/login"</script>', html(p) + html(p), b'<script id="__NEXT_DATA__">{bad}</script>']:
            with self.assertRaises(t.TransitError): source.page_props(raw)

    def test_resolved_route_needs_one_read_and_retains_source_versions(self):
        client = Fake(html(props()))
        r = t.search_route(client, args())
        self.assertEqual(len(client.urls), 1)
        self.assertEqual(r["returned_routes"], 1)  # Ignore backend Total=6, return only embedded rows.
        self.assertEqual(r["source"]["timetable_versions_ja"]["jr"], "Synthetic timetable version")
        self.assertEqual(r["source"]["rights_notice_ja"], "Synthetic rights notice")
        self.assertIn("flatlon=%2C%2C10001", client.urls[0])

    def test_query_weekday_remains_bound_to_requested_date_when_departure_is_next_day(self):
        p = props()
        f = p['naviSearchParam']['featureInfoList'][0]
        f['summaryInfo'].update(departureTime='00:01', arrivalTime='00:30', totalTime='29分')
        f['summaryInfo']['calendarData']['startTime'] = '20261103T000100'
        f['edgeInfoList'][0]['timeInfo'][0]['time'] = '00:01'
        result = t.search_route(Fake(html(p)), args())
        self.assertEqual(result['query']['date'], '2026-11-02')
        self.assertEqual(result['query']['weekday_ja'], '月曜日')
        self.assertEqual(result['routes'][0]['departure_at'], '2026-11-03T00:01:00+09:00')

    def test_all_search_modes_are_native_and_first_last_omit_time(self):
        for mode, native in t.MODES.items():
            a = args(); a.mode = mode
            p = props(); p["queryState"]["dateType"] = native
            if mode in ("first", "last"):
                a.time = None; p["queryState"].update(hour="00", minute="00")
            elif mode == "arrival": a.time = "23:45"; a.date = "2026-11-03"; p["queryState"]["day"] = "03"
            with self.subTest(mode=mode):
                client = Fake(html(p)); r = t.search_route(client, a)
                self.assertEqual(r["query"]["mode"], mode)
                self.assertIn("type=" + native, client.urls[0])

    def test_average_time_or_changed_query_is_not_exact_schedule(self):
        for change in ["average", "date", "time", "ticket", "transport"]:
            p = props()
            if change == "average": p["naviSearchParam"]["resultInfo"]["ForceAverageSearch"] = "True"
            if change == "date": p["queryState"]["day"] = "03"
            if change == "time": p["queryState"]["minute"] = "46"
            if change == "ticket": p["queryState"]["ticket"] = "ic"
            if change == "transport": p["queryState"]["useAirline"] = True
            with self.subTest(change=change), self.assertRaises(t.TransitError): t.search_route(Fake(html(p)), args())

    def test_departure_and_arrival_constraints(self):
        a = args(); a.time = "23:55"
        p = props(); p["queryState"]["minute"] = "55"
        with self.assertRaises(t.TransitError): t.search_route(Fake(html(p)), a)
        a = args(); a.mode = "arrival"
        p = props(); p["queryState"]["dateType"] = "4"
        with self.assertRaises(t.TransitError): t.search_route(Fake(html(p)), a)

    def test_source_error_is_preserved_and_schema_failure_is_not_no_service(self):
        p = props(); p["queryState"]["errorList"] = ["テストエラー"]
        with self.assertRaises(t.TransitError) as caught: t.search_route(Fake(html(p)), args())
        self.assertEqual(caught.exception.details["source_messages_ja"], ["テストエラー"])
        p = props(); del p["naviSearchParam"]
        with self.assertRaises(t.TransitError) as caught: t.search_route(Fake(html(p)), args())
        self.assertEqual(caught.exception.code, "source_schema_changed")

    def test_detail_retains_fare_group_instead_of_allocating_it(self):
        r = source.normalize_route(feature(), ORIGIN, DEST, 1, True)
        self.assertEqual(r["legs"][0]["fare_display"]["edgeGroup"], r["legs"][1]["fare_display"]["edgeGroup"])
        self.assertEqual(r["fare"]["total_jpy"], 1500)


class QualifiedTimeTests(unittest.TestCase):
    def qualified(self, arrival_kind=2):
        value = feature()
        value['edgeInfoList'][1]['timeInfo'] = [
            {'type': arrival_kind, 'time': '00:05'}, {'type': 4, 'time': '00:15'}]
        return value

    def test_qualified_times_return_unknown_not_exact_legs_or_another_alternative(self):
        for kind in (2, 5):
            p = props()
            p['naviSearchParam']['featureInfoList'] = [self.qualified(kind), feature()]
            client = Fake(html(p))
            with self.subTest(kind=kind), self.assertRaises(t.TransitError) as caught:
                t.search_route(client, args('--limit', '1'))
            self.assertEqual(caught.exception.code, 'timetable_unavailable')
            self.assertEqual(caught.exception.details['qualified_time_types'], [4] if kind == 2 else [4, 5])
            self.assertEqual(caught.exception.details['source_url'], client.urls[0])
            self.assertEqual(caught.exception.details['source']['url'], client.urls[0])
            self.assertIn('retrieved_at', caught.exception.details['source'])
            self.assertEqual(len(client.urls), 1)
            self.assertNotIn('routes', caught.exception.details)

    def test_cli_qualified_result_is_unknown_nonzero_with_native_one_read_usage(self):
        p = props(); p['naviSearchParam']['featureInfoList'] = [self.qualified(5)]
        with patch.object(urllib.request.OpenerDirector, 'open', return_value=Response(html(p))) as call, \
                redirect_stdout(io.StringIO()) as output:
            code = t.main(['route', '--from', ORIGIN['name'], '--to', DEST['name'],
                           '--from-code', ORIGIN['code'], '--to-code', DEST['code'],
                           '--date', '2026-11-02', '--time', '23:45'])
        result = json.loads(output.getvalue())
        self.assertEqual((code, result['status'], result['state']), (2, 'error', 'unknown'))
        self.assertEqual(result['error']['code'], 'timetable_unavailable')
        self.assertEqual(result['usage']['http_requests'], 1)
        self.assertNotIn('routes', result)
        call.assert_called_once()

    def test_qualification_never_hides_later_bad_time_fields(self):
        for field, value in [('type', 6), ('type', '3'), ('type', 3.0), ('type', True), ('time', '--:--')]:
            p = props(); f = self.qualified()
            f['edgeInfoList'][-1]['timeInfo'][0][field] = value
            p['naviSearchParam']['featureInfoList'] = [f]
            with self.subTest(field=field, value=value), self.assertRaises(t.TransitError) as caught:
                t.search_route(Fake(html(p)), args())
            self.assertEqual(caught.exception.code, 'source_schema_changed')

    def test_qualified_type_and_sequence_must_be_strictly_recognized(self):
        for sequence in ([{'type': '4', 'time': '00:15'}], [{'type': 4.0, 'time': '00:15'}],
                         [{'type': 2, 'time': '00:05'}, {'type': 4, 'time': '--:--'}],
                         [{'type': 4, 'time': '00:05'}, {'type': 2, 'time': '00:15'}],
                         [{'type': 4, 'time': '00:05'}, {'type': 4, 'time': '00:15'}]):
            f = self.qualified(); f['edgeInfoList'][1]['timeInfo'] = sequence
            with self.subTest(sequence=sequence), self.assertRaises(t.TransitError) as caught:
                source.normalize_route(f, ORIGIN, DEST, 1)
            self.assertEqual(caught.exception.code, 'source_schema_changed')
        f = self.qualified(); f['edgeInfoList'][0]['timeInfo'] = [{'type': 4, 'time': '23:50'}]
        with self.assertRaises(t.TransitError) as caught: source.normalize_route(f, ORIGIN, DEST, 1)
        self.assertEqual(caught.exception.code, 'source_schema_changed')

    def test_known_clock_and_other_field_damage_remain_failures(self):
        for field in ('clock', 'duration', 'fare', 'service', 'identity', 'transport'):
            f = self.qualified()
            if field == 'clock': f['edgeInfoList'][1]['timeInfo'][0]['time'] = '00:45'
            if field == 'duration': f['summaryInfo']['totalTime'] = '41分'
            if field == 'fare': f['summaryInfo']['totalPrice'] = None
            if field == 'service': f['edgeInfoList'][1]['railName'] = None
            if field == 'identity': f['edgeInfoList'][-1]['stationCode'] = '99999'
            if field == 'transport': f['edgeInfoList'][1]['accessInfo'] = {'type': 99}
            with self.subTest(field=field), self.assertRaises(t.TransitError) as caught:
                source.normalize_route(f, ORIGIN, DEST, 1)
            self.assertEqual(caught.exception.code, 'station_mismatch' if field == 'identity' else 'source_schema_changed')

    def test_later_bad_alternative_or_requested_window_is_not_unavailable(self):
        for case in ('type', 'shape', 'fare', 'time', 'query', 'later_window'):
            p = props(); bad = feature()
            if case == 'type': bad['edgeInfoList'][1]['timeInfo'][0]['type'] = 6
            if case == 'fare': bad['summaryInfo']['totalPrice'] = 'unknown'
            if case == 'shape': bad = None
            if case == 'time':
                bad = self.qualified(); bad['edgeInfoList'][-1]['timeInfo'][0]['time'] = '00:31'
            if case == 'later_window':
                bad['summaryInfo'].update(departureTime='23:40', totalTime='50分')
                bad['summaryInfo']['calendarData']['startTime'] = '20261102T234000'
                bad['edgeInfoList'][0]['timeInfo'][0]['time'] = '23:40'
            p['naviSearchParam']['featureInfoList'] = [self.qualified(), bad]
            options = args()
            if case == 'query': options.time = '23:55'; p['queryState']['minute'] = '55'
            with self.subTest(case=case), self.assertRaises(t.TransitError) as caught:
                t.search_route(Fake(html(p)), options)
            self.assertEqual(caught.exception.code, 'source_schema_changed')


class StationTests(unittest.TestCase):
    def source(self, query, names):
        rows = [{"Id": "st", "Code": str(10000 + i), "Suggest": name, "Address": "テスト県", "Yomi": "テスト"} for i, name in enumerate(names)]
        rows.append({"Id": "bu", "Code": "123", "Suggest": "テストバス停"})
        return Fake(json.dumps({"@query": query, "Result": rows}).encode())

    def test_filters_bus_and_preserves_qualifiers(self):
        rows, _ = t.stations(self.source("テスト", ["テスト(北県)", "テスト(南県)"]), "テスト")
        self.assertEqual([r["name"] for r in rows], ["テスト(北県)", "テスト(南県)"])

    def test_exact_name_resolves_but_ambiguous_and_partial_names_do_not(self):
        self.assertEqual(t.resolve(self.source("テスト", ["テスト", "東テスト"]), "テスト")["name"], "テスト")
        for names in [["テスト(北県)", "テスト(南県)"], ["東テスト"], []]:
            with self.subTest(names=names), self.assertRaises(t.TransitError): t.resolve(self.source("テスト", names), "テスト")

    def test_station_suffix_is_not_removed(self):
        self.assertNotEqual(source.text_key("富山"), source.text_key("富山駅"))
        with self.assertRaises(t.TransitError): t.resolve(self.source("富山駅", ["富山"]), "富山駅")

    def test_suggestion_query_echo_required(self):
        with self.assertRaises(t.TransitError): t.stations(self.source("別の検索", ["テスト"]), "テスト")

    def test_haneda_native_candidates_work_with_lookup_or_reused_codes(self):
        # Source-shaped names observed in both autocomplete and route output.
        # No complete upstream page or timetable is needed for this regression.
        cases = [
            ("羽田空港第1ターミナル", "羽田空港第1ターミナル(モノレール/JAL)", "29509",
             "羽田空港第１ターミナル(東京モノレール・ＪＡＬ利用)"),
            ("羽田空港第2ターミナル", "羽田空港第2ターミナル(モノレール/ANA)", "29510",
             "羽田空港第２ターミナル(東京モノレール・ＡＮＡ利用)"),
        ]
        for lookup, candidate, code, actual in cases:
            for reuse in (False, True):
                with self.subTest(code=code, reuse=reuse):
                    p = props()
                    p["naviSearchParam"]["featureInfoList"][0]["edgeInfoList"][0].update(stationName=actual, stationCode=code)
                    reads = []

                    def read(client, url):
                        reads.append(url)
                        parsed = urllib.parse.urlsplit(url)
                        query = urllib.parse.parse_qs(parsed.query)
                        if parsed.path == "/api/suggest":
                            value = query["value"][0]
                            # The actual service strips slashes and returns no
                            # candidates for the complete airport label.
                            return json.dumps({"@query": value.replace("/", ""), "Result":
                                [{"Id": "st", "Code": code, "Suggest": candidate}] if value == lookup else []}).encode()
                        self.assertEqual(parsed.path, "/search/result")
                        self.assertEqual(query["from"], [candidate])
                        self.assertEqual(query["flatlon"], [",," + code])
                        return html(p)

                    argv = ["route", "--from", candidate, "--to", DEST["name"], "--to-code", DEST["code"],
                            "--date", "2026-11-02", "--time", "23:45"] + (["--from-code", code] if reuse else [])
                    with patch.object(t.Client, "read", read), redirect_stdout(io.StringIO()) as output:
                        self.assertEqual(t.main(argv), 0)
                    result = json.loads(output.getvalue())
                    self.assertEqual(result["query"]["from"]["name"], candidate)
                    self.assertEqual(result["routes"][0]["legs"][0]["from"]["name"], actual)
                    self.assertEqual(len(reads), 1 if reuse else 2)

    def test_haneda_lookup_override_also_works_in_mixed_lookup(self):
        name = "羽田空港第1ターミナル(モノレール/JAL)"
        client = Fake(json.dumps({"@query": "羽田空港第1ターミナル", "Result":
            [{"Id": "st", "Code": "29509", "Suggest": name},
             {"Id": "st", "Code": "29510", "Suggest": "羽田空港第2ターミナル(モノレール/ANA)"}]}).encode())
        resolved = t.resolve(client, name, kind="all")
        self.assertEqual((resolved["name"], resolved["code"], resolved["kind"]), (name, "29509", "station"))
        self.assertEqual(len(client.urls), 1)

    def test_haneda_aliases_do_not_accept_another_terminal_operator_or_kind(self):
        selected = {"name": "羽田空港第1ターミナル(モノレール/JAL)", "code": "29509", "kind": "station"}
        actual = {"name": "羽田空港第１ターミナル(東京モノレール・ＪＡＬ利用)", "code": "29509", "kind": "station"}
        self.assertTrue(source.same_station(selected, actual))
        for change in [{"code": "29510"}, {"name": "羽田空港第１ターミナル(京急)"}, {"kind": "bus"}]:
            self.assertFalse(source.same_station(selected, {**actual, **change}))
        self.assertFalse(source.same_station({**selected, "code": "10000"}, {**actual, "code": "10000"}))


class BusTests(unittest.TestCase):
    def bus_props(self):
        p = props()
        p["queryState"].update(useShinkansen=False, useLimitedExpress=False, useLocalBus=True, useHighwayBus=True)
        for e in p["naviSearchParam"]["featureInfoList"][0]["edgeInfoList"][:-1]:
            e["accessInfo"] = {"type": 2}
            e["railName"] = "架空バス・テスト便"
        return p

    def rail_alternative_between_bus_stops(self):
        f = feature()
        f["edgeInfoList"] = [
            edge(ORIGIN["name"], ORIGIN["code"], [{"type": 3, "time": "23:50"}]),
            edge("架空鉄道駅", "20001", [{"type": 2, "time": "23:55"}, {"type": 1, "time": "23:55"}]),
            edge("別の架空鉄道駅", "20002", [{"type": 2, "time": "00:20"}, {"type": 1, "time": "00:20"}]),
            edge(DEST["name"], DEST["code"], [{"type": 3, "time": "00:30"}])]
        for e, mode in zip(f["edgeInfoList"], [1, 0, 1]): e["accessInfo"] = {"type": mode}
        return f

    def test_typed_stop_search_keeps_operators_and_categories(self):
        rows = [{"Id": "st", "Code": "100", "Suggest": "同名駅"},
                {"Id": "bu", "Code": "200", "Suggest": "同名駅/架空Ａバス"},
                {"Id": "bu", "Code": "201", "Suggest": "同名駅/架空Ｂバス"},
                {"Id": "bu", "Code": "202", "Suggest": "同名駅(高速・連絡バス)"},
                {"Id": "la", "Code": "", "Suggest": "同名施設"}]
        client = Fake(json.dumps({"@query": "同名", "Result": rows}).encode())
        found, _ = t.stops(client, "同名")
        self.assertEqual([r["kind"] for r in found], ["station", "bus", "bus", "bus"])
        self.assertEqual(found[1]["operator_ja"], "架空Ａバス")
        self.assertIsNone(found[-1]["operator_ja"])
        buses, _ = t.stops(client, "同名", "bus")
        self.assertEqual(len(buses), 3)
        with self.assertRaises(t.TransitError): t.resolve(client, "同名", kind="bus")

    def test_qualified_name_searches_native_stop_part_then_matches_full_name(self):
        rows = [{"Id": "bu", "Code": "200", "Suggest": "同名駅/架空Ａバス"},
                {"Id": "bu", "Code": "201", "Suggest": "同名駅/架空Ｂバス"},
                {"Id": "bu", "Code": "202", "Suggest": "同名駅(高速・連絡バス)"}]
        for name, code in [("同名駅/架空Ｂバス", "201"), ("同名駅(高速・連絡バス)", "202")]:
            client = Fake(json.dumps({"@query": "同名駅", "Result": rows}).encode())
            self.assertEqual(t.resolve(client, name, kind="bus")["code"], code)
            self.assertEqual(len(client.urls), 1)
            self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(client.urls[0]).query)["value"], ["同名駅"])
        client = Fake(json.dumps({"@query": "同名駅", "Result": rows}).encode())
        with self.assertRaises(t.TransitError): t.resolve(client, "同名駅/存在しない事業者", kind="bus")

    def test_slash_inside_rail_operator_parentheses_is_not_a_bus_qualifier(self):
        query = "空港第1ターミナル(モノレール/JAL)"
        client = Fake(json.dumps({"@query": query, "Result": [{"Id": "st", "Code": "100", "Suggest": query}]}).encode())
        self.assertEqual(t.resolve(client, query, kind="all")["name"], query)
        self.assertEqual(urllib.parse.parse_qs(urllib.parse.urlsplit(client.urls[0]).query)["value"], [query])
        self.assertEqual(t.bus_operator("同名駅/架空Ａバス(東/西)"), "架空Ａバス(東/西)")

    def test_bus_mode_checks_flags_and_returns_bus_legs(self):
        client = Fake(html(self.bus_props()))
        r = t.search_route(client, args("--transport", "bus"))
        self.assertEqual(r["routes"][0]["modes_used"], ["bus"])
        self.assertEqual(r["routes"][0]["legs"][0]["from"]["kind"], "bus")
        self.assertFalse(r["query"]["shinkansen"])
        self.assertTrue(r["query"]["highway_bus"])
        self.assertIsNone(r["source"]["bus_timetable_version"])
        for fragment in ["shin=0", "ex=0", "hb=1", "lb=1", "al=0", "sr=0"]:
            self.assertIn(fragment, client.urls[0])

    def test_bus_mode_filters_rail_before_limit_and_preserves_source_rank(self):
        p = self.bus_props()
        p["naviSearchParam"]["featureInfoList"].insert(0, self.rail_alternative_between_bus_stops())
        r = t.search_route(Fake(html(p)), args("--transport", "bus", "--limit", "1"))
        self.assertEqual(r["filtered_routes"], 1)
        self.assertEqual(r["routes"][0]["rank"], 2)
        self.assertEqual(r["returned_routes"], 1)

    def test_highway_bus_native_type_is_a_bus_including_after_midnight(self):
        p = self.bus_props()
        for e in p['naviSearchParam']['featureInfoList'][0]['edgeInfoList'][:-1]:
            e['accessInfo'] = {'type': 3}
            e['railName'] = 'Synthetic service without a transport-name hint'
        result = t.search_route(Fake(html(p)), args('--transport', 'bus'))
        route = result['routes'][0]
        self.assertEqual(route['modes_used'], ['bus'])
        self.assertEqual(route['legs'][0]['from']['kind'], 'bus')
        self.assertEqual(route['arrival_at'], '2026-11-03T00:30:00+09:00')
        self.assertEqual(route['fare']['total_jpy'], 1500)

    def test_rail_filter_excludes_a_highway_bus_alternative(self):
        p = props()
        bus = self.rail_alternative_between_bus_stops()
        bus['edgeInfoList'][1]['accessInfo'] = {'type': 3}
        p['naviSearchParam']['featureInfoList'].insert(0, bus)
        result = t.search_route(Fake(html(p)), args('--limit', '1'))
        self.assertEqual(result['filtered_routes'], 1)
        self.assertEqual(result['routes'][0]['rank'], 2)
        self.assertEqual(result['routes'][0]['modes_used'], ['rail'])

    def test_no_bus_in_embedded_alternatives_is_not_no_service(self):
        p = self.bus_props()
        p["naviSearchParam"]["featureInfoList"] = [self.rail_alternative_between_bus_stops()]
        r = t.search_route(Fake(html(p)), args("--transport", "bus"))
        self.assertEqual(r["status"], "unavailable")
        self.assertEqual(r["unavailable_reason"], "no_matching_embedded_routes")
        self.assertEqual(r["embedded_routes"], 1)

    def test_walk_only_is_not_a_bus_route(self):
        p = self.bus_props()
        for e in p["naviSearchParam"]["featureInfoList"][0]["edgeInfoList"][:-1]: e["accessInfo"] = {"type": 1}
        self.assertEqual(t.search_route(Fake(html(p)), args("--transport", "bus"))["status"], "unavailable")

    def test_unknown_transport_is_not_inferred_from_service_name(self):
        for access in [None, {"type": 4}, {"type": 99}, {"type": True}]:
            f = feature(); f["edgeInfoList"][0]["accessInfo"] = access
            with self.subTest(access=access), self.assertRaises(t.TransitError): source.normalize_route(f, ORIGIN, DEST, 1)

    def test_mixed_rail_walk_bus_preserves_points_waits_and_total_fare(self):
        p = props(); p["queryState"].update(useLocalBus=True, useHighwayBus=True)
        f = self.rail_alternative_between_bus_stops()
        for e, mode in zip(f["edgeInfoList"], [0, 1, 2]): e["accessInfo"] = {"type": mode}
        p["naviSearchParam"]["featureInfoList"] = [f]
        r = t.search_route(Fake(html(p)), args("--transport", "mixed", "--from-kind", "station", "--to-kind", "bus"))
        route = r["routes"][0]
        self.assertEqual([l["transport"] for l in route["legs"]], ["rail", "walk", "bus"])
        self.assertEqual(route["legs"][1]["from"]["kind"], "station")
        self.assertEqual(route["legs"][1]["to"]["kind"], "bus")
        self.assertEqual(route["fare"]["total_jpy"], 1500)

    def test_kind_mismatch_and_missing_reused_kind_fail(self):
        self.assertFalse(source.same_station({**ORIGIN, "kind": "station"}, {**ORIGIN, "kind": "bus"}))
        with self.assertRaises(t.TransitError): t.resolve(Fake(b""), ORIGIN["name"], ORIGIN["code"], "all")
        parser = t.build_parser()
        for extra in [["--transport", "mixed"], ["--transport", "rail", "--from-kind", "bus"]]:
            with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit): t.validate_args(parser, args(*extra))

    def test_bus_platform_is_preserved_without_turning_it_into_a_rail_track(self):
        f = feature()
        f["edgeInfoList"][0]["accessInfo"] = {"type": 2}
        f["edgeInfoList"][0]["ridingPositionInfo"] = {"departure": ["東口6", "のりば"], "arrival": ["3", "おりば"]}
        r = source.normalize_route(f, ORIGIN, DEST, 1)
        self.assertEqual(r["legs"][0]["departure_platform_ja"], "東口6のりば")
        self.assertEqual(r["legs"][0]["arrival_platform_ja"], "3おりば")


class ClientTests(unittest.TestCase):
    def test_truncated_chunked_response_returns_cli_json_without_retry(self):
        class Socket:
            def makefile(self, *args):
                return io.BytesIO(b"HTTP/1.1 200 OK\r\nTransfer-Encoding: chunked\r\n\r\n5\r\nabc")

        response = http.client.HTTPResponse(Socket())
        response.begin()
        with patch.object(urllib.request.OpenerDirector, "open", return_value=response) as call, \
                redirect_stdout(io.StringIO()) as output, redirect_stderr(io.StringIO()) as errors:
            self.assertEqual(t.main(["stations", "長野"]), 2)
        result = json.loads(output.getvalue())
        self.assertEqual(result["error"]["code"], "network_error")
        self.assertEqual(result["error"]["exception_type"], "IncompleteRead")
        self.assertEqual(result["usage"]["http_requests"], 1)
        self.assertEqual(errors.getvalue(), "")
        call.assert_called_once()

    def test_http_protocol_error_is_not_cached_or_retried(self):
        c = t.Client()
        with patch.object(c.opener, "open", side_effect=http.client.BadStatusLine("malformed status")) as call:
            with self.assertRaises(t.TransitError) as caught: c.read(t.BASE)
        self.assertEqual(caught.exception.code, "network_error")
        self.assertEqual(caught.exception.details["exception_type"], "BadStatusLine")
        self.assertEqual(c.cache, {})
        self.assertEqual(c.requests, 1)
        call.assert_called_once()

    def test_denial_is_one_attempt_and_retry_after_is_retained(self):
        c = t.Client()
        error = urllib.error.HTTPError(t.BASE, 429, "limited", {"Retry-After": "60"}, None)
        with patch.object(c.opener, "open", side_effect=error) as call:
            with self.assertRaises(t.TransitError) as caught: c.read(t.BASE + "/api/suggest?value=test")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(caught.exception.details["retry_after"], "60")
        self.assertEqual(c.usage()["http_requests"], 1)

    def test_body_limit_and_cache(self):
        c = t.Client(); response = Response(b"data")
        with patch.object(c.opener, "open", return_value=response) as call:
            self.assertEqual(c.read(t.BASE), b"data")
            self.assertEqual(c.read(t.BASE), b"data")
        self.assertEqual(call.call_count, 1)
        self.assertEqual(c.usage()["memory_cache_hits"], 1)
        c = t.Client()
        with patch.object(c.opener, "open", return_value=Response(b"x" * (source.MAX_BYTES + 1))):
            with self.assertRaises(t.TransitError) as caught: c.read(t.BASE)
        self.assertEqual(caught.exception.code, "response_too_large")

    def test_rejects_redirect_before_following_it(self):
        with self.assertRaises(t.TransitError): transport.RejectRedirect().redirect_request(None, None, 302, "moved", {}, "https://jid.jorudan.co.jp/")

    def test_doctor_and_invalid_dates_make_no_network_requests(self):
        with patch.object(t.Client, "read", side_effect=AssertionError("network")), redirect_stdout(io.StringIO()) as output:
            self.assertEqual(t.main(["doctor"]), 0)
        self.assertEqual(json.loads(output.getvalue())["usage"]["http_requests"], 0)
        for options in [["--date", "2026-02-30", "--time", "09:00"], ["--date", "2026-11-02", "--mode", "last", "--time", "23:00"], ["--date", "2026-11-02"]]:
            with self.subTest(options=options), redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                t.main(["route", "--from", "テスト", "--to", "別駅", *options])


if __name__ == "__main__":
    unittest.main()
