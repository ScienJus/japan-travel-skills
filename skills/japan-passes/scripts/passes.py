#!/usr/bin/env python3
"""Discover official Japanese rail passes and read attributed native information."""
import argparse
import json
from pathlib import Path
import shutil
import sys

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path:
    sys.path.insert(0, HERE)
import pass_source as source
import pass_providers as providers


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("doctor", help="Offline runtime, transport and source-scope checks")
    sub.add_parser(
        "providers", help="Offline official entry points and adapter coverage"
    )
    catalog = sub.add_parser(
        "list", help="Read live official pass catalogs; no product crawl"
    )
    catalog.add_argument(
        "--provider", choices=["all"] + list(providers.PROVIDERS), required=True
    )
    catalog.add_argument(
        "--query",
        help="Case/width-insensitive literal native name/region-hint text; no translation",
    )
    catalog.add_argument("--limit", type=int, default=50, help="1–100 output entries")
    show = sub.add_parser(
        "show",
        help="Validate a live catalog entry, then read product and associated conditions",
    )
    show.add_argument("--provider", choices=list(providers.PROVIDERS), required=True)
    show.add_argument(
        "--url",
        required=True,
        help="Exact details URL returned by list, including native fragment/query",
    )
    show.add_argument(
        "--expect",
        help="Expected exact live catalog entry name (width/whitespace normalized)",
    )
    show.add_argument(
        "--section",
        action="append",
        default=[],
        help="Literal heading-path filter, repeatable; notices are retained independently",
    )
    show.add_argument(
        "--outline",
        action="store_true",
        help="Return section headings without content blocks",
    )
    show.add_argument(
        "--max-blocks",
        type=int,
        default=120,
        help="1–500 returned content blocks across source documents",
    )
    return p


def problem(error):
    if isinstance(error, source.Error):
        return {"code": error.code, "message": str(error), **error.details}
    return {
        "code": "source_schema_changed",
        "message": "Unexpected official document structure; no pass facts were guessed.",
    }


def provider_records():
    return [
        {
            "provider": key,
            "name": p["name"],
            "regions": p["regions"],
            "adapter_state": (
                "implemented" if providers.supported(key) else "reference_only"
            ),
            "catalog_urls": p.get("catalogs", []),
            "reference_url": p.get("reference"),
            "transport": p.get("transport"),
            "reason": p.get("reason"),
        }
        for key, p in providers.PROVIDERS.items()
    ]


def catalog(client, args):
    if not 1 <= args.limit <= 100:
        raise source.Error("invalid_options", "Use --limit from 1 to 100.")
    if args.query is not None and not source.norm(args.query):
        raise source.Error("invalid_options", "Query must not be blank.")
    keys = list(providers.PROVIDERS) if args.provider == "all" else [args.provider]
    records = []
    coverage = []
    for provider in keys:
        try:
            entries, sources = providers.catalog(client, provider)
            coverage.append(
                {
                    "provider": provider,
                    "state": "read",
                    "source_count": len(entries),
                    "sources": sources,
                }
            )
            records.extend(entries)
        except (
            source.Error,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            RecursionError,
        ) as error:
            coverage.append(
                {
                    "provider": provider,
                    "state": "unknown",
                    "error": problem(error),
                    "reference_url": providers.PROVIDERS[provider].get("reference"),
                    "source": (
                        client.last_source if providers.supported(provider) else None
                    ),
                }
            )
    count = len(records)
    if args.query:
        query = source.norm(args.query)
        if not query:
            raise source.Error("invalid_options", "Query must not be blank.")
        records = [
            r
            for r in records
            if query
            in source.norm(r["name"] + " " + " ".join(r.get("region_hints", [])))
        ]
    matching = len(records)
    records = records[: args.limit]
    unavailable = any(c["state"] == "unknown" for c in coverage)
    return {
        "status": (
            "unavailable"
            if not count and unavailable
            else "partial" if unavailable else "ok"
        ),
        "entries": records,
        "returned_count": len(records),
        "matching_entries": matching,
        "output_truncated": matching > len(records),
        "catalog_entry_count": count,
        "provider_coverage": coverage,
        "coverage": "Only configured official catalogs, not every Japanese rail/private-rail/city pass. Entries and region hints are not a route-coverage decision.",
    }


def show(client, args):
    if not 1 <= args.max_blocks <= 500:
        raise source.Error("invalid_options", "Use --max-blocks from 1 to 500.")
    if args.expect is not None and not source.norm(args.expect):
        raise source.Error("invalid_options", "Expected name must not be blank.")
    if any(not source.norm(q) for q in args.section):
        raise source.Error("invalid_options", "Section filters must not be blank.")
    if not providers.supported(args.provider):
        p = providers.PROVIDERS[args.provider]
        raise source.Error(
            "provider_unavailable", p["reason"], reference_url=p["reference"]
        )
    try:
        valid = providers.valid(args.provider, args.url)
    except ValueError:
        valid = False
    if not valid:
        raise source.Error(
            "unsupported_url",
            "Use an exact official product URL returned by list; transaction URLs are not supported.",
        )
    records, catalog_sources = providers.catalog(client, args.provider)
    record = source.one(
        (r for r in records if r["url"] == args.url),
        "Product URL is not present in the current supported catalog.",
    )
    if args.expect and source.norm(args.expect) != source.norm(record["name"]):
        raise source.Error(
            "product_mismatch",
            "Catalog name differs from the expected pass.",
            actual=record["name"],
        )
    p = providers.PROVIDERS[args.provider]
    raw, meta = client.read(args.url, p["transport"])
    page = source.Page(raw)
    root = providers.scope(args.provider, page, args.url)
    providers.check_product(args.provider, record, root, page)
    documents = []

    def add(role, root, meta, title):
        data = source.sections(root, meta["url"], seed=[(0, record["name"])])
        if not data:
            source.fail("Official information area has no supported content.")
        documents.append(
            {
                "role": role,
                "title": title,
                "source": meta,
                "sections": data,
                "notices": source.notices(data),
            }
        )

    add("product", root, meta, page.title)
    errors = []
    if args.provider == "jr-hokkaido":
        for key in ("reserve", "use", "other"):
            try:
                node = source.one(
                    (n for n in page.main.nodes("section") if n.attrs.get("id") == key),
                    "Missing/duplicate Hokkaido common conditions section: " + key,
                )
                add("common_conditions", node, meta, page.title)
            except (
                source.Error,
                ValueError,
                TypeError,
                KeyError,
                IndexError,
                RecursionError,
            ) as error:
                errors.append(
                    {
                        "url": args.url,
                        "section": key,
                        "source": meta,
                        "error": problem(error),
                    }
                )
    for url in p.get("conditions", []):
        try:
            raw, condition_meta = client.read(url, p["transport"])
            condition_page = source.Page(raw)
            for role, node in providers.conditions(
                args.provider, condition_page, args.url
            ):
                add(role, node, condition_meta, condition_page.title)
        except (
            source.Error,
            ValueError,
            TypeError,
            KeyError,
            IndexError,
            RecursionError,
        ) as error:
            errors.append(
                {"url": url, "source": client.last_source, "error": problem(error)}
            )
    outline = [
        {"document": i, "heading_path": r["heading_path"]}
        for i, d in enumerate(documents)
        for r in d["sections"]
    ]
    remaining = args.max_blocks
    truncated = False
    returned = 0
    matched_filters = set()
    omitted_sections = []
    for document_index, doc in enumerate(documents):
        selected = []
        for record_section in doc["sections"]:
            matches = {
                q for q in args.section if source.norm(q)
                in source.norm(" / ".join(record_section["heading_path"]))
            }
            matched_filters.update(matches)
            if args.section and not matches:
                omitted_sections.append({
                    "document": document_index,
                    "heading_path": record_section["heading_path"],
                })
                continue
            if args.outline:
                continue
            blocks = record_section["blocks"]
            take = blocks[:remaining]
            remaining -= len(take)
            if len(take) < len(blocks):
                truncated = True
            if take:
                selected.append({**record_section, "blocks": take})
                returned += len(take)
        doc["sections"] = selected
    unmatched_filters = [q for q in args.section if q not in matched_filters]
    return {
        "status": "partial" if errors or truncated or unmatched_filters else "ok",
        "provider": args.provider,
        "entry": record,
        "catalog_sources": catalog_sources,
        "documents": documents,
        "conditions_errors": errors,
        "outline": outline if args.outline else None,
        "outline_only": args.outline,
        "section_filters": args.section,
        "section_selection": ({
            "scope": "filtered_view_not_complete_terms",
            "unmatched_filters": unmatched_filters,
            "omitted_sections": omitted_sections,
            "note": "Omitted sections may contain covered services, exclusions or other conditions. Absence from this view does not establish inclusion or exclusion.",
        } if args.section else None),
        "returned_blocks": returned,
        "output_truncated": truncated,
        "interpretation": {
            "prices": "Native tables/text with source heading context; purchase channels, ages, car classes and effective dates are not merged.",
            "sales": "Only explicit product-scoped catalog notices establish ended/suspended sales; unknown is not on-sale.",
            "route_coverage": "not_evaluated",
            "eligibility_decision": "not_evaluated",
            "images": "Reference links and table symbols retained; maps and images are not OCRed.",
            "source_time": "Retrieval/HTTP timestamps are not publication or travel-date validity guarantees.",
        },
    }


def main(argv=None):
    args = parser().parse_args(argv)
    client = source.Client(providers.allowed)
    try:
        if args.command == "doctor":
            result = {
                "status": "ok",
                "network_checked": False,
                "python": sys.version.split()[0],
                "dependencies": "Python 3.9+ standard library; curl required only for jr-group.",
                "curl_available": shutil.which("curl") is not None,
                "providers": provider_records(),
                "request_budget": 8,
                "unsupported": [
                    "booking/payment",
                    "automatic per-leg coverage validation",
                    "automatic savings optimization",
                    "unregistered ticket sources",
                ],
            }
        elif args.command == "providers":
            result = {
                "status": "ok",
                "network_checked": False,
                "providers": provider_records(),
            }
        elif args.command == "list":
            result = catalog(client, args)
        else:
            result = show(client, args)
    except (
        source.Error,
        ValueError,
        TypeError,
        KeyError,
        IndexError,
        RecursionError,
    ) as error:
        result = {
            "status": "error",
            "state": "unknown",
            "error": problem(error),
            "source": client.last_source,
        }
    result["usage"] = client.usage()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return 2 if result["status"] in ("error", "unavailable") else 0


if __name__ == "__main__":
    sys.exit(main())
