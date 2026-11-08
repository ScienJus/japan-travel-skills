# Query costs

Runtime dependencies are HTTPX, Beautiful Soup, and offline jpholiday. No Node.js, browser, API key, or paid scraping service is required.

These request counts assume known IDs/full URLs, no redirects, failures, or cache hits. P is result pages, D is candidates needing details, F is full reviews, C is calendar candidate dates, S is the sum of selectable party sizes across those dates, and K is related award categories.

| Operation | Typical reads |
| --- | --- |
| Suggestions / geocoding | 1 |
| Station identity and coordinates | 2 |
| Prefecture directory (`areas`) | 0 |
| Area/station catalog | 1 with a numeric parent; 2 with a prefecture name |
| Municipal neighborhoods | 2 |
| Coordinate / area / station search | P / 1 + P / 2 + P |
| List-budget filter | No additional reads |
| Meal, weekly-time or dated opening checks | Base search + D; conditions reuse details |
| Hyakumeiten filter | Base search + 1 catalog; all categories share the same search request |
| Details and courses | 2 |
| Individual `awards` | 1 with a year; otherwise up to 2 + K |
| Review excerpts / full reviews | P / P + F |
| One full review | 1 |
| Booking channel | 2 |
| Calendar without dates / with dates | 1 / 1 + C; no slot checks |
| Single-day slots with / without `--people` | 1 / 1 + S |
| Range availability with `--people` | 1 + C; up to 32 for 31 days |
| Single-date availability with `--people` | 2 |
| Availability without `--people` | 1 + C + S; request budget bounds further checks |
| `source` / `source --prime` | 1 / 2 |
| `doctor` / `usage` | 0 |

Search stops once enough matches are found. Missing coordinates, explicit area fallback, ID resolution, redirects, and failures can increase requests. Default same-site pacing is 1–2.5 seconds; actual duration depends on the source and query.

Read `usage` for actual request starts, elapsed time, waits, decoded response-body bytes, cache hits, and dependency versions. `trace` describes sources and errors; its entry count is not a request count. `--max-requests` bounds both top-level reads and actual network starts, including every redirect GET. Bytes exclude headers/TLS and compressed wire traffic; CPU, memory, model tokens, and monetary costs are not measured. Missing measurements remain null.

Save command JSON and use `python3 "<skill-dir>/scripts/tabelog.py" usage first.json second.json` to aggregate it offline without repeating queries. Do not count the same file twice. Summed durations are not wall time for overlapping commands.
