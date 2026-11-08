# Sources and request policy

All network operations use the unified CLI and Python HTTPX. Frontend endpoints are not a supported public API and may change. Prefer verified APIs, then coded HTML parsers; the current CLI has no browser dependency.

| Feature | Source |
| --- | --- |
| Suggestions / station identity | `/en/suggest/keyword_suggest`, `/web-api/v1/search-suggestions/area` |
| Area / station catalogs | `/xml/list_area1`, `/xml/list_area2`, `/xml/list_stations` |
| Municipal neighborhoods | Municipality list-page navigation |
| Geocoding | Photon `/api/` or GSI `AddressSearch` |
| Nearby / area search | `/xml/rstmap` or `/en/rstLst/` |
| Details / reviews / courses | Restaurant HTML and JSON-LD, `dtlrvwlst/`, `party/` |
| Hyakumeiten | `/web-api/v1/hyakumeiten-category-list`; all returned IDs sent together in the map/list request |
| Individual awards | Detail badges and related `award.tabelog.com` category pages |
| Booking calendar / party sizes / slots | `/en/booking/calendar/find_vacancy_date_with_status/`, `find_vacancy_member_by_date/`, `find_vacancy/` |

## Request policy

- One anonymous connection pool per command, serial reads, per-command caching, and default same-site delays of 1–2.5 seconds. Redirects are paced, revalidated and counted against the network-request budget too. Existing proxy environment settings are honored; no login cookies or personal browser data are imported.
- `--delay-min-ms` and `--delay-max-ms` accept 250–30000; maximum must be at least minimum. Defaults suit small queries. Separate processes do not share delays or cooldowns, so coordinate commands and avoid concurrent same-site runs.
- 401/403, challenges, 429/503, and server-requested cooldowns stop subsequent reads. Honor `retry_not_before` across commands. Do not rotate clients, identities, sessions, or proxies to continue after a denial.
- Keep the stable tool User-Agent, endpoint-appropriate headers, and HTTPS verification. Delays do not guarantee access or protection from blocking.
- Access failures and unrecognized responses mean unknown data, not empty results. Preserve `error`, `trace`, and coverage.
- Extend CLI code before using a new source or transport. Desktop-browser/CUA use requires explicit confirmation for the specific purpose; account access requires separate scoped consent as described in [README.md](../README.md#responsible-use-and-account-risk).

`source URL [--prime URL]` is bounded GET diagnostics on supported public endpoints. It never executes downloaded code and redacts form verification values and Google API keys, not every personal/public field. Keep captures and session data out of commits and shared reports.
