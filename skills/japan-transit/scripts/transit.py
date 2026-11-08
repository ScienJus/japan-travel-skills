#!/usr/bin/env python3
"""Bounded anonymous Yahoo! 路線情報 rail, bus and mixed-route reader."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from transit_source import (BASE, JST, MODES, STATION_LOOKUP_QUERIES, TransitError,
                            bus_name_parts, bus_operator, calendar_time, changed, decode, json_value,
                            native_url, normalize_route, page_props, source_info, text_key)
from transit_transport import Client


def stops(client, query, kind="all"):
    lookup = STATION_LOOKUP_QUERIES.get(text_key(query), query)
    if kind != "station":
        # Native bus suggestions include qualifiers the suggestion service
        # itself cannot search. Search the stop part, then resolve by the
        # unchanged full native name (operator included), never by this prefix.
        lookup = bus_name_parts(lookup)[0]
        lookup = re.sub(r"[（(]高速・連絡バス[）)]$", "", lookup)
    url = native_url("/api/suggest", {"value": lookup})
    data = json_value(decode(client.read(url)))
    if not isinstance(data, dict) or not isinstance(data.get("Result"), list):
        changed("Station suggestions no longer contain a Result array.")
    if data.get("@query") != lookup:
        changed("Suggestion response does not match the requested query.")
    result, seen = [], set()
    for row in data["Result"]:
        if not isinstance(row, dict):
            changed("Unexpected station suggestion row.")
        row_kind = {"st": "station", "bu": "bus"}.get(row.get("Id"))
        if row_kind is None or kind not in ("all", row_kind):
            continue
        code, name = row.get("Code"), row.get("Suggest")
        if not isinstance(code, str) or not re.fullmatch(r"\d+", code) or not isinstance(name, str) or not name:
            changed("Station suggestion is missing its native name/code.")
        identity = (row_kind, code)
        if identity in seen:
            continue
        seen.add(identity)
        result.append({"name": name, "code": code, "region_ja": row.get("Address"),
                       "kind": row_kind, "operator_ja": bus_operator(name) if row_kind == "bus" else None,
                       "reading_ja": row.get("Yomi"), "url": BASE + "/station/" + code})
    return result, url


def stations(client, query):
    return stops(client, query, "station")


def resolve(client, name, code=None, kind="station"):
    if code:
        # A caller can reuse a previously resolved pair. The route response must
        # still confirm both the code and exact native name for every result.
        if kind == "all":
            raise TransitError("stop_kind_required", "A reused code in mixed mode also needs an explicit station/bus kind.")
        return {"name": name, "code": code, "kind": kind}
    candidates, _ = stops(client, name, kind)
    matches = [row for row in candidates if text_key(row["name"]) == text_key(name)]
    if len(matches) == 1:
        return matches[0]
    raise TransitError("station_selection_required" if candidates else "station_not_found",
                       "Use an exact native station/bus-stop name, including its region/operator qualifier where present.",
                       query=name, candidates=candidates)


def transport_flags(args):
    use_rail = args.transport != "bus"
    use_bus = args.transport != "rail"
    return {"useAirline": False, "useShip": False, "useHighwayBus": use_bus, "useLocalBus": use_bus,
            "useShinkansen": use_rail and not args.no_shinkansen,
            "useLimitedExpress": use_rail and not args.no_limited_express}


def route_url(args, origin, destination):
    date = dt.date.fromisoformat(args.date)
    hour, minute = (args.time or "00:00").split(":")
    flags = transport_flags(args)
    params = {"from": origin["name"], "flatlon": ",," + origin["code"],
              "to": destination["name"], "tlatlon": ",," + destination["code"],
              "y": str(date.year), "m": f"{date.month:02d}", "d": f"{date.day:02d}",
              "hh": hour, "m1": minute[0], "m2": minute[1], "type": MODES[args.mode],
              "ticket": args.ticket, "expkind": {"non-reserved": "1", "reserved": "2", "green": "3"}[args.seat],
              "ws": "3", "s": {"fast": "0", "cheap": "1", "transfers": "2"}[args.sort],
              "al": "0", "shin": str(int(flags["useShinkansen"])), "ex": str(int(flags["useLimitedExpress"])),
              "hb": str(int(flags["useHighwayBus"])), "lb": str(int(flags["useLocalBus"])), "sr": "0", "userpass": "0"}
    return native_url("/search/result", params)


def check_requested_times(mode, requested, start, end):
    if mode == "departure" and start < requested:
        changed("Source departure precedes the requested departure time.")
    if mode == "arrival" and end > requested:
        changed("Source arrival exceeds the requested arrival time.")


def search_route(client, args):
    kind = {"rail": "station", "bus": "bus", "mixed": "all"}[args.transport]
    origin = resolve(client, args.origin, args.from_code, args.from_kind or kind)
    destination = resolve(client, args.destination, args.to_code, args.to_kind or kind)
    if origin["code"] == destination["code"] and origin["kind"] == destination["kind"]:
        raise TransitError("same_station", "Origin and destination refer to the same station.")
    url = route_url(args, origin, destination)
    props = page_props(client.read(url))
    state = props.get("queryState")
    if not isinstance(state, dict):
        changed("Source no longer echoes search conditions.")
    errors = state.get("errorList")
    if errors:
        raise TransitError("source_query_error", "Source could not answer the query.", source_messages_ja=errors, source_url=url)
    expected = {"year": args.date[:4], "month": args.date[5:7], "day": args.date[8:10], "dateType": MODES[args.mode]}
    hour, minute = (args.time or "00:00").split(":")
    expected.update({"hour": hour, "minute": minute, "ticket": args.ticket,
                     "expKind": {"non-reserved": "1", "reserved": "2", "green": "3"}[args.seat],
                     "sort": {"fast": "0", "cheap": "1", "transfers": "2"}[args.sort]})
    for key, value in expected.items():
        if str(state.get(key, "")).zfill(len(value)) != value:
            changed("Source changed the requested date, time, search mode or fare preference.")
    flags = transport_flags(args)
    for key, value in flags.items():
        if state.get(key) is not value:
            changed("Source changed the requested transport modes.")
    navi = props.get("naviSearchParam")
    if not isinstance(navi, dict) or not isinstance(navi.get("featureInfoList"), list):
        changed("No recognized route result was returned; this is not reported as no service.")
    info = navi.get("resultInfo") or {}
    if str(info.get("Status")) != "200":
        raise TransitError("source_query_error", "Route engine did not return success.", source_status=info.get("Status"), source_url=url)
    if str(info.get("ForceAverageSearch")).lower() != "false":
        raise TransitError("timetable_unavailable", "Source switched to average-time search; exact train times are not returned.", source_url=url)
    features = navi["featureInfoList"]
    requested = dt.datetime.fromisoformat(args.date + "T" + (args.time or "00:00")).replace(tzinfo=JST)
    parsed, qualified_types = [], set()
    for i, feature in enumerate(features):
        try:
            route = normalize_route(feature, origin, destination, i + 1, args.detail)
            check_requested_times(args.mode, requested, dt.datetime.fromisoformat(route["departure_at"]), dt.datetime.fromisoformat(route["arrival_at"]))
            parsed.append(route)
        except TransitError as error:
            if error.code != "timetable_unavailable" or not error.details.get("qualified_time_types"):
                raise
            # Pure validation continues across all embedded alternatives. A later
            # malformed record must not be hidden by a known uncertainty.
            calendar = feature["summaryInfo"]["calendarData"]
            check_requested_times(args.mode, requested, calendar_time(calendar["startTime"]), calendar_time(calendar["endTime"]))
            qualified_types.update(error.details["qualified_time_types"])
    if qualified_types:
        raise TransitError("timetable_unavailable", "Source includes qualified intermediate times; exact dated leg times are unverified. No route was returned.",
                           qualified_time_types=sorted(qualified_types), source_url=url, source=source_info(url, props))
    matching = [r for r in parsed if (args.transport == "mixed" or
                (args.transport == "rail" and "bus" not in r["modes_used"]) or
                (args.transport == "bus" and "bus" in r["modes_used"] and "rail" not in r["modes_used"]))]
    routes = matching[:args.limit]
    source = source_info(url, props)
    warnings = ["Published timetable search; live operation and seat availability are not verified.",
                "Fares are source estimates for the selected ticket/seat preference; a preference is not a guarantee.",
                "Only routes embedded in this page are returned; this is not a full day's timetable."]
    if args.transport != "rail":
        source["bus_timetable_version"] = None
        warnings.extend(["Bus coverage is limited to the source's supported stops/operators; bus timetable version is unknown. JR/private-rail versions do not date bus data.",
                         "Road traffic can change bus arrival times; booking requirements and inventory are not verified."])
    if args.transport == "bus":
        warnings.append("Bus mode disables Shinkansen/limited express and filters embedded alternatives to bus plus walking with at least one bus leg. Ordinary rail cannot be disabled through this verified website form; no matching result does not establish no bus service.")
    return {"status": "ok" if routes else "unavailable",
            "query": {"date": args.date,
                      "weekday_ja": ("月曜日", "火曜日", "水曜日", "木曜日", "金曜日", "土曜日", "日曜日")[dt.date.fromisoformat(args.date).weekday()],
                      "time": args.time, "timezone": "Asia/Tokyo", "from": origin, "to": destination,
                      "mode": args.mode, "ticket": args.ticket, "seat_preference": args.seat, "sort": args.sort,
                      "transport": args.transport, "shinkansen": flags["useShinkansen"], "limited_express": flags["useLimitedExpress"],
                      "local_bus": flags["useLocalBus"], "highway_bus": flags["useHighwayBus"], "air_ferry": False},
            "source": source,
            "unavailable_reason": None if routes else "no_matching_embedded_routes" if features else "no_embedded_routes",
            "routes": routes, "returned_routes": len(routes),
            "embedded_routes": len(features), "filtered_routes": len(parsed) - len(matching), "warnings": warnings}


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest="command", required=True)
    subs.add_parser("doctor", help="Check runtime without network access")
    lines = subs.add_parser("lines", help="List integrated official-operation line/operator sections offline")
    lines.add_argument("query", nargs="?")
    lines.add_argument("--operator", choices=["jr-west", "ir-ishikawa"], help="Filter the offline catalog by operator")
    operations = subs.add_parser("operations", help="Read current official line reports; not individual-train punctuality")
    operations.add_argument("--line", action="append", required=True, help="Exact supported native line name; repeat up to ten times")
    operations.add_argument("--operator", choices=["jr-west", "ir-ishikawa"], required=True,
                            help="Explicit supported operator scope; no automatic operator fallback")
    station = subs.add_parser("stations", help="Look up native station candidates")
    station.add_argument("query")
    stop = subs.add_parser("stops", help="Look up native rail/bus-stop candidates")
    stop.add_argument("query")
    stop.add_argument("--kind", choices=["station", "bus", "all"], default="all")
    route = subs.add_parser("route", help="Query published rail, bus or mixed routes")
    route.add_argument("--from", dest="origin", required=True)
    route.add_argument("--to", dest="destination", required=True)
    route.add_argument("--from-code", help="Reuse a previously resolved native name/code pair")
    route.add_argument("--to-code", help="Reuse a previously resolved native name/code pair")
    route.add_argument("--from-kind", choices=["station", "bus"], help="Required with a reused code in mixed mode")
    route.add_argument("--to-kind", choices=["station", "bus"], help="Required with a reused code in mixed mode")
    route.add_argument("--transport", choices=["rail", "bus", "mixed"], default="rail")
    route.add_argument("--date", required=True, help="YYYY-MM-DD, JST")
    route.add_argument("--time", help="HH:MM, JST; required for departure/arrival")
    route.add_argument("--mode", choices=list(MODES), default="departure")
    route.add_argument("--ticket", choices=["normal", "ic"], default="normal")
    route.add_argument("--seat", choices=["non-reserved", "reserved", "green"], default="non-reserved")
    route.add_argument("--sort", choices=["fast", "cheap", "transfers"], default="fast")
    route.add_argument("--no-shinkansen", action="store_true")
    route.add_argument("--no-limited-express", action="store_true")
    route.add_argument("--limit", type=int, choices=range(1, 4), default=3)
    route.add_argument("--detail", action="store_true", help="Include source fare display groups and intermediate stops")
    return parser


def validate_args(parser, args):
    if args.command in ("doctor", "lines", "operations"):
        return
    for value in ([args.query] if args.command in ("stations", "stops") else [args.origin, args.destination]):
        if not value.strip() or len(value) > 100 or any(ord(c) < 32 for c in value):
            parser.error("Station query must contain 1–100 printable characters.")
    if args.command in ("stations", "stops"):
        return
    for code, kind in [(args.from_code, args.from_kind), (args.to_code, args.to_kind)]:
        if args.transport == "mixed" and code is not None and kind is None:
            parser.error("Reusing a code in mixed mode requires its --from-kind/--to-kind station|bus.")
        expected = {"rail": "station", "bus": "bus"}.get(args.transport)
        if kind is not None and expected is not None and kind != expected:
            parser.error("Endpoint kind must match the selected rail/bus mode; use mixed for different kinds.")
    try:
        date = dt.date.fromisoformat(args.date)
        if date.isoformat() != args.date:
            raise ValueError()
    except ValueError:
        parser.error("--date must be an actual date in YYYY-MM-DD format.")
    if args.mode in ("departure", "arrival"):
        if not args.time or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", args.time):
            parser.error("Departure/arrival queries require --time HH:MM (00:00–23:59, JST).")
    elif args.time is not None:
        parser.error("First/last queries use the selected service date; omit --time.")
    for code in (args.from_code, args.to_code):
        if code is not None and not re.fullmatch(r"\d{1,10}", code):
            parser.error("Native station codes must contain 1–10 decimal digits.")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    validate_args(parser, args)
    if args.command in ("lines", "operations"):
        import rail_operations
        return rail_operations.main(args)
    client = Client()
    try:
        if args.command == "doctor":
            result = {"status": "ok", "python": sys.version.split()[0], "runtime": "Python 3.9+ standard library",
                      "source": "Yahoo! 路線情報", "operations_sources": ["JR西日本", "IRいしかわ鉄道"], "network_checked": False,
                      "account_required": False, "browser_required": False, "api_key_required": False}
        elif args.command in ("stations", "stops"):
            kind = "station" if args.command == "stations" else args.kind
            candidates, url = stops(client, args.query, kind)
            result = {"status": "ok" if candidates else "not_found", "query": args.query,
                      "source": source_info(url), "stations" if args.command == "stations" else "stops": candidates,
                      "coverage": "Native suggestions only; not an exhaustive stop catalog. Source st category can include airports. Bus operator qualifiers are preserved."}
        else:
            result = search_route(client, args)
        result["usage"] = client.usage()
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except TransitError as exc:
        result = {"status": "error", "error": {"code": exc.code, "message": str(exc), **exc.details}, "usage": client.usage()}
        if exc.code == "timetable_unavailable":
            result["state"] = "unknown"
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 2
    except (KeyError, TypeError, AttributeError, ValueError, OverflowError):
        print(json.dumps({"status": "error", "error": {"code": "source_schema_changed", "message": "Unexpected source structure; no route was guessed."},
                          "usage": client.usage()}, separators=(",", ":")))
        return 2


if __name__ == "__main__":
    sys.exit(main())
