"""Synthetic source fixtures cover the public CLI and its viewpoint-specific rules."""
import contextlib
import datetime as dt
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/japan-scenic-forecast/scripts"))
import scenic


NOW = dt.datetime(2026, 12, 28, 12, 30, tzinfo=scenic.JST)


def panel(start, icons, scope="富山市内からの立山の眺望の良さを確率で表現しています。"):
    cells = []
    for i, icon in enumerate(icons):
        date = start + dt.timedelta(days=i)
        label = f"{date.month}/{date.day}<font>({'月火水木金土日'[date.weekday()]})</font>"
        cells.append(f'<td><table><tr><td>{label}</td></tr></table><img src="{icon}"></td>')
    return (f'<img alt="立山眺望予報" src="img/view_title.gif"><table><tr>'
            + "".join(cells) + f'<td>{scope}</td></tr></table>').encode("cp932")


def cloud_data(samples):
    return json.dumps({"SUCCESS": True, "MRF": [{"INDEX": 100}],
                       "SRF": [{"TSTR": t, "INDEX": p} for t, p in samples]}).encode()


def run_cli(arguments, raw):
    with patch.object(scenic.Client, "read", return_value=raw) as read, \
            patch.object(scenic, "now_jst", return_value=NOW), contextlib.redirect_stdout(io.StringIO()) as out:
        code = scenic.main(arguments)
    return code, json.loads(out.getvalue()), read


class ScenicForecastTests(unittest.TestCase):
    def test_toyama_city_daily_cards_cross_new_year(self):
        icons = ["img/winter/winter0.gif", "img/summer/summer100.gif", "img/new/icon10.gif",
                 *(["img/winter/winter20.gif"] * 4)]
        raw = panel(NOW.date() + dt.timedelta(days=1), icons)
        rc, report, read = run_cli(["tateyama", "--date", "2026-12-29", "--date", "2026-12-30",
                                    "--date", "2026-12-31", "--date", "2027-01-01", "--date", "2027-01-15"], raw)
        self.assertEqual(rc, 0)
        read.assert_called_once_with(scenic.TATEYAMA)
        self.assertEqual(report["status"], "partial")
        self.assertEqual(report["published_range"], ["2026-12-29", "2027-01-04"])
        self.assertEqual([r["probability_percent"] for r in report["records"]], [0, 100, None, 20, None])
        self.assertEqual(report["records"][2]["reason"], "unrecognized_icon")
        self.assertEqual(report["records"][-1]["status"], "unavailable")
        self.assertIsNone(report["issued_at"])

    def test_wrong_scope_bad_card_order_or_stale_panel_fail_closed(self):
        icons = ["img/winter/winter20.gif"] * 7
        raw = panel(NOW.date(), icons)
        for body in (panel(NOW.date(), icons, scope="other city"), panel(NOW.date(), icons[:6]),
                     panel(NOW.date() - dt.timedelta(days=2), icons),
                     raw.replace(b'12/29', b'12/28'), raw.replace(b'12/28', b'12/30', 1)):
            with self.subTest(body=body[:12]):
                rc, report, _ = run_cli(["tateyama"], body)
                self.assertEqual((rc, report["state"], report["records"]), (2, "unknown", []))

    def test_three_hour_filter_preserves_zero_sentinel_and_gaps(self):
        raw = cloud_data([("2026-12-29.06:00:00", 0), ("2026-12-29.12:00:00", -9999),
                          ("2026-12-29.15:00:00", 61)])
        rc, report, read = run_cli(["twin-terrace", "--date", "2026-12-29", "--hour", "6",
                                    "--hour", "9", "--hour", "12", "--hour", "15"], raw)
        self.assertEqual(rc, 0)
        read.assert_called_once_with(scenic.TERRACE_DATA)
        self.assertEqual([r["probability_percent"] for r in report["records"]], [0, None, None, 61])
        self.assertEqual([r.get("reason") for r in report["records"]], [None, "unpublished_slot", "publisher_missing", None])
        self.assertTrue(report["records"][0]["time"].endswith("06:00:00+09:00"))

    def test_elapsed_stale_empty_and_invalid_terrace_rows(self):
        rows = [("2026-12-28.12:00:00", 66), ("2026-12-28.15:00:00", 21)]
        rc, report, _ = run_cli(["twin-terrace"], cloud_data(rows))
        self.assertEqual((rc, len(report["records"]), report["records"][0]["probability_percent"]), (0, 1, 21))
        rc, report, _ = run_cli(["twin-terrace", "--date", "2026-12-28", "--hour", "12"], cloud_data(rows))
        self.assertEqual(report["records"][0]["reason"], "elapsed")
        rc, report, _ = run_cli(["twin-terrace"], cloud_data([]))
        self.assertEqual((rc, report["status"]), (0, "unavailable"))
        for sample in ([rows[0]], [rows[1], rows[1]], [("2026-12-28.16:00:00", 2)],
                       [(rows[1][0], True)], [(rows[1][0], 101)]):
            rc, report, _ = run_cli(["twin-terrace"], cloud_data(sample))
            self.assertEqual((rc, report["state"]), (2, "unknown"))
        rc, report, read = run_cli(["twin-terrace", "--hour", "6"], b"")
        self.assertEqual((rc, report["error"]["code"]), (2, "invalid_options"))
        read.assert_not_called()
