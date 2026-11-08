"""Current official operator-scoped reports for integrated Hokuriku lines."""
from transit_network import network_reason
import datetime as dt
import http.client
import json
import re
import socket
import time
import unicodedata
import urllib.error
import urllib.request

JST = dt.timezone(dt.timedelta(hours=9), "Asia/Tokyo")
MAX_AGE_SECONDS = 600
MAX_BYTES = 2 * 1024 * 1024
WEST = "https://trafficinfo.westjr.co.jp/"
WEST_DATA = WEST + "api/v1/trafficinfo.json"
IR = "https://www.ishikawa-railway.jp/"
IR_PAGE = IR + "ishi-train/"
IR_OPERATOR = "odpt.Operator:IRIshikawa"
IR_RAILWAY = "odpt.Railway:IRIshikawa.IRIshikawa"
IR_DATA = [IR + "api/v1/" + path for path in ("message", "messages", "operation_news")]
OPERATOR_NAMES = {"jr-west": "JR西日本", "ir-ishikawa": "IRいしかわ鉄道"}
URLS = {"jr-west": {WEST_DATA}, "ir-ishikawa": set(IR_DATA)}
WEST_CODES = {"", "0000", "0001", "0003", "0999"}

# Integration references, not a stored operations feed. Through-service
# reports can describe stations beyond the operator's infrastructure.
LINES = [
    ("北陸新幹線", "jr-west", "上越妙高", "敦賀", "shinkansen", 103),
    ("北陸線", "jr-west", "近江塩津", "敦賀", "hokuriku", 27),
    ("大糸線", "jr-west", "南小谷", "糸魚川", "hokuriku", 28),
    ("高山線", "jr-west", "猪谷", "富山", "hokuriku", 29),
    ("氷見線", "jr-west", "高岡", "氷見", "hokuriku", 30),
    ("城端線", "jr-west", "高岡", "城端", "hokuriku", 31),
    ("七尾線", "jr-west", "津幡", "和倉温泉", "hokuriku", 32),
    ("越美北線（九頭竜線）", "jr-west", "越前花堂", "九頭竜湖", "hokuriku", 33),
    ("小浜線", "jr-west", "東舞鶴", "敦賀", "hokuriku", 34),
    ("IRいしかわ鉄道線", "ir-ishikawa", "大聖寺", "倶利伽羅", "ishikawa", IR_RAILWAY),
]
ALIASES = {
    "北陆新干线": "北陸新幹線", "北陆线": "北陸線", "大糸线": "大糸線",
    "高山线": "高山線", "冰见线": "氷見線", "氷见线": "氷見線", "城端线": "城端線",
    "七尾线": "七尾線", "越美北線": "越美北線（九頭竜線）", "九頭竜線": "越美北線（九頭竜線）",
    "越美北线": "越美北線（九頭竜線）", "九头龙线": "越美北線（九頭竜線）", "小浜线": "小浜線",
    "IRいしかわ線": "IRいしかわ鉄道線", "IR石川铁道线": "IRいしかわ鉄道線",
}
WARNINGS = [
    "Official reports for the requested operator only, not individual-train punctuality, live train positions or a travel-safety clearance.",
    "No listed report does not mean zero delay. Do not extend these reports to JR East, connecting lines or other operators.",
    "Section endpoints identify infrastructure references, not a filter on through-service reports or connecting lines.",
    "Area/site notices need separate review. Do not infer planned work dates from publication time.",
]


class OperationsError(Exception):
    def __init__(self, code, message, **details):
        super().__init__(message)
        self.code, self.details = code, details


def fail(message):
    raise OperationsError("source_schema_changed", message)


def now_jst():
    return dt.datetime.now(JST)


def canonical(value):
    value = unicodedata.normalize("NFKC", value).strip()
    return unicodedata.normalize("NFKC", ALIASES.get(value, value))


def descriptor(entry):
    name, operator, start, end, area, code = entry
    return {"name_ja": name, "operator": operator, "operator_ja": OPERATOR_NAMES[operator],
            "operator_section_reference": {"from_ja": start, "to_ja": end}, "source_area": area, "source_line_id": code}


def candidates(query="", operator=None):
    key = canonical(query)
    return [descriptor(e) for e in LINES if (not operator or e[1] == operator) and
            (not key or key in canonical(e[0]) or key in str(e[5]))]


def select_lines(queries, operator):
    selected = []
    if not 1 <= len(queries) <= 10:
        raise OperationsError("invalid_query", "Supply one to ten --line values.")
    for query in queries:
        if not query.strip() or len(query) > 100 or any(ord(c) < 32 for c in query):
            raise OperationsError("invalid_query", "Line names must contain 1–100 printable characters.")
        name = canonical(query)
        matches = [e for e in LINES if canonical(e[0]) == name and e[1] == operator]
        if not matches:
            raise OperationsError("unsupported_line", "No exact supported line/operator pair; no nearby line was selected.",
                                  query=query, operator=operator, candidates=candidates(operator=operator))
        for entry in matches:
            if entry not in selected:
                selected.append(entry)
    return selected


def in_hours(operator, when):
    return operator == "jr-west" and when.astimezone(JST).hour >= 6


def require_hours(operator, when):
    if not in_hours(operator, when):
        raise OperationsError("outside_reporting_hours", "Outside this adapter's supported reporting hours; status remains unknown.",
                              operator=operator, supported_hours_jst="06:00–24:00")


def timestamp(value):
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,9})?\+09:00", value):
        fail("Expected an explicit JST publisher timestamp.")
    try:
        # Python 3.9 accepts six fractional digits; the publisher uses nine.
        # Keep the original string in output and truncate only for comparison.
        comparable = re.sub(r"(\.\d{6})\d+(?=\+09:00)", r"\1", value)
        # Older Python releases accept only three or six fraction digits.
        comparable = re.sub(r"\.(\d+)(?=\+09:00)", lambda m: "." + m[1].ljust(6, "0"), comparable)
        return dt.datetime.fromisoformat(comparable)
    except ValueError:
        fail("Invalid publisher timestamp.")


def fresh(value, retrieved, operator):
    published = timestamp(value)
    age = (retrieved - published).total_seconds()
    if age < 0 or age > MAX_AGE_SECONDS:
        raise OperationsError("stale_or_future_source", "Publisher snapshot is future-dated or older than the fixed ten-minute client age limit.",
                              snapshot_at=value, retrieved_at=retrieved.isoformat(), max_age_seconds=MAX_AGE_SECONDS)
    require_hours(operator, published)
    return published


class RejectRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise OperationsError("unexpected_redirect", "Redirect was rejected; no alternate client or session was used.", http_status=code)


class Client:
    def __init__(self, operator="jr-west"):
        self.operator = operator
        self.last_started = None
        self.started = time.monotonic()
        self.requests = self.response_bytes = self.cache_hits = self.pacing_ms = 0
        self.cache = {}
        self.opener = urllib.request.build_opener(RejectRedirect())

    def read(self, url):
        if url not in URLS[self.operator]:
            raise OperationsError("unsupported_url", "Only the configured official snapshot URL may be read.")
        if url in self.cache:
            self.cache_hits += 1
            return self.cache[url]
        budget = 1 if self.operator == "jr-west" else 3
        if self.requests >= budget:
            raise OperationsError("request_budget_exhausted", "Stopped at the operator's operations-read limit.", max_requests=budget)
        delay = max(0, 1 - (time.monotonic() - self.last_started)) if self.last_started is not None else 0
        if delay:
            time.sleep(delay)
            self.pacing_ms += round(delay * 1000)
        self.last_started = time.monotonic()
        self.requests += 1
        try:
            with self.opener.open(urllib.request.Request(url, headers={
                    "User-Agent": "japan-travel-skills/0.3 (anonymous line-report reader)",
                    "Accept": "application/json,text/html;q=0.8"}), timeout=15) as response:
                if response.status != 200:
                    raise OperationsError("unexpected_status", "Expected a complete HTTP 200 response.", http_status=response.status)
                raw = response.read(MAX_BYTES + 1)
                self.response_bytes += len(raw)
                if len(raw) > MAX_BYTES:
                    raise OperationsError("response_too_large", "Source response exceeds the configured body limit.")
                length = response.headers.get("Content-Length")
                if length is not None and (not length.isascii() or not length.isdigit() or (length.lstrip("0") or "0") != str(len(raw))):
                    raise OperationsError("incomplete_response", "Body size does not match Content-Length.")
        except urllib.error.HTTPError as error:
            details = {"http_status": error.code, "url": url}
            if error.headers and error.headers.get("Retry-After"):
                details["retry_after"] = error.headers["Retry-After"]
            raise OperationsError("http_error", "Source request failed; no retry was attempted.", **details) from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, TimeoutError, socket.timeout) as error:
            if isinstance(error, http.client.IncompleteRead):
                self.response_bytes += len(error.partial)
            raise OperationsError("network_error", "Source could not be read; no retry was attempted.", url=url, exception_type=type(error).__name__, network_reason=network_reason(error)) from None
        self.cache[url] = raw, now_jst()
        return self.cache[url]

    def usage(self):
        return {"http_requests": self.requests, "response_body_bytes": self.response_bytes,
                "memory_cache_hits": self.cache_hits, "pacing_ms": self.pacing_ms,
                "elapsed_ms": round((time.monotonic() - self.started) * 1000),
                "scope": "This invocation; body bytes exclude HTTP/TLS overhead. No token or monetary estimate."}


def utf8(raw):
    try:
        return raw.decode("utf-8")
    except UnicodeError:
        fail("Official product was not valid UTF-8.")


def one(nodes, message):
    if len(nodes) != 1:
        fail(message)
    return nodes[0]


def unique_json(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("Duplicate JSON object field.")
        result[key] = value
    return result


def native_json(raw):
    return json.loads(utf8(raw), object_pairs_hook=unique_json,
                      parse_constant=lambda value: fail("Non-finite JSON value."))


def require_list(value):
    if not isinstance(value, list):
        fail("Expected a source array; missing data is not an empty array.")
    return value


def identities(value):
    rows = require_list(value)
    ids = [row["id"] for row in rows]
    if any(type(key) is not int or key < 0 for key in ids) or len(set(ids)) != len(ids):
        fail("Native identities are invalid or duplicated.")
    return rows


def code(value):
    if not isinstance(value, str) or value not in WEST_CODES:
        fail("Unsupported JR West state code.")
    return value


def report_times(value, snapshot):
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"updatedAt", "publicationDate"}:
                if timestamp(child) > snapshot:
                    fail("Report update/publication time is later than the snapshot.")
            elif key == "iconType":
                code(child)
            else:
                report_times(child, snapshot)
    elif isinstance(value, list):
        for child in value:
            report_times(child, snapshot)


def west_snapshot(raw, retrieved):
    value = native_json(raw)
    if not isinstance(value, dict):
        fail("JR West snapshot is not an object.")
    published = fresh(value["createdAt"], retrieved, "jr-west")
    maintenance = require_list(value["maintenances"])
    if not maintenance or any(type(m.get("isMaintaining")) is not bool for m in maintenance):
        fail("JR West maintenance state is incomplete.")
    if any(m["isMaintaining"] for m in maintenance):
        raise OperationsError("source_maintenance", "JR West reports maintenance; status remains unknown.")
    notices = require_list(value["systemAnnouncements"])
    if not notices or any(type(n.get("isAnnouncing")) is not bool for n in notices):
        fail("JR West system notice state is incomplete.")
    # Until active system-notice scope has been verified, do not treat a
    # potentially qualified snapshot as an unqualified operations result.
    if any(n["isAnnouncing"] for n in notices):
        raise OperationsError("source_system_notice", "JR West has an active site notice requiring direct review; status remains unknown.", official_url=WEST)
    identities(value["masterData"]["areas"])
    identities(value["areaTrafficInfos"])
    return value, published


def source_info(area, url, snapshot, retrieved):
    return {"id": "jr-west:" + area, "operator": "jr-west", "publisher": "JR西日本",
            "url": url, "data_url": WEST_DATA, "snapshot_at": snapshot, "retrieved_at": retrieved.isoformat(),
            "max_age_seconds": MAX_AGE_SECONDS, "reporting_hours_jst": "06:00–24:00",
            "reporting_policy": "Normally multiple-train delays of at least 15 minutes; Hokuriku Shinkansen uses 10 minutes. Some train-position areas report more frequently."}


def west_line(value, published, entry):
    name, operator, start, end, area, line_id = entry
    area_id, area_name = (5, "北陸新幹線") if area == "shinkansen" else (1, "北陸エリア")
    master = one([a for a in value["masterData"]["areas"] if a["id"] == area_id], "Requested master area is missing or duplicated.")
    if master["name"] != area_name:
        fail("JR West master area identity changed.")
    places = identities(master["places"])
    selected = [(p, l) for p in places for l in identities(p["lines"]) if l["id"] == line_id]
    place, line = one(selected, "Requested master line is missing or duplicated.")
    if line["name"] != name:
        fail("JR West master line name and ID disagree.")
    current = one([a for a in value["areaTrafficInfos"] if a["id"] == area_id], "Current area is missing or duplicated.")
    code(current["iconType"])
    days = require_list(current["dailyData"])
    today = published.date()
    if [d["date"] for d in days] != [(today + dt.timedelta(days=n)).isoformat() for n in range(3)]:
        fail("JR West today/tomorrow/day-after buckets are incomplete or mismatched.")
    day = days[0]
    code(day["iconType"])
    current_places = identities(day["placeTrafficInfos"])
    if {p["id"] for p in current_places} != {p["id"] for p in places} or len(current_places) != len(places):
        fail("JR West current-place coverage differs from master coverage.")
    current_place = one([p for p in current_places if p["id"] == place["id"]], "Current place is missing or duplicated.")
    code(current_place["iconType"])
    list_key = "shinkansenTrafficInfos" if area == "shinkansen" else "conventionalLineTrafficInfos"
    details_key = "shinkansenTrafficInfoDetails" if area == "shinkansen" else "conventionalLineTrafficInfoDetails"
    items = require_list(current_place[list_key])
    seen = set()
    for item in items:
        identity = item["id"]
        if type(identity) is not int or identity in seen:
            fail("JR West current line identity is invalid or duplicated.")
        seen.add(identity)
        native_line = one([l for l in place["lines"] if l["id"] == identity], "Current report line is absent from master data.")
        if item["lineName"] != native_line["name"]:
            fail("JR West report and master line names disagree.")
        code(item["iconType"])
        details = require_list(item[details_key])
        if any(not isinstance(detail, dict) for detail in details):
            fail("JR West report details must be objects.")
        if not details and item["iconType"]:
            fail("JR West line has a nonempty status without report details.")
    reports = [item for item in items if item["id"] == line_id and item[details_key]]
    context = {"scope": "Area/place context; not necessarily about the selected line.",
               "area_announcements": require_list(current["areaAnnouncements"] if area == "hokuriku" else current.get("areaAnnouncements", [])),
               "no_effect_line_reports": require_list(current_place["noEffectLineTrafficInfos"]),
               "conventional_delay_context": require_list(current["conventionalLineDelayInfos"])}
    # Preserve the source's complete selected record, including event sections,
    # prose and timestamps. Never replay trafficHistories into current reports.
    report_times(items, published)
    report_times(context, published)
    review = any(context[k] for k in context if k != "scope")
    if not any(item[details_key] for item in items) and not review and any(current_level["iconType"] for current_level in (current, day, current_place)):
        fail("JR West has a nonempty area/place state without interpretable current records.")
    return {**descriptor(entry), "source_id": operator + ":" + area,
            "state": "reports_listed" if reports else "review_required" if review else "no_listed_reports",
            "bulletins": reports, "context": context,
            "interpretation": "Native current-date records only. Empty records do not certify normal operation, no future work or punctuality."}


def ir_summary(value, checked_at):
    rows = require_list(value)
    if any(not isinstance(row, dict) for row in rows):
        fail("IR summary records must be objects.")
    reports = [row for row in rows if row.get("@type") == "odpt:TrainInformation"]
    railway = one([row for row in rows if row.get("@type") == "odpt:Railway"], "IR native railway mapping is missing or duplicated.")
    operator = one([row for row in rows if row.get("@type") == "odpt:Operator"], "IR native operator mapping is missing or duplicated.")
    if not reports or len(rows) != len(reports) + 2:
        fail("IR summary is incomplete or has unsupported record types.")
    if canonical(railway[IR_RAILWAY]) != canonical("IRいしかわ線") or unicodedata.normalize("NFKC", operator[IR_OPERATOR]).strip() != "IRいしかわ鉄道":
        fail("IR native operator/railway name mapping changed.")
    ids, published, deadlines = set(), [], []
    for report in reports:
        if report["odpt:operator"] != IR_OPERATOR or report["odpt:railway"] != IR_RAILWAY:
            fail("IR report belongs to an unexpected operator or railway.")
        identity = report["@id"]
        if not isinstance(identity, str) or not identity.strip() or identity in ids:
            fail("IR report identity is missing or duplicated.")
        ids.add(identity)
        native_text(report, "odpt:trainInformationText")
        if "odpt:trainInformationText-English" in report:
            native_text(report, "odpt:trainInformationText-English")
        issued, valid, origin = [timestamp(report[key]) for key in ("dc:date", "dct:valid", "odpt:timeOfOrgin")]
        age = (checked_at - issued).total_seconds()
        if not 0 <= age <= MAX_AGE_SECONDS or valid <= checked_at or valid <= issued:
            raise OperationsError("stale_or_future_source", "IR summary is future-dated, older than ten minutes, or past its publisher validity deadline.",
                                  snapshot_at=report["dc:date"], valid_until=report["dct:valid"], checked_at=checked_at.isoformat())
        if origin > issued:
            fail("IR source origin time is later than its generated report.")
        published.append(issued)
        deadlines.append(valid)
    return reports, min(published), min(deadlines)


def native_text(record, key):
    value = record[key]
    if not isinstance(value, str) or not value.strip():
        fail("Missing native IR report text.")
    return value


def ir_query(client, entries):
    # All three routes are independently linked by the official production app.
    # Read them serially, never replacing complete notices with the homepage banner.
    products, retrievals = [], []
    for address in IR_DATA:
        raw, retrieved = client.read(address)
        value = native_json(raw)
        products.append(value)
        retrievals.append({"url": address, "retrieved_at": retrieved.isoformat()})
        if len(products) == 1:
            ir_summary(value, retrieved)  # Stop before further reads if already invalid.
    checked_at = now_jst()
    reports, published, valid = ir_summary(products[0], checked_at)
    details = require_list(products[1]["operation_information"])
    if not details or any(not isinstance(row, dict) for row in details):
        fail("IR complete report list is empty or malformed; it cannot establish no reports.")
    for row in details:
        native_text(row, "odpt:trainInformationText")
        if "odpt:trainInformationText-English" in row:
            native_text(row, "odpt:trainInformationText-English")
        if timestamp(row["dc:date"]) > checked_at:
            fail("IR complete report has a future update time.")
    notice = products[2]["operation_news"]
    native_text(notice, "title")
    # The notice route exposes no verified generation time. Preserve it as
    # separately qualified context, never apply the summary's freshness to it.
    context = {"scope": "IR publisher's complete report list and supplemental notice; through-service wording may mention other operators.",
               "operation_information": details, "supplemental_notice": notice,
               "supplemental_notice_snapshot_at": None,
               "note": "The supplementary notice has no verified timestamp. Report update times are not necessarily event-start times."}
    source = {"id": "ir-ishikawa:ishikawa", "operator": "ir-ishikawa", "publisher": OPERATOR_NAMES["ir-ishikawa"],
              "url": IR_PAGE, "data_url": IR_DATA[0], "context_data_urls": IR_DATA[1:],
              "snapshot_at": published.isoformat(), "valid_until": valid.isoformat(),
              "retrieved_at": retrievals[-1]["retrieved_at"], "retrievals": retrievals, "checked_at": checked_at.isoformat(),
              "max_age_seconds": MAX_AGE_SECONDS, "reporting_hours_jst": None,
              "reporting_policy": "Publisher-generated summary with explicit validity deadline. Continuous reporting hours and delay thresholds are unverified.",
              "scope_note": "Summary freshness does not establish the age of the separate complete-list or supplementary-notice products."}
    return {"status": "ok", "query": {"time_scope": "current", "timezone": "Asia/Tokyo"}, "sources": [source],
            "reports": [{**descriptor(entry), "source_id": source["id"], "state": "reports_listed",
                         "bulletins": reports, "context": context,
                         "interpretation": "Native summary labels, including normal-operation wording, do not certify punctuality. Read all complete and supplemental notices."} for entry in entries],
            "warnings": WARNINGS}


def query(client, entries):
    if entries[0][1] == "ir-ishikawa":
        return ir_query(client, entries)
    require_hours("jr-west", now_jst())
    raw, retrieved = client.read(WEST_DATA)
    require_hours("jr-west", retrieved)
    value, published = west_snapshot(raw, retrieved)
    sources, reports = {}, []
    for entry in entries:
        area = entry[4]
        reports.append(west_line(value, published, entry))
        page = WEST + ("h_shinkansen.html" if area == "shinkansen" else "hokuriku.html")
        sources[area] = source_info(area, page, value["createdAt"], retrieved)
    return {"status": "ok", "query": {"time_scope": "current", "timezone": "Asia/Tokyo"},
            "sources": list(sources.values()), "reports": reports, "warnings": WARNINGS}


def main(args):
    client = Client(operator=args.operator or "jr-west")
    try:
        if args.command == "lines":
            result = {"status": "ok", "lines": candidates(args.query or "", args.operator),
                      "coverage": "Integration catalog only: {} operator/line sections in total. This offline list contains no operations status.".format(len(LINES))}
        else:
            entries = select_lines(args.line, args.operator)
            result = query(client, entries)
            result["query"].update(lines=args.line, operator=args.operator)
        result["usage"] = client.usage()
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0
    except OperationsError as error:
        problem = {"code": error.code, "message": str(error), **error.details}
    except (KeyError, TypeError, ValueError, AttributeError, OverflowError, RecursionError):
        problem = {"code": "source_schema_changed", "message": "Unexpected official source structure; no operation status was guessed."}
    print(json.dumps({"status": "error", "report_state": "unknown", "error": problem,
                      "official_pages": [IR_PAGE] if args.operator == "ir-ishikawa" else [WEST],
                      "usage": client.usage()}, ensure_ascii=False, separators=(",", ":")))
    return 2
