"""Extract facts from an identified public directory, shop or course-list page."""
import re
from urllib.parse import parse_qs, urljoin, urlsplit

from bs4 import BeautifulSoup

from .source import BASE, SHOP, SourceError


def text(node):
    if node is None:
        return None
    return " ".join(node.get_text(" ", strip=True).split()) or None


def fragment(raw):
    try:
        return BeautifulSoup(raw.decode("utf-8-sig"), "html.parser")
    except UnicodeError:
        raise SourceError("unexpected_encoding", "Expected a UTF-8 public page.") from None


def page(raw, url):
    soup = fragment(raw)
    canonical = soup.select_one('link[rel~="canonical"]')
    if canonical is None or canonical.get("href") != url:
        raise SourceError("page_mismatch", "Returned page did not identify the requested directory or shop.")
    return soup


def directory_areas(soup, url):
    # Only accept a direct child in the publisher's area hierarchy.
    if url == BASE + "/":
        segment = r"SA[0-9]{2}/"
    elif re.fullmatch(re.escape(BASE) + r"/SA[0-9]{2}/", url):
        segment = r"Y[A-Z0-9]{3}/"
    else:
        segment = r"X[A-Z0-9]{3}/"
    child_url = re.compile(re.escape(url) + segment)
    areas = {}
    for anchor in soup.select("a[href]"):
        href = urljoin(url, anchor["href"])
        if child_url.fullmatch(href) and text(anchor):
            areas.setdefault(href, {"name": text(anchor), "url": href})
    return list(areas.values())


def listing(soup, url, limit, match=None):
    cards = soup.select(".shopDetailText")
    items = []
    seen_urls = set()
    for card in cards:
        anchor = card.select_one(".shopDetailStoreName a[href]")
        href = urljoin(BASE, anchor["href"]) if anchor else ""
        if not re.fullmatch(re.escape(BASE) + SHOP, href) or not text(anchor):
            raise SourceError("source_schema_changed", "Directory card lacks an identifiable restaurant.")
        if href in seen_urls:
            continue
        seen_urls.add(href)
        items.append({"shop_id": href.removeprefix(BASE + "/str").rstrip("/"), "name": text(anchor), "url": href,
                      "access": text(card.select_one(".shopDetailInfoAccess")),
                      "dinner_budget": text(card.select_one(".dinnerBudget")),
                      "lunch_budget": text(card.select_one(".lunchBudget"))})
    if items:
        kind = "shops"
        coverage = "First directory page in publisher order; may include promotions."
    else:
        kind = "areas"
        items = directory_areas(soup, url)
        if not items:
            raise SourceError("listing_unavailable", "No supported restaurant cards or child area links.")
        coverage = "Published child areas; open a matching directory to continue."
    matched = [item for item in items if not match or match.casefold() in item["name"].casefold()]
    return {"directory": text(soup.select_one("h1")), "kind": kind, "unique_on_page": len(items),
            "matched_on_page": len(matched), kind: matched[:limit], "coverage": coverage}


def calendar_hint(soup, day):
    tables = soup.select(f'table[data-calendar="{day:%Y%m}"][summary="ネット予約の空席状況"]')
    marks = [text(cell.select_one(".status")) for table in tables for cell in table.select("td")
             if text(cell.select_one(".date")) == str(day.day)]
    symbol = marks[0] if len(marks) == 1 else None
    labels = set()
    for span in soup.select(".calendarIcnDescription li > span"):
        if symbol and text(span) == symbol:
            label = text(span.parent).removeprefix(symbol).lstrip(" ：:")
            if label:
                labels.add(label)
    label = labels.pop() if len(labels) == 1 else None
    return {"date": day.isoformat(), "state": "published" if label else "unknown", "symbol": symbol, "label": label,
            "scope": "Published day marker only; party, time and course availability unknown."}


def details(soup, shop_id, day=None):
    fields = {}
    for row in soup.select("table.infoTable tr"):
        label = text(row.find("th", recursive=False))
        value = text(row.find("td", recursive=False))
        if label and value and value not in ("－", "-"):
            fields[label] = value
    if not fields.get("店名"):
        raise SourceError("detail_unavailable", "Shop profile lacks the published shop name.")
    keys = ("住所", "アクセス", "営業時間", "定休日", "予算詳細", "料金備考", "個室", "禁煙・喫煙",
            "お子様連れ", "クレジットカード", "ネット予約受付時間")
    result = {"shop_id": shop_id, "name": fields["店名"], "details": {k: fields.get(k) for k in keys},
              "dinner_budget": text(soup.select_one(".shopInfoBudgetDinner")),
              "lunch_budget": text(soup.select_one(".shopInfoBudgetLunch"))}
    if day:
        result["calendar"] = calendar_hint(soup, day)
    return result


def courses(soup, shop_id, limit):
    prefix = f"{BASE}/str{shop_id}/"
    items = []
    for card in soup.select(".courseList > li"):
        anchor = card.select_one(".courseCassetteTitle a[href]")
        url = urljoin(prefix, anchor["href"]) if anchor else ""
        if not re.fullmatch(re.escape(prefix) + r"course_cno[a-zA-Z0-9_-]+/", url) or not text(anchor):
            raise SourceError("source_schema_changed", "Could not identify a course belonging to this shop.")
        conditions = [text(li) for li in card.select(".summaryList > li")]
        items.append({"title": text(anchor), "course_id": url.removeprefix(prefix + "course_cno").rstrip("/"), "url": url, "price": text(card.select_one(".coursePrice")),
                      "published_conditions": [s for s in conditions if s and ("利用人数" in s or "コース品数" in s)],
                      "deadline": text(card.select_one(".courseCassetteReserveLimit"))})
    if not items:
        raise SourceError("courses_unavailable", "No supported course records on the returned page.")
    return {"shop_id": shop_id, "publisher_update": text(soup.select_one(".shopInnerCourse .mainHeading .date")),
            "courses_on_page": len(items), "courses": items[:limit]}


def seats(raw, shop, course, date, time, people):
    """Verify the returned conditions before interpreting positive or empty inventory."""
    soup = fragment(raw)
    echo = soup.select_one("input#returnUrl[value]")
    day = date.strftime("%Y%m%d")
    clock = time.replace(":", "")
    expected = {"shop": shop, "course_id": course, "date": date.isoformat(), "time": time, "people": people}
    if echo is None:
        raise SourceError("stock_unverified", "No returned lookup conditions.")
    address = urlsplit(echo["value"])
    query = parse_qs(address.query)
    if (address.netloc or address.scheme or address.path != f"/str{shop}/course/rpn{people}/"
            or query.get("RDT") != [day] or query.get("RTM") != [clock]):
        raise SourceError("stock_unverified", "Returned shop, date, time or party differs from the request.")
    unavailable = soup.select_one(".reserveSearchResultNone .seatListNotFoundTitle")
    cards = soup.select(".reserveSeatListWrap .reserveSeatList > li")
    if not cards and text(unavailable) == "ご指定の条件でご予約できるお席が見つかりませんでした。":
        return {**expected, "state": "no_matching_seats", "seat_types": []}
    if not cards or unavailable is not None:
        raise SourceError("stock_unverified", "Unrecognized or conflicting seat inventory.")
    target = re.escape(f"{BASE}/str{shop}/yoyaku/reserve/{day}_{clock}_rpn{people}_cno{course}_rsi")
    types = []
    for card in cards:
        anchor = card.select_one(".reservationBtnWrap a.reservationBtn[href]")
        seat = text(card.select_one(".seatTypeName"))
        if not anchor or not seat or not re.fullmatch(target + r"[0-9]+/", urljoin(BASE, anchor["href"])):
            raise SourceError("stock_unverified", "Seat option did not identify the requested conditions.")
        if seat not in types:
            types.append(seat)
    return {**expected, "state": "available", "seat_types": types}
