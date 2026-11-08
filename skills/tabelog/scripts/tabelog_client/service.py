"""Read-only restaurant workflows; verified APIs before server-rendered HTML."""
import math
import re
from datetime import datetime
from urllib.parse import urlencode, urlsplit, urljoin

from .core import (BASE, JST, STOP_CODES, RESTAURANT_PATH, CliError, endpoint, public_url,
                   date_value, time_value, date_range, today_japan, point_value, distance,
                   cuisine_matches, retail_only, meal_schedule, calendar_decision, people_ranges, review_window)
from .parsers import (soup, text_of, parse_map, parse_detail, parse_cards, parse_reviews,
                      parse_review_read, matching_awards, parse_courses)
from .filters import budget_check, opening_arguments, opening_check
from .hyakumeiten import CATALOG_URL, parse_categories, filter_params

AREA_TYPES = {"Prefecture", "Area1", "Area2", "RailroadStation", "FullArea1", "FullArea2", "AddressMaster", "MajorMunicipal"}


class Tabelog:
    def __init__(self, client):
        self.client, self.details, self.latest = client, {}, {}
        self.course_menus = {}
        self.active_categories = None
        self.native_categories = None

    def hyakumeiten_categories(self):
        if self.native_categories is None:
            self.native_categories = self.client.read(CATALOG_URL, 'json', parse_categories)
        return self.native_categories

    def suggest(self, keyword):
        if not keyword or not keyword.strip():
            raise CliError("invalid_argument", "A nonempty suggestion query is required.")
        def parse(raw, _url):
            if not isinstance(raw, list):
                raise CliError("unexpected_response", "Expected a suggestion array.")
            if any(not isinstance(r, dict) or not isinstance(r.get('name'), str) or not r['name'].strip()
                   or not isinstance(r.get('datatype'), str) for r in raw):
                raise CliError('unexpected_response', 'Suggestion contains an invalid name or type.')
            return [{**r, "kind": "area" if r["datatype"] in AREA_TYPES else "cuisine" if r["datatype"].startswith("Genre") else "restaurant" if r["datatype"] == "AreaRestaurant" else "other"}
                    for r in raw]
        return self.client.read(endpoint("/en/suggest/keyword_suggest", {"keyword": keyword}), "json", parse)

    def station(self, keyword):
        def parse(raw, _url):
            if not isinstance(raw, dict) or not isinstance(raw.get("suggestResult"), list):
                raise CliError("unexpected_response", "Expected station suggestion data.")
            candidates = [r for r in raw["suggestResult"] if isinstance(r, dict) and r.get("type") == "RailroadStation"
                          and all(type(r.get(k)) in (int, float) and math.isfinite(r[k]) for k in ("latitude", "longitude"))]
            def norm(s):
                return re.sub(r"(?:駅|\s+(?:station|sta\.))$", "", s, flags=re.I).strip().lower()
            exact = [r for r in candidates if norm(r.get("name", "")) == norm(keyword)]
            matches = exact or candidates
            if len(matches) != 1:
                raise CliError("ambiguous_station" if matches else "station_not_found", "Station could not be resolved uniquely.", candidates=matches)
            r = matches[0]
            return {"name": r["name"], "id": str(r["typeId"]), "unverified_coordinates": point_value([r["latitude"], r["longitude"]])}
        station = self.client.read(endpoint("/web-api/v1/search-suggestions/area", {"area": keyword}), "json", parse)
        url = "https://msearch.gsi.go.jp/address-search/AddressSearch?"+urlencode({"q": station["name"]})
        def coordinates(raw, _url):
            if not isinstance(raw, list):
                raise CliError("unexpected_response", "Expected GSI geographic features.")
            candidates = [r for r in raw if isinstance(r, dict) and r.get("properties", {}).get("title") == station["name"] and r.get("geometry", {}).get("type") == "Point"]
            if len(candidates) != 1:
                raise CliError("ambiguous_station_coordinates", "GSI did not uniquely locate this station; provide --near with verified WGS84 coordinates.", candidates=candidates)
            lon, lat = candidates[0]["geometry"]["coordinates"]
            point = point_value([lat, lon])
            return {"name": station["name"], "id": station["id"], **point, "coordinate_source": url, "attribution": "国土地理院 地名・住所検索",
                    "source_discrepancy_m": distance(station["unverified_coordinates"], point),
                    "note": "Station center uses the exact-name GSI feature. Suggestion coordinates are not assumed to use the same datum."}
        return self.client.read(url, "json", coordinates)

    def ref(self, target):
        if re.fullmatch(r"\d{1,12}", target or ""):
            def parse(_body, final):
                m = RESTAURANT_PATH.search(urlsplit(final).path)
                if not m or m[2] != target:
                    raise CliError("unexpected_response", "Restaurant ID did not resolve to a matching canonical URL.")
                return {"id": m[2], "path": m[1]}
            return self.client.read(f"{BASE}/en/rstdtl/{target}/", "html", parse)
        u = urlsplit(public_url(target))
        m = RESTAURANT_PATH.search(u.path)
        if not m or u.hostname != "tabelog.com":
            raise CliError("invalid_argument", "Expected a restaurant URL or numeric ID.")
        return {"id": m[2], "path": m[1]}

    def detail(self, target, include_courses=False):
        ref = self.ref(target)
        if ref["id"] not in self.details:
            self.details[ref["id"]] = self.client.read(f'{BASE}/en/{ref["path"]}/', "html", lambda body, url: parse_detail(body, ref, url))
        item = self.details[ref["id"]]
        if not include_courses:
            return item
        if ref['id'] not in self.course_menus:
            url = f'{BASE}/{ref["path"]}/party/'
            try:
                self.course_menus[ref['id']] = self.client.read(url, 'html', lambda body, final: parse_courses(body, ref, final))
            except CliError as error:
                self.course_menus[ref['id']] = {'items': None, 'source_url': url, 'coverage': 'unknown', 'error': error.as_dict()}
        courses = self.course_menus[ref['id']]
        errors = list(item.get('errors') or [])
        errors.extend({'scope': 'courses', **error} for error in courses.get('errors', []))
        if courses.get('error'):
            errors.append({'scope': 'courses', **courses['error']})
        return {**item, 'courses': courses, **({'coverage': 'partial', 'errors': errors} if errors else {})}

    def latest_awards(self, records):
        if not any(r.get("category") for r in records):
            return self.latest
        if self.active_categories is None:
            def parse(body, _url):
                categories = {m[1] for m in re.finditer(r'href=["\'](?:https://award\.tabelog\.com)?/hyakumeiten/([a-z_]+)/?["\']', body)}
                if not categories:
                    raise CliError("unexpected_response", "Current Hyakumeiten category index could not be read.")
                return categories
            self.active_categories = self.client.read("https://award.tabelog.com/hyakumeiten/", "html", parse)
        for category in dict.fromkeys(r["category"] for r in records if r.get("category")):
            if category in self.latest:
                continue
            if category not in self.active_categories:
                self.latest[category] = None
                continue
            def edition(body, final):
                doc = soup(body)
                link = doc.select_one('link[rel="canonical"]')
                values = [final, link.get("href", "") if link else "", text_of(doc.title)]
                years = {int(m[1]) for value in values for m in re.finditer(r"\b(20\d{2})\b", value)}
                if len(years) != 1:
                    raise CliError("unexpected_response", "Current Hyakumeiten edition could not be confirmed from page identity.")
                return years.pop()
            self.latest[category] = self.client.read(f"https://award.tabelog.com/hyakumeiten/{category}/", "html", edition)
        return self.latest

    def awards(self, target, year=None, category=None):
        item = self.detail(target)
        latest = {} if year else self.latest_awards(item["awards"])
        incomplete = any(not r['year'] or not r['category'] for r in item['awards'])
        errors = list(item.get('errors') or [])
        if incomplete:
            errors.append({'code': 'unverified_award', 'message': 'Some award badges lack a recognizable year or category.'})
        return {"id": item["id"], "records": item["awards"], "matches": matching_awards(item["awards"], year, category, latest), "latest_by_category": latest,
                **({'coverage': 'partial', 'errors': errors} if errors else {}),
                "verification": "partial" if any(not r["year"] or not r["category"] for r in item["awards"]) else "observed_badges",
                "warning": "A missing or unclassified badge is unknown, not evidence that the restaurant was never selected."}

    def map_search(self, point, radius, pages, category_ids=None):
        """Yield rating-ordered pages so callers can stop before another request."""
        lat_span = radius/111000
        lon_span = lat_span/max(abs(math.cos(math.radians(point["latitude"]))), 1e-15)
        bounds = {"minLat": point["latitude"]-lat_span, "maxLat": point["latitude"]+lat_span,
                  "minLon": point["longitude"]-lon_span, "maxLon": point["longitude"]+lon_span}
        if bounds["minLat"] < -90 or bounds["maxLat"] > 90 or bounds["minLon"] < -180 or bounds["maxLon"] > 180:
            raise CliError("unsupported_bounds", "Map bounds crossing a pole or antimeridian need separate queries.")
        scanned, invalid = 0, 0
        for page in range(1, pages+1):
            url = endpoint("/xml/rstmap", filter_params({**bounds, "pg": page, "lst": 20, "SrtT": "rt"}, category_ids))
            result = self.client.read(url, "xml", lambda body, _url: parse_map(body, url))
            total = result["upstream_total"]
            scanned += len(result["items"])
            invalid += result["invalid"]
            exhausted = not result["has_next"] or not result["items"]
            yield {"items": result["items"], "meta": {"source": "map_api", "bounds": bounds, "upstream_rectangle_total": total,
                   "pages_read": page, "scanned_count": scanned, "invalid_records": invalid,
                   "coverage": "partial" if invalid else "limited" if total > scanned else "observed_rectangle",
                   "stop_reason": "source_exhausted" if exhausted else "page_limit",
                   "warnings": ["Map total describes a rectangle, not the radius or an administrative area."]}}
            if exhausted:
                break

    def area_search(self, area, pages, category_ids=None):
        candidates = [r for r in self.suggest(area) if r["kind"] == "area"]
        choices = [r for r in candidates if r.get("exact_match") is True] or candidates
        if len(choices) != 1:
            raise CliError("ambiguous_area", "Area could not be resolved uniquely.", candidates=choices)
        a = choices[0]
        query = {k: a.get(k) or "" for k in ("pal", "LstPrf", "LstAre", "station_id")}
        query.update(SrtT="rt", area_datatype=a["datatype"], area_id=a.get("id_in_datatype", ""))
        scanned, invalid = 0, 0
        for page in range(1, pages+1):
            url = endpoint("/en/rstLst/"+(f"{page}/" if page > 1 else ""), filter_params(query, category_ids))
            def parse(body, _url):
                result = parse_cards(body)
                current, count = result["pagination"]["current"], result["count"]
                if current is not None and current != page or page > 1 and count["from"] is not None and count["from"] <= (page-1)*20:
                    raise CliError("unexpected_response", "Requested result page was not returned; coverage is incomplete.")
                if not result["items"] and count["total"] != 0:
                    raise CliError("unexpected_response", "No recognizable restaurant results or explicit zero count.")
                return result
            result = self.client.read(url, "html", parse)
            total = result["count"]["total"]
            scanned += len(result["items"])
            invalid += result['invalid']
            exhausted = not result["items"] or total is not None and scanned >= total
            yield {"items": result["items"], "meta": {"source": "area_suggest_api_then_html", "resolved_area": a["name"], "upstream_area_total": total,
                   "pages_read": page, "scanned_count": scanned, "coverage": "partial" if invalid else "observed_area" if total == scanned else "limited",
                   "invalid_records": invalid,
                   "stop_reason": "source_exhausted" if exhausted else "page_limit", "warnings": []}}
            if exhausted:
                break

    def search(self, area=None, station=None, near=None, radius=1000, min_rating=None, cuisines=None, pages=2, limit=5,
               hyakumeiten=False, meal=None, budget_min=None, budget_max=None, budget_meal=None,
               open_date=None, open_at=None, open_until=None):
        cuisines = cuisines or []
        if meal and meal not in ("lunch", "dinner"):
            raise CliError("invalid_argument", "Meal must be lunch or dinner.")
        opening_arguments(open_date, open_at, open_until)
        has_opening = bool(open_date or open_at)
        has_budget = budget_min is not None or budget_max is not None
        if has_budget:
            budget_meal = budget_meal or meal
        if budget_meal not in (None, 'lunch', 'dinner') or budget_meal and not has_budget:
            raise CliError('invalid_argument', '--budget-meal accepts lunch|dinner and requires a budget bound.')
        if has_budget and ((budget_min is not None and budget_min < 0) or (budget_max is not None and budget_max < 0)
                           or budget_min is not None and budget_max is not None and budget_min > budget_max):
            raise CliError('invalid_argument', 'Expected nonnegative budget bounds with minimum <= maximum.')
        origin = point_value(near) if near else None
        if not origin and not station and not area:
            raise CliError("invalid_argument", "Provide --area, --station or --near.")
        selected = self.hyakumeiten_categories()['items'] if hyakumeiten else []
        category_ids = [r['id'] for r in selected]
        if station:
            origin = self.station(station)
        award_filter = ({'method': 'native_current_categories', 'catalog_url': CATALOG_URL,
                         'selected_categories': selected, 'operator': 'OR', 'year': None,
                         'warning': 'Server-filtered current categories; individual category/year badges are not verified.'}
                        if hyakumeiten else None)
        def matches(item):
            return (min_rating is None or item.get("rating") is not None and item["rating"] >= min_rating) and cuisine_matches(item["cuisines"], cuisines)

        def rating_key(item):
            return -(item["rating"] if item.get("rating") is not None else -1)

        items, unverified, seen, errors = [], [], set(), []
        candidates_checked = 0
        meal_check = {"candidates_checked": 0, "excluded": [], "stopped_at_limit": False}

        def check(item):
            # A known exclusion decides an AND filter even when another field is missing.
            cuisine_unknown = bool(cuisines) and not item['cuisines']
            if not cuisine_unknown and not cuisine_matches(item['cuisines'], cuisines):
                return None
            if min_rating is not None and item.get('rating') is not None and item['rating'] < min_rating:
                return None
            data = dict(item)
            if origin and "latitude" in data and "longitude" in data:
                data["distance_m"] = distance(origin, data)
                if data["distance_m"] > radius:
                    return None
            if meal and retail_only(data["cuisines"]):
                meal_check["excluded"].append({"id": item["id"], "name": item["name"], "reason": "retail_only"})
                return None
            budget = budget_check(item, budget_meal, budget_min, budget_max) if has_budget else None
            if budget and budget['status'] not in ('matches_list_budget', 'unknown', 'boundary_uncertain'):
                return None
            if min_rating is not None and item.get('rating') is None:
                unverified.append({**item, 'reason': 'Rating is missing; requested minimum cannot be verified'})
                return None
            if cuisine_unknown:
                unverified.append({**item, 'reason': 'Cuisine classifications are missing; requested cuisine cannot be verified'})
                return None
            if budget:
                if budget['status'] != 'matches_list_budget':
                    unverified.append({**item, 'reason': 'List budget unavailable or crosses the requested boundary', 'budget_filter': budget})
                    return None
                data['budget_filter'] = budget
            try:
                if meal or has_opening or (origin and ("latitude" not in data or "longitude" not in data)):
                    detail = self.detail(item["url"])
                    errors.extend({'restaurant_id': item['id'], **error} for error in detail.get('errors', []))
                    data.update(detail, name=item["name"], localized_name=detail.get("name"),
                                cuisines=item['cuisines'], localized_cuisines=detail.get('cuisines', []))
                if origin:
                    if "latitude" not in data or "longitude" not in data:
                        unverified.append({**data, "reason": "Missing restaurant coordinates"})
                        return None
                    data["distance_m"] = distance(origin, data)
                    if data["distance_m"] > radius:
                        return None
                if not matches(data):
                    return None
                if meal and not has_opening:
                    meal_check["candidates_checked"] += 1
                    schedule = meal_schedule(data, meal)
                    if schedule["status"] == "unknown":
                        unverified.append({**data, "reason": "Meal hours unavailable"})
                        return None
                    if schedule["status"] != "confirmed_regular_schedule":
                        meal_check["excluded"].append({"id": item["id"], "name": item["name"], "reason": schedule["status"]})
                        return None
                    data["meal_service"] = schedule
                if has_opening:
                    if meal:
                        meal_check['candidates_checked'] += 1
                    opening = opening_check(data, open_date, open_at, open_until, meal)
                    if opening['status'] == 'unknown':
                        unverified.append({**data, 'reason': 'Opening schedule needs verification', 'opening_filter': opening})
                        return None
                    if opening['status'] != 'matches_regular_hours':
                        return None
                    data['opening_filter'] = opening
                    if meal:
                        data['meal_service'] = {'meal': meal, 'status': 'confirmed_regular_schedule_on_date' if open_date else 'confirmed_regular_schedule_on_weekdays',
                                                'date': open_date, **({'matching_weekdays': opening['matching_weekdays']} if not open_date else {}),
                                                'notes': opening['notes'], 'warning': opening['warning']}
                return data
            except CliError as error:
                if error.code in STOP_CODES:
                    raise
                unverified.append({**item, "reason": error.code, 'error': error.as_dict()})
                return None

        def consume(batches):
            nonlocal candidates_checked
            for batch in batches:
                meta = batch["meta"]
                # Stable ties retain the upstream order; distance is only a filter.
                for item in sorted(batch["items"], key=rating_key):
                    if item["id"] in seen:
                        continue
                    seen.add(item["id"])
                    candidates_checked += 1
                    data = check(item)
                    if data is None:
                        continue
                    items.append(data)
                    if len(items) >= limit:
                        meal_check["stopped_at_limit"] = bool(meal)
                        return {**meta, "stop_reason": "limit_reached"}
            return meta

        if origin:
            try:
                meta = consume(self.map_search(origin, radius, pages, category_ids))
            except CliError as error:
                if not area or error.code in STOP_CODES:
                    raise
                # A fallback is a fresh search, not a mixture of two result sets.
                items.clear()
                unverified.clear()
                seen.clear()
                candidates_checked = 0
                meal_check.update(candidates_checked=0, excluded=[], stopped_at_limit=False)
                meta = consume(self.area_search(area, pages, category_ids))
                meta["warnings"].append(f"Map API unavailable ({error.code}); searched the explicitly supplied fallback area.")
                errors.append({'scope': 'map_search', **error.as_dict()})
        else:
            meta = consume(self.area_search(area, pages, category_ids))
        items.sort(key=rating_key)
        if unverified:
            errors.append({'code': 'unverified_candidates', 'message': 'Some restaurants could not be checked against the requested filters.',
                           'count': len(unverified)})
        if meta.get('invalid_records'):
            errors.append({'code': 'invalid_records', 'message': 'Some source restaurant records could not be parsed.', 'count': meta['invalid_records']})
        return {"items": items, "unverified": unverified, 'errors': errors,
                'coverage': 'partial' if errors else 'limited' if meta['stop_reason'] != 'source_exhausted' else 'complete',
                "meta": {**meta, "origin": origin, "radius_m": radius if origin else None,
                "sort": "rating_desc", "upstream_sort": "rt", "candidates_checked": candidates_checked,
                "matching_before_limit": len(items), **({"meal_check": meal_check} if meal else {}),
                **({'hyakumeiten_filter': award_filter} if hyakumeiten else {}),
                "filters": {"min_rating": min_rating, "cuisines": cuisines, "meal": meal, "hyakumeiten": bool(hyakumeiten),
                            'budget_min_yen': budget_min, 'budget_max_yen': budget_max, 'budget_meal': budget_meal or ('any' if has_budget else None),
                            'open_date': open_date, 'open_at': open_at, 'open_until': open_until}}}

    def reviews(self, target, since, until=None, pages=2, full=False, limit=20, meal=None):
        if meal not in (None, 'all', 'lunch', 'dinner'):
            raise CliError('invalid_argument', 'Review meal must be all, lunch or dinner.')
        meal = None if meal == 'all' else meal
        # Verified from the site's actual filter links; upstream CLI has these reversed.
        use_type = {None: 0, 'lunch': 1, 'dinner': 2}[meal]
        until = until or today_japan()
        date_value(since)
        date_value(until)
        if since > until or until > today_japan():
            raise CliError("invalid_argument", "Review window must end today or earlier, with since <= until.")
        ref = self.ref(target)
        items, unverified, seen, read, exhausted = [], [], set(), 0, False
        meal_check = {'excluded_list_records': 0, 'unknown_list_records': 0,
                      'excluded_full_visits': 0, 'unknown_full_visits': 0}
        for page in range(1, pages+1):
            url = endpoint(f'/en/{ref["path"]}/dtlrvwlst/', {"PG": page, "lc": 0, "rvw_part": "all", "smp": 1, "use_type": use_type, "srt": "visit", "sby": "D"})
            def parse(body, _url):
                result = parse_reviews(body, page)
                if not result["items"] and not result["note"] and not re.search(r"no reviews|口コミはまだ", body, re.I):
                    raise CliError("unexpected_response", "No recognizable review cards or explicit empty evidence.")
                return result
            result = self.client.read(url, "html", parse)
            read += 1
            if result["note"] or not result["items"]:
                exhausted = True
                break
            for r in result["items"]:
                key = urljoin(BASE, r["url"]) if r["url"] else None
                if key and key in seen:
                    continue
                ident = re.search(r"/(B\d+)/", key or "")
                record = {"review_url": key, "review_id": ident[1] if ident else None, "reviewer": r["reviewer"], "rating": r["rating"], "spend": r["spend"],
                          'meal': r['meal'],
                          "visited_at_raw": r["visited_at_raw"], "published_at": None,
                          **review_window(r["visited_at_raw"], since, until),
                          "content_level": "list_excerpt" if r["text"] else "rating_only", "text": r["text"]}
                if record["window"] not in ("outside_window", "future_anomaly"):
                    if meal and r['meal'] is None:
                        meal_check['unknown_list_records'] += 1
                        unverified.append({**record, 'reason': 'Review meal is not identified by the page icon'})
                        continue
                    if meal and r['meal'] != meal:
                        meal_check['excluded_list_records'] += 1
                        continue
                    if key:
                        seen.add(key)
                    items.append(record)
            if result["lastPage"] is not None and page >= result["lastPage"]:
                exhausted = True
                break
        selected = items[:limit]
        if full:
            confirmed = []
            for item in selected:
                if item["review_url"]:
                    r = self.review_read(item["review_url"])
                    visits = [{**v, **review_window(v["visited_at_raw"], since, until)} for v in r["visits"]]
                    item['visits'] = [v for v in visits if not meal or v['meal'] == meal]
                    if meal:
                        meal_check['excluded_full_visits'] += sum(v['meal'] is not None and v['meal'] != meal for v in visits)
                        unknown = [v for v in visits if v['meal'] is None]
                        meal_check['unknown_full_visits'] += len(unknown)
                        if unknown:
                            item['unverified_visits'] = unknown
                    item["content_level"] = "detail"
                    item.pop("text", None)
                    if meal and not item['visits']:
                        unverified.append({**item, 'reason': 'Full review contains no visit with a verified matching meal'})
                        continue
                confirmed.append(item)
            selected = confirmed
        errors = []
        if unverified or meal_check['unknown_full_visits']:
            errors.append({'code': 'unverified_reviews', 'message': 'Some reviews or visits could not be verified against the requested meal.'})
        if any(r['window'] in ('undated', 'boundary_uncertain') for r in selected):
            errors.append({'code': 'unverified_visit_dates', 'message': 'Some review visit dates cannot be placed precisely in the requested window.'})
        if full and any(r['content_level'] != 'detail' for r in selected):
            errors.append({'code': 'missing_review_url', 'message': 'Full text was requested but a review detail URL is missing.'})
        return {"restaurant_id": ref["id"], "items": selected, 'unverified': unverified, 'errors': errors,
                'coverage': 'partial' if errors else 'complete' if exhausted and len(items) <= limit else 'limited',
                "meta": {"since": since, "until": until, "basis": "visit", "pages_read": read,
                'meal': meal or 'all', 'use_type': use_type, 'meal_check': meal_check,
                "coverage": "partial" if errors else "observed_all_list_pages" if exhausted and len(items) <= limit else "limited", "strict_window_count": sum(r["window"] == "in_window" for r in selected),
                "warnings": ["Month-only dates crossing the window are boundary_uncertain."]}}

    def review_read(self, target):
        u = urlsplit(public_url(target))
        m = re.search(r"/(?:en/|cn/|tw/|kr/|th/)?([a-z]+/A\d{4}/A\d{6}/\d+)/dtlrvwlst/(B\d+)/", u.path)
        if not m or u.hostname != "tabelog.com":
            raise CliError("invalid_argument", "Expected a Tabelog review detail URL ending in /dtlrvwlst/B…/.")
        def parse(body, url):
            p = parse_review_read(body)
            return {"review_url": url, "review_id": m[2], "reviewer": p["reviewer"], "visits": [{k: v[k] for k in ("visited_at_raw", "rating", "text", "spend", 'meal')} | {"content_level": "detail" if v["text"] else "rating_only"} for v in p["visits"]]}
        return self.client.read(f"{BASE}/en/{m[1]}/dtlrvwlst/{m[2]}/", "html", parse)

    def calendar(self, ident):
        def parse(raw, _url):
            if not isinstance(raw, dict) or not isinstance(raw.get("list"), list):
                raise CliError("unexpected_response", "Calendar list is missing.")
            seen, items = set(), []
            for d in raw["list"]:
                if not isinstance(d, dict) or not all(type(d.get(k)) is int for k in ("year", "month", "day", "available")):
                    raise CliError("unexpected_response", "Malformed calendar entry.")
                day = date_value(f'{d["year"]:04d}-{d["month"]:02d}-{d["day"]:02d}')
                if day in seen:
                    raise CliError("unexpected_response", "Duplicate calendar date; overview cannot safely exclude dates.")
                seen.add(day)
                items.append({"date": day, "raw_status": d["available"]})
            return items
        # The frontend requests one restaurant-wide overview, without date/party filters.
        return self.client.read(endpoint("/en/booking/calendar/find_vacancy_date_with_status/", {"rst_id": ident}), "json", parse)

    def member_options(self, ident, day):
        def parse(raw, _url):
            rows = raw.get('svpsOpts') if isinstance(raw, dict) else None
            if not isinstance(rows, list) or not rows:
                raise CliError('unexpected_response', 'Party-size options are missing; availability is unknown.')
            options, seen = [], set()
            for row in rows:
                if (not isinstance(row, dict) or type(row.get('member_num')) is not int
                        or not 1 <= row['member_num'] <= 99 or row['member_num'] in seen
                        or type(row.get('status')) is not int):
                    raise CliError('unexpected_response', 'Malformed or duplicate party-size option.')
                number, status = row['member_num'], row['status']
                seen.add(number)
                options.append({'people': number, 'raw_status': status,
                                'hint': 'selectable' if status == 2 else 'not_selectable' if status == 0 else 'unknown'})
            options.sort(key=lambda r: r['people'])
            available = [r['people'] for r in options if r['raw_status'] == 2]
            unknown = [r['people'] for r in options if r['hint'] == 'unknown']
            return {'people_options': options, 'selectable_people': available,
                    'selectable_people_ranges': people_ranges(available), 'unknown_people': unknown,
                    'errors': ([{'code': 'unrecognized_member_status', 'people': unknown,
                                 'message': 'Party-size options contain unrecognized availability states.'}] if unknown else []),
                    'coverage': 'partial' if unknown else 'returned_options'}
        return self.client.read(endpoint('/en/booking/calendar/find_vacancy_member_by_date/',
                                        {'rst_id': ident, 'svd': day.replace('-', '')}), 'json', parse)

    def calendar_query(self, target, start=None, end=None, people=None):
        if end and not start:
            raise CliError('invalid_argument', 'An end date requires a start date.')
        days = date_range(start, end or start) if start else None
        if (start and start < today_japan()) or people is not None and (type(people) is not int or not 1 <= people <= 99):
            raise CliError('invalid_argument', 'Use today or a future date and, if specified, 1..99 guests.')
        ident = target if re.fullmatch(r'\d{1,12}', target) else self.ref(target)['id']
        if days is None:
            overview = self.calendar(ident)
            return {'restaurant_id': ident, 'people': people, 'requested_range': None, 'calendar': overview,
                    'dates': [{**r, 'calendar_hint': calendar_decision(r['raw_status'])['hint'],
                               'status': 'overview_only', 'selectable_people': None, 'selectable_people_ranges': None}
                              for r in overview],
                    'coverage': 'returned_overview', 'member_coverage': 'not_queried',
                    'query_plan': {'member_queries': 0, 'slot_queries': 0},
                    'warning': 'Full upstream overview only; date coverage is controlled by the upstream. No party-size or time-slot verification. Specify a date/window to discover selectable people.'}
        overview, error, stopped = [], None, False
        try:
            overview = self.calendar(ident)
        except CliError as failure:
            error, stopped = failure.as_dict(), failure.code in STOP_CODES
        by_date = {r['date']: r['raw_status'] for r in overview}
        dates, queries, stop_error = [], 0, error if stopped else None
        for day in days:
            raw = by_date.get(day)
            decision = calendar_decision(raw)
            row = {'date': day, 'raw_status': raw, 'calendar_hint': decision['hint'],
                   'status': 'unknown', 'selectable_people': None, 'selectable_people_ranges': None,
                   'error': stop_error if stopped else {'code': 'not_queried', 'message': 'Party sizes have not been checked.'}}
            if not error and decision['skip_online_slots']:
                row.update(status='calendar_excluded')
                row.pop('error')
            elif not stopped:
                try:
                    queries += 1
                    members = self.member_options(ident, day)
                    row.update(members, status='unknown' if members['coverage'] == 'partial' else 'member_options')
                    row.pop('error')
                    if people is not None:
                        option = next((r for r in members['people_options'] if r['people'] == people), None)
                        row['requested_people_hint'] = option['hint'] if option else 'unknown'
                        if option is None:
                            row.update(status='unknown', error={'code': 'unverified_people', 'message': 'Requested party size was not returned by the source.'})
                except CliError as failure:
                    row['error'] = failure.as_dict()
                    stopped = failure.code in STOP_CODES
                    if stopped:
                        stop_error = failure.as_dict()
            dates.append(row)
        return {'restaurant_id': ident, 'people': people, 'requested_range': {'start': start, 'end': end or start},
                'calendar': overview, 'dates': dates, 'coverage': 'partial' if error or any(r['status'] == 'unknown' for r in dates) else 'complete',
                'errors': ([{'scope': 'calendar', **error}] if error else []) +
                          [{'date': row['date'], **row['error']} for row in dates if row.get('error')] +
                          [{'date': row['date'], **failure} for row in dates for failure in row.get('errors', [])],
                'query_plan': {'calendar_error': error, 'member_queries': queries, 'slot_queries': 0},
                'warning': 'English-channel date and party-size hints only, across all meals. Not verified time slots, seat types or restaurant capacity; omitted sizes are unknown.'}

    def all_party_slots(self, ident, day, time=None, after='00:00', before='23:59', exclude_elapsed=False):
        members = self.member_options(ident, day)
        results = [{'people': n, 'status': 'unknown', 'offered_times': None, 'matching_times': None,
                    'error': {'code': 'not_queried', 'message': 'Party size has not been checked.'}}
                   for n in members['selectable_people']]
        error, queries = None, 0
        for row in results:
            try:
                queries += 1
                offered = self.slots(ident, day, row['people'], time)
                now = datetime.now(JST)
                matching = [t for t in offered if after <= t <= before and
                            (not exclude_elapsed or day != now.date().isoformat() or t > now.strftime('%H:%M'))]
                row.update(status='ok', offered_times=offered, matching_times=matching)
                row.pop('error')
            except CliError as failure:
                row['error'] = failure.as_dict()
                if failure.code in STOP_CODES:
                    error = failure.as_dict()
                    break
        available = [r['people'] for r in results if r['matching_times']]
        by_time = {}
        for row in results:
            for value in row['matching_times'] or []:
                by_time.setdefault(value, []).append(row['people'])
        return {**members, 'people_results': results, 'available_people': available,
                'unknown_people': sorted(set(members['unknown_people']) | {r['people'] for r in results if r['status'] == 'unknown'}),
                'available_people_ranges': people_ranges(available),
                'matching_times': sorted(by_time),
                'time_options': [{'time': t, 'available_people': sizes, 'people_ranges': people_ranges(sizes)}
                                 for t, sizes in sorted(by_time.items())],
                'coverage': 'partial' if members['unknown_people'] or any(r['status'] == 'unknown' for r in results) else 'complete',
                'errors': members.get('errors', []) + [{'people': row['people'], **row['error']} for row in results if row.get('error')],
                'query_plan': {'member_queries': 1, 'slot_queries': queries},
                **({'error': error} if error else {}),
                'warning': 'Only returned selectable party sizes are checked. Ranges are supported party sizes, not a free-seat count or seat-type guarantee.'}

    def slots(self, ident, date, people, time=None):
        def parse(raw, _url):
            d = raw.get("base_date") if isinstance(raw, dict) else None
            if not isinstance(d, dict) or not all(type(d.get(k)) is int for k in ("year", "month", "day")) or f'{d["year"]:04d}-{d["month"]:02d}-{d["day"]:02d}' != date or type(raw.get("members")) is not int or raw["members"] != people or not isinstance(raw.get("selection"), dict):
                raise CliError("unexpected_response", "Slot response did not confirm the requested date and party size.")
            return sorted({time_value(s.get("time") if isinstance(s, dict) else None) for s in raw["selection"].values()})
        params = {"rst_id": ident, "svd": date.replace("-", ""), "svps": people}
        if time is not None:
            params['svt'] = time_value(time).replace(':', '')
        return self.client.read(endpoint("/en/booking/calendar/find_vacancy/", params), "json", parse)

    def availability(self, target, start, people=None, end=None, time=None, after="00:00", before="23:59"):
        end = end or start
        days = date_range(start, end)
        for value in (after, before):
            time_value(value)
        if time is not None:
            time_value(time)
        if (people is not None and (type(people) is not int or not 1 <= people <= 99)) or start < today_japan() or after > before:
            raise CliError("invalid_argument", "Use a future date range, 1..99 guests and after <= before.")
        ident = target if re.fullmatch(r"\d{1,12}", target) else self.ref(target)["id"]
        calendar, calendar_error, stopped = [], None, False
        try:
            calendar = self.calendar(ident)
        except CliError as error:
            calendar_error, stopped = error.as_dict(), error.code in STOP_CODES
        by_date = {d["date"]: d["raw_status"] for d in calendar}
        dates = []
        for day in days:
            raw = by_date.get(day)
            decision = calendar_decision(raw)
            row = {"date": day, "raw_calendar_status": raw, "calendar_hint": decision["hint"]}
            if len(days) > 1 and not calendar_error and decision["skip_online_slots"]:
                row.update(status="calendar_excluded", verification="calendar_overview", offered_times=None, matching_times=[], reason=decision["hint"])
            else:
                row.update(status="unknown", verification="not_queried", offered_times=None, matching_times=None,
                           error=calendar_error if calendar_error and stopped else {"code": "not_queried", "message": "Date has not been checked."})
            dates.append(row)
        planned = sum(d["status"] != "calendar_excluded" for d in dates)
        slot_queries, member_queries, contradictions = 0, 0, []
        for day in dates:
            if stopped:
                break
            if day["status"] == "calendar_excluded":
                continue
            try:
                if people is None:
                    member_queries += 1
                    result = self.all_party_slots(ident, day['date'], time, after, before, exclude_elapsed=True)
                    slot_queries += result['query_plan']['slot_queries']
                    day.pop('error', None)
                    day.update(result, status='unknown' if result['coverage'] == 'partial' else 'ok',
                               verification='member_options_and_slot_api')
                    stopped = result.get('error', {}).get('code') in STOP_CODES
                    if result['available_people'] and calendar_decision(day['raw_calendar_status'])['skip_online_slots']:
                        contradictions.append(day['date'])
                    continue
                slot_queries += 1
                offered = self.slots(ident, day["date"], people, time)
                now = datetime.now(JST)
                day.pop("error", None)
                day.update(status="ok", verification="slot_api", offered_times=offered,
                           matching_times=[t for t in offered if after <= t <= before and (day["date"] != now.date().isoformat() or t > now.strftime("%H:%M"))])
                if offered and calendar_decision(day["raw_calendar_status"])["skip_online_slots"]:
                    contradictions.append(day["date"])
            except CliError as error:
                day.update(status="unknown", verification="member_api_failed" if people is None else "slot_api_failed", error=error.as_dict())
                stopped = error.code in STOP_CODES
        skipped = sum(d["status"] == "calendar_excluded" for d in dates)
        unknown = sum(d["status"] == "unknown" for d in dates)
        return {"restaurant_id": ident, "people": people, "requested_range": {"start": start, "end": end, "after": after, "before": before, "anchor_time": time}, "calendar": calendar, "dates": dates,
                "coverage": "partial" if unknown or calendar_error or contradictions else "complete",
                'errors': ([{'scope': 'calendar', **calendar_error}] if calendar_error else []) +
                          [{'date': row['date'], **row['error']} for row in dates if row.get('error')] +
                          [{'date': row['date'], **failure} for row in dates for failure in row.get('errors', [])] +
                          ([{'code': 'conflicting_inventory', 'dates': contradictions, 'message': 'Calendar and slot responses disagree.'}] if contradictions else []),
                "coverage_basis": "calendar_screening_and_party_size_slot_verification" if people is None else
                                  "calendar_screening_and_candidate_slot_verification" if skipped else "all_dates_slot_verified",
                "query_plan": {"strategy": "calendar", "requested_dates": len(days), "planned_slot_queries": planned if people is not None else None,
                               "planned_candidate_dates": planned, "member_queries": member_queries, "slot_queries": slot_queries,
                               "slot_verified_dates": sum(any(r['status'] == 'ok' for r in d.get('people_results', [])) if people is None else d['status'] == 'ok' for d in dates),
                               "calendar_excluded_dates": skipped, "saved_slot_queries": skipped if people is not None else None,
                               "unknown_dates": unknown, "calendar_error": calendar_error, "calendar_slot_contradictions": contradictions},
                "warnings": ["Calendar candidates are not confirmed dinner inventory; candidates, missing dates and unknown codes require date/party-specific slots."]
                + (["Excluded dates follow the verified inbound frontend non-selectable states 0/3/4; offered_times=null means no slot request was made."] if skipped else [])
                + (["Calendar unavailable; safe daily fallback unless access/rate/request-budget limits stopped the query."] if calendar_error else [])
                + (["Calendar/slot responses disagree: inventory changed or the calendar contract drifted. Do not rely on pruning until reviewed."] if contradictions else [])
                + ["Responses are sequential snapshots, not atomic inventory. Inbound inventory may differ from Japanese-site courses; no reservation was submitted."]}

    def channel(self, target):
        ref, detail = self.ref(target), self.detail(target)
        try:
            days = self.calendar(ref["id"])
            return {"restaurant_id": ref["id"], "tabelog_online": "confirmed" if days else "unknown", "reservation_policy": detail["reservation_policy"],
                    "evidence": "Anonymous inbound booking calendar API", "warning": "A channel is not a confirmed date/time slot."}
        except CliError as error:
            return {"restaurant_id": ref["id"], "tabelog_online": "unknown", "reservation_policy": detail["reservation_policy"], "error": error.as_dict()}
