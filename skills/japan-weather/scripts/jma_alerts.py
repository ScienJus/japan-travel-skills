"""Timestamped JMA meteorological-warning snapshots from the official XML feed."""
import datetime as dt
import http.client
import re
import socket
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET

from weather_common import JST, WeatherError, network_reason

FEED_URL = "https://www.data.jma.go.jp/developer/xml/feed/regular.xml"
PAGE_URL = "https://www.jma.go.jp/bosai/warning/"
DATA_URL = re.compile(r"https://www\.data\.jma\.go\.jp/developer/xml/data/[0-9]{14}_[0-9]+_VPWS50_[0-9]{6}\.xml")
TITLE = "気象警報・注意報（Ｒ０６）（集約通報）"
MAX_BYTES = 8 * 1024 * 1024
MAX_AGE_SECONDS = 30 * 60
ATOM = "{http://www.w3.org/2005/Atom}"
REPORT = "{http://xml.kishou.go.jp/jmaxml1/}"
HEAD = "{http://xml.kishou.go.jp/jmaxml1/informationBasis1/}"
BODY = "{http://xml.kishou.go.jp/jmaxml1/body/meteorology1/}"
AREA_TYPE = "気象警報・注意報（市町村等）"
NONE = "発表警報・注意報はなし"
ACTIVE = {"発表", "継続", "特別警報から危険警報", "特別警報から警報", "特別警報から注意報",
          "危険警報から警報", "危険警報から注意報", "警報から注意報"}


def changed(message, **details):
    raise WeatherError("alert_schema_changed", message, **details)


def xml(raw, expected):
    try:
        raw.decode("utf-8-sig")
    except UnicodeError:
        changed("Expected UTF-8 alert XML.")
    if b"\x00" in raw:
        changed("NUL/UTF-16 XML is not supported.")
    if re.search(br"<!\s*(?:DOCTYPE|ENTITY)\b", raw, re.I):
        changed("XML declarations with document types/entities are not supported.")
    try:
        root = ET.fromstring(raw)  # nosec B314 -- UTF-8, NUL and DTD/entity checks above; regression-tested.
    except (ET.ParseError, ValueError, LookupError):
        changed("Source did not return well-formed supported XML.")
    if root.tag != expected:
        changed("Unexpected XML root or namespace.")
    return root


def one(parent, tag):
    nodes = parent.findall(tag)
    if len(nodes) != 1:
        changed("Missing or duplicate XML field.", field=tag.rsplit("}", 1)[-1])
    return nodes[0]


def text(parent, tag):
    node = one(parent, tag)
    value = node.text
    if not value or not value.strip():
        changed("Empty required XML field.", field=tag.rsplit("}", 1)[-1])
    return value.strip()


def optional_text(parent, tag):
    nodes = parent.findall(tag)
    if len(nodes) > 1:
        changed("Duplicate optional XML field.")
    if not nodes:
        return None
    if not nodes[0].text or not nodes[0].text.strip():
        changed("Empty optional XML field.")
    return nodes[0].text.strip()


def instant(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        changed("Expected an explicit source timestamp and timezone.")
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(JST)
    except ValueError:
        changed("Invalid source timestamp.")


def fresh(value, now):
    age = (now - value).total_seconds()
    if age < 0:
        raise WeatherError("future_alert_snapshot", "Cannot confirm a future-dated alert snapshot.", timestamp=value.isoformat())
    if age > MAX_AGE_SECONDS:
        raise WeatherError("stale_alert_snapshot", "Cannot confirm alert status: the snapshot exceeds the 30-minute client age policy.",
                           timestamp=value.isoformat(), age_seconds=round(age), max_age_seconds=MAX_AGE_SECONDS)
    return round(age, 3)


def select_entry(raw, now):
    root = xml(raw, ATOM + "feed")
    feed_updated = instant(text(root, ATOM + "updated"))
    if feed_updated > now:
        raise WeatherError("future_alert_snapshot", "The alert feed has a future-dated update timestamp.")
    candidates = {}
    for entry in root.findall(ATOM + "entry"):
        title = entry.findtext(ATOM + "title", "")
        url = entry.findtext(ATOM + "id", "")
        if title != TITLE and "_VPWS50_" not in url:
            continue
        if text(entry, ATOM + "title") != TITLE or not DATA_URL.fullmatch(text(entry, ATOM + "id")):
            changed("Aggregate feed entry has an unexpected title or data URL.")
        links = [n for n in entry.findall(ATOM + "link") if n.get("type") == "application/xml"]
        if len(links) != 1 or links[0].get("href") != url:
            changed("Aggregate feed entry ID and XML link do not agree.")
        updated = instant(text(entry, ATOM + "updated"))
        if updated > feed_updated:
            changed("Entry timestamp is later than its enclosing feed timestamp.")
        if url in candidates and candidates[url] != updated:
            changed("Conflicting timestamps for the same aggregate URL.")
        candidates[url] = updated
    if not candidates:
        raise WeatherError("alert_snapshot_not_found", "The regular feed contains no supported aggregate; current status is unknown.")
    latest_time = max(candidates.values())
    latest = [url for url, updated in candidates.items() if updated == latest_time]
    if len(latest) != 1:
        changed("Multiple different aggregates have the same latest timestamp.")
    fresh(latest_time, now)
    return {"url": latest[0], "updated_at": latest_time, "feed_updated_at": feed_updated}


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WeatherError("unexpected_redirect", "Alert source redirected; no redirect was followed.", http_status=code)


class Client:
    def __init__(self, timeout=15):
        self.timeout = timeout
        self.requests = self.response_bytes = self.pacing_ms = 0
        self.started = time.monotonic()
        self.last_started = None
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url):
        if url != FEED_URL and not DATA_URL.fullmatch(url):
            raise WeatherError("unsupported_url", "Only the official regular feed and VPWS50 XML URLs are allowed.")
        if self.requests >= 2:
            raise WeatherError("request_budget_exhausted", "Stopped at two reads for the alert query.")
        if self.last_started is not None:
            delay = max(0, 1 - (time.monotonic() - self.last_started))
            if delay:
                time.sleep(delay)
                self.pacing_ms += round(delay * 1000)
        self.last_started = time.monotonic()
        self.requests += 1
        request = urllib.request.Request(url, headers={
            "User-Agent": "japan-travel-skills/0.3 (anonymous JMA alert reader)", "Accept": "application/xml"})
        try:
            with self.opener.open(request, timeout=self.timeout) as response:
                if response.status != 200:
                    raise WeatherError("unexpected_status", "Expected a complete HTTP 200 alert response.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes += len(raw)
                if len(raw) > MAX_BYTES:
                    raise WeatherError("response_too_large", "Alert response exceeds the 8 MiB limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise WeatherError("incomplete_response", "Alert body size does not match Content-Length.")
        except urllib.error.HTTPError as exc:
            details = {"http_status": exc.code}
            if exc.headers and exc.headers.get("Retry-After"):
                details["retry_after"] = exc.headers["Retry-After"]
            raise WeatherError("http_error", "Alert source failed or denied the request; no retry was attempted.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, TimeoutError, socket.timeout, OSError) as exc:
            if isinstance(exc, http.client.IncompleteRead):
                self.response_bytes += len(exc.partial)
            raise WeatherError("network_error", "Could not read alert source; no retry was attempted.", exception_type=type(exc).__name__, network_reason=network_reason(exc)) from None
        return raw

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "pacing_ms": self.pacing_ms, "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "scope": "This invocation; Consumed body bytes, including available partial reads, excluding HTTP/TLS overhead. No token or monetary estimate."}


def kind_record(node, snapshot_at, detail):
    status = text(node, BODY + "Status")
    if status not in ACTIVE | {"解除", NONE}:
        changed("Unknown alert status; current state cannot be inferred.")
    date_node = one(node, BODY + "DateTime")
    if date_node.get("type") != "発表時刻":
        changed("Unexpected per-kind timestamp type.")
    issued = instant(text(node, BODY + "DateTime"))
    if issued > snapshot_at:
        changed("An alert issue time is later than the snapshot target time.")
    name, code = optional_text(node, BODY + "Name"), optional_text(node, BODY + "Code")
    if status == NONE:
        if name is not None or code is not None:
            changed("An explicit no-warning item unexpectedly contains a warning identity.")
    elif not name or not code or not re.fullmatch(r"[0-9]{2}", code) or code == "00":
        changed("Missing or invalid alert name/code.")
    item = {"code": code, "name_ja": name, "status_ja": status, "issued_at": issued.isoformat()}
    condition = optional_text(node, BODY + "Condition")
    if condition:
        item["condition_ja"] = condition
    additions = node.findall(BODY + "Addition")
    if len(additions) > 1:
        changed("Duplicate warning additions.")
    if additions:
        note_nodes = additions[0].findall(BODY + "Note")
        if any(not n.text or not n.text.strip() for n in note_nodes):
            changed("Empty warning addition note.")
        notes = [n.text.strip() for n in note_nodes]
        if notes:
            item["notes_ja"] = notes
    if detail:
        previous = node.findall(BODY + "LastKind")
        if len(previous) > 1:
            changed("Duplicate previous-warning identity.")
        if previous:
            item["previous"] = {"code": text(previous[0], BODY + "Code"), "name_ja": text(previous[0], BODY + "Name")}
    return item


def parse_snapshot(raw, entry, expected_codes, now, detail=False):
    root = xml(raw, REPORT + "Report")
    control, head, body = one(root, REPORT + "Control"), one(root, HEAD + "Head"), one(root, BODY + "Body")
    if (text(control, REPORT + "Title") != TITLE or text(control, REPORT + "Status") != "通常" or
            text(control, REPORT + "EditorialOffice") != "気象庁本庁" or text(control, REPORT + "PublishingOffice") != "気象庁"):
        changed("Expected the normal national JMA aggregate; test/training/other products are not used.")
    if (text(head, HEAD + "Title") != "警戒・注意事項集約定時通報" or text(head, HEAD + "InfoKind") != "気象警報・注意報" or
            text(head, HEAD + "InfoKindVersion") != "1.5_0" or text(head, HEAD + "InfoType") not in ("発表", "訂正")):
        changed("Unsupported alert product, version or information type.")
    published, snapshot = instant(text(control, REPORT + "DateTime")), instant(text(head, HEAD + "TargetDateTime"))
    if published != entry["updated_at"] or instant(text(head, HEAD + "ReportDateTime")) != snapshot or published < snapshot:
        changed("Feed/control/target timestamps do not agree.")
    fresh(published, now)
    age = fresh(snapshot, now)
    section = [w for w in body.findall(BODY + "Warning") if w.get("type") == AREA_TYPE]
    if len(section) != 1:
        changed("Missing or duplicate municipality status section; absence is not a clearance.")
    areas = {}
    for item in section[0].findall(BODY + "Item"):
        area = one(item, BODY + "Area")
        code, name = text(area, BODY + "Code"), text(area, BODY + "Name")
        if not re.fullmatch(r"[0-9]{7}", code) or code in areas:
            changed("Invalid or duplicate municipality area code.")
        nodes = item.findall(BODY + "Kind")
        if not nodes:
            changed("Missing municipal warning status; an empty item is not no-warning.")
        kinds = [kind_record(k, snapshot, detail) for k in nodes]
        if any(k["status_ja"] == NONE for k in kinds) and len(kinds) != 1:
            changed("An explicit no-warning status is mixed with other states.")
        codes = [k["code"] for k in kinds if k["code"] is not None]
        if len(codes) != len(set(codes)):
            changed("Duplicate warning kinds for a municipality.")
        active = [k for k in kinds if k["status_ja"] in ACTIVE]
        released = [k for k in kinds if k["status_ja"] == "解除"]
        areas[code] = {"source_area": {"code": code, "name_ja": name},
                       "alert_state": "active" if active else ("cleared" if released else "none"),
                       "has_active_alerts": bool(active), "alerts": active}
        if released:
            areas[code]["released_alerts"] = released
        if kinds[0]["status_ja"] == NONE:
            areas[code]["no_alert_status"] = kinds[0]
    # The full code set must match maintained routing metadata. This rejects
    # partial-but-well-formed snapshots and outdated municipality catalogs.
    missing, extra = set(expected_codes) - set(areas), set(areas) - set(expected_codes)
    if missing or extra:
        raise WeatherError("alert_area_catalog_mismatch", "Snapshot/catalog municipality coverage differs; current status cannot be confirmed. Review the source and refresh routing metadata.",
                           missing_area_count=len(missing), new_area_count=len(extra),
                           missing_codes=sorted(missing)[:10], new_codes=sorted(extra)[:10])
    return areas, {"snapshot_at": snapshot.isoformat(), "published_at": published.isoformat(),
                   "snapshot_age_seconds": age, "max_snapshot_age_seconds": MAX_AGE_SECONDS,
                   "info_type_ja": text(head, HEAD + "InfoType"), "schema_version": "1.5_0", "municipality_count": len(areas)}


def query(client, cities, catalog, now_fn, detail=False):
    entry = select_entry(client.read(FEED_URL), now_fn())
    raw = client.read(entry["url"])
    now = now_fn()
    areas, metadata = parse_snapshot(raw, entry, catalog["areas"]["class20s"], now, detail)
    results = []
    for city in cities:
        code = city["code"]
        results.append({"city": city, **areas[code],
                        "official_page": PAGE_URL + "#area_type=class20s&area_code=" + code})
    return {"status": "ok", "timezone": "Asia/Tokyo", "cities": results,
            "catalog_retrieved_at": catalog["retrieved_at"],
            "source": {"publisher": "気象庁", "product": "VPWS50", "feed_url": FEED_URL, "url": entry["url"],
                       "feed_updated_at": entry["feed_updated_at"].isoformat(), "retrieved_at": now.isoformat(),
                       "processed": True, **metadata},
            "scope": {"included": "VPWS50 meteorological warnings and advisories for the exact municipality/subdivision",
                      "excluded": ["separate river flood-warning products", "earthquake/tsunami/volcanic warnings", "evacuation orders", "future alert forecasts"]},
            "warnings": ["This is a timestamped public-feed snapshot, not guaranteed real-time delivery or a safety clearance.",
                         "A subdivision result does not establish status for the rest of the city. No legacy JSON or cached snapshot fallback is used."]}
