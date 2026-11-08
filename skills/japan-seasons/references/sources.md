# Seasonal sources and result contract

## Supported public scope

[Weathernews foliage](https://weathernews.jp/koyo/) supplies named spot conditions and viewing milestones. [Weathernews sakura](https://weathernews.jp/sakura/) supplies spot forecasts, reported/estimated conditions and seasonal availability. [Japan Meteorological Corporation autumn](https://n-kishou.com/corp/news-contents/autumn/) and [sakura](https://n-kishou.com/corp/news-contents/sakura/) corporate releases supply selected city tables. The code reads these original pages, not search snippets. No JMC paid お天気ナビゲータ data or private API is integrated.

Weathernews, 日本気象株式会社 and 気象庁 are distinct publishers. The [JMA discontinuation notice](https://www.jma.go.jp/jma/press/0912/25a/091225sakura.html) explains that JMA stopped sakura forecasts while retaining observations. This tool does not generate its own predictions or imply a government endorsement.

## Commands and discovery

- `areas --season foliage|sakura`: one live Weathernews portal read returns native region and prefecture links and their slugs; not every link is a flat spot directory.
- `spots --season ... --area SLUG [SEARCH]`: one live directory read, retaining exact names, IDs, prefectures and cities. Only entries actually linked in the visible page are exposed. A recognized foliage regional overview instead returns `error.code=unsupported_area`, `directory_kind=regional_overview` and native `candidate_areas` inside the error. Choose the relevant prefecture slug for subsequent discovery; no child is selected or fetched automatically. This is narrower-input guidance, not an empty match list. Some sakura prefecture URLs contain regional data; native `pref_en` must match the requested slug. A substring is only a suggestion.
- `cities --season ...`: one live JMC release read lists only the cities in that public table. This is not the provider's entire paid catalog.
- `query --season ... --year YEAR --city NATIVE_CITY --spot NATIVE_SPOT --area SLUG`: two Weathernews reads (directory plus exact spot) and one JMC read. Replace `--area` with a previously verified `--spot-id` to reduce the query to two reads.

`query` always attempts both requested providers independently and includes both records. Native spot names are exact after Unicode/whitespace normalization. JMC also accepts a small explicit set of city aliases such as 金泽 → 金沢. Ambiguity, unsupported scope and identity disagreement do not cause a nearby substitute. Weathernews IDs are season-specific: the checked Kenrokuen foliage ID is 25605; its sakura ID is 257.

## Weathernews page contract

The original UTF-8 server-rendered page supplies a season/year title, canonical URL, native spot heading and Nuxt JSON. The implementation reads selected primitive JSON references without executing scripts, evaluating code, or fetching client assets. It validates canonical route/ID, native spot ID/name, visible title, and directory-versus-spot city/prefecture when directory resolution was used. Source-owned spot-kind and typical timing fields retain their labels. A provider's photo/source credit does not establish authorship of its prediction.

Foliage regional overviews have native prefecture jump navigation and matching prefecture blocks with dedicated more-spots links. The complete block set must agree with that navigation, headings and child URLs before offering `candidate_areas`. Their highlights/rankings lack the full directory contract and are not converted into spot results. Missing or contradictory structures remain schema errors, not selection guidance. This recognition does not extend to unverified sakura regional templates.

Foliage state must have explicit display flags. Hidden content/dates are not predictions. Visible condition/date text must agree with the corresponding page data. Predictions additionally require the visible milestone label and approximate/onward text to agree. `best_viewing_start` and `leaf_fall_start` are approximate starts, not an inferred interval of guaranteed peak viewing. Source labels remain native. Condition dates are bound to the published season year, validated as not future-dated and returned with `age_days`; retrieval is not observation time.

Forecast issue timestamps are unavailable (`issued_at=null`). The condition's as-of date cannot fill that gap. Historical usual timing stays raw; it is never converted into this year's forecast. Community reports/photos are excluded from official-condition fields. The parser does not infer a stage from a status icon or a nearby location.

The sakura forecast contract was traced to the public page's own `SpotObsFcstCard` and month/day formatter. Only rendered `kaikaList__item` entries with matching page-data dates, known labels and a true prediction marker become forecasts: 開花予想日 (`flowering`), 五分咲き (`half_bloom`), 満開 (`full_bloom`) and 桜吹雪 (`petal_blizzard`). Source condition ranks hide milestones after their stage passes; missing displayed milestones stay unavailable even when old dates remain in JSON. Petal blizzard is a named stage, not a guaranteed last viewing date. The forecast's `fcst_tree_kind` cultivar is retained per event; general park cultivars remain separate. Source dates have daily precision, not an implied confidence guarantee.

For sakura conditions, visible 最終取材日 and source `shuzai=""` yield `reported_condition`. Visible ～の推定状況 and `shuzai="data"` yield `estimated_condition`, never an observed opening/full-bloom date. Unknown modes and mismatched visible dates return unknown. Condition dates remain separate from forecast issue times.

Ended sakura seasons retain old conditions and as-of dates as `archived`; forecasts remain unavailable even if leftover dates are present. A requested new season stays unavailable until the source publishes it. A next-season publication announcement is not a flowering prediction. Active-season Weathernews sakura results have limited live validation; unsupported or contradictory layouts return unknown. Runtime queries read only the SSR page, without downloading or executing client assets.

## JMC public-table contract

The release title binds season year and edition; the native release date is separate from row dates. A release may occur in the year before its target spring. Validate its date, exact quantity headers, native city identities, complete red/yellow city coverage and the observed-value legend. Do not pin a city catalog or forecast dates offline.

Native `autumn01`/`autumn02` and `sakura01`/`sakura02` cells distinguish forecasts and observations. The parser retains `events[].kind` per cell, rather than treating every value under a forecast header as predicted. Unknown markers fail. Empty/unannounced values remain unavailable. Observed events cannot be future-dated; a forecast can be in the past without becoming an observation. Foliage trees retain native species. Sakura release scope is ソメイヨシノ, not all cherry cultivars. Normal dates/differences stay separate, with no invented current-year event.

JMC's city red-leaf/gingko dates are phenological references; they are not a prediction that every park in that city is at peak. `release_published_on` does not establish `cell_updated_at` or forecast issue time. Per-cell update and issue times therefore remain null. Historical/ended seasons remain archived; requested years absent from the current page return unavailable with no inherited event dates.

Month/day values are bound to the explicit source season. Autumn events apparently crossing into the following January need stronger year evidence and currently fail rather than guessing a year. All dates use JST. Neither adapter extrapolates new dates from temperature or averages competing provider dates.

## Independent output and failures

`providers[]` always has Weathernews and JMC entries for `query`. Each contains status, publisher, requested/actual scope, source season, events, source URL and retrieval information when available. Weathernews adds a separately dated `condition`; JMC adds publication/edition metadata. Neither provider is a fallback for the other.

`comparison.same_location_and_metric=false` explicitly identifies spot-versus-city scope. A source failure remains visible beside a good result. Top-level `partial` can mean a provider error/unavailability or differing provider states; inspect the actual records. Both errors return exit 2. Completed archived or unavailable queries exit 0. `doctor` and `--help` are offline. No errors fabricate empty normal conditions, a consensus forecast, precise certainty or missing data from the other source.

Discovery errors identify the requested provider and source URL when known. A completed body read retains its retrieval time even if parsing or narrower-input selection fails; a failed transport has no retrieval time. Validation before any source selection/read does not manufacture source provenance. Regional `unsupported_area` still exits 2 with `state=unknown` for the requested spot; a genuine schema failure retains its stopping rule. In `query`, regional selection guidance remains beside the independently requested JMC record.

Requests are fixed anonymous HTTPS routes on `weathernews.jp` and `n-kishou.com`, with at most three reads per invocation, per-provider budgets (two and one), one-second pacing, 15-second socket timeouts, 2 MiB bodies, and no redirects/retries. URL query strings, report/photo routes, arbitrary hosts, paid routes and user-supplied full URLs are rejected. Stop on denials; do not use accounts, cookies, visitor fingerprints or browser sessions. Source error diagnostics do not authorize another identity. No persistent cache, capture replay or polling is used.

Retain attribution, original links and provider qualifications. Follow [Weathernews terms](https://weathernews.jp/ip/kiyaku/202603/index.html) and JMC's published information-use conditions; public readability is not an unrestricted redistribution license. Do not bundle raw pages, prediction databases or community photos. MIT covers project code only.
