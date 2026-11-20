"""Offline Hot Pepper contracts, using invented shop and course records."""
import argparse
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "skills/hot-pepper/scripts"))
from hotpepper_client import cli, pages
from hotpepper_client.source import BASE, Client, SourceError

SHOP = "J000000001"
PROFILE = f"{BASE}/str{SHOP}/"


def document(body, url=PROFILE):
    html = f'<html><head><link rel="canonical" href="{url}"></head><body>{body}</body></html>'
    return html.encode("utf-8")


def card(shop_id):
    return (f'<div class="shopDetailText"><h3 class="shopDetailStoreName">'
            f'<a href="/str{shop_id}/">店 {shop_id}</a></h3>'
            '<span class="dinnerBudget">3001～4000円</span></div>')


class HotPepperTests(unittest.TestCase):
    def test_list_preserves_order_skips_repeated_cards_and_limits_output(self):
        url = BASE + "/SA63/Y841/X841/"
        body = document(card(SHOP) * 2 + card("J000000002"), url)
        output = StringIO()
        with patch.object(Client, "read", autospec=True, return_value=body) as get, redirect_stdout(output):
            self.assertEqual(cli.main(["list", url, "--limit", "1"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["data"]["unique_on_page"], 2)
        self.assertEqual([item["shop_id"] for item in result["data"]["shops"]], [SHOP])
        self.assertIsNone(result["data"]["shops"][0]["lunch_budget"])
        self.assertEqual(result["source"]["url"], url)
        self.assertEqual(get.call_args.args[1], url)
        self.assertEqual(get.call_count, 1)

    def test_navigate_and_filter_only_direct_child_areas(self):
        for parent, child in (("/", "SA11/"), ("/SA11/", "Y055/"), ("/SA11/Y055/", "X150/")):
            url = BASE + parent
            body = (f'<a href="{parent}{child}">例の場所</a>' * 2
                    + '<a href="https://example.test/SA01/">別の場所</a>')
            soup = pages.page(document(body, url), url)
            result = pages.listing(soup, url, 5, "例")
            self.assertEqual(result["kind"], "areas")
            self.assertEqual(result["unique_on_page"], 1)
            self.assertEqual(result["areas"], [{"name": "例の場所", "url": url + child}])
            self.assertEqual(pages.listing(soup, url, 5, "未掲載")["matched_on_page"], 0)

    def test_restrict_input_redirects_and_canonical_identity(self):
        for value in (BASE + ".example/SA63/", "/CSP/", "/SA63/?q=x", "/SA63/../"):
            with self.subTest(value=value), self.assertRaises(argparse.ArgumentTypeError):
                cli.area_url(value)
        with self.assertRaises(SourceError):
            Client().read(PROFILE + "reserve/")
        with self.assertRaises(SourceError):
            pages.page(document("unrelated page", url=BASE), PROFILE)
        with self.assertRaises(SourceError):
            pages.listing(pages.page(document("<p>missing listing</p>"), PROFILE), PROFILE, 1)

    def test_calendar_uses_exact_month_and_published_legend(self):
        def calendar(month, mark):
            return (f'<table summary="ネット予約の空席状況" data-calendar="{month}"><tr><td>'
                    f'<p class="date">2</p><span class="status">{mark}</span></td></tr></table>')

        body = ('<table class="infoTable"><tr><th>店名</th><td>例</td></tr></table>'
                + calendar("203012", "□") + calendar("203011", "◎")
                + '<ul class="calendarIcnDescription"><li><span>□</span>：リクエスト予約可</li></ul>')
        soup = pages.page(document(body), PROFILE)
        data = pages.details(soup, SHOP, date(2030, 12, 2))
        self.assertEqual(data["calendar"]["label"], "リクエスト予約可")
        self.assertEqual(data["calendar"]["state"], "published")
        self.assertIsNone(data["details"]["定休日"])
        for day in (date(2030, 12, 3), date(2031, 12, 2), date(2030, 11, 2)):
            self.assertEqual(pages.calendar_hint(soup, day)["state"], "unknown")
        duplicate = pages.page(document(body + calendar("203012", "休")), PROFILE)
        self.assertEqual(pages.calendar_hint(duplicate, date(2030, 12, 2))["state"], "unknown")

    def test_courses_keep_conditions_and_reject_cross_shop_links(self):
        body = ('<ul class="courseList"><li><h3 class="courseCassetteTitle">'
                '<a href="course_cnod1/">テスト</a></h3><p class="coursePrice">5,000円（税込）</p>'
                '<ul class="summaryList"><li>利用人数：2名～</li></ul>'
                '<div class="courseCassetteReserveLimit">前日まで ※曜日による</div></li></ul>')
        soup = pages.page(document(body), PROFILE)
        course, = pages.courses(soup, SHOP, 5)["courses"]
        self.assertEqual(course["published_conditions"], ["利用人数：2名～"])
        self.assertEqual(course["price"], "5,000円（税込）")
        self.assertIn("曜日", course["deadline"])
        self.assertEqual(course["url"], PROFILE + "course_cnod1/")
        for invalid in (body.replace('href="course_', 'href="/strJ000000002/course_'), "<p>layout changed</p>"):
            with self.assertRaises(SourceError):
                pages.courses(pages.page(document(invalid), PROFILE), SHOP, 5)

    def test_failure_is_reported_with_source_and_without_alternate_reads(self):
        output = StringIO()
        with patch.object(Client, "read", side_effect=SourceError("http_error", "Denied", http_status=403)) as read:
            with redirect_stdout(output):
                self.assertEqual(cli.main(["detail", PROFILE]), 1)
        read.assert_called_once_with(PROFILE)
        result = json.loads(output.getvalue())
        self.assertEqual(result["error"]["http_status"], 403)
        self.assertEqual(result["source"]["url"], PROFILE)

    def test_slot_stock_requires_date_party_time_shop_and_course_evidence(self):
        echo = '<input id="returnUrl" value="/strJ000000001/course/rpn2/?RDT=20301202&amp;RTM=1830">'
        href = PROFILE + "yoyaku/reserve/20301202_1830_rpn2_cnod1_rsi123/"
        available = (f'<div class="reserveSeatListWrap"><ul class="reserveSeatList"><li>'
                     f'<span class="seatTypeName">カウンター</span><div class="reservationBtnWrap">'
                     f'<a class="reservationBtn" href="{href}">予約する</a></div></li></ul></div>')
        empty = ('<div class="reserveSearchResultNone"><p class="seatListNotFoundTitle">'
                 'ご指定の条件でご予約できるお席が見つかりませんでした。</p></div>')

        def read(html):
            return pages.seats(html.encode(), SHOP, "d1", date(2030, 12, 2), "18:30", 2)

        self.assertEqual(read(echo + available)["seat_types"], ["カウンター"])
        self.assertEqual(read(echo + empty)["state"], "no_matching_seats")
        for body in (available, echo + available + empty, echo + available.replace("cnod1", "cnod2"),
                     echo.replace("rpn2", "rpn3") + empty, echo.replace("20301202", "20301203") + available,
                     echo.replace("1830", "1900") + empty, echo + "<p>◎</p>"):
            with self.subTest(body=body), self.assertRaises(SourceError):
                read(body)

    def test_slots_cli_uses_only_the_readonly_stock_endpoint(self):
        output = StringIO()
        with patch.object(Client, "read", side_effect=SourceError("http_error", "Unavailable")) as read:
            with redirect_stdout(output):
                code = cli.main(["slots", SHOP, "--course", "d1", "--date", "2030-12-02",
                                 "--time", "18:30", "--people", "2"])
        self.assertEqual(code, 1)
        read.assert_called_once_with(BASE + "/CSP/imrCourseCalendar/ajaxCourseFullDateStock"
                                     "?SP=J000000001&RDT=20301202&CN=d1&CB=&RTM=1830&RPN=2")
        self.assertEqual(json.loads(output.getvalue())["source"]["url"], PROFILE + "course_cnod1/?RDT=20301202")
