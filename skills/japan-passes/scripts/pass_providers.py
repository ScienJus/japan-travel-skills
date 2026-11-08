"""Official provider entry points and live catalog bindings; no bundled prices."""

import re
import urllib.parse as urls
import pass_source as s

WEST = "https://www.westjr.co.jp/travel-information/en/tickets-passes/"
PROVIDERS = {
    "jr-west": {
        "name": "JR-WEST",
        "regions": "Kansai, Hokuriku, Chugoku, Shikoku and joint regional passes",
        "catalogs": [WEST + "jrwest-rail-pass/", WEST + "other/"],
        "transport": "python",
    },
    "jr-central": {
        "name": "JR-Central/JR-West Tourist Pass",
        "regions": "Central Japan, Tokai, Kansai, Hokuriku, Fuji",
        "catalogs": ["https://touristpass.jp/en/"],
        "transport": "python",
        "conditions": ["https://touristpass.jp/when_using/en/"],
    },
    "jr-hokkaido": {
        "name": "JR Hokkaido",
        "regions": "Hokkaido",
        "catalogs": ["https://www.jrhokkaido.co.jp/global/english/ticket/"],
        "transport": "python",
    },
    "jr-shikoku": {
        "name": "JR Shikoku",
        "regions": "Shikoku",
        "catalogs": ["https://shikoku-railwaytrip.com/pass-information/"],
        "transport": "python",
    },
    "jr-group": {
        "name": "JAPAN RAIL PASS / JR Group",
        "regions": "Nationwide",
        "catalogs": ["https://japanrailpass.net/en/purchase/price/"],
        "transport": "curl",
        "conditions": [
            "https://japanrailpass.net/en/about_jrp/riyou/",
            "https://japanrailpass.net/en/about_jrp/route/",
        ],
    },
    "jr-east": {
        "name": "JR East",
        "regions": "Tokyo, Kanto, Tohoku, Niigata, Nagano and joint passes",
        "reference": "https://www.jreast.co.jp/multi/pass/",
        "state": "reference_only",
        "reason": "Anonymous direct access is not supported by this adapter.",
    },
    "jr-kyushu": {
        "name": "JR Kyushu",
        "regions": "Kyushu",
        "reference": "https://www.jrkyushu.co.jp/english/railpass/railpass.html",
        "state": "reference_only",
        "reason": "Anonymous direct access is not supported by this adapter.",
    },
}


def supported(provider):
    return "catalogs" in PROVIDERS[provider]


def valid(provider, url):
    p = urls.urlsplit(url)
    if p.scheme != "https" or p.username or p.password or p.port is not None:
        return False
    if provider not in PROVIDERS or not supported(provider):
        return False
    fixed = PROVIDERS[provider]["catalogs"] + PROVIDERS[provider].get("conditions", [])
    if url in fixed:
        return True
    if provider == "jr-west":
        return (
            p.netloc == "www.westjr.co.jp"
            and not p.query
            and not p.fragment
            and bool(
                re.fullmatch(
                    r"/travel-information/en/tickets-passes/(?:jrwest-rail-pass|other)/[a-z0-9_-]+/(?:index\.html)?",
                    p.path,
                )
            )
        )
    if provider == "jr-central":
        return (
            p.netloc == "touristpass.jp"
            and not p.query
            and not p.fragment
            and bool(re.fullmatch(r"/en/[a-z_]+/", p.path))
        )
    if provider == "jr-hokkaido":
        return (
            p.netloc == "www.jrhokkaido.co.jp"
            and p.path == "/global/english/ticket/railpass/index.html"
            and not p.query
            and (not p.fragment or bool(re.fullmatch(r"[a-z0-9_-]+", p.fragment)))
        )
    if provider == "jr-shikoku":
        return (
            p.netloc == "shikoku-railwaytrip.com"
            and p.path == "/pass-information/"
            and p.query in ("pref=all", "pref=kagawa")
            and not p.fragment
        )
    return False


def allowed(url):
    try:
        return any(valid(p, url) for p in PROVIDERS)
    except ValueError:
        return False


def check_page(provider, page):
    expected = {
        "jr-west": r"JR-WEST|West Japan|Rail Pass",
        "jr-central": r"Tourist Pass",
        "jr-hokkaido": r"Hokkaido|Rail Pass",
        "jr-shikoku": r"SHIKOKU|Shikoku",
        "jr-group": r"JAPAN RAIL PASS",
    }[provider]
    if not re.search(expected, page.title, re.I):
        s.fail("Official document title does not match its provider.")


def entry(provider, name, url, node=None, kind="pass"):
    value = {
        "provider": provider,
        "name": s.text(name),
        "url": url,
        "kind": kind,
        "sales_status": {"state": "unknown", "evidence": None},
    }
    if node is not None:
        raw = node.text()
        match = re.search(
            r"(?:Sales ended|Sales suspended|Discontinued)[^.]*\.", raw, re.I
        )
        if match:
            value["sales_status"] = {
                "state": "ended_or_suspended",
                "evidence": match[0],
            }
        value["region_hints"] = [
            n.attrs["alt"] for n in node.nodes("img") if n.attrs.get("alt")
        ]
    if not value["name"]:
        s.fail("Empty official catalog entry name.")
    return value


def discover(provider, page, url):
    check_page(provider, page)
    records = []
    if provider == "jr-west":
        cards = list(page.main.nodes("li", "item"))
        for node in cards:
            headings = list(node.nodes("h2"))
            if len(headings) != 1:
                continue
            links = [
                urls.urljoin(url, n.attrs.get("href", "")) for n in node.nodes("a")
            ]
            links = [
                u
                for u in links
                if valid(provider, u) and u not in PROVIDERS[provider]["catalogs"]
            ]
            if not links:
                continue
            heading = headings[0]
            name = s.text(
                " ".join(
                    c.text() if isinstance(c, s.Node) else c
                    for c in heading.children
                    if not isinstance(c, s.Node)
                    or "note" not in c.attrs.get("class", "").split()
                )
            )
            records.append(
                entry(
                    provider,
                    name,
                    s.one(links, "Ambiguous official pass details link."),
                    node,
                )
            )
    elif provider == "jr-central":
        scope = s.one(
            (n for n in page.main.nodes() if n.attrs.get("id") == "touristpass"),
            "Missing Tourist Pass catalog area.",
        )
        for node in scope.nodes("div", "item"):
            heading = s.one(node.nodes("h3"), "Missing Tourist Pass name.")
            link = s.one(
                node.nodes("a", "btn-detail"), "Missing Tourist Pass details link."
            )
            target = urls.urljoin(url, link.attrs.get("href", ""))
            if not valid(provider, target):
                s.fail("Unexpected Tourist Pass details URL.")
            records.append(
                entry(provider, heading.text() + " Tourist Pass", target, node)
            )
    elif provider == "jr-hokkaido":
        for link in page.main.nodes("a"):
            target = urls.urljoin(url, link.attrs.get("href", ""))
            if not valid(provider, target) or not urls.urlsplit(target).fragment:
                continue
            node = link.parent
            while node is not None and not list(node.nodes("h3")):
                node = node.parent
            if node is None:
                s.fail("Missing Hokkaido pass heading.")
            heading = s.one(node.nodes("h3"), "Ambiguous Hokkaido pass card.")
            records.append(entry(provider, heading.text(), target, node))
    elif provider == "jr-shikoku":
        for link in page.root.nodes("a"):
            target = urls.urljoin(url, link.attrs.get("href", ""))
            if not valid(provider, target) or not urls.urlsplit(target).query:
                continue
            if not link.text():
                continue
            record = entry(provider, link.text(), target, kind="pass")
            variant = dict(urls.parse_qsl(urls.urlsplit(target).query))["pref"]
            for note in page.main.nodes("p", "pass-status-note"):
                if (
                    "-" + variant in note.attrs.get("class", "").split()
                    and "no longer available for purchase" in note.text().lower()
                ):
                    record["sales_status"] = {
                        "state": "ended_or_suspended",
                        "evidence": note.text(),
                    }
            records.append(record)
    elif provider == "jr-group":
        if "JAPAN RAIL PASS" not in page.main.text():
            s.fail("Missing nationwide pass identity.")
        records = [entry(provider, "JAPAN RAIL PASS", url, kind="pass_family")]
    unique = {}
    for record in records:
        if record["url"] in unique and s.norm(unique[record["url"]]["name"]) != s.norm(
            record["name"]
        ):
            s.fail("Catalog entry has conflicting names.")
        unique[record["url"]] = record
    if not unique:
        s.fail(
            "No supported entries in the official catalog; coverage is unknown, not empty."
        )
    if len(unique) > 100:
        s.fail("Official catalog exceeds the adapter scope.")
    return list(unique.values())


def catalog(client, provider):
    profile = PROVIDERS[provider]
    if not supported(provider):
        raise s.Error(
            "provider_unavailable",
            profile["reason"],
            reference_url=profile["reference"],
        )
    records = []
    sources = []
    for url in profile["catalogs"]:
        raw, meta = client.read(url, profile["transport"])
        page = s.Page(raw)
        records.extend(discover(provider, page, url))
        sources.append(meta)
    unique = {r["url"]: r for r in records}
    return list(unique.values()), sources


def scope(provider, page, url):
    check_page(provider, page)
    p = urls.urlsplit(url)
    if provider == "jr-hokkaido":
        if not p.fragment:
            s.fail("Select a native Hokkaido product fragment from the catalog.")
        return s.one(
            (n for n in page.main.nodes("section") if n.attrs.get("id") == p.fragment),
            "Missing selected Hokkaido pass section.",
        )
    if provider == "jr-shikoku":
        value = dict(urls.parse_qsl(p.query)).get("pref")
        return s.one(
            (
                n
                for n in page.main.nodes("div", "js-toggle-content")
                if "-" + str(value) in n.attrs.get("class", "").split()
            ),
            "Missing selected Shikoku pass area.",
        )
    return page.main


def conditions(provider, page, product_url):
    check_page(provider, page)
    if provider == "jr-central":
        slug = urls.urlsplit(product_url).path.strip("/").split("/")[-1]
        classes = {
            "takayama_hokuriku": "guide_takayama",
            "alpine": "guide_alpine",
            "ise_kumano": "guide_ise",
            "fuji_shizuoka": "guide_fuji",
        }
        if slug not in classes:
            s.fail("No validated product-specific Tourist Pass terms binding.")
        common = [
            s.one(
                (n for n in page.main.nodes("section") if n.attrs.get("id") == key),
                "Missing common Tourist Pass terms.",
            )
            for key in ("conditions_for_use", "important_notes")
        ]
        specific = s.one(
            page.main.nodes("div", classes[slug]),
            "Missing product-specific Tourist Pass terms.",
        )
        return [
            ("common_eligibility", common[0]),
            ("product_conditions", specific),
            ("common_conditions", common[1]),
        ]
    return [("conditions", page.main)]


def check_product(provider, record, root, page):
    if provider == "jr-group":
        return

    def key(value):
        return re.sub(r"[-‐‑–—’']", "", s.norm(value))

    name = key(record["name"])
    candidates = [n.text() for n in root.nodes() if n.tag in ("h1", "h2")]
    if provider == "jr-shikoku":
        candidates.append(root.text())
    if not any(name in key(v) for v in candidates):
        s.fail("Product document does not match the live catalog name.")
