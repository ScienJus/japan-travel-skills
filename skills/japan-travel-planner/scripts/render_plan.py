#!/usr/bin/env python3
"""Render a researched plan as a local HTML guide or a presentation brief. No queries."""

import argparse
import datetime as dt
import hashlib
from html import escape
import base64
import json
import math
from pathlib import Path
import re
from urllib.parse import urlsplit


SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
MAX_BYTES = 2 * 1024 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}\Z")
ROLES = {"fixed", "selected", "candidate", "backup"}
EVIDENCE = {"verified", "unverified", "illustrative"}
KINDS = {"hotel", "attraction", "restaurant", "transport"}

GUIDE_LABELS = {
    "en": {
        "SKIP": "Skip to itinerary", "NOTEBOOK": "JAPAN / TRAVEL NOTEBOOK", "DAYS": "Days",
        "PLACES": "PLACES / ORIENTATION", "ZOOM_IN": "Zoom in", "ZOOM_OUT": "Zoom out",
        "MAP": "Place locations", "BEFORE": "BEFORE YOU GO",
        "NOSCRIPT": "Enable JavaScript to use the day views and place list. Keep the original plan JSON as a companion file.",
    },
    "zh-CN": {
        "SKIP": "跳到行程", "NOTEBOOK": "日本 / 旅行手记", "DAYS": "行程日期",
        "PLACES": "地点 / 位置参考", "ZOOM_IN": "放大", "ZOOM_OUT": "缩小",
        "MAP": "地点位置", "BEFORE": "出发之前",
        "NOSCRIPT": "启用 JavaScript 即可查看每日行程和地点清单。请保留原始行程 JSON 作为配套文件。",
    },
    "ja": {
        "SKIP": "旅程へ移動", "NOTEBOOK": "日本 / 旅のしおり", "DAYS": "旅行日",
        "PLACES": "訪問先 / 位置の目安", "ZOOM_IN": "拡大", "ZOOM_OUT": "縮小",
        "MAP": "訪問先の位置", "BEFORE": "出発前に",
        "NOSCRIPT": "日ごとの旅程と訪問先の一覧を使うにはJavaScriptを有効にしてください。元の旅程JSONも一緒に保管してください。",
    },
}


class PlanError(ValueError):
    """A field location and fixed message, without echoing supplied values."""


def require(condition, field, message):
    if not condition:
        raise PlanError(field + ": " + message)


def obj(value, allowed, required, field):
    require(isinstance(value, dict), field, "expected an object")
    require(set(value) <= set(allowed), field, "unexpected fields; remove private or unsupported data")
    require(set(required) <= set(value), field, "missing required fields")


def text(value, field, maximum=2000):
    require(isinstance(value, str) and bool(value.strip()) and len(value) <= maximum,
            field, "expected bounded text")


def array(value, field, maximum=200):
    require(isinstance(value, list) and len(value) <= maximum, field, "expected a bounded list")


def identifier(value, field):
    require(isinstance(value, str) and ID.fullmatch(value), field, "expected an identifier")


def date(value, field):
    try:
        require(isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value), field,
                "expected YYYY-MM-DD")
        dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        raise PlanError(field + ": expected a valid YYYY-MM-DD date") from None


def url(value, field):
    text(value, field)
    try:
        parsed = urlsplit(value)
        valid = (parsed.scheme == "https" and parsed.hostname and not parsed.username
                 and not parsed.password and not any(c.isspace() or ord(c) < 32 for c in value))
    except ValueError:
        valid = False
    require(valid, field, "expected an HTTPS URL without credentials")


def sources(value, field):
    array(value, field, 20)
    for index, source in enumerate(value):
        at = "{}[{}]".format(field, index)
        obj(source, {"title", "url", "checked_on", "scope"}, {"title", "url"}, at)
        text(source["title"], at + ".title", 200)
        url(source["url"], at + ".url")
        if "checked_on" in source:
            date(source["checked_on"], at + ".checked_on")
        if "scope" in source:
            text(source["scope"], at + ".scope")


def records(plan, key, allowed, required, maximum=200):
    array(plan[key], key, maximum)
    seen = set()
    for index, record in enumerate(plan[key]):
        at = "{}[{}]".format(key, index)
        obj(record, allowed | {"id"}, required | {"id"}, at)
        identifier(record["id"], at + ".id")
        require(record["id"] not in seen, at + ".id", "duplicate identifier")
        seen.add(record["id"])
        yield record, at


def validate(plan):
    """Validate relationships and provenance; this does not verify travel facts."""
    required = {"schema_version", "title", "language", "revision", "demo", "notice",
                "cities", "places", "days", "legs", "open_questions"}
    obj(plan, required, required, "plan")
    require(type(plan["schema_version"]) is int and plan["schema_version"] == 1, "schema_version",
            "unsupported schema version")
    require(plan["language"] in tuple(GUIDE_LABELS), "language", "supported languages: en, zh-CN, ja")
    require(type(plan["demo"]) is bool, "demo", "expected a boolean")
    for field in ("title", "revision", "notice"):
        text(plan[field], field, 200 if field != "notice" else 2000)

    cities = set()
    for city, at in records(plan, "cities", {"name", "summary"}, {"name", "summary"}, 50):
        text(city["name"], at + ".name", 200)
        text(city["summary"], at + ".summary")
        cities.add(city["id"])
    require(cities, "cities", "at least one city is required")

    places = {}
    fields = {"city_id", "kind", "name", "role", "evidence", "notes", "sources", "coordinates"}
    for place, at in records(plan, "places", fields, fields - {"coordinates"}):
        require(isinstance(place["city_id"], str) and place["city_id"] in cities, at + ".city_id", "unknown city")
        require(isinstance(place["kind"], str) and place["kind"] in KINDS, at + ".kind", "unknown place category")
        require(isinstance(place["role"], str) and place["role"] in ROLES, at + ".role", "unknown plan role")
        require(isinstance(place["evidence"], str) and place["evidence"] in EVIDENCE, at + ".evidence", "unknown evidence status")
        for field in ("name", "notes"):
            text(place[field], at + "." + field)
        sources(place["sources"], at + ".sources")
        require(place["evidence"] != "verified" or place["sources"], at + ".sources",
                "verified facts need scoped sources")
        if place.get("coordinates") is not None:
            point = place["coordinates"]
            obj(point, {"lat", "lon", "source_url", "checked_on", "precision"},
                {"lat", "lon", "source_url", "checked_on", "precision"}, at + ".coordinates")
            for axis, limit in (("lat", 85), ("lon", 180)):
                number = point[axis]
                require(type(number) in (int, float) and -limit <= number <= limit and math.isfinite(number),
                        at + ".coordinates." + axis, "invalid latitude/longitude")
            url(point["source_url"], at + ".coordinates.source_url")
            date(point["checked_on"], at + ".coordinates.checked_on")
            text(point["precision"], at + ".coordinates.precision")
        places[place["id"]] = place

    days = {}
    previous = ""
    fields = {"date", "title", "city_ids", "base_city_id", "base_place_id", "summary", "visits", "leg_ids"}
    for day, at in records(plan, "days", fields, fields, 60):
        date(day["date"], at + ".date")
        require(day["date"] > previous, at + ".date", "days must have distinct increasing dates")
        previous = day["date"]
        for field in ("title", "summary"):
            text(day[field], at + "." + field)
        array(day["city_ids"], at + ".city_ids", 50)
        require(day["city_ids"] and all(isinstance(c, str) for c in day["city_ids"])
                and len(set(day["city_ids"])) == len(day["city_ids"])
                and all(c in cities for c in day["city_ids"]), at + ".city_ids", "unknown or duplicate city")
        base = day["base_city_id"]
        require(base is None or isinstance(base, str) and base in day["city_ids"], at + ".base_city_id", "overnight city must belong to day")
        hotel = day["base_place_id"]
        require(hotel is None or (isinstance(hotel, str) and hotel in places and places[hotel]["kind"] == "hotel"
                                  and places[hotel]["city_id"] == base), at + ".base_place_id", "invalid hotel/base")
        array(day["visits"], at + ".visits", 50)
        for index, visit in enumerate(day["visits"]):
            vat = at + ".visits[{}]".format(index)
            obj(visit, {"place_id", "time", "notes"}, {"place_id", "time", "notes"}, vat)
            require(isinstance(visit["place_id"], str) and visit["place_id"] in places
                    and places[visit["place_id"]]["city_id"] in day["city_ids"],
                    vat + ".place_id", "unknown place or wrong city")
            for field in ("time", "notes"):
                text(visit[field], vat + "." + field)
        array(day["leg_ids"], at + ".leg_ids", 50)
        require(all(isinstance(leg, str) for leg in day["leg_ids"])
                and len(set(day["leg_ids"])) == len(day["leg_ids"]), at + ".leg_ids", "invalid or duplicate leg")
        days[day["id"]] = day
    require(days, "days", "at least one day is required")

    legs = {}
    fields = {"day_id", "from_place_id", "to_place_id", "mode", "time", "role", "evidence", "notes", "sources"}
    for leg, at in records(plan, "legs", fields, fields, 500):
        require(isinstance(leg["day_id"], str) and leg["day_id"] in days, at + ".day_id", "unknown day")
        day = days[leg["day_id"]]
        require(leg["id"] in day["leg_ids"], at + ".id", "leg must be listed by its day")
        for field in ("from_place_id", "to_place_id"):
            require(isinstance(leg[field], str) and leg[field] in places and places[leg[field]]["city_id"] in day["city_ids"],
                    at + "." + field, "unknown endpoint or wrong day city")
        require(isinstance(leg["role"], str) and leg["role"] in ROLES, at + ".role", "unknown plan role")
        require(isinstance(leg["evidence"], str) and leg["evidence"] in EVIDENCE, at + ".evidence", "unknown evidence status")
        for field in ("mode", "time", "notes"):
            text(leg[field], at + "." + field)
        sources(leg["sources"], at + ".sources")
        require(leg["evidence"] != "verified" or leg["sources"], at + ".sources", "verified legs need sources")
        legs[leg["id"]] = leg
    for day in days.values():
        require(all(leg in legs for leg in day["leg_ids"]), "days.leg_ids", "unknown leg")
        require(all(legs[leg]["day_id"] == day["id"] for leg in day["leg_ids"]),
                "days.leg_ids", "leg belongs to another day")
    array(plan["open_questions"], "open_questions", 100)
    for index, question in enumerate(plan["open_questions"]):
        text(question, "open_questions[{}]".format(index))
    return plan


def render_html(plan):
    validate(plan)
    payload = json.dumps(plan, ensure_ascii=False, allow_nan=False)
    for character, escaped in (("<", "\\u003c"), (">", "\\u003e"), ("&", "\\u0026"),
                               ("\u2028", "\\u2028"), ("\u2029", "\\u2029")):
        payload = payload.replace(character, escaped)
    script = (ASSETS / "guide.js").read_text(encoding="utf-8")
    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
    template = (ASSETS / "guide.html").read_text(encoding="utf-8")
    # A callable substitution prevents replacements inside user-supplied content.
    slots = {"PLAN": payload, "SCRIPT": script, "SCRIPT_HASH": digest,
             "STYLE": (ASSETS / "guide.css").read_text(encoding="utf-8")}
    slots.update({key: escape(label) for key, label in GUIDE_LABELS[plan["language"]].items()})
    slots.update(LANG=plan["language"], TITLE=escape(plan["title"]))
    return re.sub(r"@@([A-Z_]+)@@", lambda m: slots[m[1]], template)


def presentation_brief(plan):
    validate(plan)
    # Keep source records complete; authoring tools must treat them as data, not instructions.
    return ((ASSETS / "presentation.md").read_text(encoding="utf-8")
            + "\n## Plan records\n\n```json\n"
            + json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n```\n")


def reject_constant(_value):
    raise PlanError("plan: non-finite numbers are unsupported")


def write_output(plan, output, kind):
    require(kind in ("html", "brief"), "format", "unsupported output format")
    output = Path(output).expanduser().resolve()
    roots = [SKILL]
    checkout = SKILL.parent.parent
    if (checkout / "scripts/build_plugin.py").is_file():
        roots.append(checkout)
    require(not any(output == root or root in output.parents for root in roots), "output",
            "generated files must stay outside the skill and source checkout")
    content = render_html(plan) if kind == "html" else presentation_brief(plan)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(content)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path, help="Plan JSON; see references/plan-data.md")
    parser.add_argument("--output", required=True, type=Path, help="New file outside the source/installed skill")
    parser.add_argument("--format", choices=("html", "brief"), default="html")
    args = parser.parse_args()
    try:
        require(args.input.is_file(), "input", "expected a regular file")
        with args.input.open("rb") as stream:
            data = stream.read(MAX_BYTES + 1)
        require(len(data) <= MAX_BYTES, "input", "plan exceeds the size limit")
        plan = json.loads(data.decode("utf-8-sig"), parse_constant=reject_constant)
        write_output(plan, args.output, args.format)
    except PlanError as error:
        # PlanError messages contain fixed schema locations, never supplied values/keys.
        print(json.dumps({"status": "error", "reason": "invalid_plan_or_output", "detail": str(error)}))
        return 1
    except (OSError, UnicodeError, ValueError, TypeError, KeyError, RecursionError):
        # JSON parser messages and filesystem errors can contain private input or local paths.
        print(json.dumps({"status": "error", "reason": "invalid_plan_or_output",
                          "hint": "Check the data contract, output location and whether the file already exists."}))
        return 1
    print(json.dumps({"status": "ok", "format": args.format, "network_requests": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
