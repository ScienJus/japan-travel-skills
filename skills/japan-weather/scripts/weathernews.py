"""Weathernews public website adapter. No accounts, browser state or JS execution."""
import datetime as dt
import json
import math
import re
import urllib.parse
from bisect import bisect_right
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


def verified_point_code(payload, location):
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
    return point_jcode


def location_warnings(city):
    warnings = [
        "Publisher issue time is not exposed by this website JSON; issued_at is unknown. Sequence start time and HTTP retrieval time are not issue times.",
        "Forecast is for the website's municipality reference coordinates; it is not a mountain or exact-address forecast.",
    ]
    if municipality_query(city) != city["name"]:
        warnings.append("JMA catalog subdivision " + city["name"] + " resolves to a Weathernews municipality reference point; the subdivision is not independently forecast here.")
    return warnings


def parse_forecast(payload, city, location, dates, now, codes):
    if not isinstance(payload, dict) or not isinstance(payload.get("mrf"), list) or not payload["mrf"]:
        raise WeatherError("source_schema_changed", "Weathernews daily forecast list is missing or empty.")
    point_jcode = verified_point_code(payload, location)
    point = {"name": location["name"], "jcode": point_jcode,
             "latitude": location["latitude"], "longitude": location["longitude"]}
    ref = {"kind": "daily", "issued_at": None, "point": point}
    warnings = location_warnings(city)
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

def hourly_value(row, key, low, high):
    value = row.get(key)
    if value is None or value == "":
        return None
    try:
        if isinstance(value, bool):
            raise ValueError()
        value = float(value)
        if not low <= value <= high:
            raise ValueError()
    except (TypeError, ValueError, OverflowError):
        raise WeatherError("source_schema_changed", "Invalid Weathernews hourly " + key + " value.") from None
    return value


# Entry i is the lower bound of Beaufort force i + 1 in m/s.
WIND_THRESHOLDS = (0.3, 1.6, 3.4, 5.5, 8.0, 10.8, 13.9, 17.2, 20.8, 24.5, 28.5, 32.7)
INTENSITY_LABELS = {
    "zh": {
        "wind": ("静风", "软风", "轻风", "微风", "和风", "清劲风", "强风", "疾风", "大风", "烈风", "狂风", "暴风", "飓风级"),
        "rain": ("小雨", "中雨", "大雨"),
        "precipitation": ("弱降水", "中等降水", "强降水"),
        "dry": "无明显降水",
    },
    "ja": {
        "wind": ("静穏", "至軽風", "軽風", "軟風", "和風", "疾風", "雄風", "強風", "疾強風", "大強風", "全強風", "暴風", "颶風"),
        "rain": ("弱い雨", "中程度の雨", "強い雨"),
        "precipitation": ("弱い降水", "中程度の降水", "強い降水"),
        "dry": "目立った降水なし",
    },
    "en": {
        "wind": ("calm", "light air", "light breeze", "gentle breeze", "moderate breeze",
                 "fresh breeze", "strong breeze", "near gale", "gale", "strong gale",
                 "storm", "violent storm", "hurricane force"),
        "rain": ("light rain", "moderate rain", "heavy rain"),
        "precipitation": ("light precipitation", "moderate precipitation", "heavy precipitation"),
        "dry": "no measurable precipitation",
    },
}


def measurement_display(value, unit, label, lang):
    number_text = str(value).removesuffix(".0")
    suffix = f" ({label})" if lang == "en" else f"（{label}）"
    return f"{number_text} {unit}{suffix}"


def wind_display(speed, lang):
    if speed is None:
        return None
    force = bisect_right(WIND_THRESHOLDS, speed)
    return measurement_display(speed, "m/s", INTENSITY_LABELS[lang]["wind"][force], lang)


def precipitation_display(amount, weather_ja, lang):
    if amount is None:
        return None
    labels = INTENSITY_LABELS[lang]
    label = labels["dry"]
    if amount > 0:
        # Mixed and unspecified phases share the same bands with neutral labels.
        weather = weather_ja or ""
        liquid = "雨" in weather and "雪" not in weather and "みぞれ" not in weather
        band = 0 if amount <= 2.5 else 1 if amount <= 8 else 2
        label = labels["rain" if liquid else "precipitation"][band]
    return measurement_display(amount, "mm", label, lang)


def parse_hourly(payload, city, location, hours, now, codes, lang="zh"):
    if not isinstance(payload, dict) or not isinstance(payload.get("srf"), list):
        raise WeatherError("source_schema_changed", "Weathernews hourly forecast list is missing.")
    point_code = verified_point_code(payload, location)
    current_hour = now.replace(minute=0, second=0, microsecond=0)
    by_time = {}
    for row in payload["srf"]:
        if not isinstance(row, dict):
            raise WeatherError("source_schema_changed", "Invalid Weathernews hourly row.")
        epoch = number(row.get("tm"))
        try:
            instant = dt.datetime.fromtimestamp(epoch, JST) if epoch is not None else None
        except (OSError, OverflowError, ValueError):
            instant = None
        if instant is None or instant.minute or instant.second or instant in by_time:
            raise WeatherError("source_schema_changed", "Expected a unique hourly Weathernews timestamp.")
        by_time[instant] = row

    selected = []
    for hour in hours:
        row = by_time.get(hour, {}) if hour >= current_hour else {}
        code = number(row.get("WX"))
        labels = codes["labels"].get(str(code), []) if code != 999 else []
        values = {"weather_ja": labels[0] if labels else None,
                  "temperature_c": hourly_value(row, "AIRTMP", -100, 70),
                  "precipitation_mm": hourly_value(row, "PREC", 0, 500),
                  "wind_speed_m_s": hourly_value(row, "WNDSPD", 0, 150)}
        missing = [key for key, value in values.items() if value is None]
        status = "unavailable" if len(missing) == len(values) else "partial" if missing else "ok"
        rain = precipitation_display(values["precipitation_mm"], values["weather_ja"], lang)
        wind = wind_display(values["wind_speed_m_s"], lang)
        item = {"time": hour.isoformat(), "status": status, "weather_code": code,
                **values, "missing_fields": missing, "precipitation_display": rain, "wind_display": wind}
        if lang == "zh":
            item.update(precipitation_display_zh=rain, wind_display_zh=wind)
        selected.append(item)
    statuses = {hour["status"] for hour in selected}
    available = sorted(t for t in by_time if t >= current_hour)
    url = location["url"].removesuffix("week.html")
    return {
        "city": {k: city[k] for k in ("query", "code", "name", "name_en", "alias_used")},
        "location": dict({k: v for k, v in location.items() if not k.startswith("_")}, point_jcode=point_code, url=url),
        "status": statuses.pop() if len(statuses) == 1 else "partial", "timezone": "Asia/Tokyo",
        "first_published_hour": available[0].isoformat() if available else None,
        "last_published_hour": available[-1].isoformat() if available else None,
        "issued_at": {"hourly": None}, "hours": selected, "warnings": location_warnings(city),
        "source": {"id": "weathernews", "name": "Weathernews", "url": url, "data_url": data_url(location)},
    }
