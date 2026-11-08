# Official rail-pass sources

The adapter reads current official English-language HTML. It is an attributed document extractor, not a ticket eligibility or route-coverage engine. Public readability is not a contracted API or a grant of redistribution rights. Follow each publisher's site terms, retain links and attribution, and do not distribute raw captures or bulk copy catalogs.

| Provider | Live discovery | Detail scope | Transport |
| --- | --- | --- | --- |
| `jr-group` | [JAPAN RAIL PASS types and prices](https://japanrailpass.net/en/purchase/price/) | Family-level car/age/duration/channel price tables, plus [eligibility](https://japanrailpass.net/en/about_jrp/riyou/) and [route/use conditions](https://japanrailpass.net/en/about_jrp/route/) | System curl |
| `jr-west` | [JR-WEST Rail Pass](https://www.westjr.co.jp/travel-information/en/tickets-passes/jrwest-rail-pass/) and [other passes](https://www.westjr.co.jp/travel-information/en/tickets-passes/other/) | Information pages linked by supported pass cards, including joint regional products | Python HTTPS |
| `jr-central` | [Tourist Pass](https://touristpass.jp/en/) | Selected product plus its own section and common sections from [conditions for use](https://touristpass.jp/when_using/en/) | Python HTTPS |
| `jr-hokkaido` | [JR Hokkaido tickets](https://www.jrhokkaido.co.jp/global/english/ticket/) | Native product fragments in [rail passes](https://www.jrhokkaido.co.jp/global/english/ticket/railpass/index.html), plus common reservation/use/other-conditions sections | Python HTTPS |
| `jr-shikoku` | [JR Shikoku pass information](https://shikoku-railwaytrip.com/pass-information/) | Native `pref=all` and `pref=kagawa` variants, separately scoped | Python HTTPS |
| `jr-east` | [Official entry](https://www.jreast.co.jp/multi/pass/) | Reference only; no CLI source reads | None |
| `jr-kyushu` | [Official entry](https://www.jrkyushu.co.jp/english/railpass/railpass.html) | Reference only; no CLI source reads | None |

This is nationwide product discovery within these source families, not an exhaustive inventory of Japan's city, private-rail, bus or regional discount tickets. Kyushu can appear through a readable joint JR-West product; this does not establish support for JR Kyushu's own catalog. JR East/JR Kyushu reference links remain available for independent research. Do not describe them as integrated API providers.

## Catalog and product identity

The configured live catalogs determine current names and supported product links. No prices, pass lists or validity dates are bundled. Provider URL patterns constrain information documents; a `show` URL must also match a current supported catalog entry. Booking links, reservation forms, arbitrary URL parameters, credentials and foreign hosts are rejected before network access.

Each provider has a specific catalog contract: West pass cards/headings, Tourist Pass item/detail links, Hokkaido named fragment cards, Shikoku native variant links, and the nationwide pass family price document. Page titles and selected product headings are checked. A missing/changed catalog produces unknown rather than zero supported passes. A provider's catalog is a listing source, not proof that a product remains on sale.

Hokkaido's shared document contains multiple products with differing prices and eligibility. Only the selected fragment is extracted, along with common reservation/use/other-conditions sections; purchasing-location directories and unrelated product sections are not automatically followed. Shikoku's HTML contains both visible/hidden variants; extracting the whole page would mix products. Product-scoped sales-status notes outside those variants are carried from the catalog into the entry.

Tourist Pass conditions contain several product accordions. Known native URL slugs bind each supported product to its own terms section. Newly discovered products without a validated terms binding yield a conditions error; other products' terms are never substituted. Nationwide eligibility and route-condition documents are independent sources with separate retrieval metadata and error states.

## Loss-aware records

`documents[].sections[]` retains native heading paths and text/table/image blocks. Header/data cell types and row/column spans remain explicit. Responsive exact duplicate blocks are removed within a section; price channels and distinct table layouts remain separate. There is no canonical numeric price or automatic fare-savings calculation. Marketing sections are omitted at recognized headings; this is a bounded information view, not an archival copy of every page element.

Image URLs/alt text and table icons are reference-only. Empty icon alt text does not establish the symbol's meaning; keep the source legend and inspect the original image when material. Route maps, qualification diagrams and image-only information are not machine verified. Original hyperlinks inside prose are not expanded; use the attributed document to consult linked material. Important eligibility details, seasonal operating days, supplementary charges or selected train exclusions may require additional source reading before recommending a pass.

Dated text notices are also retained separately from section filters and output truncation. They preserve publisher wording, not an inferred effective period. Sales status is conservative: only explicit product-scoped catalog notices establish ended/suspended; absent notices remain unknown. A retained price table or generic all-year statement must not override an explicit cessation notice. Previously purchased passes may have different validity; keep any stated exception.

National pass prices can differ by purchase channel. Nozomi/Mizuho conditions may require an additional ticket rather than a simple covered/excluded flag. Eligibility may include Japanese nationals meeting overseas conditions. Hokkaido products need not share other providers' Temporary Visitor requirement. Keep the original qualification statements and exceptions; do not decide eligibility from a nationality alone.

## Network and result boundaries

Normal `list` requests: West two, other implemented providers one each, all six total. Normal `show`: West three, Tourist Pass three, Hokkaido two, Shikoku two, nationwide three. Repeated documents share one per-invocation read, including the nationwide catalog/price document and Hokkaido fragments/common sections. No supplemental links are crawled implicitly beyond the fixed condition documents.

The shared maximum is eight requests, serial 1.5-second pacing, 2 MiB per response. Python timeout is 15 seconds per socket operation; the nationwide curl transport has a 10-second connection limit, 20-second total transfer limit and 25-second process timeout. Curl ignores user curl configuration, uses HTTPS/TLS 1.2 or newer and does not follow redirects. The explicit transport accommodates local Python TLS limitations; it is not a fallback after access denial. No retries, accounts, cookies, persistent cache or alternate-client bypass.

`publisher_updated_at` remains unknown unless supported explicitly; HTTP Last-Modified and retrieval time do not establish current price validity. Source failure stops further host requests within the invocation. A conditions failure makes `show` partial while retaining other documents. An all-provider list preserves readable provider records and reports inaccessible ones independently. `--section` only filters returned content; it does not reduce fetches. `section_selection` identifies omitted document/heading paths and unmatched filters; unmatched filters make the result partial. Intentional filtering is not output truncation or proof of complete terms. Native notices and entry sales state must still be read alongside filtered prices. `--outline` provides headings without blocks, with the same source reads. Prefer a single unfiltered `show` for ordinary comparisons rather than fetching an outline and the same product again.

These documents support travel planning and independent source checks. They do not check seat inventory, reserve trains, buy passes, or guarantee a route's eligibility. Timetable routes and fares belong to the transit skill; a pass-specific recommendation must retain exceptions rather than treating regional name overlap as route proof.
