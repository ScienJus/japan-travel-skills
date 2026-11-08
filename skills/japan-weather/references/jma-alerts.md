# JMA meteorological warnings and advisories

## Source and scope

Use the [official public XML PULL service](https://xml.kishou.go.jp/xmlpull.html), not the legacy website JSON. The [2026 system change](https://www.jma.go.jp/jma/kishou/know/bosai/keiho-update2026/) introduced split event products VPWW55–61 and the nationwide VPWS50 aggregate. The [current technical materials](https://xml.kishou.go.jp/tec_material.html) provide format, code and message documentation. [Technical information 634](https://www.data.jma.go.jp/suishin/jyouhou/pdf/634.pdf) explains the new product roles. The implementation's supported message is `気象警報・注意報（Ｒ０６）（集約通報）`, schema version `1.5_0`.

This command uses the official XML aggregate, not the legacy website warning JSON or the separate river-warning input. Website JSON is not a fallback for this command.

VPWS50 periodically aggregates current meteorological-warning/advisory states nationally. Observed recent aggregate intervals were about ten minutes, with some variation; do not present this as a delivery SLA. The [public-feed caveats](https://xml.kishou.go.jp/considerationforxml.pdf) explicitly allow delays/stoppages. Per-kind issue times can be older than the aggregate because an ongoing warning or a last no-warning state does not need to be newly issued every interval.

This command does not incorporate separate river flood-warning products (VXKO/VXSU), earthquake, tsunami, volcanic information, evacuation orders or future warning outlooks. The official manual requires additional river products for the full flood-related picture. Do not label a valid VPWS50 no-warning state as all-hazards safety.

## Request and selection

1. GET `https://www.data.jma.go.jp/developer/xml/feed/regular.xml`.
2. Select the latest supported VPWS50 entry by its timezone-aware Atom `updated`, independent of feed order. The title, entry ID and XML link must agree. Only URLs matching `https://www.data.jma.go.jp/developer/xml/data/YYYYMMDDhhmmss_N_VPWS50_NNNNNN.xml` are accepted. Same-ID duplicate entries are deduplicated only when timestamps agree. Conflicting entries or multiple different latest URLs fail.
3. GET that exact XML. Parse it as UTF-8 with the standard library. DTD/entity declarations, unsupported namespaces, malformed or partial documents fail. Validate normal operational status (`通常`), national publisher/editorial office, product title, schema version and `InfoType=発表|訂正`. Test/training messages and unsupported information types are not used. The feed-entry time must equal the XML control publication time. Head report and target times must agree; publication cannot precede the target time.

There are at most two reads per invocation, including queries for up to ten areas. Both are anonymous HTTPS reads, with no account, cookies, browser, key, JavaScript, polling daemon, persistent cache or event replay. Request starts are serial and at least one second apart. Each read has a configurable 1–60 second socket timeout (default 15), an 8 MiB response cap, HTTP status/Content-Length checks, no redirects and no retry. A larger nationwide severe-weather message can exceed the cap; the result then stays unknown rather than becoming empty. HTTP errors preserve status and Retry-After when supplied.

One snapshot serves multiple requested areas. `usage` measures this invocation's attempts, completed body-read bytes, pacing and elapsed time; it does not estimate tokens or cost.

## Freshness and completeness

The fixed age policy is **1,800 seconds** for the aggregate target time and publication time, evaluated after the source reads, inclusive of the boundary. Future timestamps are rejected. Feed timestamps are also checked for future values and internal ordering. Stale or future data is an error with current status unknown; no older feed entry, legacy JSON, previously cached result or alternate provider is substituted. The 30-minute budget is a conservative client policy, not a guarantee of JMA's delivery speed.

Read municipal states only from the Body's `Warning[type="気象警報・注意報（市町村等）"]`. The Headline is a summary and can omit clear areas; `LastKind` describes the previous state and is not a current warning. There must be exactly one municipal section and one item per unique seven-digit area code. Each item must have an explicit supported status and per-kind publication timestamp, no later than the snapshot target. Duplicate warning codes or no-warning status mixed with active kinds fail.

The complete set of XML municipality/subdivision codes must match the bundled JMA routing catalog; the code does not hardcode a national count. A partial-but-well-formed snapshot or a changed area catalog returns `alert_area_catalog_mismatch` for the entire query. Inspect the official source and use the existing `refresh_catalog.py` maintainer workflow when routing metadata has actually changed. Never treat a missing area as a clear area or guess a replacement.

The existing municipality catalog is used for names, exact codes and disambiguation. Alert resolution rejects forecast reference aliases that silently narrow the requested geography. For example, Tokyo's forecast reference 千代田区 is not all Tokyo; 富山市平地 is not all 富山市. Select the intended exact native area name/code from returned candidates. 長野市 currently has areas `2020111` (長野市長野) and `2020112` (長野市鬼無里戸隠). Query both explicitly for both areas. The XML may use shortened names such as 長野 and 鬼無里戸隠; output retains both the catalog identity and the source area label.

## Output and failure behavior

Successful output has `status=ok`, `timezone=Asia/Tokyo`, shared `source` metadata and `cities`:

- `city`: the requested/resolved catalog municipality or subdivision, including alias use when applicable.
- `source_area`: exact XML code and label; the code is the identity, not a possibly repeated local name.
- `alert_state=active`: one or more current kinds. `alerts` retains the published Japanese name, code, current status, issue time, significant condition and addition notes. A downgrade such as 警報から注意報 remains active. Warning labels are read from XML, never decoded using forecast or legacy warning tables.
- `alert_state=none`: explicit `発表警報・注意報はなし`. Its status and issue time are retained under `no_alert_status`. Missing fields are never converted into this state.
- `alert_state=cleared`: the complete snapshot explicitly contains released kinds and no active kind. Releases remain in `released_alerts`; they are not current alerts.
- `has_active_alerts`: a boolean only after all source validation passes. It is not a travel-safety flag.
- `official_page`: JMA's page linked to the exact code.

`--detail` adds prior kind identity as `previous`; it does not add it to current alerts. Numeric forecast properties are not included by this command. Official names, statuses, conditions and notes are preserved rather than rewritten as independent forecasts.

Shared `source` includes publisher/product, feed and immutable XML URLs, feed update, aggregate target (`snapshot_at`), publication and retrieval times, age/budget, schema version, publication/correction type and municipal count. Per-kind `issued_at` is separate from the aggregate time and is not independently subject to a 30-minute age cutoff.

Any source, freshness, schema, identity or completeness failure returns **exit 2**, JSON `status=error`, `alert_state=unknown` and `manual_check_url`. No `cities` result, empty alert list or false boolean is fabricated on failure. Invalid CLI syntax uses argparse stderr/exit 2. No historical/future date argument is accepted. An exit-0 result means a validated snapshot was obtained, not that it contains no warnings or that any activity is safe.

## Attribution and validation

Attribute processed output to 気象庁 and retain the official source/time/scope. Follow [JMA content-use terms](https://www.jma.go.jp/jma/kishou/info/coment.html) and the public XML caveats. The command selects and normalizes official information; it does not publish independent warnings or guarantee delivery.
