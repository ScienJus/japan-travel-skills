"""DOM-based parsers. Upstream selector attribution is retained under licenses/."""
import copy
import html
import json
import re
import xml.etree.ElementTree as ET
from urllib.parse import urljoin, urlsplit, parse_qs

from bs4 import BeautifulSoup

from .core import BASE, RESTAURANT_PATH, CliError, point_value
from .detail_info import practical_info


def soup(value):
    return BeautifulSoup(value, "html.parser")


def text_of(value):
    if value is None:
        return ""
    value = value.decode_contents() if hasattr(value, "decode_contents") else str(value)
    value = re.sub(r"<br\s*/?>", "\n", value, flags=re.I)
    value = re.sub(r"<[^>]+>", "", value)
    value = re.sub(r"[ \t\r\f\v]+", " ", value)
    value = re.sub(r" ?\n ?", "\n", value)
    return re.sub(r"\n{2,}", "\n", html.unescape(value).replace("\xa0", " ")).strip()


def number(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(re.sub(r"[,\s]", "", str(value)))
        return result if result != float("inf") and result != float("-inf") and result == result else None
    except ValueError:
        return None


def pick(node, selector):
    element = node.select_one(selector)
    return text_of(element) or None


def pagination(body):
    doc = soup(body) if isinstance(body, str) else body
    values = [number(text_of(n)) for n in doc.select(".c-pagination__num")]
    values = [int(v) for v in values if v is not None]
    return {"current": number(pick(doc, ".c-pagination__num.is-current")), "last": max(values) if values else None}


def parse_map(body, source):
    if '\x00' in body or re.search(r"<!\s*(?:DOCTYPE|ENTITY)\b", body, re.I):
        raise CliError("unexpected_response", "DTD/entities are not accepted in map XML.")
    try:
        root = ET.fromstring(body)  # nosec B314 -- NUL and DTD/entities rejected above; regression-tested.
        info = root.find("srchinfo")
        if root.tag != "markers" or info is None or not re.fullmatch(r"\d+", info.get("cnt", "")):
            raise ValueError()
    except (ET.ParseError, ValueError):
        raise CliError("unexpected_response", "Expected restaurant map XML.") from None
    items, invalid = [], 0
    for marker in root.findall("marker"):
        a = marker.attrib
        path = RESTAURANT_PATH.search(a.get("rsturl", ""))
        try:
            point = point_value([a.get("lat"), a.get("lng")])
        except CliError:
            invalid += 1
            continue
        if not path or path[2] != a.get("id") or not a.get("rstname"):
            invalid += 1
            continue
        score = number(a.get("score"))
        items.append({"id": a["id"], "name": a["rstname"], "url": f"{BASE}/{path[1]}/",
                      "rating": score if score is not None and 0 < score <= 5 else None,
                      "review_count": int(a["rvwcnt"]) if a.get("rvwcnt", "").isdigit() else None,
                      "cuisines": [s.strip() for s in re.split(r"[、,]", a.get("rstcat", "")) if s.strip()], **point,
                      "coordinate_source": source, "budgets": {"lunch": a.get("price_range1"), "dinner": a.get("price_range2")},
                      "budget_raw": {"price_range1": a.get("price_range1"), "price_range2": a.get("price_range2")}})
    total = int(info.get("cnt"))
    if not items and (total or invalid):
        raise CliError("unexpected_response", "Map contained no usable restaurant records.")
    return {"items": items, "upstream_total": total, "invalid": invalid, "has_next": bool(info.get("nextpg"))}


def parse_awards(body, source):
    doc = soup(body) if isinstance(body, str) else body
    region = doc.select_one(".rstinfo-table") or doc
    records = {}
    for badge in region.select('[class*="c-badge-hyakumeiten"]'):
        caption = text_of(badge.select_one("i") or badge)
        year = re.search(r"\b(20\d{2})\b", caption)
        anchor = badge.find_parent("a") or badge.select_one("a")
        url = anchor.get("href", "") if anchor else ""
        match = re.search(r"award\.tabelog\.com/hyakumeiten/([a-z_]+)/?(20\d{2})", url)
        record = {"type": "hyakumeiten", "caption": caption, "year": int(year[1]) if year else int(match[2]) if match else None,
                  "category": match[1] if match else None, "source": source, "official_url": html.unescape(url) if match else None}
        records[(record["category"] or caption, record["year"])] = record
    return list(records.values())


def matching_awards(records, year=None, category=None, latest=None):
    return [r for r in records if r.get("type") == "hyakumeiten" and (not category or r.get("category") == category)
            and (r.get("year") == year if year else bool(r.get("category")) and r.get("year") == (latest or {}).get(r["category"]))]


def _cell_text(cell):
    cell = copy.deepcopy(cell)
    for node in cell.select(".rstinfo-table__map-wrap, button, [class*=pr-comment__more-icon]"):
        node.decompose()
    for notice in cell.select(".rstinfo-table__notice"):
        if notice.find("a"):
            notice.decompose()
    for icon in cell.select("i.c-rating-v3__time[aria-label]"):
        icon.replace_with("\n"+icon["aria-label"]+": ")
    for line in cell.select("span.line"):
        line.replace_with("\n")
    value = re.sub(r"</(?:p|li|div|dd|dt|h\d)>", "\n", cell.decode_contents(), flags=re.I)
    return text_of(value).replace("～", "~")


def _day_list(title):
    names = {"sun": 0, "mon": 1, "tue": 2, "wed": 3, "thu": 4, "fri": 5, "sat": 6}
    result = []
    for part in re.split(r"[,、，]", title):
        span = re.match(r"\s*([A-Za-z]{3})[a-z]*\s*[-–]\s*([A-Za-z]{3})", part)
        if span and span[1].lower() in names and span[2].lower() in names:
            start, end = names[span[1].lower()], names[span[2].lower()]
            result += [(start+i) % 7 for i in range((end-start) % 7+1)]
        elif part.strip()[:3].lower() in names:
            result.append(names[part.strip()[:3].lower()])
    return result


def _hour_range(value):
    match = re.search(r"(\d{1,2}):(\d{2})\s*(AM|PM)?\s*[-–〜~]\s*(\d{1,2}):(\d{2})\s*(AM|PM)?", value, re.I)
    if not match:
        return None
    def minute(h, m, meridiem):
        hour = int(h) if not meridiem else int(h) % 12 + (12 if meridiem.upper() == "PM" else 0)
        return hour*60+int(m)
    start, end = minute(*match.group(1, 2, 3)), minute(*match.group(4, 5, 6))
    if end <= start:
        end += 1440
    result = {"open": start, "close": end}
    order = re.search(r"L\.?O\.?\s*([^\n]*)", value, re.I)
    if order and order[1].strip():
        result["lastOrder"] = order[1].strip()
    return result


def parse_hours(doc):
    result = []
    for item in doc.select(".rstinfo-table__business-list > .rstinfo-table__business-item"):
        title = item.find("p", class_="rstinfo-table__business-title", recursive=False)
        if not title:
            continue
        values = [text_of(n) for n in item.select(".rstinfo-table__business-dtl-text")]
        row = {"title": text_of(title), "dayList": _day_list(text_of(title)),
               "closed": any(v.lower() in ("closed", "정기휴일", "公休日", "定期休息日", "วันหยุด", "定休日", "休業", "休み") for v in values),
               "rangeList": [r for v in values if (r := _hour_range(v)) is not None]}
        kinds = []
        for token in re.split(r'[,、，]', text_of(title).lower()):
            token = token.strip()
            if token in ('public holiday', 'public holidays', 'holiday', 'holidays', '祝日'):
                kinds.append('holiday')
            elif token in ('day before public holiday', 'day before holiday', '祝前日'):
                kinds.append('before_holiday')
            elif token in ('day after public holiday', 'day after holiday', '祝後日'):
                kinds.append('after_holiday')
        if kinds:
            row['day_types'] = kinds
        result.append(row)
    return result


def parse_detail(body, ref, url):
    doc, ld, info, errors = soup(body), {}, [], []
    for script in doc.select('script[type="application/ld+json"]'):
        try:
            value = json.loads(script.string or script.get_text())
            blocks = value if isinstance(value, list) else value.get("@graph", [value])
            ld = next((b for b in blocks if isinstance(b, dict) and (b.get("@type") == "Restaurant" or isinstance(b.get("@type"), list) and "Restaurant" in b["@type"])), ld)
        except (ValueError, TypeError, AttributeError):
            errors.append({'scope': 'structured_detail', 'code': 'unexpected_response',
                           'message': 'Restaurant structured data could not be parsed; HTML fields are retained.'})
    tables = doc.select(".rstinfo-table tr, .rstinfo-table__table tr")
    if tables:
        for row in tables:
            label, cell = row.find("th", recursive=False), row.find("td", recursive=False)
            if cell is None or label is None:
                continue
            if "rstinfo-badge" in cell.get("class", []):
                value = "\n".join(dict.fromkeys(text_of(n) for n in cell.select('[class*="c-badge-"] i')))
            else:
                value = _cell_text(cell)
            if value:
                info.append({"label": text_of(label) or "Phone", "value": value})
    name = ld.get("name") or pick(doc, ".rdheader-rstname")
    if not name:
        raise CliError("unexpected_response", "Restaurant identity is missing.")
    aggregate = ld.get("aggregateRating") or {}
    result = {"id": ref["id"], "name": name, "url": url,
              "rating": number(aggregate.get("ratingValue", pick(doc, ".rdheader-rating__score-val-dtl"))),
              "review_count": number(aggregate.get("ratingCount")),
              "cuisines": [s.strip() for s in re.split(r"[、,]", ld.get("servesCuisine", "")) if s.strip()],
              "price_range": ld.get("priceRange", "").replace("～", "~") or None, "phone": ld.get("telephone"),
              "hours": parse_hours(doc), "info": info, "awards": parse_awards(doc, url),
              "reservation_policy": [r for r in info if re.search(r"reserv|予約", r["label"], re.I)],
              "practical_info": practical_info(doc, info, url),
              "data_source": "server-rendered HTML and Restaurant JSON-LD; no verified standalone detail API"}
    try:
        geo = ld.get("geo", {})
        result.update(point_value([geo.get("latitude"), geo.get("longitude")]), coordinate_source=url)
    except CliError:
        if ld.get('geo'):
            errors.append({'scope': 'coordinates', 'code': 'unexpected_response', 'message': 'Published restaurant coordinates are invalid.'})
    if errors:
        result.update(coverage='partial', errors=errors)
    return result


def parse_courses(body, ref, url):
    doc = soup(body)
    identity = doc.select_one('link[rel="canonical"]') or doc.select_one('meta[property="og:url"]')
    identity_url = (identity.get('href') or identity.get('content')) if identity else url
    if not re.search(r'/'+re.escape(ref['id'])+r'(?:/|$)', urlsplit(identity_url).path):
        raise CliError('unexpected_response', 'Course page restaurant identity does not match.')
    items = []
    for card in doc.select('.rstdtl-course-list__inner'):
        anchor = card.select_one('.rstdtl-course-list__target[href]')
        name = pick(card, '.rstdtl-course-list__course-title-text')
        if not anchor or not name:
            raise CliError('unexpected_response', 'Unrecognized course card.')
        link = urljoin(url, anchor['href'])
        parsed = urlsplit(link)
        match = re.search(r'/party/(\d+)', parsed.path)
        ident = match[1] if match else parse_qs(parsed.query).get('pplan_id', [None])[0]
        if parsed.hostname != 'tabelog.com' or not ident or match and f'/{ref["id"]}/party/' not in parsed.path:
            raise CliError('unexpected_response', 'Unrecognized course identity/link.')
        price = number(pick(card, '.rstdtl-course-list__price-num em'))
        rules = []
        for node in card.select('.rstdtl-course-list__course-rule'):
            for term in node.select('dt'):
                value = term.find_next_sibling('dd')
                if value:
                    rules.append({'label': text_of(term), 'value': text_of(value)})
        items.append({'id': ident, 'name': name, 'url': link, 'price_yen': price,
                      'price_raw': pick(card, '.rstdtl-course-list__price'),
                      'tax': pick(card, '.rstdtl-course-list__price-num-tax'),
                      'description': pick(card, '.rstdtl-course-list__desc'),
                      'labels': [text_of(x) for x in card.select('.rstdtl-course-list__label')], 'rules': rules})
    items = list({r['id']: r for r in items}.values())
    pager = pagination(doc)
    empty = bool(re.search(r'コース(?:情報)?(?:は|が)(?:登録されていません|ありません)|no courses', text_of(doc), re.I))
    if not items and not identity and not doc.select_one('.rdheader-rstname'):
        raise CliError('unexpected_response', 'Unrecognized restaurant course page; empty inventory is not established.')
    errors = []
    if pager['last'] and pager['last'] > 1:
        errors.append({'code': 'incomplete_courses', 'message': 'Only the first course page was read; more course pages are listed.'})
    if not items and not empty:
        errors.append({'code': 'unverified_courses', 'message': 'No course cards or explicit empty-menu notice were recognized.'})
    return {'items': items if items or empty else None, 'source_url': url, 'errors': errors, 'coverage': 'partial' if pager['last'] and pager['last'] > 1 else
            'listed_courses' if items else 'explicit_empty' if empty else 'not_listed',
            'warning': 'Published course summaries only; menus, dates and prices may have conditions. No seat inventory was queried.'}


def parse_cards(body):
    doc, items, invalid = soup(body), [], 0
    for card in doc.select(".list-rst"):
        anchor = card.select_one(".list-rst__rst-name-target")
        ident, url = card.get("data-rst-id"), card.get("data-detail-url") or (anchor.get("href") if anchor else None)
        if not ident or not url or not text_of(anchor):
            invalid += 1
            continue
        match = RESTAURANT_PATH.search(urlsplit(urljoin(BASE, url)).path)
        if urlsplit(urljoin(BASE, url)).hostname != 'tabelog.com' or not match or match[2] != ident:
            invalid += 1
            continue
        genre = pick(card, ".list-rst__area-genre") or ""
        budgets = {}
        for meal in ("dinner", "lunch"):
            icon = card.select_one(".c-rating-v3__time--"+meal)
            val = icon.find_next_sibling("span", class_="c-rating-v3__val") if icon else None
            budgets[meal] = text_of(val) or None
        items.append({"id": ident, "name": text_of(anchor), "url": urljoin(BASE, url),
                      "rating": number(pick(card, ".list-rst__rating-val")), "review_count": number(pick(card, ".list-rst__rvw-count-num")),
                      "cuisines": [s.strip() for s in "/".join(genre.split(" / ")[1:]).split(",") if s.strip()], "budgets": budgets, "awards": []})
    counts = [number(text_of(n)) for n in doc.select(".c-page-count__num strong")]
    count = {"from": counts[0] if len(counts) > 0 else None, "to": counts[1] if len(counts) > 1 else None, "total": counts[2] if len(counts) > 2 else None}
    if len(counts) == 2 and doc.select_one(".rstlist-notfound"):
        count = {"from": 0, "to": 0, "total": 0}
    return {"items": items, "invalid": invalid, "count": count, "pagination": pagination(doc)}


def _review_fields(node, detail=False):
    ratings = node.select_one(".rvw-item__single-ratings-total" if detail else ".rvw-item__ratings-total")
    meals = [meal for meal in ('lunch', 'dinner') if ratings and ratings.select_one('.c-rating-v3__time--'+meal)]
    return {"reviewer": pick(node, ".rvw-item__rvwr-name"), "rating": number(pick(ratings, ".c-rating-v3__val")) if ratings else None,
            'meal': meals[0] if len(meals) == 1 else None,
            "spend": (pick(node, ".rvw-item__payment-amount-delimiter") or "").replace("～", "~") or None,
            "visited_at_raw": pick(node, ".rvw-item__date-inner span"),
            "text": pick(node, ".rvw-item__rvw-comment p")}


def parse_reviews(body, page):
    doc = soup(body)
    pager = pagination(doc)
    if pager["current"] is not None and pager["current"] != page:
        raise CliError('unexpected_response', 'Review pagination does not match the requested page; remaining reviews are unknown.')
    items = []
    for node in doc.select(".rvw-item.js-rvw-item-clickable-area"):
        clone = copy.deepcopy(node)
        for badge in clone.select(".rstdtl-rvw-country"):
            badge.decompose()
        link = node if node.has_attr("data-detail-url") else node.select_one("[data-detail-url]")
        items.append({**_review_fields(clone), "url": link.get("data-detail-url") if link else None})
    return {"items": items, "lastPage": pager["last"], "note": None}


def parse_review_read(body):
    doc = soup(body)
    for badge in doc.select(".rstdtl-rvw-country"):
        badge.decompose()
    visits = [_review_fields(node, True) for node in doc.select(".rvw-item__review-contents")]
    if not visits:
        raise CliError("unexpected_response", "No recognizable review body.")
    return {"reviewer": pick(doc, ".rvw-item__rvwr-name"), "visits": visits}
