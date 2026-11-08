"""Validation and pure domain rules shared by network and offline commands."""
import calendar
import math
import re
from datetime import date, datetime, timedelta, timezone
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

JST = timezone(timedelta(hours=9))
BASE = "https://tabelog.com"
STOP_CODES = {"rate_limited", "request_budget", "access_denied", "verification_required", "service_unavailable", "retry_later"}
RESTAURANT_PATH = re.compile(r"/(?:en/|cn/|tw/|kr/|th/)?([a-z]+/A\d{4}/A\d{6}/(\d+))/?(?:$|[?#])")


class CliError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details

    def as_dict(self):
        return {"code": self.code, "message": str(self), **self.details}


def stamp():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def today_japan():
    return datetime.now(JST).date().isoformat()


def date_value(value):
    try:
        if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value) or date.fromisoformat(value).isoformat() != value:
            raise ValueError()
    except (ValueError, TypeError):
        raise CliError("invalid_argument", "Expected a valid YYYY-MM-DD date.") from None
    return value


def time_value(value):
    if not isinstance(value, str) or not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
        raise CliError("invalid_argument", "Expected HH:MM in Japan time.")
    return value


def date_range(start, end):
    first, last = date.fromisoformat(date_value(start)), date.fromisoformat(date_value(end))
    count = (last-first).days + 1
    if not 1 <= count <= 31:
        raise CliError("invalid_argument", "Expected a date window of 1..31 days.")
    return [(first + timedelta(days=i)).isoformat() for i in range(count)]


def month_ago(value=None):
    d = date.fromisoformat(value or today_japan())
    year, month = (d.year, d.month-1) if d.month > 1 else (d.year-1, 12)
    return date(year, month, min(d.day, calendar.monthrange(year, month)[1])).isoformat()


def public_url(value):
    try:
        u = urlsplit(value)
        allowed = u.hostname in {"tabelog.com", "award.tabelog.com", "msearch.gsi.go.jp"} or (
            u.hostname == 's.tabelog.com' and re.fullmatch(r'/en/TopRestaurants/(?:|(?:[a-z]+/)?rstLst/)', u.path)) or (
            u.hostname == 'selection.tabelog.com' and re.fullmatch(r'/(?:[a-z]+/)?rstLst/(?:\d+/)?', u.path)) or (
            u.hostname == 'photon.komoot.io' and u.path in ('/api', '/api/')) or (
            u.hostname == "tblg.k-img.com" and u.path.startswith("/javascripts/assets/") and u.path.endswith(".js"))
        if u.scheme != "https" or not allowed or u.username or u.password or u.port not in (None, 443):
            raise ValueError()
        return u.geturl()
    except (ValueError, TypeError):
        raise CliError("invalid_url", "Only HTTPS URLs on supported Tabelog/geocoding endpoints are accepted.") from None


def safe_url(value):
    u = urlsplit(public_url(value))
    query = [(k, v) for k, v in parse_qsl(u.query, keep_blank_values=True) if not re.search(r"token|cookie|__cf_|csrf", k, re.I)]
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(query), ""))


def endpoint(path, params=None):
    return BASE + path + "?" + urlencode(params or {})


def point_value(value):
    try:
        values = value.split(",") if isinstance(value, str) else value
        if len(values) != 2 or any(isinstance(x, bool) or x is None or str(x).strip() == "" for x in values):
            raise ValueError()
        lat, lon = map(float, values)
        if not math.isfinite(lat) or not math.isfinite(lon) or abs(lat) > 90 or abs(lon) > 180:
            raise ValueError()
        return {"latitude": lat, "longitude": lon}
    except (TypeError, ValueError):
        raise CliError("invalid_argument", "Expected latitude,longitude in WGS84.") from None


def distance(a, b):
    la, lb = math.radians(a["latitude"]), math.radians(b["latitude"])
    h = math.sin((lb-la)/2)**2 + math.cos(la)*math.cos(lb)*math.sin(math.radians(b["longitude"]-a["longitude"])/2)**2
    return 2*6371008.8*math.asin(math.sqrt(max(0, min(1, h))))


CUISINES = {
    "寿司": ["寿司", "鮨", "sushi"], "烧鸟": ["焼き鳥", "焼鳥", "yakitori"], "烧肉": ["焼肉", "yakiniku"],
    "拉面": ["ラーメン", "ramen"], "法餐": ["フレンチ", "french"], "意餐": ["イタリアン", "italian"],
    "居酒屋": ["居酒屋", "izakaya"], "天妇罗": ["天ぷら", "天麩羅", "tempura"], "荞麦面": ["そば", "蕎麦", "soba"],
    "乌冬": ["うどん", "udon"], "鳗鱼": ["うなぎ", "鰻", "unagi"],
    "日料": ["日本料理", "和食", "japanese", "寿司", "鮨", "sushi", "焼き鳥", "yakitori", "天ぷら", "tempura", "そば", "soba", "うどん", "udon", "うなぎ", "unagi", "懐石", "kaiseki"],
}


def cuisine_matches(actual, wanted):
    text = "|".join(actual).lower()
    return not wanted or any(alias.lower() in text for w in wanted for alias in CUISINES.get(w, [w]))


def retail_only(cuisines):
    pattern = r"和菓子|洋菓子|ケーキ|チョコレート|せんべい|大福|どら焼き|たい焼き・大判焼き|ソフトクリーム|ジェラート・アイスクリーム|Japanese sweets|Western sweets|Cake|Chocolate|Confectionery|Wagashi|Ice cream|Soft serve"
    return bool(cuisines) and all(re.fullmatch(pattern, c.strip(), re.I) for c in cuisines)


def meal_schedule(item, meal):
    if meal not in ("lunch", "dinner"):
        raise CliError("invalid_argument", "Meal must be lunch or dinner.")
    start, end = (660, 840) if meal == "lunch" else (1020, 1260)
    regular = []
    for group in item.get("hours", []):
        ranges = [r for r in group["rangeList"] if r["open"] < end and r["close"] > start]
        if not group["closed"] and group["dayList"] and ranges:
            regular.append({**group, "rangeList": ranges})
    return {"meal": meal, "status": "retail_only" if retail_only(item.get("cuisines", [])) else "confirmed_regular_schedule" if regular else "no_regular_overlap" if item.get("hours") else "unknown",
            "window": "11:00–14:00" if meal == "lunch" else "17:00–21:00", "regular_schedule": regular,
            "notes": [r for r in item.get("info", []) if re.search(r"business hours|reservation availability|remarks", r["label"], re.I)],
            "warning": "Regular hours overlap the meal window on at least one weekday; not a specific visit-date or menu/seat availability guarantee. Read free-text exceptions."}


def calendar_decision(raw):
    meanings = {0: "not_selectable_online", 1: "limited", 2: "available", 3: "closed", 4: "telephone_only"}
    known = type(raw) is int and raw in meanings
    return {"hint": meanings[raw] if known else "unknown", "skip_online_slots": known and raw in (0, 3, 4)}


def people_ranges(values):
    """Compress only consecutive, explicitly observed party sizes."""
    ranges = []
    for value in sorted(set(values)):
        if ranges and value == ranges[-1]['max'] + 1:
            ranges[-1]['max'] = value
        else:
            ranges.append({'min': value, 'max': value})
    return ranges


def review_window(visited, since, until, now=None):
    now = now or today_japan()
    value = visited or ""
    months = list(calendar.month_name)[1:]
    english = re.search(r"(?:Visited on )?("+"|".join(months)+r")(?:\s+(\d{1,2}))?,?\s+(20\d{2})", value, re.I)
    if english:
        month = next(i+1 for i, m in enumerate(months) if m.lower() == english[1].lower())
        value = f"{english[3]}/{month:02d}" + (f"/{english[2]}" if english[2] else "")
    exact = re.search(r"(\d{4})[/-](\d{1,2})[/-](\d{1,2})(?!\d)", value)
    month = re.search(r"(\d{4})[/-](\d{1,2})(?!\d)", value)
    unknown = {"precision": "unknown", "date": None, "window": "undated"}
    if not month:
        return unknown
    try:
        year, m = int(month[1]), int(month[2])
        lo = date(year, m, int(exact[3]) if exact else 1).isoformat()
        hi = lo if exact else now if lo[:7] == now[:7] else date(year, m, calendar.monthrange(year, m)[1]).isoformat()
    except ValueError:
        return unknown
    window = "future_anomaly" if lo > now else "outside_window" if hi < since or lo > until else "in_window" if lo >= since and hi <= until else "boundary_uncertain"
    return {"precision": "day" if exact else "month", "date": lo if exact else lo[:7], "window": window}
