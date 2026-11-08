#!/usr/bin/env python3
"""Read Japan's published public holidays from the Cabinet Office CSV."""
import ssl
import argparse
import csv
import datetime as dt
import hashlib
import http.client
import io
import json
import re
import socket
import sys
import time
import urllib.error
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9), "Asia/Tokyo")
SOURCE_URL = "https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv"
PAGE_URL = "https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html"
MAX_BYTES = 256 * 1024
WEEKDAYS_JA = ("月", "火", "水", "木", "金", "土", "日")


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


class HolidayError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def changed(message):
    raise HolidayError("source_schema_changed", message)


def parse_csv(raw):
    """Validate the export before treating missing dates as non-holidays."""
    try:
        text = raw.decode("cp932")
        rows = list(csv.reader(io.StringIO(text), strict=True))
    except (UnicodeError, csv.Error):
        changed("Expected the Cabinet Office's Shift_JIS CSV.")
    if not rows or rows[0] != ["国民の祝日・休日月日", "国民の祝日・休日名称"]:
        changed("Holiday CSV columns changed.")
    holidays = {}
    previous = None
    for row in rows[1:]:
        if len(row) != 2 or not re.fullmatch(r"[0-9]{4}/[0-9]{1,2}/[0-9]{1,2}", row[0]):
            changed("Malformed holiday row.")
        try:
            date = dt.date(*map(int, row[0].split("/")))
        except ValueError:
            changed("Invalid holiday date.")
        name = row[1]
        if not name or name != name.strip() or any(ord(c) < 32 for c in name):
            changed("Invalid holiday name.")
        if date.year < 1955 or (previous is not None and date <= previous):
            changed("Holiday dates must be unique and strictly ordered, from 1955 onward.")
        holidays[date] = name
        previous = date
    if not holidays:
        changed("Empty holiday export.")
    first, last = min(holidays), max(holidays)
    # The official export covers whole calendar years, not just its first/last
    # listed holiday. These boundary checks also reject truncated final years.
    for year in range(first.year, last.year + 1):
        if (holidays.get(dt.date(year, 1, 1)) != "元日" or
                holidays.get(dt.date(year, 11, 23)) != "勤労感謝の日"):
            changed("An exported year lacks its expected boundary holidays.")
    return holidays, dt.date(first.year, 1, 1), dt.date(last.year, 12, 31)


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise HolidayError("unexpected_redirect", "Source redirected; no redirect was followed.", http_status=code)


class Client:
    def __init__(self):
        self.started = time.monotonic()
        self.requests = self.response_bytes = 0
        self.opener = urllib.request.build_opener(RejectRedirect())

    def fetch(self):
        if self.requests:
            raise HolidayError("request_budget_exhausted", "Only one source read is allowed per invocation.")
        self.requests += 1
        try:
            request = urllib.request.Request(SOURCE_URL, headers={
                "User-Agent": "japan-travel-skills/0.1 (public holiday reader)",
                "Accept": "text/csv",
            })
            with self.opener.open(request, timeout=15) as response:
                if response.status != 200:
                    raise HolidayError("unexpected_status", "Expected a complete HTTP 200 export.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes = len(raw)
                if len(raw) > MAX_BYTES:
                    raise HolidayError("response_too_large", "Source export exceeds 256 KiB.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise HolidayError("incomplete_response", "Response size does not match Content-Length.")
                last_modified = response.headers.get("Last-Modified")
            holidays, start, end = parse_csv(raw)
        except urllib.error.HTTPError as exc:
            details = {"http_status": exc.code}
            if exc.headers and exc.headers.get("Retry-After"):
                details["retry_after"] = exc.headers["Retry-After"]
            raise HolidayError("http_error", "Source denied or failed the request; no retry was attempted.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            if isinstance(exc, http.client.IncompleteRead):
                self.response_bytes += len(exc.partial)
            raise HolidayError("network_error", "Could not read source; no retry was attempted.", exception_type=type(exc).__name__, network_reason=network_reason(exc)) from None
        source = {
            "publisher": "内閣府", "url": SOURCE_URL, "page_url": PAGE_URL,
            "retrieved_at": dt.datetime.now(JST).isoformat(timespec="seconds"),
            "http_last_modified": last_modified,
            "sha256": hashlib.sha256(raw).hexdigest(), "processed": True,
            "coverage": {"from": start.isoformat(), "to": end.isoformat(),
                         "basis": "Whole calendar years in the official CSV; not the first/last holiday dates."},
            "record_count": len(holidays),
        }
        return holidays, start, end, source

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "scope": "This invocation; Consumed body bytes, including available partial reads, excluding HTTP/TLS overhead. No token or monetary estimate."}


def day_record(date, holidays, coverage_start, coverage_end):
    known = coverage_start <= date <= coverage_end
    weekend = date.weekday() >= 5
    holiday = date in holidays if known else None
    return {"date": date.isoformat(), "weekday_ja": WEEKDAYS_JA[date.weekday()],
            "is_weekend": weekend, "is_public_holiday": holiday,
            "holiday_name_ja": holidays.get(date) if known else None,
            "is_weekend_or_holiday": True if weekend or holiday else (False if known else None),
            "holiday_status": "known" if known else "outside_published_coverage"}


def consecutive_breaks(start, end, holidays, coverage_start, coverage_end):
    """Find complete weekend/public-holiday blocks overlapping the query."""
    # Only classify blocks within published coverage. Unknown neighbors remain
    # explicit boundaries, even when a weekend can independently be identified.
    lo, hi = max(start, coverage_start), min(end, coverage_end)
    blocks = []
    if lo > hi:
        return blocks
    def off(date):
        return date.weekday() >= 5 or date in holidays
    cursor = lo
    while cursor <= hi:
        if not off(cursor):
            cursor += dt.timedelta(days=1)
            continue
        first = last = cursor
        while first > coverage_start and off(first - dt.timedelta(days=1)):
            first -= dt.timedelta(days=1)
        while last < coverage_end and off(last + dt.timedelta(days=1)):
            last += dt.timedelta(days=1)
        count = (last - first).days + 1
        if count >= 2:
            blocks.append({"from": first.isoformat(), "to": last.isoformat(), "days": count,
                           "includes_public_holiday": any(first <= d <= last for d in holidays),
                           "boundary_complete": first > coverage_start and last < coverage_end})
        cursor = last + dt.timedelta(days=1)
    return blocks


def query(start, end, holidays, coverage_start, coverage_end):
    days = [day_record(start + dt.timedelta(days=i), holidays, coverage_start, coverage_end)
            for i in range((end - start).days + 1)]
    known = sum(day["holiday_status"] == "known" for day in days)
    status = "ok" if known == len(days) else ("partial" if known else "unavailable")
    return {"status": status, "timezone": "Asia/Tokyo",
            "query": {"from": start.isoformat(), "to": end.isoformat()}, "days": days,
            "consecutive_breaks": consecutive_breaks(start, end, holidays, coverage_start, coverage_end),
            "break_definition": "Consecutive Saturdays/Sundays or CSV-listed public holidays, at least two days, overlapping the query; may extend beyond the query. Not an employer or facility schedule.",
            "warnings": ["Holiday names are preserved as published. Generic 休日 is not relabeled as a particular legal subtype.",
                         "Weekdays without a listed holiday are not proof of business opening. Obon and year-end closures are not inferred."]}


def iso_date(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.")
    try:
        return dt.date.fromisoformat(value)
    except ValueError:
        raise argparse.ArgumentTypeError("Invalid calendar date.") from None


def year_value(value):
    if not re.fullmatch(r"[0-9]{4}", value) or not 1 <= int(value) <= 9999:
        raise argparse.ArgumentTypeError("Use a four-digit year from 0001 to 9999.")
    return int(value)


def date_range(args, parser, now=None):
    if args.year is not None:
        return dt.date(args.year, 1, 1), dt.date(args.year, 12, 31)
    if args.start is not None:
        if args.end is None:
            parser.error("--from requires --to.")
        start, end = args.start, args.end
        if end < start or (end - start).days >= 366:
            parser.error("Use an inclusive range of 1 to 366 dates.")
        return start, end
    if args.end is not None:
        parser.error("--to requires --from.")
    date = args.date if args.date is not None else (now or dt.datetime.now(JST)).astimezone(JST).date()
    return date, date


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("doctor", help="Check the runtime without network access.")
    lookup = subs.add_parser("query", help="Read the official CSV once and select dates (default: today in JST).")
    dates = lookup.add_mutually_exclusive_group()
    dates.add_argument("--date", type=iso_date)
    dates.add_argument("--from", dest="start", type=iso_date)
    dates.add_argument("--year", type=year_value)
    lookup.add_argument("--to", dest="end", type=iso_date)
    lookup.add_argument("--holidays-only", action="store_true", help="Return only listed holidays in days; coverage and breaks still describe the full interval.")
    args = parser.parse_args(argv)
    if args.command == "doctor":
        print(json.dumps({"status": "ok", "python": sys.version.split()[0],
                          "dependencies": "Python 3.9+ standard library", "network_checked": False,
                          "source": SOURCE_URL}, ensure_ascii=False))
        return 0
    if args.end is not None and (args.year is not None or args.date is not None):
        parser.error("--to may only be used with --from.")
    start, end = date_range(args, parser)
    client = Client()
    try:
        holidays, coverage_start, coverage_end, source = client.fetch()
        result = query(start, end, holidays, coverage_start, coverage_end)
        result["query"]["holidays_only"] = args.holidays_only
        if args.holidays_only:
            result["days"] = [day for day in result["days"] if day["is_public_holiday"] is True]
        result["source"] = source
        result["usage"] = client.usage()
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except HolidayError as exc:
        print(json.dumps({"status": "error", "error": {"code": exc.code, "message": str(exc), **exc.details},
                          "source_url": SOURCE_URL, "usage": client.usage()}, ensure_ascii=False))
        return 2


if __name__ == "__main__":
    sys.exit(main())
