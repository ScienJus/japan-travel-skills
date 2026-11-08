"""Offline, synthetic operator-shaped fixtures; no copied upstream bulletins."""
from http_test_support import Response
import copy
import datetime as dt
import http.client
import importlib.util
import io
import json
import sys
import unittest
import urllib.error
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/japan-transit/scripts"
sys.path.insert(0, str(SCRIPTS))
import rail_operations as o

SPEC = importlib.util.spec_from_file_location("transit_operations_test", SCRIPTS / "transit.py")
t = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(t)
NOW = dt.datetime(2026, 11, 1, 12, 43, 50, tzinfo=o.JST)
STAMP = "2026-11-01T12:42:11.121508601+09:00"


def native_report():
    return {"id": 103, "lineName": "北陸新幹線", "iconType": "0003", "shinkansenTrafficInfoDetails": [
        {"trafficId": 90001, "iconType": "0003", "conditionName": "一部列車遅延", "publicationDate": "2026-11-01T12:18:00+09:00",
         "sections": [{"startStation": "テスト駅甲", "endStation": "テスト駅乙", "upAndDown": "上り"}],
         "versionDetail": [{"id": 90002, "updatedAt": "2026-11-01T12:18:00+09:00", "body": "Synthetic test bulletin, not an actual incident."}]}]}


def west_data():
    value = {"createdAt": STAMP, "maintenances": [{"id": 1, "isMaintaining": False}],
             "systemAnnouncements": [{"id": 1, "isAnnouncing": False}], "masterData": {"areas": []}, "areaTrafficInfos": []}
    for area_id, place_id, name, lines, key in [
            (1, 2, "北陸エリア", [(27, "北陸線"), (28, "大糸線"), (29, "高山線"), (30, "氷見線"),
                               (31, "城端線"), (32, "七尾線"), (33, "越美北線（九頭竜線）"), (34, "小浜線")], "conventionalLineTrafficInfos"),
            (5, 9, "北陸新幹線", [(103, "北陸新幹線")], "shinkansenTrafficInfos")]:
        value["masterData"]["areas"].append({"id": area_id, "name": name, "places": [
            {"id": place_id, "lines": [{"id": code, "name": name} for code, name in lines]}]})
        value["areaTrafficInfos"].append({"id": area_id, "iconType": "", "areaAnnouncements": [],
            "conventionalLineDelayInfos": [], "trafficHistories": [{"id": 90000, "body": "Synthetic old history"}],
            "dailyData": [{"date": (NOW.date() + dt.timedelta(days=n)).isoformat(), "iconType": "", "placeTrafficInfos": [
                {"id": place_id, "iconType": "", key: [], "noEffectLineTrafficInfos": []}]} for n in range(3)]})
    return value


def west_area(value, shinkansen=True):
    return value["areaTrafficInfos"][1 if shinkansen else 0]


def west_place(value, shinkansen=True, day=0):
    return west_area(value, shinkansen)["dailyData"][day]["placeTrafficInfos"][0]


def west_result(value=None, line="北陸新幹線"):
    value = value if value is not None else west_data()
    parsed, stamp = o.west_snapshot(json.dumps(value).encode(), NOW)
    return o.west_line(parsed, stamp, o.select_lines([line], "jr-west")[0])


class SelectionAndTimeTests(unittest.TestCase):
    def test_catalog_and_operator_sections(self):
        self.assertEqual(len(o.candidates()), 10)
        self.assertEqual(len(o.candidates(operator="jr-west")), 9)
        rows = o.select_lines(["大糸线", "大糸線"], "jr-west")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0][2], rows[0][3]), ("南小谷", "糸魚川"))

    def test_unsupported_pair_and_partial_name_are_not_substituted(self):
        for name, operator in [("北陸", "jr-west"), ("北陸本線", "jr-west"), ("高山本線", "jr-west"),
                               ("七尾線", "jr-east"), ("しなの鉄道", "jr-west"), ("", "jr-west")]:
            with self.subTest(name=name), self.assertRaises(o.OperationsError):
                o.select_lines([name], operator)

    def test_native_parentheses_and_explicit_nicknames_deduplicate(self):
        rows = o.select_lines(["越美北線（九頭竜線）", "越美北線(九頭竜線)", "越美北線", "九頭竜線", "九头龙线"], "jr-west")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "越美北線（九頭竜線）")
        self.assertEqual(o.candidates("越美北線(九頭竜線)")[0]["source_line_id"], 33)

    def test_new_sections_retain_official_hokuriku_scope(self):
        expected = {"北陸線": ("近江塩津", "敦賀", 27), "高山線": ("猪谷", "富山", 29),
                    "氷見線": ("高岡", "氷見", 30), "城端線": ("高岡", "城端", 31),
                    "越美北線（九頭竜線）": ("越前花堂", "九頭竜湖", 33), "小浜線": ("東舞鶴", "敦賀", 34)}
        for name, (start, end, identity) in expected.items():
            with self.subTest(name=name):
                row, = o.select_lines([name], "jr-west")
                self.assertEqual((row[2], row[3], row[4], row[5]), (start, end, "hokuriku", identity))

    def test_reporting_hours_exclude_midnight_through_0559(self):
        for hour in range(24):
            self.assertEqual(o.in_hours("jr-west", NOW.replace(hour=hour)), hour >= 6)

    def test_freshness_rejects_future_and_stale_not_old_event_times(self):
        for delta in [-1, 601]:
            with self.subTest(delta=delta), self.assertRaises(o.OperationsError):
                o.fresh((NOW - dt.timedelta(seconds=delta)).isoformat(), NOW, "jr-west")
        self.assertIsNotNone(o.fresh((NOW - dt.timedelta(seconds=600)).isoformat(), NOW, "jr-west"))

    def test_nine_digit_timestamp_works_on_python39(self):
        self.assertEqual(o.timestamp(STAMP).microsecond, 121508)
        for fraction in ["1", "12", "1234", "123456789"]:
            self.assertEqual(o.timestamp("2026-11-01T12:42:11." + fraction + "+09:00").hour, 12)
        for value in ["2026-11-01T12:42:11Z", "2026-11-01", "2026-02-30T12:00:00+09:00"]:
            with self.assertRaises(o.OperationsError): o.timestamp(value)



class WestTests(unittest.TestCase):

    def test_same_name_in_kinki_does_not_supply_hokuriku_reports(self):
        data = west_data()
        data["masterData"]["areas"].append({"id": 2, "name": "近畿エリア", "places": [
            {"id": 3, "lines": [{"id": 1, "name": "北陸線"}]}]})
        kinki = copy.deepcopy(west_area(data, False))
        kinki["id"] = 2
        row = native_report()
        row.update(id=1, lineName="北陸線")
        row["conventionalLineTrafficInfoDetails"] = row.pop("shinkansenTrafficInfoDetails")
        kinki["dailyData"][0]["placeTrafficInfos"][0].update(id=3, conventionalLineTrafficInfos=[row])
        data["areaTrafficInfos"].append(kinki)
        result = west_result(data, "北陸線")
        self.assertEqual((result["source_line_id"], result["state"], result["bulletins"]), (27, "no_listed_reports", []))
        # A same-named line elsewhere cannot fill a missing Hokuriku identity.
        data["masterData"]["areas"][0]["places"][0]["lines"].pop(0)
        with self.assertRaises(o.OperationsError): west_result(data, "北陸線")

    def test_added_line_native_id_name_mismatch_fails(self):
        data = west_data()
        data["masterData"]["areas"][0]["places"][0]["lines"][2]["name"] = "高山本線"
        with self.assertRaises(o.OperationsError): west_result(data, "高山線")

    def test_empty_today_is_no_listed_reports_not_normal_or_punctual(self):
        result = west_result()
        self.assertEqual(result["state"], "no_listed_reports")
        self.assertEqual(result["bulletins"], [])
        self.assertNotIn("is_operating", result)

    def test_native_delay_sections_and_old_issue_time_are_preserved(self):
        data = west_data()
        west_place(data)["shinkansenTrafficInfos"] = [native_report()]
        result = west_result(data)
        self.assertEqual(result["state"], "reports_listed")
        self.assertEqual(result["bulletins"][0]["shinkansenTrafficInfoDetails"][0]["sections"][0]["upAndDown"], "上り")

    def test_conventional_line_contract_and_empty_placeholder(self):
        data = west_data(); row = native_report()
        row.update(id=32, lineName="七尾線")
        row["conventionalLineTrafficInfoDetails"] = row.pop("shinkansenTrafficInfoDetails")
        west_place(data, False)["conventionalLineTrafficInfos"] = [row]
        self.assertEqual(west_result(data, "七尾線")["state"], "reports_listed")
        row["conventionalLineTrafficInfoDetails"] = []; row["iconType"] = ""
        self.assertEqual(west_result(data, "七尾線")["state"], "no_listed_reports")
        row["iconType"] = "0003"
        with self.assertRaises(o.OperationsError): west_result(data, "七尾線")

    def test_tomorrow_and_history_are_not_current_incidents(self):
        data = west_data()
        west_place(data, day=1)["shinkansenTrafficInfos"] = [native_report()]
        self.assertEqual(west_result(data)["state"], "no_listed_reports")

    def test_area_work_notice_is_context_not_a_line_specific_delay(self):
        data = west_data()
        west_area(data, False)["areaAnnouncements"] = [{"id": 90003, "versions": [
            {"title": "Synthetic future work on another line", "updatedAt": "2026-10-01T12:00:00+09:00", "body": "Synthetic context."}]}]
        result = west_result(data, "七尾線")
        self.assertEqual(result["state"], "review_required")
        self.assertEqual(result["bulletins"], [])
        self.assertEqual(len(result["context"]["area_announcements"]), 1)

    def test_no_effect_and_conventional_delay_context_requires_review(self):
        for key in ["no_effect", "delay_context"]:
            data = west_data()
            if key == "no_effect": west_place(data)["noEffectLineTrafficInfos"] = [{"id": 90005, "iconType": "0000"}]
            else: west_area(data)["conventionalLineDelayInfos"] = [{"id": 90006, "updatedAt": "2026-11-01T12:41:00+09:00"}]
            self.assertEqual(west_result(data)["state"], "review_required")

    def test_maintenance_and_active_site_notice_fail_closed(self):
        for key, flag in [("maintenances", "isMaintaining"), ("systemAnnouncements", "isAnnouncing")]:
            data = west_data(); data[key][0][flag] = True
            with self.assertRaises(o.OperationsError): west_result(data)
        for flag in [None, 0, "false"]:
            data = west_data(); data["maintenances"][0]["isMaintaining"] = flag
            with self.assertRaises(o.OperationsError): west_result(data)

    def test_missing_arrays_are_unknown_not_no_reports(self):
        for key in ["shinkansenTrafficInfos", "noEffectLineTrafficInfos"]:
            data = west_data(); del west_place(data)[key]
            with self.assertRaises((o.OperationsError, KeyError)): west_result(data)
        data = west_data(); del west_area(data, False)["areaAnnouncements"]
        with self.assertRaises(KeyError): west_result(data, "七尾線")

    def test_missing_or_mismatched_master_and_current_identity_fail(self):
        mutations = [lambda d: d["masterData"]["areas"][1]["places"][0]["lines"][0].update(name="other"),
                     lambda d: west_place(d).update(id=99),
                     lambda d: d["areaTrafficInfos"].append(copy.deepcopy(d["areaTrafficInfos"][1])),
                     lambda d: d["masterData"]["areas"][0].update(id=True)]
        for change in mutations:
            data = west_data(); change(data)
            with self.assertRaises(o.OperationsError): west_result(data)

    def test_duplicate_line_reports_and_mismatched_name_fail(self):
        for duplicate in [True, False]:
            data = west_data(); row = native_report()
            if duplicate: west_place(data)["shinkansenTrafficInfos"] = [row, copy.deepcopy(row)]
            else: row["lineName"] = "other"; west_place(data)["shinkansenTrafficInfos"] = [row]
            with self.assertRaises(o.OperationsError): west_result(data)

    def test_wrong_today_or_missing_date_bucket_fails(self):
        for wrong in [True, False]:
            data = west_data()
            if wrong: west_area(data)["dailyData"][0]["date"] = "2026-11-02"
            else: west_area(data)["dailyData"].pop()
            with self.assertRaises(o.OperationsError): west_result(data)

    def test_unknown_area_and_nested_status_codes_fail(self):
        for nested in [True, False]:
            data = west_data()
            if nested:
                row = native_report(); row["shinkansenTrafficInfoDetails"][0]["iconType"] = "9999"
                west_place(data)["shinkansenTrafficInfos"] = [row]
            else: west_area(data)["iconType"] = "9999"
            with self.assertRaises(o.OperationsError): west_result(data)

    def test_nonempty_state_cannot_hide_missing_reports(self):
        data = west_data(); west_place(data)["iconType"] = "0003"
        with self.assertRaises(o.OperationsError): west_result(data)

    def test_future_report_update_and_stale_snapshot_fail(self):
        data = west_data(); row = native_report()
        row["shinkansenTrafficInfoDetails"][0]["versionDetail"][0]["updatedAt"] = "2026-11-01T13:00:00+09:00"
        west_place(data)["shinkansenTrafficInfos"] = [row]
        with self.assertRaises(o.OperationsError): west_result(data)
        data = west_data(); data["createdAt"] = "2026-11-01T12:00:00+09:00"
        with self.assertRaises(o.OperationsError): west_result(data)

    def test_duplicate_json_fields_invalid_utf8_and_nan_fail(self):
        for raw in [b'{"createdAt":"x","createdAt":"y"}', b'\xff', b'{"createdAt":NaN}']:
            with self.assertRaises(o.OperationsError): o.west_snapshot(raw, NOW)


class CommandTests(unittest.TestCase):
    def command(self, args, reader=None, at=NOW):
        if args[0] == "operations" and "--operator" not in args:
            args = args + ["--operator", "jr-west"]
        with patch.object(o, "now_jst", return_value=at), patch.object(o.Client, "read", side_effect=reader or AssertionError("network")) as read, redirect_stdout(io.StringIO()) as output:
            result = t.main(args)
        return result, json.loads(output.getvalue()), read

    def test_offline_catalog_and_unsupported_line_make_zero_reads(self):
        result, value, call = self.command(["lines"])
        self.assertEqual((result, len(value["lines"])), (0, 10)); call.assert_not_called()
        result, value, call = self.command(["operations", "--line", "unknown"])
        self.assertEqual((result, value["report_state"]), (2, "unknown")); call.assert_not_called()

    def test_batch_uses_one_snapshot_and_preserves_each_section(self):
        data = west_data(); west_place(data)["shinkansenTrafficInfos"] = [native_report()]
        result, value, call = self.command(["operations", "--line", "北陸新幹線", "--line", "大糸線", "--line", "七尾線"], lambda url: (json.dumps(data).encode(), NOW))
        self.assertEqual((result, len(value["reports"]), call.call_count), (0, 3, 1))
        self.assertEqual([r["state"] for r in value["reports"]], ["reports_listed", "no_listed_reports", "no_listed_reports"])
        self.assertEqual(value["reports"][1]["operator_section_reference"]["from_ja"], "南小谷")

    def test_all_nine_lines_share_one_read_and_filter_native_reports(self):
        data = west_data()
        row = native_report()
        row.update(id=30, lineName="氷見線")
        row["conventionalLineTrafficInfoDetails"] = row.pop("shinkansenTrafficInfoDetails")
        west_place(data, False)["conventionalLineTrafficInfos"] = [row]
        args = ["operations"]
        for entry in o.LINES:
            if entry[1] != "jr-west":
                continue
            args.extend(["--line", entry[0]])
        result, value, call = self.command(args, lambda url: (json.dumps(data).encode(), NOW))
        self.assertEqual((result, len(value["reports"]), call.call_count), (0, 9, 1))
        self.assertEqual(len(value["sources"]), 2)
        for report in value["reports"]:
            with self.subTest(name=report["name_ja"]):
                self.assertEqual(report["state"], "reports_listed" if report["source_line_id"] == 30 else "no_listed_reports")
                self.assertEqual(report["bulletins"], [row] if report["source_line_id"] == 30 else [])

    def test_source_failure_returns_unknown_without_empty_reports(self):
        result, value, call = self.command(["operations", "--line", "北陸新幹線"], o.OperationsError("network_error", "Synthetic network failure"))
        self.assertEqual((result, value["report_state"], call.call_count), (2, "unknown", 1))
        self.assertNotIn("reports", value)

    def test_missing_source_structure_is_structured_unknown(self):
        result, value, _ = self.command(["operations", "--line", "北陸新幹線"], lambda url: (b'{}', NOW))
        self.assertEqual((result, value["report_state"], value["error"]["code"]), (2, "unknown", "source_schema_changed"))

    def test_outside_hours_preflight_makes_zero_reads(self):
        result, value, call = self.command(["operations", "--line", "北陸新幹線"], at=NOW.replace(hour=3))
        self.assertEqual((result, value["error"]["code"]), (2, "outside_reporting_hours")); call.assert_not_called()

    def test_no_date_option_and_no_unverified_operator_choice(self):
        for options in [["--operator", "jr-west", "--date", "2026-11-02"], ["--operator", "jr-east"], ["--operator", "all"], []]:
            with patch.object(o.Client, "read", side_effect=AssertionError("network")) as read, redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
                t.main(["operations", "--line", "北陸新幹線"] + options)
            read.assert_not_called()



class ClientTests(unittest.TestCase):
    def test_cache_budget_and_exact_product_allowlist(self):
        c = o.Client()
        with patch.object(c.opener, "open", return_value=Response(b"{}")) as call:
            self.assertEqual(c.read(o.WEST_DATA)[0], b"{}")
            self.assertEqual(c.read(o.WEST_DATA)[0], b"{}")
            call.assert_called_once()
        with self.assertRaises(o.OperationsError): c.read(o.WEST_DATA + "?other=1")
        c.cache.clear(); c.requests = 1
        with self.assertRaises(o.OperationsError): c.read(o.WEST_DATA)

    def test_response_size_protocol_and_denial_are_bounded_without_retry(self):
        for error in [urllib.error.HTTPError(o.WEST_DATA, 429, "limited", {"Retry-After": "60"}, None),
                      http.client.IncompleteRead(b"partial"), OSError("unavailable")]:
            c = o.Client()
            with patch.object(c.opener, "open", side_effect=error) as call, self.assertRaises(o.OperationsError) as caught:
                c.read(o.WEST_DATA)
            self.assertEqual((call.call_count, c.requests, c.cache), (1, 1, {}))
            if isinstance(error, urllib.error.HTTPError): self.assertEqual(caught.exception.details["retry_after"], "60")
        c = o.Client()
        with patch.object(c.opener, "open", return_value=Response(b"x" * (o.MAX_BYTES + 1))), self.assertRaises(o.OperationsError): c.read(o.WEST_DATA)

    def test_redirect_rejected(self):
        with self.assertRaises(o.OperationsError): o.RejectRedirect().redirect_request(None, None, 302, "moved", {}, "https://example.com")


if __name__ == "__main__":
    unittest.main()
