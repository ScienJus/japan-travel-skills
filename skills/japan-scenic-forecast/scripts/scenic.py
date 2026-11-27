#!/usr/bin/env python3
"""Query the Tateyama outlook from Toyama City or the Twin Terrace sea-of-clouds forecast."""
import argparse
import datetime as dt
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
from scenic_source import Client, JST, SourceError, TATEYAMA, TERRACE, TERRACE_DATA, fail, now_jst


# Individually reviewed publisher artwork. Unknown artwork has no numeric value.
VIEWING_ICONS = {f"img/{season}/{season}{p}.gif": p
                 for season in ("summer", "winter") for p in range(0, 101, 10)}
DAY_LABEL = re.compile(r"([0-9]{1,2})/([0-9]{1,2})\(([月火水木金土日])\)")
SITES = {
    "tateyama": {"viewpoint": "Toyama City (富山市内)", "phenomenon": "Tateyama mountain range visibility",
                 "resolution": "daily", "page_url": TATEYAMA, "data_url": TATEYAMA},
    "twin-terrace": {"viewpoint": "FUJIYAMA Twin Terrace, Fuefuki", "phenomenon": "sea of clouds",
                     "resolution": "3h", "page_url": TERRACE, "data_url": TERRACE_DATA},
}


class TateyamaPanel(HTMLParser):
    """Collect each outer cell from the forecast table following the title image."""
    def __init__(self):
        super().__init__()
        self.awaiting_table = False
        self.depth = 0
        self.panels = 0
        self.cells = []
        self.cell = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "img" and attrs.get("src") == "img/view_title.gif" and attrs.get("alt") == "立山眺望予報":
            self.awaiting_table = True
        elif tag == "table" and (self.depth or self.awaiting_table):
            if self.awaiting_table:
                self.panels += 1
                self.awaiting_table = False
            self.depth += 1
        elif tag == "td" and self.depth == 1:
            if self.cell is not None:
                fail("Overlapping Tateyama forecast cells.")
            self.cell = {"text": [], "icons": []}
            self.cells.append(self.cell)
        elif tag == "img" and self.depth == 1 and self.cell is not None:
            self.cell["icons"].append(attrs.get("src"))

    def handle_endtag(self, tag):
        if tag == "td" and self.depth == 1:
            self.cell = None
        if tag == "table" and self.depth:
            self.depth -= 1

    def handle_data(self, data):
        if self.cell is not None:
            self.cell["text"].append(data)


def tateyama_panel(raw, today):
    panel = TateyamaPanel()
    panel.feed(raw.decode("cp932"))
    panel.close()
    days = []
    scope_found = False
    for cell in panel.cells:
        label = "".join("".join(cell["text"]).split())
        if "富山市内からの立山の眺望の良さを確率で表現" in label:
            scope_found = True
        match = DAY_LABEL.fullmatch(label)
        if match:
            if len(cell["icons"]) != 1:
                fail("Expected one viewing icon in the dated Tateyama cell.")
            month, day, weekday = match.groups()
            days.append(((int(month), int(day), weekday), cell["icons"][0]))
    if panel.panels != 1 or panel.depth or not scope_found or len(days) != 7:
        fail("Expected the seven-day Toyama City viewing panel.")

    # The source omits the year. Match the entire run to adjacent JST dates,
    # including the weekday on every card and the year rollover in December.
    for start in (today, today + dt.timedelta(days=1)):
        result = {}
        for i, (label, icon) in enumerate(days):
            date = start + dt.timedelta(days=i)
            if label != (date.month, date.day, "月火水木金土日"[date.weekday()]):
                break
            p = VIEWING_ICONS.get(icon)
            result[date] = {"date": date.isoformat(), "probability_percent": p,
                            "status": "ok" if p is not None else "unknown"}
            if p is None:
                result[date]["reason"] = "unrecognized_icon"
        else:
            return result
    raise SourceError("invalid_coverage", "Dates and weekdays do not match a current seven-day panel.")


def terrace_panel(raw, now):
    payload = json.loads(raw.decode("utf-8-sig"))
    if not isinstance(payload, dict) or payload.get("SUCCESS") is not True:
        raise SourceError("source_unavailable", "The tourism portal did not return a successful forecast.")
    if not isinstance(payload.get("SRF"), list):
        fail("Missing the three-hour Twin Terrace forecast.")
    rows = {}
    for row in payload["SRF"]:
        if not isinstance(row, dict) or not isinstance(row.get("TSTR"), str):
            fail("Missing Twin Terrace forecast timestamp.")
        stamp = dt.datetime.strptime(row["TSTR"], "%Y-%m-%d.%H:%M:%S").replace(tzinfo=JST)
        if stamp.hour % 3 or stamp.minute or stamp.second or stamp in rows:
            fail("Expected unique three-hour JST slots.")
        p = row.get("INDEX")
        if type(p) is not int or (p != -9999 and not 0 <= p <= 100):
            fail("Invalid cloud-sea probability.")
        rows[stamp] = {"time": stamp.isoformat(), "probability_percent": None if p == -9999 else p,
                       "status": "unavailable" if p == -9999 else "ok"}
        if p == -9999:
            rows[stamp]["reason"] = "publisher_missing"
    if rows and (max(rows) < now or min(rows) > now + dt.timedelta(days=1)):
        raise SourceError("invalid_coverage", "The three-hour panel does not cover an upcoming forecast window.")
    return rows


def unavailable(key, value, reason="outside_published_coverage"):
    return {key: value.isoformat(), "status": "unavailable", "reason": reason, "probability_percent": None}


def select_terrace(rows, dates, hours, now):
    if dates:
        stamps = [dt.datetime.combine(day, dt.time(hour), JST)
                  for day in dates for hour in (hours or range(0, 24, 3))]
    else:
        stamps = sorted(stamp for stamp in rows if stamp >= now)
    first, last = (min(rows), max(rows)) if rows else (None, None)
    result = []
    for stamp in stamps:
        if stamp < now:
            result.append(unavailable("time", stamp, "elapsed"))
        elif stamp in rows:
            result.append(rows[stamp])
        elif first is not None and first < stamp < last:
            result.append(unavailable("time", stamp, "unpublished_slot"))
        else:
            result.append(unavailable("time", stamp))
    return result


def cli_date(value):
    if not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", value):
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.")
    return dt.date.fromisoformat(value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    modes = parser.add_subparsers(dest="site", required=True)
    modes.add_parser("doctor", help="Offline runtime and supported viewpoints")
    for site, info in SITES.items():
        mode = modes.add_parser(site, help=info["phenomenon"] + " from " + info["viewpoint"])
        mode.add_argument("--date", action="append", type=cli_date, help="Exact JST date; repeat to compare dates")
        if site == "twin-terrace":
            mode.add_argument("--hour", action="append", type=int, choices=range(0, 24, 3),
                              help="Published three-hour JST slot; repeat with --date to compare")
    args = parser.parse_args(argv)
    client = Client()
    if args.site == "doctor":
        result = {"status": "ok", "dependencies": "Python 3.9+ standard library", "network_checked": False,
                  "sites": list(SITES)}
    else:
        info = SITES[args.site]
        result = {"site": args.site, "forecast_provider": "Weathernews", **info, "timezone": "Asia/Tokyo", "issued_at": None,
                  "retrieved_at": None, "records": []}
        try:
            dates = sorted(set(args.date or []))
            hours = sorted(set(getattr(args, "hour", None) or []))
            if len(dates) > 14 or (hours and not dates):
                raise SourceError("invalid_options", "Use up to 14 dates; --hour requires --date.")
            raw = client.read(info["data_url"])
            now = now_jst()
            result["retrieved_at"] = now.isoformat()
            if args.site == "tateyama":
                rows = tateyama_panel(raw, now.date())
                records = [rows.get(day) or unavailable("date", day) for day in dates or sorted(rows)]
            else:
                rows = terrace_panel(raw, now)
                records = select_terrace(rows, dates, hours, now)
            result["published_range"] = ([min(rows).isoformat(), max(rows).isoformat()] if rows else [])
            states = {row["status"] for row in records}
            result["status"] = next(iter(states)) if len(states) == 1 else "partial" if states else "unavailable"
            result["records"] = records
        except (ValueError, RecursionError):
            result.update(status="error", state="unknown", error={"code": "source_schema_changed",
                          "message": "Could not parse the source encoding, JSON or forecast timestamp."})
        except SourceError as error:
            result.update(status="error", state="unknown", error={"code": error.code, "message": str(error), **error.details})
    result["usage"] = client.usage()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 2 if result["status"] == "error" else 0


if __name__ == "__main__":
    sys.exit(main())
