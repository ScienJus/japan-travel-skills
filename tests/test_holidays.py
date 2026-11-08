"""Offline behavioral checks for the Cabinet Office holiday reader."""
import contextlib
import datetime as dt
import http.client
import importlib.util
import io
import json
from pathlib import Path
import unittest
from unittest.mock import patch, Mock
import urllib.error

SCRIPT = Path(__file__).resolve().parents[1] / "skills/japan-holidays/scripts/holidays.py"
spec = importlib.util.spec_from_file_location("japan_holidays", SCRIPT)
h = importlib.util.module_from_spec(spec)
spec.loader.exec_module(h)


def export(rows):
    return ("国民の祝日・休日月日,国民の祝日・休日名称\r\n" +
            "\r\n".join(",".join(row) for row in rows) + "\r\n").encode("cp932")


# Selected observed source rows; not a complete calendar or a runtime fallback.
ROWS = [
    ("2026/1/1", "元日"), ("2026/5/3", "憲法記念日"),
    ("2026/5/4", "みどりの日"), ("2026/5/5", "こどもの日"), ("2026/5/6", "休日"),
    ("2026/9/21", "敬老の日"), ("2026/9/22", "休日"), ("2026/9/23", "秋分の日"),
    ("2026/11/3", "文化の日"), ("2026/11/23", "勤労感謝の日"),
    ("2027/1/1", "元日"), ("2027/3/21", "春分の日"), ("2027/3/22", "休日"),
    ("2027/11/23", "勤労感謝の日"),
]
RAW = export(ROWS)
HOLIDAYS, START, END = h.parse_csv(RAW)


class ParsingTests(unittest.TestCase):
    def test_whole_year_coverage_includes_december(self):
        self.assertEqual((START, END), (dt.date(2026, 1, 1), dt.date(2027, 12, 31)))
        record = h.day_record(dt.date(2027, 12, 31), HOLIDAYS, START, END)
        self.assertIs(record["is_public_holiday"], False)

    def test_preserves_generic_and_special_labels(self):
        raw = export([("2019/1/1", "元日"), ("2019/4/30", "休日"),
                      ("2019/5/1", "休日（祝日扱い）"), ("2019/5/2", "休日"),
                      ("2019/10/22", "休日（祝日扱い）"), ("2019/11/23", "勤労感謝の日")])
        holidays, start, end = h.parse_csv(raw)
        self.assertEqual(h.day_record(dt.date(2019, 5, 1), holidays, start, end)["holiday_name_ja"], "休日（祝日扱い）")
        self.assertEqual(HOLIDAYS[dt.date(2026, 5, 6)], HOLIDAYS[dt.date(2026, 9, 22)])

    def test_rejects_bad_or_truncated_exports(self):
        cases = [b"<html>denied</html>", b"\xff", export([]), export(ROWS[:-1]),
                 export(ROWS + [ROWS[-1]]), export(list(reversed(ROWS))),
                 export([("2026/1/1", "元日"), ("2026/2/30", "x"), ("2026/11/23", "勤労感謝の日")]),
                 export([("2026/1/1", "元日"), ("2026/11/23", "")]),
                 export([("2026/1/1", "元日"), ("2028/1/1", "元日"), ("2028/11/23", "勤労感謝の日")])]
        for raw in cases:
            with self.subTest(raw=raw[:60]), self.assertRaises(h.HolidayError) as cm:
                h.parse_csv(raw)
            self.assertEqual(cm.exception.code, "source_schema_changed")


class QueryTests(unittest.TestCase):
    def query(self, start, end=None):
        return h.query(dt.date.fromisoformat(start), dt.date.fromisoformat(end or start), HOLIDAYS, START, END)

    def test_holiday_weekday_and_unlisted_weekend(self):
        monday = self.query("2026-11-23")["days"][0]
        self.assertEqual(monday["weekday_ja"], "月")
        self.assertIs(monday["is_weekend"], False)
        self.assertIs(monday["is_public_holiday"], True)
        self.assertEqual(monday["holiday_name_ja"], "勤労感謝の日")
        sunday = self.query("2026-11-22")["days"][0]
        self.assertIs(sunday["is_weekend"], True)
        self.assertIs(sunday["is_public_holiday"], False)
        self.assertIs(sunday["is_weekend_or_holiday"], True)

    def test_break_expands_beyond_query_and_does_not_bridge_leave(self):
        result = self.query("2026-11-23")
        self.assertEqual(result["consecutive_breaks"], [{"from": "2026-11-21", "to": "2026-11-23", "days": 3,
                          "includes_public_holiday": True, "boundary_complete": True}])
        self.assertEqual(self.query("2026-11-03")["consecutive_breaks"], [])
        self.assertIs(self.query("2026-11-02")["days"][0]["is_weekend_or_holiday"], False)

    def test_september_five_day_break_and_may_substitute(self):
        september = self.query("2026-09-18", "2026-09-24")
        self.assertEqual([(b["from"], b["to"], b["days"]) for b in september["consecutive_breaks"]],
                         [("2026-09-19", "2026-09-23", 5)])
        self.assertEqual(self.query("2026-05-06")["consecutive_breaks"][0]["from"], "2026-05-02")

    def test_ordinary_weekend_and_no_duplicate_blocks(self):
        result = self.query("2026-11-06", "2026-11-16")
        self.assertEqual(len(result["consecutive_breaks"]), 2)
        self.assertTrue(all(b["days"] == 2 and not b["includes_public_holiday"] for b in result["consecutive_breaks"]))

    def test_unpublished_year_is_unknown_not_false(self):
        result = self.query("2028-01-01", "2028-01-03")
        self.assertEqual(result["status"], "unavailable")
        self.assertTrue(all(d["is_public_holiday"] is None for d in result["days"]))
        self.assertIs(result["days"][0]["is_weekend_or_holiday"], True)
        self.assertIsNone(result["days"][-1]["is_weekend_or_holiday"])
        self.assertEqual(result["consecutive_breaks"], [])

    def test_partial_coverage_and_boundary_uncertainty(self):
        result = self.query("2025-12-31", "2026-01-02")
        self.assertEqual(result["status"], "partial")
        result = self.query("2027-01-01")
        self.assertEqual(result["consecutive_breaks"][0]["days"], 3)
        holidays = {dt.date(2026, 1, 1): "元日", dt.date(2026, 1, 2): "test"}
        result = h.query(START, START, holidays, START, END)
        self.assertIs(result["consecutive_breaks"][0]["boundary_complete"], False)

    def test_no_year_end_or_obon_closure_inferred(self):
        for day in ("2026-08-13", "2026-12-29", "2026-12-31"):
            with self.subTest(day=day):
                self.assertIs(self.query(day)["days"][0]["is_public_holiday"], False)


class ClientAndCliTests(unittest.TestCase):
    def response(self, raw=RAW, status=200, headers=None):
        response = Mock()
        response.status = status
        response.headers = headers or {"Content-Length": str(len(raw)), "Last-Modified": "test-date"}
        response.read.return_value = raw
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        return response

    def invoke(self, argv, raw=RAW):
        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(h.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = self.response(raw)
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = h.main(argv)
            return code, json.loads(stdout.getvalue()), factory.return_value.open

    def test_single_online_read_for_year_and_filtered_output(self):
        code, result, opened = self.invoke(["query", "--year", "2026", "--holidays-only"])
        self.assertEqual(code, 0)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["days"]), 10)
        self.assertEqual(result["usage"]["http_requests"], 1)
        self.assertEqual(result["usage"]["response_body_bytes"], len(RAW))
        self.assertEqual(result["source"]["coverage"]["to"], "2027-12-31")
        opened.assert_called_once()
        self.assertEqual(opened.call_args[0][0].full_url, h.SOURCE_URL)
        self.assertEqual(opened.call_args.kwargs["timeout"], 15)

    def test_empty_filtered_unknown_query_stays_unavailable(self):
        code, result, opened = self.invoke(["query", "--year", "2028", "--holidays-only"])
        self.assertEqual((code, result["status"], result["days"]), (0, "unavailable", []))

    def test_new_year_automatically_available(self):
        raw = export(ROWS + [("2028/1/1", "元日"), ("2028/11/23", "勤労感謝の日")])
        code, result, _ = self.invoke(["query", "--date", "2028-01-01"], raw)
        self.assertEqual((code, result["status"]), (0, "ok"))
        self.assertIs(result["days"][0]["is_public_holiday"], True)

    def test_doctor_never_constructs_client(self):
        with patch.object(h, "Client", side_effect=AssertionError("network")), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(h.main(["doctor"]), 0)
        self.assertIs(json.loads(out.getvalue())["network_checked"], False)

    def test_default_date_uses_jst_not_utc_or_host_timezone(self):
        args = Mock(year=None, start=None, end=None, date=None)
        start, end = h.date_range(args, Mock(), dt.datetime(2026, 11, 1, 16, 0, tzinfo=dt.timezone.utc))
        self.assertEqual((start, end), (dt.date(2026, 11, 2), dt.date(2026, 11, 2)))

    def test_leap_year_has_366_days(self):
        code, result, _ = self.invoke(["query", "--year", "2028"])
        self.assertEqual((code, len(result["days"])), (0, 366))

    def test_argument_errors_make_no_requests(self):
        cases = [["--date", "2026-02-30"], ["--date", "2026-1-1"],
                 ["--date", "2026-01-01", "--to", "2026-01-02"], ["--from", "2026-01-01"],
                 ["--to", "2026-01-01"], ["--year", "0000"],
                 ["--from", "2026-02-01", "--to", "2026-01-01"],
                 ["--from", "2026-01-01", "--to", "2027-01-02"],
                 ["--year", "2026", "--date", "2026-01-01"]]
        for argv in cases:
            with self.subTest(argv=argv), patch.object(h, "Client", side_effect=AssertionError("network")), \
                    contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as cm:
                h.main(["query"] + argv)
            self.assertEqual(cm.exception.code, 2)

    def test_network_error_is_structured_and_not_retried(self):
        for exc in (urllib.error.URLError("denied"), http.client.IncompleteRead(b"partial"),
                    http.client.BadStatusLine("oops"), TimeoutError()):
            with self.subTest(exc=type(exc).__name__), patch.object(h.urllib.request, "build_opener") as factory:
                factory.return_value.open.side_effect = exc
                with contextlib.redirect_stdout(io.StringIO()) as out:
                    code = h.main(["query", "--date", "2026-11-23"])
                result = json.loads(out.getvalue())
                self.assertEqual((code, result["error"]["code"]), (2, "network_error"))
                factory.return_value.open.assert_called_once()

    def test_http_error_and_schema_error_are_not_offline_fallbacks(self):
        with patch.object(h.urllib.request, "build_opener") as factory:
            factory.return_value.open.side_effect = urllib.error.HTTPError(h.SOURCE_URL, 503, "busy", {}, None)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                code = h.main(["query"])
            result = json.loads(out.getvalue())
            self.assertEqual((code, result["error"]["http_status"]), (2, 503))
        code, result, _ = self.invoke(["query"], b"<html>changed</html>")
        self.assertEqual((code, result["error"]["code"]), (2, "source_schema_changed"))

    def test_rejects_partial_status_size_mismatch_and_oversized_body(self):
        cases = [(self.response(status=206), "unexpected_status"),
                 (self.response(headers={"Content-Length": str(len(RAW) + 5)}), "incomplete_response"),
                 (self.response(raw=b"x" * (h.MAX_BYTES + 1)), "response_too_large")]
        for response, expected in cases:
            with self.subTest(expected=expected), patch.object(h.urllib.request, "build_opener") as factory:
                factory.return_value.open.return_value = response
                with self.assertRaises(h.HolidayError) as cm:
                    h.Client().fetch()
                self.assertEqual(cm.exception.code, expected)

    def test_redirect_and_second_read_rejected(self):
        with self.assertRaises(h.HolidayError) as cm:
            h.RejectRedirect().redirect_request(None, None, 302, "moved", {}, "https://example.com")
        self.assertEqual(cm.exception.code, "unexpected_redirect")
        with patch.object(h.urllib.request, "build_opener") as factory:
            factory.return_value.open.return_value = self.response()
            client = h.Client()
            client.fetch()
            with self.assertRaises(h.HolidayError) as cm:
                client.fetch()
            self.assertEqual(cm.exception.code, "request_budget_exhausted")
            factory.return_value.open.assert_called_once()


if __name__ == "__main__":
    unittest.main()
