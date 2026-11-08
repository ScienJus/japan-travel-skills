"""Weathernews public website adapter. No accounts, browser state or JS execution."""
import datetime as dt
import json
import math
import re
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

from weather_common import JST, WeatherError, number

SEARCH_URL = "https://weathernews.jp/onebox/api_search.cgi"
DATA_URL = "https://site.weathernews.jp/lba/wxdata/api_data_ss1/v2"
LEGEND_URL = "https://wxtech.weathernews.com/products/data/api/table/wxcode-forecast/"
CODES_PATH = Path(__file__).resolve().parent / "data/weathernews_codes.json"


class IconLegendParser(HTMLParser):
    """Extract code/short-label pairs from the publisher's forecast code table."""
    def __init__(self):
        super().__init__()
        self.cells = []
        self.capture = False
        self.parts = []
        self.labels = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr":
            self.cells = []
        if tag == "td":
            self.capture = True
            self.parts = []

    def handle_data(self, data):
        if self.capture:
            self.parts.append(data)

    def handle_endtag(self, tag):
        if tag == "td" and self.capture:
            label = "".join(self.parts).strip()
            self.cells.append(label)
            self.capture = False
        if tag == "tr" and len(self.cells) >= 2 and re.fullmatch(r"\d{3}", self.cells[0]):
            code, label = self.cells[:2]
            if label and label not in self.labels.setdefault(code, []):
                self.labels[code].append(label)


def load_codes():
    return json.loads(CODES_PATH.read_text(encoding="utf-8"))


def municipality_query(city):
    # JMA sometimes splits a municipality into plains/mountain/directional areas.
    # Weathernews lookup is by municipality; preserve that scope change below.
    match = re.match(r"^(.+[市区町村])", city["name"])
    return match.group(1) if match else city["name"]


def resolve_location(rows, city):
    if not isinstance(rows, list):
        raise WeatherError("source_schema_changed", "Weathernews search response is not a list.")
    code = city["code"][:5]
    matches = {}
    for row in rows:
        if not isinstance(row, dict):
            raise WeatherError("source_schema_changed", "Invalid Weathernews location entry.")
        url = urllib.parse.urlsplit(urllib.parse.urljoin("https://weathernews.jp", row.get("url", "")))
        route = re.fullmatch(r"/onebox/tenki/([a-z]+)/([0-9]{5})/(?:week\.html)?", url.path)
        if url.scheme != "https" or url.netloc != "weathernews.jp" or not route or route.group(2) != code:
            continue
        lat, lon = float(row["lat"]), float(row["lon"])
        if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise WeatherError("source_schema_changed", "Invalid Weathernews coordinates.")
        location = {"name": row.get("loc") or row.get("q"), "jcode": code,
                    "latitude": lat, "longitude": lon,
                    "url": "https://weathernews.jp/onebox/tenki/" + route.group(1) + "/" + code + "/week.html",
                    "scope": "municipality_reference_point"}
        matches[(lat, lon, location["url"])] = location
    if len(matches) != 1:
        raise WeatherError("weathernews_location_unresolved", "Weathernews did not return one matching municipality reference point; no neighboring place was substituted.",
                           municipality=city["name"], expected_jcode=code,
                           candidates=[{"name": r.get("loc"), "url": r.get("url")} for r in rows[:10] if isinstance(r, dict)])
    location = next(iter(matches.values()))
    # Designated-city search results explicitly list the city and its wards.
    # The city reference point's reverse-geocoded JCODE can be one of those wards.
    # Accept only relationships present in that same native search response.
    # City codes do not share a fixed suffix (for example Fukuoka is 40130).
    location["_point_jcodes"] = [code]
    if municipality_query(city).endswith("市"):
        for row in rows:
            name = row.get("loc", "")
            url = urllib.parse.urlsplit(urllib.parse.urljoin("https://weathernews.jp", row.get("url", "")))
            route = re.fullmatch(r"/onebox/tenki/([a-z]+)/([0-9]{5})/(?:week\.html)?", url.path)
            same_parent = any(name.startswith(parent) and name[len(parent):].endswith("区")
                              for parent in (location["name"], municipality_query(city)))
            if (same_parent and url.scheme == "https" and url.netloc == "weathernews.jp"
                    and route and route.group(2)[:2] == code[:2]
                    and route.group(1) == urllib.parse.urlsplit(location["url"]).path.split("/")[3]):
                location["_point_jcodes"].append(route.group(2))
    return location


def find_location(client, city):
    params = urllib.parse.urlencode({"query": municipality_query(city), "lang": ""})
    return resolve_location(client.get_json(SEARCH_URL + "?" + params), city)


def data_url(location):
    return DATA_URL + "?" + urllib.parse.urlencode({"lat": location["latitude"], "lon": location["longitude"]})


def parse_forecast(payload, city, location, dates, now, codes):
    if not isinstance(payload, dict) or not isinstance(payload.get("mrf"), list) or not payload["mrf"]:
        raise WeatherError("source_schema_changed", "Weathernews daily forecast list is missing or empty.")
    geo = payload.get("geo", {})
    point_jcode = str(geo.get("JCODE"))
    if payload.get("is_japan") != 1 or point_jcode not in location.get("_point_jcodes", [location["jcode"]]):
        raise WeatherError("weathernews_location_mismatch", "Forecast data belongs to a different municipality.")
    try:
        point_matches = all(abs(float(geo[k]) - location[v]) < 0.001 for k, v in (("lat", "latitude"), ("lon", "longitude")))
    except (KeyError, TypeError, ValueError):
        point_matches = False
    if not point_matches:
        raise WeatherError("weathernews_location_mismatch", "Forecast coordinates differ from the resolved reference point.")
    point = {"name": location["name"], "jcode": point_jcode,
             "latitude": location["latitude"], "longitude": location["longitude"]}
    ref = {"kind": "daily", "issued_at": None, "point": point}
    warnings = [
        "Publisher issue time is not exposed by this website JSON; issued_at is unknown. Sequence start time and HTTP retrieval time are not issue times.",
        "Forecast is for the website's municipality reference coordinates; it is not a mountain or exact-address forecast.",
    ]
    if municipality_query(city) != city["name"]:
        warnings.append("JMA catalog subdivision " + city["name"] + " resolves to a Weathernews municipality reference point; the subdivision is not independently forecast here.")
    days = {}
    for row in payload["mrf"]:
        if not isinstance(row, dict):
            raise WeatherError("source_schema_changed", "Invalid Weathernews daily forecast row.")
        instant = dt.datetime.fromtimestamp(number(row["tm"]), JST)
        if instant.time() != dt.time(0):
            raise WeatherError("source_schema_changed", "Weathernews daily timestamp is not a JST day boundary.")
        date = instant.date().isoformat()
        if date in days:
            raise WeatherError("source_schema_changed", "Duplicate Weathernews daily forecast date.")
        wx = number(row.get("WX"))
        labels = codes["labels"].get(str(wx), []) if wx != 999 else []
        minimum, maximum, pop = (number(row.get(k)) for k in ("MINT", "MAXT", "POP"))
        if any(v is not None and not -100 <= v <= 70 for v in (minimum, maximum)) or (minimum is not None and maximum is not None and minimum > maximum):
            raise WeatherError("source_schema_changed", "Invalid Weathernews temperature; no sentinel value was treated as a real temperature.")
        if pop is not None and not 0 <= pop <= 100:
            raise WeatherError("source_schema_changed", "Invalid Weathernews precipitation probability.")
        reliability = row.get("reliability") or None
        if reliability is not None and reliability not in ("A", "B", "C", "D", "E"):
            raise WeatherError("source_schema_changed", "Unrecognized Weathernews reliability grade.")
        missing = []
        if wx is None or not labels:
            missing.append("weather")
            if wx == 999:
                warnings.append("Weathernews code 999 explicitly marks No Data.")
            elif wx is not None:
                warnings.append("Unknown Weathernews weather icon code " + str(wx) + "; retained without a guessed description.")
        if minimum is None:
            missing.append("temperature.min_c")
        if maximum is None:
            missing.append("temperature.max_c")
        if pop is None:
            missing.append("precipitation")
        days[date] = {
            "date": date, "status": "partial" if missing else "ok", "missing_fields": missing,
            "weather": dict(ref, code=str(wx) if wx is not None else None,
                            code_system="weathernews", text_ja=labels[0] if labels else None,
                            text_origin="publisher_code_table"),
            "temperature": dict(ref, min_c=minimum, max_c=maximum),
            "precipitation": dict(ref, daily_percent=pop, periods=[]),
            "reliability": reliability,
        }
    available_dates = sorted(days)
    # Website coverage is today + 14 days. Cap exposure even if the upstream
    # unexpectedly adds longer-range rows, while retaining honest missing dates.
    horizon_end = now.date() + dt.timedelta(days=14)
    available_dates = [d for d in available_dates if now.date() <= dt.date.fromisoformat(d) <= horizon_end]
    selected = []
    for date in dates:
        if date in available_dates:
            selected.append(days[date])
        else:
            selected.append({"date": date, "status": "unavailable", "weather": None,
                             "temperature": None, "precipitation": None, "reliability": None,
                             "missing_fields": ["weather", "temperature.min_c", "temperature.max_c", "precipitation"]})
    status = "ok" if all(d["status"] == "ok" for d in selected) else "partial"
    if all(d["status"] == "unavailable" for d in selected):
        status = "unavailable"
    if max(days) < now.date().isoformat():
        warnings.append("All returned forecast dates are in the past; this response cannot answer upcoming weather.")
    return {
        "city": {k: city[k] for k in ("query", "code", "name", "name_en", "alias_used")},
        "location": dict({k: v for k, v in location.items() if not k.startswith("_")}, point_jcode=point_jcode),
        "status": status, "timezone": "Asia/Tokyo",
        "available_dates": available_dates, "issued_at": {"daily": None}, "days": selected,
        "reliability_scale": {"source": "weathernews", "grades": ["A", "B", "C", "D", "E"],
                              "meaning": "Precipitation occurrence forecast reliability; A highest. Not interchangeable with JMA A/B/C."},
        "warnings": warnings,
        "source": {"id": "weathernews", "name": "Weathernews", "publisher": "株式会社ウェザーニューズ",
                   "url": location["url"], "data_url": data_url(location),
                   "processing": "Selected daily website JSON fields; weather labels from publisher's forecast code table. No forecast interpolation or independent prediction."},
    }
