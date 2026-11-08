# NAOJ sunrise and sunset

## Official sources

- [国立天文台 暦計算室「こよみの計算」](https://eco.mtk.nao.ac.jp/cgi-bin/koyomi/koyomix.cgi): live form and calculation results.
- [Selecting locations](https://eco.mtk.nao.ac.jp/koyomi/koyomix/help_koyomix_place.html): reference-city menu and other website location modes.
- [Sunrise/sunset definitions](https://eco.mtk.nao.ac.jp/koyomi/wiki/C6FCA4CEBDD0C6FEA4EAA4C8C6EEC3E62FC6FCA4CEBDD0C6FEA4EAA4CEC4EAB5C1.html).
- [Glossary](https://eco.mtk.nao.ac.jp/koyomi/faq/glossary.html): sunrise, transit, twilight and elevation.
- [Site-use rules](https://eco.mtk.nao.ac.jp/koyomi/site/).

Each invocation reads the live domestic location and supported-year menus; neither set is bundled or hardcoded. Overseas entries are excluded. The implementation accepts the modern Gregorian years offered there; arbitrary historical dates, overseas locations, custom coordinates, municipal search and the long-term calculator are outside this integration.

## Request flow

1. GET the calculator URL without parameters. Read `select[name=NAO_id]` options as native code/label pairs, and `select[name=year]` as current supported years. Names/codes are resolved within this response; no previous catalog or guessed nearby point is used.
2. For a resolved Japanese location and supported date range, GET the same URL with verified form parameters. The webpage form uses POST, but the same calculator was also verified to accept these ordinary GET queries. No JavaScript, fingerprint, cookies, visitor initialization or authenticated identity is required.

| Parameter | Value/meaning |
| --- | --- |
| `year`, `month`, `day` | First requested calendar date |
| `hour=0`, `min=0` | Daily calculation anchor |
| `NAO_id` | Exact menu location code; preserve leading zeros |
| `lst=9` | UTC+9 / JST |
| `choice=0`, `choice0=0` | Main named-location selection |
| `btn00=Go` | Sunrise, sunset and solar transit calculation |
| `div=1`, `divu=3` | One-day spacing |
| `len=N`, `lenu=3` | N days, including the first; tool limit 31 dates |
| `cg=0` | Standard table |
| `drtn=1` | Include published daylight length |
| `nocalc=0` | Perform the selected calculation |
| `nomenu=1` | Suppress the large repeated form in the result |

HTML is EUC-JP, not UTF-8. Parse it with the standard-library HTML parser. The result is under `div#skipr`, with a named-location label, latitude/longitude/elevation/JST line, and `table.result`. Its observed headers are `年月日`, `出`, `方位[°]`, `南中`, `高度[°]`, `入り`, `方位[°]`, `長さ`. Do not run script tags or request analytics/assets.

Only the configured HTTPS calculator URL is allowed. Requests are serial, paced at least one second between starts, capped at two reads per invocation and 512 KiB per body, with a 15-second socket timeout, no redirects/retries and no persistent storage. HTTP denial, protocol errors, body-size mismatch and invalid EUC-JP produce structured errors. Do not silently fall back to another host, another calculator mode or a previous response.

## Validation and output

The result must identify the requested native label, state JST, contain exactly one standard sunrise/sunset table and return every requested daily date in order with no duplicate/extra dates. Coordinates, elevation, clocks and angles are validated. Sunrise, solar transit and sunset must be ordered within that JST date. Unknown table formats or missing events are errors, not zero values. The supported domestic reference locations are outside the polar-day/night regime; no polar-event semantics are inferred.

- `status=ok`: all requested dates parsed successfully. An unsupported menu year returns `unavailable` and an empty `days`; it does not trigger calculation or clamp the date. City discovery with no matches returns `not_found`. Exact city resolution failures return `status=error`, exit 2 and candidates where available.
- `location`: current menu identity, result latitude/longitude/elevation and explicit reference-point scope. Coordinates are degree decimals as returned by NAOJ; these are not a geocoded entrance or observation-site guarantee. The current parser accepts domestic reference coordinates and preserves nonzero elevations such as 富士山頂 (3776 m).
- `days`: ISO date, full JST sunrise/sunset timestamps at the source's minute resolution, and `daylight_minutes` normalized from the published `長さ` column. Solar transit and angles are added only with `--detail`.
- `source`: publisher, catalog URL, exact calculation URL, current menu years, result site-version marker when present, attribution and retrieval timestamp in JST. Retrieval time is not an ephemeris model revision date.
- `usage`: attempted HTTP reads, completed-response body bytes (excluding HTTP/TLS overhead), pacing and elapsed milliseconds. No token/cost estimate.

Do not recompute daylight length from rounded clocks. The source independently rounds clocks and duration; the parser retains its published duration and allows at most one minute of difference.

## Interpretation and attribution

NAOJ defines sunrise/sunset by the Sun's upper edge meeting the apparent horizon, with atmospheric refraction in its model. Mountain ridges, buildings and the visible local skyline are not included. A high point's source elevation can affect the calculation and must not be reset to sea level. Actual sunshine duration, cloud visibility, dawn/dusk brightness, terrain-specific shadow and safe hiking deadlines require other information. Do not equate sunset with complete darkness or use the result as a weather forecast.

Attribute processed results to 国立天文台 暦計算室, retain the source URL and `(C) NAOJ`. The site's rules permit use of page content and request source indication/linking for citations. Project MIT licensing applies to code and does not replace NAOJ's content-use terms. Stop on access denial or schema changes and inspect the official source with bounded HTTP/web tools before updating the adapter.
