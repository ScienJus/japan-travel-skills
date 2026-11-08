#!/usr/bin/env python3
"""Read Japanese city forecasts and official warning snapshots without accounts or browser state."""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

from weather_common import Client, JST, MAX_BYTES, WeatherError, number, timestamp
import weathernews
import jma_alerts
import jma_climate

BASE = "https://www.jma.go.jp/bosai/"
CATALOG_PATH = Path(__file__).resolve().parent / "data/catalog.json"

# These aliases deliberately resolve to a named municipality, not to a prefecture.
# Tokyo is explicitly the Chiyoda ward reference; Toyama is explicitly the plain.
ALIASES = {
    "金泽": "1720100", "金澤": "1720100", "金泽市": "1720100",
    "富山": "1620111", "富山市": "1620111", "toyama": "1620111",
    "东京": "1310100", "東京": "1310100", "tokyo": "1310100",
    "大阪": "2710000", "京都": "2610000", "札幌": "0110000",
    "横滨": "1410011", "横濱": "1410011", "名古屋": "2310000",
    "广岛": "3410100", "廣島": "3410100", "福冈": "4013000",
    "福岡": "4013000", "神户": "2811000", "神戶": "2811000",
    "那霸": "4720100",
    "奈良": "2920101", "长野": "2020111", "長野": "2020111",
    "新潟": "1510000", "镰仓": "1420400", "鎌倉": "1420400",
}


def now_jst():
    return dt.datetime.now(JST)


def normalize(value):
    return unicodedata.normalize("NFKC", value).strip().casefold()


def load_catalog():
    return json.loads(CATALOG_PATH.read_text(encoding="utf-8"))


def city_info(code, catalog):
    areas = catalog["areas"]
    city = areas["class20s"][code]
    local = areas["class15s"][city["parent"]]
    region_code = local["parent"]
    region = areas["class10s"][region_code]
    office_code = region["parent"]
    return {
        "code": code, "name": city["name"], "name_en": city.get("enName"),
        "office_code": office_code, "office": areas["offices"][office_code]["name"],
        "product_code": catalog["office_paths"].get(office_code, office_code),
        "short_range_area": {"code": region_code, "name": region["name"]},
    }


def names(city):
    values = [city["name"], city.get("enName", ""), city.get("kana", "")]
    if city["name"].endswith(("市", "町", "村", "区")):
        values.append(city["name"][:-1])
    for ending in (" City", " Town", " Village", " Ward"):
        if city.get("enName", "").endswith(ending):
            values.append(city["enName"][:-len(ending)])
    return {normalize(x) for x in values if x}


def search_cities(query, catalog, office=None):
    query = normalize(query)
    entries = catalog["areas"]["class20s"]
    alias = ALIASES.get(query)
    exact = [c for c, v in entries.items() if query == c or query in names(v)]
    if alias in entries:
        exact = [alias]
    codes = exact or [c for c, v in entries.items() if any(query in n for n in names(v))]
    results = [city_info(c, catalog) for c in codes]
    return [v for v in results if not office or office in (v["office_code"], v["office"])]


def resolve_city(query, catalog, office=None):
    matches = search_cities(query, catalog, office)
    # A unique substring is a suggestion, not authority to substitute a place.
    if len(matches) == 1:
        code = matches[0]["code"]
        city = catalog["areas"]["class20s"][code]
        if normalize(query) == code or normalize(query) in names(city) or ALIASES.get(normalize(query)) == code:
            return dict(matches[0], query=query, alias_used=ALIASES.get(normalize(query)) == code)
    raise WeatherError(
        "ambiguous_city" if matches else "unknown_city",
        "Use an exact Japanese/English municipality name or a returned municipality code; --office can disambiguate.",
        query=query, candidates=matches[:20], total_candidates=len(matches),
    )


def resolve_alert_city(query, catalog, office=None):
    city = resolve_city(query, catalog, office)
    native = catalog["areas"]["class20s"][city["code"]]
    # Forecast reference aliases must not turn a whole-city warning request
    # into a ward/subdivision result. Explicit native subdivision names/codes
    # remain usable; unambiguous full-municipality aliases such as 金泽 work.
    reference_alias = normalize(query) in ("东京", "東京", "tokyo")
    narrowed = city["alias_used"] and not native["name"].endswith(("市", "町", "村", "区")) and normalize(query) not in names(native)
    if reference_alias or narrowed:
        stem = re.match(r"^.*?[市町村]", native["name"])
        if reference_alias:
            candidates = [info for info in (city_info(code, catalog) for code in catalog["areas"]["class20s"])
                          if info["office_code"] == city["office_code"]]
        else:
            # search_cities applies forecast aliases; use the catalog's names
            # directly for these discovery candidates, without selecting one.
            candidates = [city_info(code, catalog) for code, value in catalog["areas"]["class20s"].items()
                          if value["name"].startswith(stem.group() if stem else native["name"]) and
                          city_info(code, catalog)["office_code"] == city["office_code"]]
        raise WeatherError("alert_scope_required", "This forecast alias identifies only a ward/subdivision. Select the intended exact native area name/code; a citywide alert state was not inferred.",
                           query=query, forecast_reference=city, candidates=candidates[:20], total_candidates=len(candidates))
    return city


def value_at(area, key, index):
    values = area.get(key, [])
    return values[index] if index < len(values) else None


def series_area(product, code, key):
    matches = [(s, a) for s in product.get("timeSeries", []) for a in s.get("areas", [])
               if a.get("area", {}).get("code") == code and key in a]
    if len(matches) > 1:
        raise WeatherError("source_schema_changed", "Multiple series match the same forecast field.")
    return matches[0] if matches else (None, None)


def provenance(product, area, kind):
    return {"area": area["area"], "issued_at": product["reportDatetime"], "kind": kind}


def new_day(date):
    return {"date": date, "weather": None, "temperature": None,
            "precipitation": None, "reliability": None}


def merge_forecast(payload, city, catalog, dates, now):
    if not isinstance(payload, list) or len(payload) != 2:
        raise WeatherError("source_schema_changed", "Expected JMA short-range and weekly products.")
    short, week = payload
    for product in payload:
        if not isinstance(product.get("timeSeries"), list) or not product["timeSeries"]:
            raise WeatherError("source_schema_changed", "Missing forecast time series.")
        timestamp(product["reportDatetime"])
    office = city["office_code"]
    region = city["short_range_area"]["code"]
    days = {}
    warnings = ["Weather is a regional forecast; temperatures are for the named representative station, not every point in the municipality."]
    if city["alias_used"]:
        warnings.append("Input alias resolved to " + city["name"] + "; inspect the resolved municipality.")

    # Seasonal weekly regions can change. Select only codes in JMA's mapping for
    # this short-range region that actually occur in this source response.
    candidates = catalog["week_area_codes"].get(region, [])
    matches = []
    for mapping in catalog["week_areas"].get(office, []):
        if mapping["week"] in candidates:
            series, area = series_area(week, mapping["week"], "weatherCodes")
            if area is not None:
                matches.append((mapping, series, area))
    if len(matches) != 1:
        raise WeatherError("unsupported_forecast_mapping", "Cannot uniquely resolve the weekly forecast area.")
    mapping, series, area = matches[0]
    for i, instant in enumerate(series["timeDefines"]):
        date = timestamp(instant).date().isoformat()
        day = days.setdefault(date, new_day(date))
        code = value_at(area, "weatherCodes", i)
        label = catalog["weather_codes"].get(code)
        if code:
            day["weather"] = dict(provenance(week, area, "weekly"), code=code,
                                  text_ja=label["ja"] if label else None,
                                  text_en=label["en"] if label else None)
            if not label:
                warnings.append("Unrecognized JMA weather code: " + code)
        day["precipitation"] = dict(provenance(week, area, "weekly"),
                                    daily_percent=number(value_at(area, "pops", i)), periods=[])
        day["reliability"] = value_at(area, "reliabilities", i) or None

    series, area = series_area(week, mapping["amedas"], "tempsMin")
    if area is not None:
        for i, instant in enumerate(series["timeDefines"]):
            date = timestamp(instant).date().isoformat()
            day = days.setdefault(date, new_day(date))
            day["temperature"] = {
                "station": area["area"], "issued_at": week["reportDatetime"], "kind": "weekly",
                "min_c": number(value_at(area, "tempsMin", i)),
                "max_c": number(value_at(area, "tempsMax", i)),
                "min_range_c": [number(value_at(area, k, i)) for k in ("tempsMinLower", "tempsMinUpper")],
                "max_range_c": [number(value_at(area, k, i)) for k in ("tempsMaxLower", "tempsMaxUpper")],
            }

    series, area = series_area(short, region, "weatherCodes")
    if area is not None:
        for i, instant in enumerate(series["timeDefines"]):
            date = timestamp(instant).date().isoformat()
            day = days.setdefault(date, new_day(date))
            code = value_at(area, "weatherCodes", i)
            if not code:
                continue
            label = catalog["weather_codes"].get(code, {})
            day["weather"] = dict(provenance(short, area, "short_range"), code=code,
                                  text_ja=value_at(area, "weathers", i) or label.get("ja"),
                                  text_en=label.get("en"), wind_ja=value_at(area, "winds", i))
            # Weekly A/B/C describes the weekly precipitation forecast, not this
            # replacement short-range weather forecast.
            day["reliability"] = None

    series, area = series_area(short, region, "pops")
    if area is not None:
        for i, instant in enumerate(series["timeDefines"]):
            start = timestamp(instant)
            date = start.date().isoformat()
            day = days.setdefault(date, new_day(date))
            if not day["precipitation"] or day["precipitation"]["kind"] != "short_range":
                day["precipitation"] = dict(provenance(short, area, "short_range"), daily_percent=None, periods=[])
            day["precipitation"]["periods"].append({
                "start": start.isoformat(), "end": (start + dt.timedelta(hours=6)).isoformat(),
                "percent": number(value_at(area, "pops", i)),
            })

    # Use JMA's explicit representative station for this short-range region.
    # It may differ from the weekly station; never silently carry one station's
    # values or uncertainty ranges into another station's temperature record.
    short_mappings = [m for m in catalog["short_areas"].get(office, []) if m["class10"] == region]
    if len(short_mappings) == 1:
        stations = short_mappings[0]["amedas"]
        if stations:
            series, area = series_area(short, stations[0], "temps")
            if area is not None:
                for i, instant in enumerate(series["timeDefines"]):
                    point = timestamp(instant)
                    # JMA labels 00:00 slots as minimum and 09:00 as maximum.
                    # Morning/11:00 products can also include today's maximum.
                    if point.hour not in (0, 9):
                        continue
                    val = number(value_at(area, "temps", i))
                    if val is None:
                        continue
                    date = point.date().isoformat()
                    day = days.setdefault(date, new_day(date))
                    if not day["temperature"] or day["temperature"]["kind"] != "short_range":
                        day["temperature"] = {"station": area["area"], "kind": "short_range",
                                              "issued_at": short["reportDatetime"], "min_c": None,
                                              "max_c": None, "min_range_c": None, "max_range_c": None}
                    day["temperature"]["min_c" if point.hour == 0 else "max_c"] = val

    available_dates = sorted(d for d, v in days.items() if v["weather"])
    output_days = []
    for date in dates:
        day = days.get(date, new_day(date))
        missing = []
        if not day["weather"]:
            missing.append("weather")
        temp = day["temperature"] or {}
        for key in ("min_c", "max_c"):
            if temp.get(key) is None:
                missing.append("temperature." + key)
        precip = day["precipitation"] or {}
        if precip.get("daily_percent") is None and not any(p["percent"] is not None for p in precip.get("periods", [])):
            missing.append("precipitation")
        day["missing_fields"] = missing
        day["status"] = "unavailable" if not day["weather"] else "partial" if missing else "ok"
        output_days.append(day)
    for kind, product in (("short_range", short), ("weekly", week)):
        age = (now - timestamp(product["reportDatetime"])).total_seconds()
        if age > 36 * 3600:
            warnings.append(kind + " product was issued over 36 hours ago; do not describe it as current.")
        if age < -600:
            warnings.append(kind + " issue time is ahead of the local clock; check clock/source alignment.")
    status = "ok" if all(d["status"] == "ok" for d in output_days) else "partial"
    if all(d["status"] == "unavailable" for d in output_days):
        status = "unavailable"
    return {
        "city": city, "status": status, "timezone": "Asia/Tokyo",
        "available_dates": available_dates, "days": output_days,
        "issued_at": {"short_range": short["reportDatetime"], "weekly": week["reportDatetime"]},
        "warnings": warnings,
        "source": {"id": "jma", "name": "Japan Meteorological Agency", "publisher": short.get("publishingOffice"),
                   "url": BASE + "forecast/#area_type=class20s&area_code=" + city["code"],
                   "data_url": BASE + "forecast/data/forecast/" + city["product_code"] + ".json",
                   "processing": "Selected and normalized from JMA products; no independent forecast or interpolation."},
    }


def compact_forecast(forecast):
    """Deduplicate field provenance while retaining scope and missing values."""
    result = {k: v for k, v in forecast.items() if k != "days"}
    references = {}
    days = []
    for day in forecast["days"]:
        item = {"date": day["date"], "status": day["status"],
                "weather_ja": (day["weather"] or {}).get("text_ja"),
                "weather_code": (day["weather"] or {}).get("code"),
                "temperature_c": [(day["temperature"] or {}).get(k) for k in ("min_c", "max_c")],
                "precipitation_percent": (day["precipitation"] or {}).get("daily_percent"),
                "reliability": day["reliability"], "sources": {}}
        for field in ("weather", "temperature", "precipitation"):
            record = day[field]
            if record is None:
                continue
            ref = {k: record[k] for k in ("kind", "issued_at", "area", "station", "point") if k in record}
            key = field + "_" + record["kind"]
            if key in references and references[key] != ref:
                raise WeatherError("source_schema_changed", "Inconsistent field provenance within one forecast.")
            references[key] = ref
            item["sources"][field] = key
        periods = (day["precipitation"] or {}).get("periods", [])
        if periods:
            item["precipitation_6h"] = []
            for period in periods:
                start, end = timestamp(period["start"]), timestamp(period["end"])
                end_hour = "24:00" if end.date() > start.date() else end.strftime("%H:%M")
                item["precipitation_6h"].append({"hours": start.strftime("%H:%M") + "-" + end_hour, "percent": period["percent"]})
        if day["missing_fields"]:
            item["missing_fields"] = day["missing_fields"]
        days.append(item)
    result["field_sources"] = references
    result["days"] = days
    return result


def iso_date(text):
    try:
        return dt.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError("Use YYYY-MM-DD.") from None


def bounded_days(value):
    n = int(value)
    if not 1 <= n <= 14:
        raise argparse.ArgumentTypeError("Days must be between 1 and 14.")
    return n


def requested_dates(args, now):
    today = now.date()
    if args.date:
        start = end = args.date
    elif args.start or args.end:
        if not args.start or not args.end:
            raise WeatherError("invalid_date_range", "--from and --to must be supplied together.")
        start, end = args.start, args.end
    else:
        start = today + dt.timedelta(days=1)
        default_days = 7 if args.source == "jma" else 14
        end = start + dt.timedelta(days=(args.days or default_days) - 1)
    if start < today or end < start or (end - start).days >= 14:
        raise WeatherError("invalid_date_range", "Use today/future dates and a range of at most 14 dates, with --to on or after --from.")
    return [(start + dt.timedelta(days=i)).isoformat() for i in range((end - start).days + 1)]


def parser():
    root = argparse.ArgumentParser(description="Japanese forecasts, JMA warnings and monthly station climate normals. Anonymous JSON output; no dependencies.")
    sub = root.add_subparsers(dest="command", required=True)
    jma_climate.add_parsers(sub)
    sub.add_parser("doctor", help="Offline runtime and catalog checks")
    cities = sub.add_parser("cities", help="Offline Japanese/English municipality search")
    cities.add_argument("query")
    cities.add_argument("--office", help="JMA office code or exact Japanese office area name")
    cities.add_argument("--limit", type=int, default=10)
    forecast = sub.add_parser("forecast", help="Get website daily forecasts from one or both Japanese sources")
    forecast.add_argument("--source", choices=("weathernews", "jma", "both"), default="weathernews", help="Default weathernews (two weeks); jma retains official regional forecasts; both returns separate records")
    forecast.add_argument("--city", required=True, action="append", help="Exact municipality name/alias/code; repeat for up to 10 cities")
    forecast.add_argument("--office", help="Disambiguate municipality by office code/name")
    group = forecast.add_mutually_exclusive_group()
    group.add_argument("--days", type=bounded_days, help="1-14 dates starting tomorrow in JST; default 14 (JMA: 7)")
    group.add_argument("--date", type=iso_date, help="One exact JST date")
    group.add_argument("--from", dest="start", type=iso_date, help="First JST date, inclusive; requires --to")
    forecast.add_argument("--to", dest="end", type=iso_date, help="Last JST date, inclusive; requires --from")
    forecast.add_argument("--timeout", type=float, default=15, help="Per-request timeout in seconds (1-60; default 15)")
    forecast.add_argument("--detail", action="store_true", help="Include original field structure, English labels, wind and temperature uncertainty bounds")
    alerts = sub.add_parser("alerts", help="Current timestamped JMA meteorological warnings/advisories from the official XML aggregate")
    alerts.add_argument("--city", required=True, action="append", help="Exact municipality/subdivision name/code; repeat for up to 10 areas")
    alerts.add_argument("--office", help="Disambiguate municipality by office code/name")
    alerts.add_argument("--timeout", type=float, default=15, help="Per-request socket timeout (1-60 seconds)")
    alerts.add_argument("--detail", action="store_true", help="Include previous warning identity as context, never as a current warning")
    return root


def main(argv=None):
    args = parser().parse_args(argv)
    if args.command in ("climate", "climate-stations", "climate-regions"):
        return jma_climate.main(args)
    client = Client()
    try:
        catalog = load_catalog()
        if args.command == "doctor":
            result = {"status": "ok", "python": sys.version.split()[0], "dependencies": "Python standard library only",
                      "municipalities": len(catalog["areas"]["class20s"]), "catalog_retrieved_at": catalog["retrieved_at"],
                      "weathernews_icon_codes": len(weathernews.load_codes()["labels"]),
                      "sources": ["weathernews", "jma"], "network_checked": False}
        elif args.command == "cities":
            if not args.query.strip() or not 1 <= args.limit <= 100:
                raise WeatherError("invalid_query", "Provide a nonempty city query and --limit between 1 and 100.")
            matches = search_cities(args.query, catalog, args.office)
            result = {"status": "ok", "cities": matches[:args.limit], "total_matches": len(matches),
                      "catalog_retrieved_at": catalog["retrieved_at"]}
        elif args.command == "alerts":
            if not 1 <= len(args.city) <= 10 or not 1 <= args.timeout <= 60:
                raise WeatherError("invalid_options", "Use up to 10 cities and a timeout from 1 to 60 seconds.")
            cities = [resolve_alert_city(query, catalog, args.office) for query in args.city]
            client = jma_alerts.Client(timeout=args.timeout)
            result = jma_alerts.query(client, cities, catalog, now_jst, args.detail)
        else:
            if not 1 <= len(args.city) <= 10 or not 1 <= args.timeout <= 60:
                raise WeatherError("invalid_options", "Use up to 10 cities and a timeout from 1 to 60 seconds.")
            if args.end and not args.start:
                raise WeatherError("invalid_date_range", "--to requires --from.")
            client.timeout = args.timeout
            now = now_jst()
            dates = requested_dates(args, now)
            cities = [resolve_city(query, catalog, args.office) for query in args.city]
            forecasts = []
            for city in cities:
                if args.source in ("weathernews", "both"):
                    location = weathernews.find_location(client, city)
                    forecasts.append(weathernews.parse_forecast(
                        client.get_json(weathernews.data_url(location)), city, location, dates, now, weathernews.load_codes()))
                if args.source in ("jma", "both"):
                    forecasts.append(merge_forecast(client.get(city["product_code"]), city, catalog, dates, now))
            status = "ok" if all(x["status"] == "ok" for x in forecasts) else "partial"
            if all(x["status"] == "unavailable" for x in forecasts):
                status = "unavailable"
            result = {"status": status,
                      "retrieved_at": now_jst().isoformat(), "requested_dates": dates,
                      "catalog_retrieved_at": catalog["retrieved_at"],
                      "format": "detail" if args.detail else "compact",
                      "forecasts": forecasts if args.detail else [compact_forecast(f) for f in forecasts]}
        result["usage"] = client.usage()
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except WeatherError as exc:
        result = {"status": "error", "error": {"code": exc.code, "message": str(exc), **exc.details}, "usage": client.usage()}
    except (KeyError, TypeError, IndexError, ValueError, AttributeError, OverflowError, RecursionError):
        message = "Unexpected catalog/alert structure; alert status could not be confirmed." if args.command == "alerts" else "Unexpected catalog/forecast structure; no missing values were fabricated."
        result = {"status": "error", "error": {"code": "source_schema_changed", "message": message}, "usage": client.usage()}
    except OSError:
        result = {"status": "error", "error": {"code": "catalog_unavailable", "message": "Cannot read the bundled catalog."}, "usage": client.usage()}
    if args.command == "alerts":
        result["alert_state"] = "unknown"
        result["manual_check_url"] = jma_alerts.PAGE_URL
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 2


if __name__ == "__main__":
    sys.exit(main())
