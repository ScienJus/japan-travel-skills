#!/usr/bin/env python3
"""Build localized GitHub Pages documents and public demos outside the checkout."""

import argparse
from html import escape
import json
from pathlib import Path
from posixpath import relpath
import shutil
from string import Template
import subprocess
import sys
from tempfile import TemporaryDirectory
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
DEMO_BRIEF = "assets/kyoto-nara-presentation.md"
LOCALES = {"en": "", "zh-CN": "zh/", "ja": "ja/"}
LANGUAGE_NAMES = {"en": "English", "zh-CN": "简体中文", "ja": "日本語"}
WORKED_CASE = "hokuriku-six-days.html"
ARTICLES = {
    "check-japan-itinerary.html": ("docs/check-japan-itinerary.md", "article0"),
    "japan-itinerary-map-and-powerpoint.html": ("docs/japan-itinerary-map-and-powerpoint.md", "article1"),
    WORKED_CASE: ("skills/japan-travel-planner/examples/hokuriku-six-days.md", "hokuriku"),
}
NAVIGATION = ("example", "start", "tools", "install")
TRANSLATABLE_PLAN_FIELDS = {
    "title", "notice", "name", "summary", "notes", "mode", "time", "scope", "precision",
    "open_questions",
}


def catalog(lang, filename):
    data = json.loads((SITE / "locales" / lang / filename).read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(not isinstance(value, str) or not value.strip()
                                         for value in data.values()):
        raise ValueError("Invalid translation catalog: {} / {}".format(lang, filename))
    return data


def route(lang, page):
    return LOCALES[lang] + ("" if page == "index.html" else page)


def language_links(lang, page, label):
    current_directory = (LOCALES[lang] + page).rpartition("/")[0] or "."
    links = []
    for locale, prefix in LOCALES.items():
        relative = relpath(prefix + page, current_directory)
        current = ' aria-current="page"' if locale == lang else ""
        links.append('<a href="{}" hreflang="{}" lang="{}"{}>{}</a>'.format(
            relative, locale, locale, current, LANGUAGE_NAMES[locale]))
    return '<nav class="language-nav" aria-label="{}">{}</nav>'.format(escape(label), " ".join(links))



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
    for page, (filename, _) in ARTICLES.items():
        if relative == filename:
            return urlunsplit(("", "", page, target.query, target.fragment))
    return REPOSITORY + "/blob/main/" + quote(relative, safe="/") + urlunsplit(
        ("", "", "", target.query, target.fragment)
    )


def render_article(source, translated):
    md = MarkdownIt("commonmark", {"html": False}).enable("table")
    tokens = md.parse(translated.read_text(encoding="utf-8"))
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


def render_page(lang, page, title, description, base, content, labels, assets):
    home = page == "index.html"
    prefix = "" if home else "index.html"
    navigation = "".join('<a href="{}#{}">{}</a>'.format(prefix, anchor, escape(labels[anchor]))
                         for anchor in NAVIGATION)
    script = '\n  <script src="{}/trip.js" defer></script>'.format(assets) if home else ""
    alternates = [
        '<link rel="alternate" hreflang="{}" href="{}">'.format(locale, escape(base + route(locale, page)))
        for locale in LOCALES
    ]
    alternates.append('<link rel="alternate" hreflang="x-default" href="{}">'.format(
        escape(base + route("en", page))))
    return template("page.html").substitute(
        title=escape(title), description=escape(description), canonical=escape(base + route(lang, page)),
        repository=REPOSITORY, navigation=navigation, content=content, script=script, lang=lang,
        brand_href="#top" if home else "index.html",
        assets=assets, alternates="\n  ".join(alternates),
        language_nav=language_links(lang, page, labels["language_label"]),
        **{key: escape(value) for key, value in labels.items()},
    )


def plan_key(item, index):
    if isinstance(item, dict):
        if "id" in item:
            return item["id"]
        if "url" in item:
            return quote(item["url"], safe="")
        if "place_id" in item:
            return "{}:{}".format(index, item["place_id"])
    return str(index)


def localized_plan(plan, lang):
    translations = catalog(lang, "demo.json")
    used = set()

    def translate(value, path="", prose=False):
        if isinstance(value, dict):
            return {key: translate(item, path + "/" + key, key in TRANSLATABLE_PLAN_FIELDS)
                    for key, item in value.items()}
        if isinstance(value, list):
            return [translate(item, path + "/" + plan_key(item, index), prose)
                    for index, item in enumerate(value)]
        if isinstance(value, str) and prose:
            if path in translations:
                used.add(path)
                return translations[path]
            if lang != "zh-CN":
                raise ValueError("Missing {} demo translation at {}".format(lang, path))
        return value

    result = translate(plan)
    if used != translations.keys():
        raise ValueError("Unused {} demo translations: {}".format(lang, sorted(translations.keys() - used)))
    result["language"] = lang
    return result


def make_demo(output, example, lang, labels):
    target = output / DEMO
    for kind, path in (("html", target), ("brief", output / DEMO_BRIEF)):
        subprocess.run([sys.executable, str(PLANNER / "scripts/render_plan.py"),
                        "--input", str(example), "--output", str(path), "--format", kind],
                       check=True)
    html = target.read_text(encoding="utf-8")
    # The surrounding guides are the search landing pages for this example.
    html = html.replace("</head>", '<meta name="robots" content="noindex,follow">\n</head>', 1)
    navigation = language_links(lang, DEMO, labels["language_label"])
    html = html.replace('<div id="stats"', navigation + '<div id="stats"', 1)
    html = html.replace("</style>", """
.language-nav { display: flex; flex-wrap: wrap; gap: .45rem 1rem; margin: 0 0 1rem; }
.language-nav a { color: #eef5e8; font-size: .84rem; }
.language-nav [aria-current="page"] { font-weight: 800; }
</style>""", 1)
    target.write_text(html, encoding="utf-8")
    if lang != "en":
        brief = output / DEMO_BRIEF
        _, marker, records = brief.read_text(encoding="utf-8").partition("\n## Plan records\n\n")
        if not marker:
            raise ValueError("Missing plan records in presentation brief")
        intro = (SITE / "locales" / lang / "presentation.md").read_text(encoding="utf-8")
        brief.write_text(intro.rstrip() + "\n\n## " + labels["plan_records"] + "\n\n" + records,
                         encoding="utf-8")


def build_locale(output, base, lang, plan, example_path):
    destination = output / LOCALES[lang]
    destination.mkdir(parents=True, exist_ok=True)
    assets = "../assets" if LOCALES[lang] else "assets"
    raw_labels = catalog(lang, "site.json")
    labels = {key: escape(value) for key, value in raw_labels.items()}
    home = {key: escape(value) for key, value in catalog(lang, "home.json").items()}
    (destination / "index.html").write_text(render_page(
        lang, "index.html", raw_labels["home_title"], raw_labels["home_description"], base,
        template("home.html").substitute(repository=REPOSITORY, assets=assets, demo=DEMO,
                                         brief=DEMO_BRIEF, worked_case=WORKED_CASE, **home),
        raw_labels, assets,
    ), encoding="utf-8")

    for page, (filename, key) in ARTICLES.items():
        source = ROOT / filename
        translated = source if lang == "en" else SITE / "locales" / lang / source.name
        title, body, sections = render_article(source, translated)
        demo = page == "japan-itinerary-map-and-powerpoint.html"
        if page == WORKED_CASE:
            body = body.replace("<table>", '<div class="table-scroll" tabindex="0" role="region" '
                                'aria-label="{}"><table>'.format(labels["hokuriku_table"]))
            body = body.replace("</table>", "</table></div>")
        button = ""
        if demo:
            sections.append(("demo", raw_labels["example_title"]))
            button = '<a class="button primary" href="#demo">{}</a>'.format(labels["example_cta"])
        links = "".join('<a href="#{}">{}</a>'.format(anchor, escape(label))
                        for anchor, label in sections)
        content = (
            '<header class="shell article-head"><p class="eyebrow">{}</p><h1>{}</h1>{}</header>'
            '<div class="shell article-layout">'
            '<aside class="article-index"><p class="eyebrow">{}</p>'
            '<nav aria-label="{}">{}</nav></aside>'
            '<article class="prose">{}</article></div>'
        ).format(labels[key + "_kicker"], escape(title), button, labels["contents"],
                 labels["sections"], links, body)
        if demo:
            content += (
                '<section class="shell demo-section" id="demo" aria-labelledby="demo-title">'
                '<p class="eyebrow">{example_kicker}</p><h2 id="demo-title">{example_title}</h2>'
                '<p>{example_description}</p><a class="button" href="{url}">{example_full}</a>'
                '<iframe class="demo-frame" src="{url}" loading="lazy" title="{example_frame}" '
                'sandbox="allow-scripts allow-downloads allow-popups allow-popups-to-escape-sandbox"></iframe></section>'
            ).format(url=DEMO, **labels)
        (destination / page).write_text(render_page(
            lang, page, title + " | Japan Travel Skills", raw_labels[key + "_description"],
            base, content, raw_labels, assets,
        ), encoding="utf-8")

    example_path.write_text(json.dumps(localized_plan(plan, lang), ensure_ascii=False), encoding="utf-8")
    make_demo(destination, example_path, lang, raw_labels)


def build(output, site_url):
    base = canonical_base(site_url)
    output = output.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Build output must stay outside the source checkout")
    output.mkdir(parents=True, exist_ok=False)
    (output / "assets").mkdir()
    assets = (
        "field-guide.css", "navigation.js", "trip.js", "kyoto-kiyomizu.jpg", "nara-park.jpg",
        "manrope.woff2", "manrope-OFL.txt",
    )
    for asset in assets:
        shutil.copyfile(SITE / "assets" / asset, output / "assets" / asset)
    plan = json.loads((PLANNER / "examples/kyoto-nara-demo.json").read_text(encoding="utf-8"))
    if plan.get("demo") is not True:
        raise ValueError("The public plan must be marked as a demo")
    with TemporaryDirectory() as directory:
        example_path = Path(directory) / "sample.json"
        for lang in LOCALES:
            build_locale(output, base, lang, plan, example_path)

    sitemap = ElementTree.Element("urlset", xmlns="http://www.sitemaps.org/schemas/sitemap/0.9")
    for lang in LOCALES:
        for page in ("index.html", *ARTICLES):
            ElementTree.SubElement(ElementTree.SubElement(sitemap, "url"), "loc").text = base + route(lang, page)
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
    print("Built the product site and sample trip in English, Simplified Chinese and Japanese.")


if __name__ == "__main__":
    main()
