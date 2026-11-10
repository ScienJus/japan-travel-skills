#!/usr/bin/env python3
"""Build the three GitHub Pages documents and public demo outside the checkout."""

import argparse
from html import escape
import json
from pathlib import Path
import shutil
from string import Template
import subprocess
import sys
from urllib.parse import quote, unquote, urlsplit, urlunsplit
from xml.etree import ElementTree

from markdown_it import MarkdownIt

from check_privacy import check_root


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"
REPOSITORY = "https://github.com/ScienJus/japan-travel-skills"
DEFAULT_URL = "https://www.scienjus.com/japan-travel-skills/"
PLANNER = ROOT / "skills/japan-travel-planner"
DEMO = "assets/kyoto-nara-demo.html"
ARTICLES = {
    "check-japan-itinerary.html": (
        "docs/check-japan-itinerary.md", "01 / Review",
        "Check a Japan itinerary with Codex for closures, last admission and tight rail or bus connections. Keep fixed bookings and source links.",
    ),
    "japan-itinerary-map-and-powerpoint.html": (
        "docs/japan-itinerary-map-and-powerpoint.md", "02 / Share",
        "Turn a Japan itinerary into an interactive HTML map and PowerPoint handoff. Open a Kyoto–Nara demo and generate both views from one plan.",
    ),
}
NAVIGATION = (
    ("index.html", "Overview"),
    ("check-japan-itinerary.html", "Check an itinerary"),
    ("japan-itinerary-map-and-powerpoint.html", "Map & PowerPoint"),
)


def canonical_base(value):
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.query or parsed.fragment or "\\" in value
            or any(c.isspace() or ord(c) < 32 for c in value)
            or any(part in (".", "..") for part in unquote(parsed.path).split("/"))):
        raise ValueError("Site URL must be a public HTTPS base without credentials, queries or fragments")
    return value.rstrip("/") + "/"


def template(name):
    return Template((SITE / "templates" / name).read_text(encoding="utf-8"))


def article_link(href, source):
    target = urlsplit(href)
    if target.scheme == "https" and target.hostname and target.username is None:
        return href
    if target.scheme or target.netloc or not target.path:
        if not target.scheme and not target.netloc and target.fragment:
            return href
        raise ValueError("Unsupported article link in {}".format(source.name))
    path = (source.parent / unquote(target.path)).resolve()
    if ROOT not in path.parents or not path.is_file():
        raise ValueError("Unresolved article link in {}".format(source.name))
    relative = path.relative_to(ROOT).as_posix()
    for page, (filename, _, _) in ARTICLES.items():
        if relative == filename:
            return urlunsplit(("", "", page, target.query, target.fragment))
    return REPOSITORY + "/blob/main/" + quote(relative, safe="/") + urlunsplit(
        ("", "", "", target.query, target.fragment)
    )


def render_article(source):
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(source.read_text(encoding="utf-8"))
    if len(tokens) < 3 or tokens[0].type != "heading_open" or tokens[0].tag != "h1":
        raise ValueError("Article needs an opening H1: {}".format(source.name))
    title = tokens[1].content
    sections = []
    for index, token in enumerate(tokens[3:], start=3):
        if token.type == "heading_open" and token.tag == "h2":
            anchor = "section-{}".format(len(sections) + 1)
            token.attrSet("id", anchor)
            sections.append((anchor, tokens[index + 1].content))
        for child in token.children or ():
            if child.type == "link_open":
                child.attrSet("href", article_link(child.attrGet("href"), source))
    return title, md.renderer.render(tokens[3:], md.options, {}), sections


def render_page(page, title, description, canonical, content):
    navigation = []
    for href, label in NAVIGATION:
        current = ' aria-current="page"' if href == page else ""
        navigation.append('<a href="{}"{}>{}</a>'.format(href, current, escape(label)))
    return template("page.html").substitute(
        title=escape(title), description=escape(description), canonical=escape(canonical),
        repository=REPOSITORY, navigation="".join(navigation), content=content,
    )


def make_demo(output):
    example = PLANNER / "examples/kyoto-nara-demo.json"
    if json.loads(example.read_text(encoding="utf-8")).get("demo") is not True:
        raise ValueError("The public plan must be marked as a demo")
    target = output / DEMO
    subprocess.run([sys.executable, str(PLANNER / "scripts/render_plan.py"),
                    "--input", str(example), "--output", str(target)], check=True)
    html = target.read_text(encoding="utf-8")
    if html.count("</head>") != 1:
        raise ValueError("Unexpected demo HTML structure")
    # The demo is directly usable; the surrounding article is the search landing page.
    target.write_text(html.replace("</head>", '<meta name="robots" content="noindex,follow">\n</head>', 1),
                      encoding="utf-8")


def build(output, site_url):
    base = canonical_base(site_url)
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Build output must stay outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    (output / "assets").mkdir()
    for asset in ("site.css", "kyoto-evening.jpg"):
        shutil.copyfile(SITE / "assets" / asset, output / "assets" / asset)
    (output / "index.html").write_text(render_page(
        "index.html", "Japan Travel Skills — Japan itinerary planning for Codex",
        "Plan and check Japan itineraries with read-only Agent Skills. Look up rail and bus routes, hotels and food, and share an interactive map or presentation brief.",
        base, template("home.html").substitute(repository=REPOSITORY),
    ), encoding="utf-8")

    for page, (source, kicker, description) in ARTICLES.items():
        title, body, sections = render_article(ROOT / source)
        demo = page == "japan-itinerary-map-and-powerpoint.html"
        button = '<a class="button primary" href="#demo">Try the Kyoto–Nara demo</a>' if demo else ""
        if demo:
            sections.append(("demo", "Explore Kyoto and Nara"))
        links = "".join('<a href="#{}">{}</a>'.format(anchor, escape(label))
                        for anchor, label in sections)
        theme = "share-task" if demo else "review-task"
        content = (
            '<header class="shell article-head {}"><p class="kicker">{}</p><h1>{}</h1>{}</header>'
            '<div class="shell article-layout">'
            '<aside class="article-index"><p class="kicker">On this page</p>'
            '<nav aria-label="Article sections">{}</nav></aside>'
            '<article class="prose">{}</article></div>'
        ).format(theme, escape(kicker), escape(title), button, links, body)
        if demo:
            content += (
                '<section class="shell demo-section" id="demo" aria-labelledby="demo-title">'
                '<p class="kicker">Public example / 01</p><h2 id="demo-title">Explore Kyoto and Nara</h2>'
                '<p>Switch dates to follow the stops and connections, then filter hotels, sights or food. '
                'This illustrative plan includes candidate choices and checks still to make.</p>'
                '<a class="button" href="{0}">Open the full interactive guide</a>'
                '<iframe class="demo-frame" src="{0}" loading="lazy" title="Interactive Kyoto and Nara itinerary demo" '
                'sandbox="allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox"></iframe></section>'
            ).format(DEMO)
        (output / page).write_text(render_page(page, title + " | Japan Travel Skills", description,
                                              base + page, content), encoding="utf-8")

    make_demo(output)
    sitemap = ElementTree.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for suffix in ("", *ARTICLES):
        ElementTree.SubElement(ElementTree.SubElement(sitemap, "url"), "loc").text = base + suffix
    ElementTree.ElementTree(sitemap).write(output / "sitemap.xml", encoding="utf-8", xml_declaration=True)
    (output / ".nojekyll").touch()
    findings = check_root(output)
    if findings:
        print(json.dumps(findings), file=sys.stderr)
        raise ValueError("Generated site failed the privacy check")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True, help="New directory outside the checkout")
    parser.add_argument("--site-url", default=DEFAULT_URL, help="Canonical HTTPS base URL")
    args = parser.parse_args()
    try:
        build(args.output, args.site_url)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        parser.exit(1, "Build failed: {}\n".format(error))
    print("Built three documentation pages and one interactive demo.")


if __name__ == "__main__":
    main()
