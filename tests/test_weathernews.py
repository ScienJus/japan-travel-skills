import contextlib
import datetime as dt
import io
import json
import unittest
from unittest.mock import patch

from test_weather import w, payload as jma_payload

wn = w.weathernews


def search_rows():
    return [{"lat": 36.56114, "lon": 136.65654, "loc": "石川県金沢市", "q": "金沢市",
             "url": "/onebox/tenki/ishikawa/17201/?fm=onebox"}]


def forecast_payload():
    start = w.timestamp("2026-10-31T00:00:00+09:00")
    return {
        "is_japan": 1, "geo": {"JCODE": "17201", "lat": 36.56114, "lon": 136.65654},
        "mrf_attr": {"time": int(start.timestamp()), "stride": 86400},
        "mrf": [{"tm": int((start + dt.timedelta(days=i)).timestamp()), "WX": 203 if i % 2 else 101,
                 "MAXT": 19, "MINT": 0, "POP": 0 if i == 1 else 50,
                 "reliability": "E" if i >= 11 else ""} for i in range(15)],
    }


class WeathernewsTests(unittest.TestCase):
    def setUp(self):
        self.catalog = w.load_catalog()
        self.codes = wn.load_codes()
        self.city = w.resolve_city("金泽", self.catalog)
        self.location = wn.resolve_location(search_rows(), self.city)
        self.payload = forecast_payload()
        self.now = w.timestamp("2026-10-31T22:00:00+09:00")
        self.dates = [(self.now.date() + dt.timedelta(days=i)).isoformat() for i in range(1, 15)]

    def parse(self, dates=None):
        return wn.parse_forecast(self.payload, self.city, self.location, dates or self.dates, self.now, self.codes)

    def test_full_fourteen_future_dates(self):
        result = self.parse()
        self.assertEqual(result["status"], "ok")
        self.assertEqual(len(result["days"]), 14)
        self.assertEqual(result["days"][-1]["date"], "2026-11-14")
        self.assertEqual(result["days"][0]["temperature"]["min_c"], 0)
        self.assertEqual(result["days"][0]["precipitation"]["daily_percent"], 0)

    def test_start_timestamp_is_not_issue_time(self):
        result = self.parse()
        self.assertIsNone(result["issued_at"]["daily"])
        self.assertIsNone(result["days"][0]["weather"]["issued_at"])
        self.assertTrue(any("Sequence start time" in text for text in result["warnings"]))

    def test_code_labels_come_from_weathernews_table(self):
        self.assertEqual(self.parse()["days"][0]["weather"]["text_ja"], "くもり時々雨")
        self.assertEqual(self.parse()["days"][0]["weather"]["text_origin"], "publisher_code_table")
        self.assertEqual(self.codes["labels"]["600"], ["うすぐもり"])

    def test_reliability_scale_is_separate_from_jma(self):
        result = self.parse()
        self.assertIsNone(result["days"][0]["reliability"])
        self.assertEqual(result["days"][-1]["reliability"], "E")
        self.assertEqual(result["reliability_scale"]["source"], "weathernews")

    def test_missing_days_do_not_shift_values(self):
        del self.payload["mrf"][4]
        result = self.parse()
        self.assertEqual(result["status"], "partial")
        self.assertEqual(result["days"][3]["status"], "unavailable")
        self.assertEqual(result["days"][4]["date"], "2026-11-05")
        self.assertEqual(result["days"][4]["status"], "ok")

    def test_missing_fields_and_unknown_codes_stay_explicit(self):
        self.payload["mrf"][1].update({"WX": 777, "MINT": "", "POP": None})
        day = self.parse()["days"][0]
        self.assertEqual(day["status"], "partial")
        self.assertEqual(day["weather"]["code"], "777")
        self.assertIsNone(day["weather"]["text_ja"])
        self.assertIn("precipitation", day["missing_fields"])

    def test_nodata_code_is_not_a_forecast(self):
        self.payload["mrf"][1]["WX"] = 999
        self.assertIn("weather", self.parse()["days"][0]["missing_fields"])

    def test_outside_horizon_does_not_extend_prediction(self):
        self.assertEqual(self.parse(["2026-12-01"])["status"], "unavailable")

    def test_wrong_municipality_or_coordinates_rejected(self):
        self.payload["geo"]["JCODE"] = "17202"
        with self.assertRaises(w.WeatherError):
            self.parse()
        self.payload["geo"]["JCODE"] = "17201"
        self.payload["geo"]["lat"] = 35
        with self.assertRaises(w.WeatherError):
            self.parse()

    def test_designated_city_point_can_belong_to_explicit_native_ward(self):
        city = w.resolve_city("大阪", self.catalog)
        rows = [dict(search_rows()[0], loc="大阪市", url="/onebox/tenki/osaka/27100/"),
                dict(search_rows()[0], loc="大阪市北区", url="/onebox/tenki/osaka/27127/")]
        location = wn.resolve_location(rows, city)
        data = forecast_payload()
        data["geo"]["JCODE"] = "27127"
        result = wn.parse_forecast(data, city, location, self.dates, self.now, self.codes)
        self.assertEqual(result["location"]["jcode"], "27100")
        self.assertEqual(result["location"]["point_jcode"], "27127")
        self.assertNotIn("_point_jcodes", result["location"])

    def test_city_codes_without_00_suffix_accept_only_explicit_native_wards(self):
        for name, prefecture, city_code, ward_name, ward_code in (
                ("福岡市", "fukuoka", "40130", "福岡市中央区", "40133"),
                ("川崎市", "kanagawa", "14130", "川崎市川崎区", "14131"),
                ("浜松市南部", "shizuoka", "22130", "浜松市中央区", "22138"),
                ("堺市", "osaka", "27140", "堺市堺区", "27141")):
            with self.subTest(city=name):
                city = w.resolve_city(name, self.catalog)
                rows = [dict(search_rows()[0], loc=wn.municipality_query(city), url="/onebox/tenki/{}/{}/".format(prefecture, city_code)),
                        dict(search_rows()[0], loc=ward_name, url="/onebox/tenki/{}/{}/".format(prefecture, ward_code))]
                location = wn.resolve_location(rows, city)
                data = forecast_payload()
                data["geo"]["JCODE"] = ward_code
                result = wn.parse_forecast(data, city, location, self.dates, self.now, self.codes)
                self.assertEqual(result["location"]["jcode"], city_code)
                self.assertEqual(result["location"]["point_jcode"], ward_code)
                # The same ward code is rejected without a native search relationship.
                location = wn.resolve_location(rows[:1], city)
                with self.assertRaises(w.WeatherError):
                    wn.parse_forecast(data, city, location, self.dates, self.now, self.codes)

    def test_ward_relationship_must_retain_native_city_and_prefecture(self):
        city = w.resolve_city("福岡市", self.catalog)
        parent = dict(search_rows()[0], loc="福岡市", url="/onebox/tenki/fukuoka/40130/")
        for name, url, point_code in (
                ("別の市中央区", "/onebox/tenki/fukuoka/40133/", "40133"),
                ("福岡市中央区", "/onebox/tenki/fukuoka/14131/", "14131"),
                ("福岡市中央区", "/onebox/tenki/kanagawa/40133/", "40133"),
                ("福岡市中央区", "https://evil.example/onebox/tenki/fukuoka/40133/", "40133")):
            with self.subTest(name=name, url=url):
                location = wn.resolve_location([parent, dict(parent, loc=name, url=url)], city)
                data = forecast_payload()
                data["geo"]["JCODE"] = point_code
                with self.assertRaises(w.WeatherError):
                    wn.parse_forecast(data, city, location, self.dates, self.now, self.codes)

    def test_nearby_city_is_not_treated_as_a_ward(self):
        city = w.resolve_city("大阪", self.catalog)
        rows = [dict(search_rows()[0], loc="大阪市", url="/onebox/tenki/osaka/27100/"),
                dict(search_rows()[0], loc="東大阪市", url="/onebox/tenki/osaka/27227/")]
        location = wn.resolve_location(rows, city)
        data = forecast_payload()
        data["geo"]["JCODE"] = "27227"
        with self.assertRaises(w.WeatherError):
            wn.parse_forecast(data, city, location, self.dates, self.now, self.codes)

    def test_duplicate_dates_rejected(self):
        self.payload["mrf"].append(dict(self.payload["mrf"][0]))
        with self.assertRaises(w.WeatherError):
            self.parse()

    def test_invalid_probability_and_temperature_sentinels_rejected(self):
        for key, value in (("POP", 999), ("MINT", -999), ("MAXT", 999), ("reliability", "F")):
            data = forecast_payload()
            data["mrf"][1][key] = value
            with self.assertRaises(w.WeatherError):
                wn.parse_forecast(data, self.city, self.location, self.dates, self.now, self.codes)

    def test_search_filters_by_municipality_code_not_name_only(self):
        bad = dict(search_rows()[0], url="/onebox/tenki/tokyo/13101/")
        result = wn.resolve_location([bad] + search_rows(), self.city)
        self.assertEqual(result["jcode"], "17201")
        self.assertNotIn("?", result["url"])

    def test_foreign_or_ambiguous_search_urls_not_followed(self):
        for url in ("https://evil.example/onebox/tenki/ishikawa/17201/", "http://weathernews.jp/onebox/tenki/ishikawa/17201/", "/onebox/tenki/ishikawa/17202/"):
            with self.assertRaises(w.WeatherError):
                wn.resolve_location([dict(search_rows()[0], url=url)], self.city)
        with self.assertRaises(w.WeatherError):
            wn.resolve_location(search_rows() + [dict(search_rows()[0], lat=36.7)], self.city)

    def test_subdivision_lookup_uses_municipality_name(self):
        for query, expected in (("富山", "富山市"), ("奈良", "奈良市"), ("四日市市", "四日市市")):
            self.assertEqual(wn.municipality_query(w.resolve_city(query, self.catalog)), expected)

    def test_compact_format_preserves_point_provenance(self):
        result = w.compact_forecast(self.parse())
        self.assertEqual(result["field_sources"]["temperature_daily"]["point"]["jcode"], "17201")
        self.assertIsNone(result["field_sources"]["weather_daily"]["issued_at"])

    def test_code_table_parser_reads_only_table_rows(self):
        parser = wn.IconLegendParser()
        parser.feed('<script>203=wrong</script><table><tr><td>203</td><td>くもり時々雨</td><td><img alt="other"></td></tr></table>')
        self.assertEqual(parser.labels, {"203": ["くもり時々雨"]})

    def test_default_source_and_two_week_limit(self):
        args = w.parser().parse_args(["forecast", "--city", "金泽"])
        self.assertEqual(args.source, "weathernews")
        self.assertEqual(len(w.requested_dates(args, self.now)), 14)
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            w.parser().parse_args(["forecast", "--city", "金泽", "--days", "15"])

    def test_cli_can_return_separate_sources_without_filling_jma_gaps(self):
        def read(url):
            if "api_search.cgi" in url:
                return search_rows()
            if "www.jma.go.jp" in url:
                return jma_payload()
            return self.payload
        with patch.object(w.Client, "get_json", side_effect=read), patch.object(w, "now_jst", return_value=self.now), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(w.main(["forecast", "--city", "金泽", "--source", "both"]), 0)
        result = json.loads(out.getvalue())
        self.assertEqual([f["source"]["id"] for f in result["forecasts"]], ["weathernews", "jma"])
        self.assertEqual(result["forecasts"][0]["days"][-1]["status"], "ok")
        self.assertEqual(result["forecasts"][1]["days"][-1]["status"], "unavailable")

    def test_out_of_range_source_timestamp_is_a_structured_schema_error(self):
        self.payload['mrf'][0]['tm'] = 10**100
        with patch.object(w.Client, 'get_json', side_effect=[search_rows(), self.payload]), \
                patch.object(w, 'now_jst', return_value=self.now), contextlib.redirect_stdout(io.StringIO()) as out:
            self.assertEqual(w.main(['forecast', '--city', '金泽', '--days', '1']), 2)
        value = json.loads(out.getvalue())
        self.assertEqual(value['error']['code'], 'source_schema_changed')


if __name__ == "__main__":
    unittest.main()
