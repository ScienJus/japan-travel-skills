"""Pure Yahoo timetable parsing, source identities and result metadata; no network calls."""
import datetime as dt
from html.parser import HTMLParser
import json
import re
import unicodedata
import urllib.parse

JST = dt.timezone(dt.timedelta(hours=9), "Asia/Tokyo")
BASE = "https://transit.yahoo.co.jp"
MAX_BYTES = 2 * 1024 * 1024
MODES = {"departure": "1", "arrival": "4", "first": "3", "last": "2"}
# Exact aliases observed between the source's own suggestion and route output.
# Keep aliases code-scoped; never remove operator qualifiers generically.
STATION_ALIASES = {
    "25891": {"関西空港駅(鉄道)", "関西空港(鉄道)"},
    "29509": {"羽田空港第1ターミナル(モノレール/JAL)", "羽田空港第1ターミナル(東京モノレール・JAL利用)"},
    "29510": {"羽田空港第2ターミナル(モノレール/ANA)", "羽田空港第2ターミナル(東京モノレール・ANA利用)"},
    "29671": {"羽田空港第3ターミナル(モノレール)", "羽田空港第3ターミナル(東京モノレール)"},
}
# The source generates these candidate names but strips their slash when used
# as autocomplete input. Shorten only the search text for these verified names;
# resolution and endpoint checks still use the complete native identity.
STATION_LOOKUP_QUERIES = {
    "羽田空港第1ターミナル(モノレール/JAL)": "羽田空港第1ターミナル",
    "羽田空港第2ターミナル(モノレール/ANA)": "羽田空港第2ターミナル",
}



class TransitError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def changed(message):
    raise TransitError("source_schema_changed", message)


def native_url(path, params):
    return BASE + path + "?" + urllib.parse.urlencode(params)


def decode(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        changed("Expected a UTF-8 source response.")


def json_value(text):
    try:
        return json.loads(text)
    except (ValueError, TypeError):
        changed("Source JSON is invalid.")


class NextData(HTMLParser):
    def __init__(self):
        super().__init__()
        self.capture = False
        self.parts = []
        self.count = 0

    def handle_starttag(self, tag, attrs):
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.capture = True
            self.count += 1

    def handle_endtag(self, tag):
        if tag == "script":
            self.capture = False

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)


def page_props(raw):
    parser = NextData()
    parser.feed(decode(raw))
    if parser.count != 1:
        changed("Expected exactly one public page JSON block; no JavaScript was executed.")
    data = json_value("".join(parser.parts))
    try:
        props = data["props"]["pageProps"]
    except (KeyError, TypeError):
        changed("Page data no longer contains pageProps.")
    if not isinstance(props, dict):
        changed("Page properties are not an object.")
    return props


def text_key(value):
    # Do not strip 駅: 富山 and 富山駅 can identify different rail stops.
    return unicodedata.normalize("NFKC", value).strip()


def same_station(selected, actual):
    if actual["code"] != selected["code"]:
        return False
    if selected.get("kind") and actual.get("kind") not in (None, "unknown", selected["kind"]):
        return False
    names = {text_key(selected["name"]), text_key(actual["name"])}
    return len(names) == 1 or names.issubset(STATION_ALIASES.get(selected["code"], set()))


def bus_operator(name):
    # The native slash qualifier names an operator. Generic highway/airport
    # stop labels do not identify one, so leave those unknown.
    return bus_name_parts(name)[1]


def bus_name_parts(name):
    depth = 0
    for i, char in enumerate(name):
        if char in "(（":
            depth += 1
        elif char in ")）":
            depth = max(0, depth - 1)
        elif char == "/" and depth == 0:
            return name[:i], name[i + 1:] or None
    return name, None


def integer(value):
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        changed("Boolean supplied as a numeric field.")
    text = str(value).replace(",", "")
    if not re.fullmatch(r"\d+", text):
        changed("Unexpected numeric source field.")
    return int(text)


def duration(value):
    if not isinstance(value, str):
        changed("Missing journey duration.")
    match = re.fullmatch(r"(?:(\d+)日)?(?:(\d+)時間)?(?:(\d+)分)?", value)
    if not match or not any(match.groups()):
        changed("Unrecognized journey duration.")
    days, hours, minutes = [int(x or 0) for x in match.groups()]
    return days * 1440 + hours * 60 + minutes


def calendar_time(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{8}T\d{6}", value):
        changed("Missing absolute route calendar timestamp.")
    try:
        return dt.datetime.strptime(value, "%Y%m%dT%H%M%S").replace(tzinfo=JST)
    except ValueError:
        changed("Invalid route calendar timestamp.")


def clock_minutes(value):
    match = re.fullmatch(r"([0-4]?\d):([0-5]\d)", str(value))
    if not match or int(match[1]) > 47:
        changed("Unrecognized route clock time.")
    return (int(match[1]) % 24) * 60 + int(match[2])


def node_times(edges, start, end):
    """Anchor the sequence to source calendar dates; check both boundaries."""
    sequences, qualified_types = [], set()
    for index, edge in enumerate(edges):
        if not isinstance(edge, dict):
            changed("A route point is not an object.")
        infos = edge.get("timeInfo")
        if not isinstance(infos, list) or not infos:
            changed("A route point has no verified time sequence.")
        sequence, seen = [], set()
        for info in infos:
            if not isinstance(info, dict) or type(info.get("type")) is not int or info["type"] not in (1, 2, 3, 4, 5):
                changed("Unrecognized route time type.")
            kind = info["type"]
            if kind in seen:
                changed("Duplicate route time type.")
            seen.add(kind)
            sequence.append((kind, clock_minutes(info.get("time"))))
        if seen & {4, 5}:
            # Only these intermediate patterns have been observed with qualified
            # (parenthesized) labels. Their clock semantics are not interpreted.
            if index in (0, len(edges) - 1) or [kind for kind, _ in sequence] not in ([2, 4], [5, 4]):
                changed("Unrecognized qualified route time sequence.")
            qualified_types.update(seen & {4, 5})
        sequences.append(sequence)
    previous = start
    nodes = []
    for index, sequence in enumerate(sequences):
        values = {}
        for kind, minutes in sequence:
            if kind in (4, 5):
                continue
            value = previous.replace(hour=minutes // 60, minute=minutes % 60, second=0, microsecond=0)
            if value < previous:
                value += dt.timedelta(days=1)
            if value > end:
                changed("Route point time exceeds the source calendar end.")
            previous = value
            values[kind] = value
        if index == 0:
            departure, arrival = values.get(1, values.get(3)), None
            if departure != start:
                changed("Departure clock does not match the source calendar start.")
        elif index == len(edges) - 1:
            departure, arrival = None, values.get(2, values.get(3))
            if arrival != end:
                changed("Arrival clock does not match the source calendar end.")
        elif any(kind in (4, 5) for kind, _ in sequence):
            arrival, departure = values.get(2), None
        else:
            departure, arrival = values.get(1, values.get(3)), values.get(2, values.get(3))
            if arrival is None or departure is None or departure < arrival:
                changed("Intermediate arrival/departure times are incomplete.")
        nodes.append((arrival, departure))
    if qualified_types:
        raise TransitError("timetable_unavailable", "Recognized qualified intermediate times cannot be verified as exact dated leg times.",
                           qualified_time_types=sorted(qualified_types))
    return nodes


def point(edge, kind=None):
    name, code = edge.get("stationName"), edge.get("stationCode")
    if not isinstance(name, str) or not name or not isinstance(code, str) or not re.fullmatch(r"\d+", code):
        changed("Route point is not a supported station/bus stop with a native code.")
    result = {"name": name, "code": code}
    if kind is not None:
        result["kind"] = kind
        if kind == "bus":
            result["operator_ja"] = bus_operator(name)
    return result


def leg_transport(edge):
    access = edge.get("accessInfo")
    if not isinstance(access, dict) or type(access.get("type")) is not int:
        changed("Route leg lacks a verified source transport type.")
    # Native type 3 is highway bus (rendered with icnHighwayBus), distinct
    # from the type-2 local/airport bus. Both use the supported bus mode.
    mode = {0: "rail", 1: "walk", 2: "bus", 3: "bus"}.get(access["type"])
    if mode is None:
        changed("Unsupported source transport type; no leg mode was guessed.")
    return mode


def route_points(edges, modes, origin, destination):
    points = []
    for i, edge in enumerate(edges):
        outgoing = modes[i] if i < len(modes) else None
        incoming = modes[i - 1] if i > 0 else None
        mode = outgoing if outgoing in ("rail", "bus") else incoming
        kind = {"rail": "station", "bus": "bus"}.get(mode)
        if kind is None:
            selected = origin if i == 0 else destination if i == len(edges) - 1 else {}
            kind = selected.get("kind", "unknown")
        points.append(point(edge, kind))
    return points


def platform(edge, key):
    value = (edge.get("ridingPositionInfo") or {}).get(key)
    if not isinstance(value, list) or len(value) != 2 or value[0] is None:
        return None
    return "".join(str(x) for x in value)


def normalize_route(feature, origin, destination, rank, detail=False):
    if not isinstance(feature, dict):
        changed("A route alternative is not an object.")
    summary, edges = feature.get("summaryInfo"), feature.get("edgeInfoList")
    if not isinstance(summary, dict) or not isinstance(edges, list) or len(edges) < 2 or any(not isinstance(edge, dict) for edge in edges):
        changed("Incomplete route summary/points.")
    modes = [leg_transport(edge) for edge in edges[:-1]]
    points = route_points(edges, modes, origin, destination)
    for selected, actual in [(origin, points[0]), (destination, points[-1])]:
        if not same_station(selected, actual):
            raise TransitError("station_mismatch", "Source selected a different station; no substitute is returned.", requested=selected, actual=actual)
    calendar = summary.get("calendarData") or {}
    start, end = calendar_time(calendar.get("startTime")), calendar_time(calendar.get("endTime"))
    minutes = duration(summary.get("totalTime"))
    if end < start or (end - start).total_seconds() != minutes * 60:
        changed("Source calendar duration and summary disagree.")
    if clock_minutes(summary.get("departureTime")) != start.hour * 60 + start.minute or clock_minutes(summary.get("arrivalTime")) != end.hour * 60 + end.minute:
        changed("Summary clocks disagree with source calendar dates.")
    legs, waits, seat_types = [], [], []
    for i, edge in enumerate(edges[:-1]):
        service = edge.get("railName")
        if not isinstance(service, str) or not service:
            changed("A route leg has incomplete service/times.")
        leg = {"from": points[i], "to": points[i + 1], "transport": modes[i],
               "departure_at": None, "arrival_at": None,
               "service_ja": service, "departure_platform_ja": platform(edge, "departure"),
               "arrival_platform_ja": platform(edge, "arrival")}
        price = edge.get("priceInfo") or {}
        if price.get("isExpDisplay") and price.get("isExpFirst") and integer(price.get("expPrice")):
            label = price.get("expType")
            if isinstance(label, str) and label and label not in seat_types:
                seat_types.append(label)
        if detail:
            leg["fare_display"] = {k: price.get(k) for k in ["edgeGroup", "price", "expPrice", "expType", "isExpDisplay", "isExpFirst", "cashOnly", "isForecast"]}
            leg["intermediate_stops"] = edge.get("stopStationList") or []
        legs.append(leg)
        for note in [edge.get("preCautionalComment"), edge.get("diaInfoStatus")]:
            if note:
                leg.setdefault("source_notices", []).append(note)
    total = integer(summary.get("totalPrice"))
    transfers = integer(summary.get("transferCount"))
    if total is None or transfers is None:
        changed("Route fare or transfer count is missing.")
    times = node_times(edges, start, end)
    for i, leg in enumerate(legs):
        departure, arrival = times[i][1], times[i + 1][0]
        if departure is None or arrival is None or arrival < departure:
            changed("A route leg has incomplete service/times.")
        leg.update(departure_at=departure.isoformat(), arrival_at=arrival.isoformat())
        if i > 0:
            wait = int((times[i][1] - times[i][0]).total_seconds() / 60)
            waits.append({"station": points[i], "minutes": wait})
    return {"rank": rank, "departure_at": start.isoformat(), "arrival_at": end.isoformat(),
            "duration_minutes": minutes, "transfers": transfers,
            "fare": {"total_jpy": total, "detail_ja": summary.get("totalPriceDetail"), "priced_seat_labels_ja": seat_types},
            "legs": legs, "connection_waits": waits, "modes_used": sorted(set(modes))}


class StripTags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)


def source_info(url, props=None):
    result = {"name": "Yahoo! 路線情報", "url": url, "processed": True,
              "retrieved_at": dt.datetime.now(JST).isoformat(timespec="seconds")}
    if props is not None:
        notices = ((props.get("kousyouResult") or {}).get("detail") or {})
        result["timetable_versions_ja"] = {key: notices[key] for key in ("jr", "shitetsu") if notices.get(key)}
        notice = notices.get("kousyou")
        if isinstance(notice, str):
            parser = StripTags(); parser.feed(notice)
            result["rights_notice_ja"] = " ".join(parser.parts)
    return result
