# Fuji-view source and field contract

## Source choice

[富士見予報](https://www.fuji-san.info/) is published by [株式会社応用気象エンジニアリング / AMECS](https://www.amecs.co.jp/), a Japanese professional meteorological company. Its company page describes its forecasting work and forecast permission. JMA's [2025 guidebook](https://www.jma.go.jp/jma/kishou/books/jma-guidebook/GuideBook2025.pdf) also lists the company under permission number 17. This establishes professional provenance; it does not independently validate this particular index's accuracy. It is a commercial provider product, not a JMA-issued visibility forecast.

The public page explains a numerical-ensemble basis and a 1–10 富士見指数, with higher numbers indicating greater possibility of seeing Fuji. Updates are described as around 16:00 daily. Coverage is broad views from the **north and south foothills**, separately for 午前 and 午後. No verified point coordinates, lake/park identifiers, exact period boundaries, calibration statistics or per-period probability definition are available in this integration. Do not invent them.

## Weathernews summit map

The [富士山眺望指数 map](https://weathernews.jp/mountain/fuji_viewable/) covers views *toward* Fuji
from mountain summits. The [publisher's explanation](https://jp.weathernews.com/wp-content/uploads/2026/04/20260407-app.pdf)
describes terrain eligibility, cloud around both mountains and atmospheric conditions between them.
Local vegetation may obscure an otherwise possible view.

The map requests `https://site.weathernews.jp/api/mountain/list?ids=...` with comma-separated
five-digit mountain IDs. The CLI uses only this anonymous map request. Use the returned name and
the requested ID. Only `day0` (JST midnight) and `fuji_viewable_index` describe the dated Fuji
grades. Keep unrelated mountain-weather fields out of the report. The map component maps codes
0/1 to × 難しい, 2 to △ わずかにチャンスあり, 3 to ○ チャンスあり and 4/5 to ◎ よく見える.
The series starts on `day0`. Before 18:00 JST the map can use yesterday's base for today's and
tomorrow's entries. At or after 18:00 require coverage of tomorrow and the following day.
Limit results to the displayed dates. An absent series yields unavailable. A stale or invalid
series yields unknown. `day0` anchors the series and does not establish the issue time.
The summit grades and the AMECS scores have separate scales and geographic scopes.

## AMECS live page and data contract

Each query checks the Japanese page's title, seven date-column pairs, AM/PM order, north/south numeric rows and 1–10 scale. It follows only the single first-party `./lib/t24.js?<12-digit-version>` reference, reads it as text and checks the selected CSV routes and the original numeric DOM-write formula. It does not execute downloaded code or fetch advertisements, tracking, third-party scripts, satellite images or the POST-based image-list endpoint.

The selected native routes are:

- `https://www.fuji-san.info/data/fdata_N.csv`: northern view.
- `https://www.fuji-san.info/data/fdata_S.csv`: southern view.

The script turns the raw input into the displayed index using `min(10, ceil(value / 10) + 1)`. A raw zero becomes index **1**, raw 70 becomes **8**, and values at/above 90 give **10**. This is the publisher's presentation rule, not a new model or a percentage conversion. Raw inputs are validated but not exposed as measured probabilities.

The checked CSV begins with an initialization timestamp and explicit `JST` label. Remaining rows contain full dates with reference times 09:00 and 15:00, alternating daily from the following day. Other timezone conventions are unsupported until verified; do not guess UTC conversion. Validate dates/order, two columns, integer input 0–100 and at least fourteen slots. Empty or `-` values are unavailable, never zero. Unknown text, duplicate/reordered dates and an incomplete product fail with unknown state.

The backend includes more than seven days. Only the first fourteen slots belong to the checked visible panel, so later backend rows remain unavailable even when numeric values exist. Distant query dates do not extend coverage. Full dates handle year boundaries without assigning the current year to month/day strings.

## Time, status and output

`source_initialization_time` comes from the CSV header and page's `init` label. It is not a verified issue/publication time; `issued_at` stays null. HTTP Last-Modified is preserved raw as transport metadata. `source.retrieved_at` is the response-read completion time. Each direction keeps its own metadata.

The fixed **client policy** rejects a future initialization or one older than 36 hours, and checks again after all reads. This accommodates the checked 09:00 initialization and approximate afternoon updates. It is neither a publisher validity deadline nor proof that a newer run does not exist. No custom freshness override, stale-data fallback or capture replay is provided.

`records[]` contains each requested direction, including independent errors. Successful source records have broad scope, initialization, seven-day coverage, scale and requested `days[]`. Periods retain their index or explicit unavailability. A reference clock passing never turns a forecast into an observation. Different north/south initializations are not compared as one run; top-level status is partial even if both records individually contain valid values.

Source/schema/transport failures are errors with `state=unknown` and no fabricated indices. Missing dates or explicit missing values are unavailable. Mixed results are partial. Both errors or failure of the shared page/script contract exit 2; completed partial/unavailable queries exit 0. `doctor` is offline.

One-side queries make three GETs, both-side queries four: page, one script and selected CSVs. Fixed HTTPS routes only; no redirects/retries, cookies, account/session import or browser. One-second minimum spacing, 15-second socket timeout and 128 KiB response cap. Invocation-local caching shares repeated reads. A denial is not permission to switch identities or clients.

## Current images are a separate source

For current visual evidence use original official directory pages:

- [山梨県公式観光情報 — 今見える富士山ライブカメラ](https://www.yamanashi-kankou.jp/heritage/fujisanwatcher/jp/live/).
- [静岡県 — ライブカメラ富士山ビュー](https://www.pref.shizuoka.jp/fujisanview/1044916.html): 清水, 富士宮 and 御殿場 entries.

These are reference links, not a maintained local camera catalog or CLI status endpoint. The CLI does not download frames or decide whether Fuji is visible. Camera location, frame time, darkness and outages need separate checking. Neither a good index nor a visible mountain establishes safe climbing conditions.

## Information rights

AMECS's [use notice](https://www.amecs.co.jp/index.html#contact) disclaims availability/quality guarantees and restricts secondary copying, distribution, publication and other reuse without permission. Keep queries on demand with attribution and original links. Do not distribute a capture archive, database or mirrored feed. Code licensing grants no rights to provider data.

Camera imagery has separate conditions. The Yamanashi directory marks some images as prohibiting secondary use; Shizuoka describes attribution and noncommercial conditions. Linking to original pages does not copy their images into this package. Do not infer unrestricted reuse from public access.
