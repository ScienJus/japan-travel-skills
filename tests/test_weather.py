import contextlib
import importlib.util
import io
import json
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("weather", ROOT / "skills/japan-weather/scripts/weather.py")
w = importlib.util.module_from_spec(spec)
spec.loader.exec_module(w)


def payload():
    # Synthetic, source-shaped data: different dates/regions/stations by field.
    return [
        {"publishingOffice": "金沢地方気象台", "reportDatetime": "2026-10-31T17:00:00+09:00", "timeSeries": [
            {"timeDefines": ["2026-10-31T17:00:00+09:00", "2026-11-01T00:00:00+09:00", "2026-11-02T00:00:00+09:00"],
             "areas": [{"area": {"code": "170010", "name": "加賀"}, "weatherCodes": ["100", "200", "203"], "weathers": ["晴れ", "くもり", "くもり時々雨"]},
                       {"area": {"code": "170020", "name": "能登"}, "weatherCodes": ["300", "300", "300"], "weathers": ["雨", "雨", "雨"]}]},
            {"timeDefines": ["2026-10-31T18:00:00+09:00", "2026-11-01T00:00:00+09:00", "2026-11-01T06:00:00+09:00", "2026-11-01T12:00:00+09:00", "2026-11-01T18:00:00+09:00"],
             "areas": [{"area": {"code": "170010", "name": "加賀"}, "pops": ["30", "0", "10", "20", "40"]}]},
            {"timeDefines": ["2026-11-01T00:00:00+09:00", "2026-11-01T09:00:00+09:00"],
             "areas": [{"area": {"code": "56227", "name": "金沢"}, "temps": ["0", "19"]},
                       {"area": {"code": "56052", "name": "輪島"}, "temps": ["-2", "15"]}]},
        ]},
        {"publishingOffice": "金沢地方気象台", "reportDatetime": "2026-10-31T11:00:00+09:00", "timeSeries": [
            {"timeDefines": ["2026-11-01T00:00:00+09:00", "2026-11-02T00:00:00+09:00", "2026-11-03T00:00:00+09:00"],
             "areas": [{"area": {"code": "170000", "name": "石川県"}, "weatherCodes": ["200", "203", "100"], "pops": ["", "80", "0"], "reliabilities": ["", "", "A"]}]},
            {"timeDefines": ["2026-11-01T00:00:00+09:00", "2026-11-02T00:00:00+09:00", "2026-11-03T00:00:00+09:00"],
             "areas": [{"area": {"code": "56227", "name": "金沢"}, "tempsMin": ["", "14", "-2"], "tempsMax": ["", "18", "12"],
                        "tempsMinLower": ["", "13", "-4"], "tempsMinUpper": ["", "15", "0"], "tempsMaxLower": ["", "16", "10"], "tempsMaxUpper": ["", "20", "14"]}]},
        ]},
    ]


class WeatherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = w.load_catalog()

    def setUp(self):
        self.now = w.timestamp("2026-10-31T20:00:00+09:00")
        self.city = w.resolve_city("金泽", self.catalog)
        self.source = payload()
        self.dates = ["2026-11-01", "2026-11-02", "2026-11-03"]

    def merge(self, source=None, city=None, dates=None, now=None, catalog=None):
        return w.merge_forecast(source or self.source, city or self.city, catalog or self.catalog, dates or self.dates, now or self.now)

    def test_catalog_ancestry_for_every_municipality(self):
        for code in self.catalog["areas"]["class20s"]:
            self.assertIn(w.city_info(code, self.catalog)["office_code"], self.catalog["areas"]["offices"])

    def test_every_alias_resolves_to_existing_municipality(self):
        for alias, code in w.ALIASES.items():
            self.assertEqual(w.resolve_city(alias, self.catalog)["code"], code)

    def test_japanese_english_and_code_resolve_without_network(self):
        for query in ("金沢市", "金沢", "Kanazawa", "kanazawa city", "1720100", "かなざわし"):
            self.assertEqual(w.resolve_city(query, self.catalog)["code"], "1720100")

    def test_ambiguous_city_does_not_choose_a_prefecture(self):
        with self.assertRaises(w.WeatherError) as caught:
            w.resolve_city("府中市", self.catalog)
        self.assertEqual(caught.exception.code, "ambiguous_city")
        self.assertEqual(len(caught.exception.details["candidates"]), 2)
        self.assertEqual(w.resolve_city("府中市", self.catalog, "130000")["code"], "1320600")

    def test_unknown_city_and_substring_never_substituted(self):
        for query in ("London", "Kanazaw"):
            with self.assertRaises(w.WeatherError):
                w.resolve_city(query, self.catalog)

    def test_combined_product_routing(self):
        self.assertEqual(w.resolve_city("帯広市", self.catalog)["product_code"], "014100")
        self.assertEqual(w.resolve_city("奄美市", self.catalog)["product_code"], "460100")

    def test_joins_by_actual_date_and_preserves_field_sources(self):
        result = self.merge()
        tomorrow, next_day, later = result["days"]
        self.assertEqual(tomorrow["temperature"]["max_c"], 19)
        self.assertEqual(next_day["temperature"]["max_c"], 18)
        self.assertEqual(next_day["weather"]["kind"], "short_range")
        self.assertEqual(next_day["precipitation"]["kind"], "weekly")
        self.assertEqual(later["weather"]["area"]["code"], "170000")
        self.assertEqual(later["reliability"], "A")

    def test_zero_negative_and_blank_values(self):
        tomorrow, _, later = self.merge()["days"]
        self.assertEqual(tomorrow["temperature"]["min_c"], 0)
        self.assertEqual(tomorrow["precipitation"]["periods"][0]["percent"], 0)
        self.assertIsNone(tomorrow["precipitation"]["daily_percent"])
        self.assertEqual(later["temperature"]["min_c"], -2)
        self.assertEqual(later["precipitation"]["daily_percent"], 0)

    def test_six_hour_probabilities_do_not_become_daily_probability(self):
        pop = self.merge()["days"][0]["precipitation"]
        self.assertIsNone(pop["daily_percent"])
        self.assertEqual(len(pop["periods"]), 4)
        self.assertEqual(pop["periods"][-1]["end"], "2026-11-02T00:00:00+09:00")

    def test_regional_station_is_not_relabelled_as_requested_city(self):
        result = self.merge(city=w.resolve_city("輪島市", self.catalog))
        self.assertEqual(result["days"][0]["weather"]["area"]["name"], "能登")
        self.assertEqual(result["days"][0]["temperature"]["station"]["name"], "輪島")
        self.assertEqual(result["days"][1]["temperature"]["station"]["name"], "金沢")

    def test_outside_horizon_remains_unavailable(self):
        result = self.merge(dates=["2026-12-01"])
        self.assertEqual(result["status"], "unavailable")
        self.assertIsNone(result["days"][0]["weather"])

    def test_mixed_coverage_is_partial(self):
        result = self.merge(dates=["2026-11-01", "2026-12-01"])
        self.assertEqual(result["status"], "partial")

    def test_missing_temperature_stays_null(self):
        self.source[1]["timeSeries"][1]["areas"][0]["tempsMin"][2] = ""
        result = self.merge()["days"][2]
        self.assertEqual(result["status"], "partial")
        self.assertIn("temperature.min_c", result["missing_fields"])

    def test_morning_temperature_slots_and_today(self):
        temp = self.source[0]["timeSeries"][2]
        temp["timeDefines"] = ["2026-10-31T09:00:00+09:00", "2026-10-31T09:00:00+09:00", "2026-11-01T00:00:00+09:00", "2026-11-01T09:00:00+09:00"]
        temp["areas"][0]["temps"] = ["20", "20", "12", "19"]
        result = self.merge(dates=["2026-10-31", "2026-11-01"])
        self.assertIsNone(result["days"][0]["temperature"]["min_c"])
        self.assertEqual(result["days"][0]["temperature"]["max_c"], 20)
        self.assertEqual(result["days"][1]["temperature"]["min_c"], 12)

    def test_stale_and_future_products_have_explicit_warnings(self):
        stale = self.merge(now=w.timestamp("2026-11-03T12:00:00+09:00"))
        self.assertTrue(any("36 hours" in x for x in stale["warnings"]))
        future = self.merge(now=w.timestamp("2026-10-31T08:00:00+09:00"))
        self.assertTrue(any("ahead" in x for x in future["warnings"]))

    def test_unknown_code_preserves_number(self):
        self.source[1]["timeSeries"][0]["areas"][0]["weatherCodes"][2] = "999"
        result = self.merge()
        self.assertEqual(result["days"][2]["weather"]["code"], "999")
        self.assertIsNone(result["days"][2]["weather"]["text_ja"])
        self.assertTrue(any("999" in x for x in result["warnings"]))
        self.assertEqual(w.compact_forecast(result)["days"][2]["weather_code"], "999")

    def test_seasonal_mapping_matches_actual_product_not_list_order(self):
        catalog = json.loads(json.dumps(self.catalog))
        catalog["week_area_codes"]["170010"] = ["170000", "170100"]
        catalog["week_areas"]["170000"].append({"srf": "170010", "week": "170100", "amedas": "56227"})
        self.source[1]["timeSeries"][0]["areas"][0]["area"]["code"] = "170100"
        result = self.merge(catalog=catalog)
        self.assertEqual(result["days"][2]["weather"]["area"]["code"], "170100")

    def test_unmapped_weekly_region_fails_explicitly(self):
        self.source[1]["timeSeries"][0]["areas"][0]["area"]["code"] = "999999"
        with self.assertRaises(w.WeatherError) as caught:
            self.merge()
        self.assertEqual(caught.exception.code, "unsupported_forecast_mapping")

    def test_compact_output_retains_provenance_and_midnight_boundary(self):
        result = w.compact_forecast(self.merge())
        day = result["days"][0]
        self.assertEqual(day["precipitation_6h"][-1]["hours"], "18:00-24:00")
        self.assertEqual(result["field_sources"][day["sources"]["temperature"]]["station"]["code"], "56227")
        self.assertEqual(day["temperature_c"], [0, 19])

    def test_default_dates_use_japan_timezone(self):
        args = w.parser().parse_args(["forecast", "--city", "金沢"])
        now = w.timestamp("2026-10-31T16:30:00+00:00")
        self.assertEqual(w.requested_dates(args, now)[0], "2026-11-02")

    def test_date_filters_and_past_date_rejection(self):
        for opts in (["--date", "2026-12-01"], ["--from", "2026-12-01", "--to", "2026-12-02"]):
            args = w.parser().parse_args(["forecast", "--city", "金沢"] + opts)
            self.assertEqual(w.requested_dates(args, self.now)[0], "2026-12-01")
        args = w.parser().parse_args(["forecast", "--city", "金沢", "--date", "2026-10-30"])
        with self.assertRaises(w.WeatherError):
            w.requested_dates(args, self.now)

    def test_network_requests_reused_within_invocation(self):
        raw = json.dumps(self.source).encode("utf-8")
        client = w.Client()
        with patch.object(client.opener, "open") as get:
            get.return_value.__enter__.return_value.status = 200
            get.return_value.__enter__.return_value.headers = {}
            get.return_value.__enter__.return_value.read.return_value = raw
            self.assertEqual(client.get("170000"), client.get("170000"))
            self.assertEqual(get.call_count, 1)
            self.assertEqual(client.requests, 1)
            self.assertEqual(client.cache_hits, 1)

    def test_throttling_is_one_attempt_without_retry(self):
        error = w.urllib.error.HTTPError("https://www.jma.go.jp/", 429, "Too Many Requests", {}, None)
        client = w.Client()
        with patch.object(client.opener, "open", side_effect=error) as get:
            with self.assertRaises(w.WeatherError) as caught:
                client.get("170000")
            self.assertEqual(caught.exception.code, "http_error")
            self.assertEqual(get.call_count, 1)

    def test_oversized_response_rejected(self):
        client = w.Client()
        with patch.object(client.opener, "open") as get:
            get.return_value.__enter__.return_value.status = 200
            get.return_value.__enter__.return_value.headers = {}
            get.return_value.__enter__.return_value.read.return_value = b" " * (w.MAX_BYTES + 1)
            with self.assertRaises(w.WeatherError) as caught:
                client.get("170000")
            self.assertEqual(caught.exception.code, "response_too_large")

    def test_doctor_and_lookup_are_offline(self):
        for args in (["doctor"], ["cities", "金泽"]):
            with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network access")), contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(w.main(args), 0)
                self.assertEqual(json.loads(out.getvalue())["usage"]["http_requests"], 0)

    def test_bad_city_rejected_before_any_forecast_read(self):
        with patch("urllib.request.OpenerDirector.open", side_effect=AssertionError("Network access")), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(w.main(["forecast", "--city", "金泽", "--city", "London"]), 2)
            self.assertEqual(json.loads(out.getvalue())["error"]["code"], "unknown_city")


if __name__ == "__main__":
    unittest.main()
