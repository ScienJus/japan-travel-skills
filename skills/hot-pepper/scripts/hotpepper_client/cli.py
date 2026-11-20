"""Hot Pepper Gourmet read-only CLI."""
import argparse
import datetime as dt
import json
import re
import sys
from importlib.metadata import version

from . import pages
from .source import AREA, BASE, COURSE_ID, SHOP_ID, STOCK, Client, SourceError


def area_url(value):
    path = value.removeprefix(BASE)
    if path != "/" and not re.fullmatch(AREA, path):
        raise argparse.ArgumentTypeError("Use a published Hot Pepper /SA…/ area directory URL or path.")
    return BASE + path


def restaurant(value):
    match = re.fullmatch(re.escape(BASE) + rf"/str({SHOP_ID})/", value)
    if match:
        return match[1]
    if re.fullmatch(SHOP_ID, value):
        return value
    raise argparse.ArgumentTypeError("Use a shop ID (J plus nine digits) or its canonical shop URL.")


def main(argv=None):
    if sys.version_info < (3, 11, 5):
        raise SystemExit("Hot Pepper Gourmet requires Python >=3.11.5.")
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Check local dependencies offline")
    listing = sub.add_parser("list", help="List restaurants on one public area directory page")
    listing.add_argument("area", type=area_url)
    listing.add_argument("--match", help="Substring of the published area or shop name on this page")
    detail = sub.add_parser("detail", help="Read practical details and an optional date marker")
    detail.add_argument("shop", type=restaurant)
    detail.add_argument("--date", type=dt.date.fromisoformat, help="Calendar date in Japan (YYYY-MM-DD)")
    courses = sub.add_parser("courses", help="Read listed course prices and conditions")
    courses.add_argument("shop", type=restaurant)
    slots = sub.add_parser("slots", help="Verify seats for one published course, date, time and party")
    slots.add_argument("shop", type=restaurant)
    slots.add_argument("--course", required=True, help="Published ID from courses, including seat-only offers")
    slots.add_argument("--date", type=dt.date.fromisoformat, required=True)
    slots.add_argument("--time", required=True, help="Local arrival time HH:MM (00:00–23:59)")
    slots.add_argument("--people", type=int, choices=range(1, 1000), metavar="1..999", required=True)
    for p in (listing, courses):
        p.add_argument("--limit", type=int, choices=range(1, 21), default=5, metavar="1..20")
    args = parser.parse_args(argv)
    client = Client()
    result = {"status": "ok", "source": {"name": "ホットペッパーグルメ"}}
    try:
        if args.command == "doctor":
            result["data"] = {"python": sys.version.split()[0], "beautifulsoup4": version("beautifulsoup4"),
                              "account_required": False, "network_checked": False}
        elif args.command == "slots":
            if not re.fullmatch(COURSE_ID, args.course) or not re.fullmatch(r"(?:[01][0-9]|2[0-3]):[0-5][0-9]", args.time):
                parser.error("Use a published course ID and HH:MM time.")
            day = args.date.strftime("%Y%m%d")
            clock = args.time.replace(":", "")
            url = (f"{BASE}{STOCK}?SP={args.shop}&RDT={day}&CN={args.course}"
                   f"&CB=&RTM={clock}&RPN={args.people}")
            result["source"]["url"] = f"{BASE}/str{args.shop}/course_cno{args.course}/?RDT={day}"
            result["data"] = pages.seats(client.read(url), args.shop, args.course, args.date, args.time, args.people)
            result["source"]["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
        else:
            url = args.area if args.command == "list" else f"{BASE}/str{args.shop}/"
            if args.command == "courses":
                url += "course/"
            result["source"]["url"] = url
            soup = pages.page(client.read(url), url)
            result["source"]["retrieved_at"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
            if args.command == "list":
                result["data"] = pages.listing(soup, url, args.limit, args.match)
            elif args.command == "detail":
                result["data"] = pages.details(soup, args.shop, args.date)
            else:
                result["data"] = pages.courses(soup, args.shop, args.limit)
    except SourceError as error:
        result.update(status="error", error={"code": error.code, "message": str(error), **error.details})
    result["usage"] = client.usage()
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["status"] == "ok" else 1
