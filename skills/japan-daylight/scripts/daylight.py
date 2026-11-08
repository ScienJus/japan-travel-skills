#!/usr/bin/env python3
"""Query NAOJ's live sunrise/sunset calculator for Japanese named locations."""
import ssl
import argparse
import datetime as dt
import http.client
import json
import math
import re
import socket
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

JST = dt.timezone(dt.timedelta(hours=9), "Asia/Tokyo")
BASE = "https://eco.mtk.nao.ac.jp/cgi-bin/koyomi/koyomix.cgi"
MAX_BYTES = 512 * 1024
ALIASES = {"金泽": "金沢", "长野": "長野", "东京": "東京", "横滨": "横浜",
           "kanazawa": "金沢", "nagano": "長野", "toyama": "富山", "fukui": "福井",
           "tokyo": "東京", "kyoto": "京都", "osaka": "大阪", "sapporo": "札幌"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


def network_reason(error, *, timeout_types=(), protocol_types=()):
    """Classify typed evidence only; never inspect exception messages or implicit context."""
    seen = set()
    for _ in range(8):
        if not isinstance(error, BaseException) or id(error) in seen:
            break
        seen.add(id(error))
        if isinstance(error, (TimeoutError,) + timeout_types):
            return "timeout"
        if isinstance(error, socket.gaierror):
            return "dns"
        if isinstance(error, ssl.SSLError):
            return "tls"
        if isinstance(error, ConnectionRefusedError):
            return "connection_refused"
        if isinstance(error, (ConnectionResetError, ConnectionAbortedError, BrokenPipeError)):
            return "connection_lost"
        if isinstance(error, (http.client.HTTPException,) + protocol_types):
            return "protocol"
        reason = error.reason if isinstance(error, urllib.error.URLError) else None
        error = reason if isinstance(reason, BaseException) else error.__cause__
    return "unknown"


class DaylightError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def changed(message):
    raise DaylightError("source_schema_changed", message)


def key(text):
    return unicodedata.normalize("NFKC", text).strip().casefold()


class Node:
    def __init__(self, tag, attrs=()):
        self.tag, self.attrs, self.children = tag, dict(attrs), []

    def text(self):
        return "".join(c if isinstance(c, str) else c.text() for c in self.children).strip()

    def find(self, tag):
        for child in self.children:
            if isinstance(child, Node):
                if child.tag == tag:
                    yield child
                yield from child.find(tag)


class Page(HTMLParser):
    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]
        self.feed(text)
        self.close()

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def unique(nodes, message):
    nodes = list(nodes)
    if len(nodes) != 1:
        changed(message)
    return nodes[0]


def parse_catalog(text):
    root = Page(text).root
    selects = list(root.find("select"))
    places = unique((n for n in selects if n.attrs.get("name") == "NAO_id"), "Location menu missing or duplicated.")
    years = unique((n for n in selects if n.attrs.get("name") == "year"), "Year menu missing or duplicated.")
    points, codes = [], set()
    for option in places.find("option"):
        code, label = option.attrs.get("value", ""), option.text()
        match = re.fullmatch(r"(.+)\(([^()]+)\)", label)
        if not re.fullmatch(r"[0-9]{2}", code) or code in codes or not match:
            changed("Location menu format changed.")
        codes.add(code)
        name, region = match.groups()
        if region in ("北海道", "日本") or region.endswith(("都", "府", "県")):
            points.append({"code": code, "name_ja": name, "region_ja": region, "label_ja": label})
    supported = []
    for option in years.find("option"):
        value = option.attrs.get("value", "")
        if not re.fullmatch(r"[0-9]{4}", value) or not 1955 <= int(value) <= 9998:
            changed("Expected modern Gregorian years in the current calculator menu.")
        supported.append(int(value))
    if not points or not supported or supported != sorted(set(supported)):
        changed("Empty location menu or unordered/duplicate year menu.")
    return points, supported


def search_points(points, query):
    needle = ALIASES.get(key(query), key(query))
    needle = key(needle)
    return [p for p in points if any(needle in key(p[f]) for f in ("name_ja", "region_ja", "label_ja"))]


def resolve(points, query):
    needle = key(ALIASES.get(key(query), query))
    matches = [p for p in points if needle in (key(p["name_ja"]), key(p["label_ja"]), key(p["name_ja"] + "市"))]
    if len(matches) != 1:
        raise DaylightError("ambiguous_city" if matches else "city_not_found",
                            "Use an exact Japanese location name from the live menu; no nearby location was substituted.",
                            candidates=matches or search_points(points, query))
    return matches[0]


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise DaylightError("unexpected_redirect", "Source redirected; no redirect was followed.", http_status=code)


class Client:
    def __init__(self):
        self.started = time.monotonic()
        self.requests = self.response_bytes = self.pacing_ms = 0
        self.last_started = None
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url):
        if url.split("?", 1)[0] != BASE:
            raise DaylightError("unsupported_url", "Only the configured NAOJ calculator may be queried.")
        if self.requests >= 2:
            raise DaylightError("request_budget_exhausted", "Stopped at two reads per invocation.")
        if self.last_started is not None:
            delay = max(0, 1 - (time.monotonic() - self.last_started))
            if delay:
                time.sleep(delay)
                self.pacing_ms += round(delay * 1000)
        self.requests += 1
        self.last_started = time.monotonic()
        try:
            request = urllib.request.Request(url, headers={
                "User-Agent": "japan-travel-skills/0.1 (anonymous daylight reader)", "Accept": "text/html"})
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise DaylightError("unexpected_status", "Expected HTTP 200.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes += len(raw)
                if len(raw) > MAX_BYTES:
                    raise DaylightError("response_too_large", "Source response exceeds 512 KiB.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise DaylightError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as exc:
            details = {"http_status": exc.code}
            if exc.headers and exc.headers.get("Retry-After"):
                details["retry_after"] = exc.headers["Retry-After"]
            raise DaylightError("http_error", "Source denied or failed the request; no retry was attempted.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            if isinstance(exc, http.client.IncompleteRead):
                self.response_bytes += len(exc.partial)
            raise DaylightError("network_error", "Could not read source; no retry was attempted.", exception_type=type(exc).__name__, network_reason=network_reason(exc)) from None
        try:
            return raw.decode("euc_jp")
        except UnicodeError:
            changed("Expected the calculator's EUC-JP HTML.")

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "pacing_ms": self.pacing_ms, "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "scope": "This invocation; Consumed body bytes, including available partial reads, excluding HTTP/TLS overhead. No token or monetary estimate."}


def calculation_url(point, start, end):
    params = {"year": start.year, "month": start.month, "day": start.day, "hour": 0, "min": 0,
              "NAO_id": point["code"], "lst": 9, "choice": 0, "choice0": 0, "btn00": "Go",
              "div": 1, "divu": 3, "len": (end - start).days + 1, "lenu": 3,
              "cg": 0, "drtn": 1, "nocalc": 0, "nomenu": 1}
    return BASE + "?" + urllib.parse.urlencode(params)


def clock(value, seconds=False):
    pattern = r"([0-9]{1,2}):([0-9]{2}):([0-9]{2})" if seconds else r"([0-9]{1,2}):([0-9]{2})"
    match = re.fullmatch(pattern, value)
    if not match:
        changed("Expected a published clock time.")
    values = tuple(map(int, match.groups()))
    try:
        return dt.time(*values)
    except ValueError:
        changed("Invalid published clock time.")


def number(value, low, high):
    try:
        parsed = float(value)
    except ValueError:
        changed("Invalid numeric result.")
    if not math.isfinite(parsed) or not low <= parsed <= high:
        changed("Numeric result outside its expected range.")
    return parsed


def parse_result(text, point, start, end, detail=False):
    root = Page(text).root
    result = unique((n for n in root.find("div") if n.attrs.get("id") == "skipr"), "Result section missing or duplicated.")
    headings = list(result.find("h3"))
    if not headings or headings[0].text() != "日の出入り":
        changed("Expected sunrise/sunset results.")
    direct_divs = [c for c in result.children if isinstance(c, Node) and c.tag == "div"]
    if len(direct_divs) != 2 or not direct_divs[0].text().startswith(point["label_ja"] + ": "):
        raise DaylightError("location_mismatch", "The calculator returned a different or missing named location.")
    coordinates = re.fullmatch(r"緯度:([-+0-9.]+)°\s+経度:([-+0-9.]+)°\s+標高:\s*([-+0-9.]+) m\s+標準時:UT\+9h", direct_divs[1].text())
    if not coordinates:
        changed("Missing coordinates/elevation or non-JST result.")
    latitude = number(coordinates[1], 20, 46)
    longitude = number(coordinates[2], 122, 154)
    elevation = number(coordinates[3], -500, 5000)
    location = {**point, "latitude": latitude, "longitude": longitude, "elevation_m": elevation,
                "scope": "NAOJ named reference location; not a geocoded address or attraction entrance."}
    table = unique((n for n in result.find("table") if "result" in n.attrs.get("class", "").split()), "Result table missing or duplicated.")
    rows = list(table.find("tr"))
    expected_header = ["年月日", "出", "方位[°]", "南中", "高度[°]", "入り", "方位[°]", "長さ"]
    if not rows or [n.text() for n in rows[0].find("th")] != expected_header:
        changed("Sunrise/sunset table columns changed.")
    dates = [start + dt.timedelta(days=i) for i in range((end - start).days + 1)]
    if len(rows) - 1 != len(dates):
        changed("Result does not contain exactly the requested number of dates.")
    days = []
    for row, expected_date in zip(rows[1:], dates):
        cells = [n.text() for n in row.find("td")]
        if len(cells) != 8 or not re.fullmatch(r"[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}", cells[0]):
            changed("Malformed sunrise/sunset result row.")
        try:
            date = dt.date(*map(int, cells[0].split("/")))
        except ValueError:
            changed("Invalid result date.")
        if date != expected_date:
            raise DaylightError("date_mismatch", "The calculator did not return the requested daily dates.")
        sunrise, noon, sunset, duration = clock(cells[1]), clock(cells[3], True), clock(cells[5]), clock(cells[7])
        if not sunrise < noon < sunset:
            changed("Sunrise, solar transit and sunset clocks are not ordered.")
        rise_azimuth, noon_altitude, set_azimuth = number(cells[2], 0, 360), number(cells[4], 0, 90), number(cells[6], 0, 360)
        minutes = duration.hour * 60 + duration.minute
        displayed_minutes = (sunset.hour * 60 + sunset.minute) - (sunrise.hour * 60 + sunrise.minute)
        if abs(minutes - displayed_minutes) > 1:
            changed("Published daylight length disagrees with the displayed rise/set interval by more than rounding.")
        day = {"date": date.isoformat(), "sunrise": dt.datetime.combine(date, sunrise, JST).isoformat(timespec="minutes"),
               "sunset": dt.datetime.combine(date, sunset, JST).isoformat(timespec="minutes"), "daylight_minutes": minutes}
        if detail:
            day.update(solar_noon=dt.datetime.combine(date, noon, JST).isoformat(timespec="seconds"),
                       sunrise_azimuth_deg=rise_azimuth, sunset_azimuth_deg=set_azimuth, solar_noon_altitude_deg=noon_altitude)
        days.append(day)
    version = re.search(r"ver\.([A-Za-z0-9.]+)", result.text())
    return location, days, version.group(1) if version else None


def iso_date(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid calendar date.") from None


def date_range(args, parser, now=None):
    if args.start is not None:
        if args.end is None:
            parser.error("--from requires --to.")
        start, end = args.start, args.end
        if end < start or (end - start).days >= 31:
            parser.error("Use an inclusive range of 1 to 31 dates.")
        return start, end
    if args.end is not None:
        parser.error("--to requires --from and cannot be combined with --date.")
    date = args.date or (now or dt.datetime.now(JST)).astimezone(JST).date()
    return date, date


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("doctor", help="Check the runtime without network access.")
    cities = subs.add_parser("cities", help="Read current Japanese named locations from NAOJ's menu.")
    cities.add_argument("query", nargs="?", default="")
    lookup = subs.add_parser("query", help="Query sunrise/sunset (default date: today in JST).")
    lookup.add_argument("--city", required=True)
    dates = lookup.add_mutually_exclusive_group()
    dates.add_argument("--date", type=iso_date)
    dates.add_argument("--from", dest="start", type=iso_date)
    lookup.add_argument("--to", dest="end", type=iso_date)
    lookup.add_argument("--detail", action="store_true", help="Include solar transit and source angles.")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        print(json.dumps({"status": "ok", "python": sys.version.split()[0], "dependencies": "Python 3.9+ standard library",
                          "network_checked": False, "source": BASE}, ensure_ascii=False))
        return 0
    if args.command == "query":
        start, end = date_range(args, parser)
    client = Client()
    try:
        points, years = parse_catalog(client.read(BASE))
        source = {"publisher": "国立天文台 暦計算室", "catalog_url": BASE, "processed": True,
                  "menu_years": years, "attribution": "(C) NAOJ"}
        if args.command == "cities":
            matches = search_points(points, args.query)
            result = {"status": "ok" if matches else "not_found", "query": args.query, "locations": matches, "source": source}
        else:
            point = resolve(points, args.city)
            result = {"status": "unavailable", "timezone": "Asia/Tokyo",
                      "query": {"city": args.city, "from": start.isoformat(), "to": end.isoformat()},
                      "location": point, "days": [], "source": source}
            if any(year not in years for year in range(start.year, end.year + 1)):
                result["unavailable_reason"] = "outside_current_calculator_menu_years"
            else:
                url = calculation_url(point, start, end)
                location, days, version = parse_result(client.read(url), point, start, end, args.detail)
                source.update(url=url, site_version=version)
                result.update(status="ok", location=location, days=days,
                              daylight_duration_basis="NAOJ's published 長さ column, independently rounded; may differ by one minute from subtracting displayed clocks.",
                              warnings=["Astronomical sunrise/sunset; terrain and buildings are not modeled. This is not a weather or visibility forecast.",
                                        "Sunset is not the end of twilight or a guaranteed safe outdoor activity cutoff."])
        source["retrieved_at"] = dt.datetime.now(JST).isoformat(timespec="seconds")
        result["usage"] = client.usage()
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except (DaylightError, RecursionError) as exc:
        if isinstance(exc, RecursionError):
            exc = DaylightError("source_schema_changed", "Source HTML exceeds supported nesting depth.")
        print(json.dumps({"status": "error", "error": {"code": exc.code, "message": str(exc), **exc.details},
                          "source_url": BASE, "usage": client.usage()}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
