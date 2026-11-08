# Pocket Concierge discovery and availability

Use the absolute entry point and dependency setup from [SKILL.md](../SKILL.md).

Check both JSON `status` and the exit code: `0` means `ok`, `3` means `partial` with top-level `errors`, and `1` means `error` with an `error`. Report the failure causes alongside known results. Missing required session fields, malformed source data and failed requests must not become an empty menu/no sessions or a success. Normal page/result limits use `coverage=limited`; optional absent source fields may remain null.


## Commands

| Command | Scope and options |
| --- | --- |
| `filters`, `areas`, `cuisines` | Native catalog IDs and labels; one read each |
| `search` | `--keyword`, `--area`, repeatable `--cuisine`, `--budget-min`, `--budget-max`, `--meal lunch/dinner`, `--date`, `--people`, `--instant`, `--pages` (default 2), `--limit` (default 5) |
| `detail RESTAURANT` | Address, hours, conditions and courses; `--no-courses` omits course fields; optional `--meal` and `--course ID` |
| `courses RESTAURANT` | Listed courses and restaurant fee conditions; optional `--meal` and `--course ID` |
| `calendar RESTAURANT` | Restaurant-level reservation/waitlist date hints; optional `--date` or `--from/--to`; no party, meal, course or seat verification |
| `slots RESTAURANT --date DATE` | Public sessions for one date; optional `--people`, `--meal`, `--course ID`, `--seat TYPE`, `--time` or `--after/--before` |
| `availability RESTAURANT` | `--date` or `--from/--to` (1–31 days); same session filters as `slots`; ranges screen the calendar first |
| `doctor`, `usage RESULT_JSON...` | Offline dependency checks and saved usage aggregation |

`RESTAURANT` is a public restaurant URL or numeric ID. Course IDs come from that restaurant's details/courses; seat types come from actual sessions, such as `COUNTER` or `TABLE`. Unsupported parameters are rejected before requests. There is no arbitrary source/GraphQL command and no account or reservation mutation command.

Shared flags may appear before or after the command: `--lang ja|en` (default ja), `--timeout`, `--max-requests`, `--delay-min-ms`, `--delay-max-ms`. Japanese source names are the default; English queries do not automatically trigger extra Japanese translation reads. Reply in the user's language and retain source names.

## Discovery and prices

Resolve native area/cuisine IDs with the catalogs, or pass an exact native label. Names cost one additional shared catalog read; numeric IDs need no lookup. Areas are Pocket Concierge search regions, not municipal polygons. There is no coordinate-radius, Tabelog-rating or award filter. Do not silently substitute another region.

Date/party search uses native filters; `--people` requires `--date` for search. Search results are discovery evidence, including request-booking restaurants. `--instant` restricts the native instant-confirmation mode. `--meal` selects the source course service type. Budgets are native per-person price-search filters in JPY; retain source price bands and do not claim final course/seat verification from a search result. Pagination stops once enough results are returned. Limited pages are not exhaustive coverage.

Course prices distinguish `per_guest` and `fixed_per_group`; `all_in_total` is null. Preserve course notes and `reservation_terms` together, including contradictions about tax or service fees. A listed course does not establish date eligibility, seats or a final total.

`detail.practical_info` groups reservation, payment and child-policy evidence from venue terms/FAQ, with the native booking entry. It reuses the existing detail read, including with `--no-courses`. Prose-only acceptance/payment flags stay null; `transactions_allowed` is not interpreted as on-site card acceptance. Read age/meal qualifiers verbatim. No child eligibility, extra booking channels or date-specific seats are inferred from these details.

## Inventory interpretation

- A `ReservableAvailability` session with `booking_mode=instant_confirmation` is a public instant-confirmation option, not an existing reservation. `reservation_request` requires the restaurant's later confirmation. A `WaitlistableAvailability` is only a waitlist signal; its session ID is null. Keep all three distinct.
- `--people` is optional for sessions. Omission returns each slot's `min_people`/`max_people` directly without enumerating people. These are supported party sizes, not free-seat counts. Missing bounds, unknown seat/meal matches or booking mode remain `unverified`/partial; do not infer eligibility. Waitlists retain their own `unknown` fields and also make coverage partial when eligibility is unknown. No child/baby eligibility is inferred.
- Each session retains its course and seating type. Session IDs can repeat across courses; do not discard course/session combinations. A date-wide range does not mean every course/time accepts that range.
- Source offset timestamps are retained; queries use Asia/Tokyo dates. Time filters match only the reported `startTime`, with inclusive bounds. The source's `endTime` may equal the start or span a window; it is not a meal duration. Do not invent intermediate starts. Elapsed starts are omitted.
- `calendar` is not party specific. Its missing reservation signal does not establish sold-out or closed status. Range availability checks sessions only on calendar candidate dates; calendar-only rows have `slots=null` and are not course/seat/person checks. Single-date availability reads sessions directly.
- Inspect `status`, `coverage`, `errors`, `unverified`, `verification`, `coverage_basis` and `trace`. `coverage=complete` means the required source reads completed under the screening policy, not exhaustive restaurant inventory. Null, failed or unqueried data stays unknown. Waitlist/availability observations never hold seats.

Examples use the absolute `<skill-dir>` and Python environment resolved in `SKILL.md`.

```bash
python3 "<skill-dir>/scripts/pocket_concierge.py" areas
python3 "<skill-dir>/scripts/pocket_concierge.py" search --area 20 --date 2026-12-02 --people 2 --meal dinner --instant --limit 5
python3 "<skill-dir>/scripts/pocket_concierge.py" detail 245672
python3 "<skill-dir>/scripts/pocket_concierge.py" calendar 245672 --from 2026-12-01 --to 2026-12-03
python3 "<skill-dir>/scripts/pocket_concierge.py" slots 245672 --date 2026-12-02 --people 2 --seat COUNTER
python3 "<skill-dir>/scripts/pocket_concierge.py" availability 245672 --from 2026-12-01 --to 2026-12-03 --people 2 --meal dinner
```

Replace example dates and IDs with the user's actual scope. Report restaurant links, Japan dates, people/course/seat filters, observation time, source scopes and errors. Include actual commands, relevant dependencies and measured usage for tool-use, reproducibility, efficiency or technical-failure questions. Do not re-query just to explain costs.

## Request policy and costs

Requests are serial with default 1–2.5-second gaps, per-command memory caching, a 15-second request timeout, an 8 MiB response bound and a default 20-attempt budget (maximum 80). Delay flags accept 250–30000 ms; maximum must be at least minimum. Denials, challenges, 401/403/429/503 or `Retry-After` stop further reads; honor `retry_not_before`. GraphQL errors, including partial-data errors, stop further queries and are not empty inventory. No automatic retries or identity/proxy rotation. Coordinate separate commands; they share no pacing or cooldown state.

Catalogs, one search page, details/courses, a calendar, or a single date's sessions each need one HTTP read. Named search filters add one cached catalog read; numeric IDs add none. Range availability needs one calendar plus one read per candidate date. Omitting people causes no additional requests. Defaults bound further reads; an exhausted budget produces partial coverage. Runtime uses HTTPX directly; no external CLI, paid scraping service or browser is installed. `usage` measures request starts, consumed decoded bytes, elapsed duration and pacing; it does not measure wire traffic, CPU, memory, model tokens or money.

## Responsible use and references

Provided for learning, research and reference. Follow platform terms, applicable laws and privacy/data-use requirements. Do not bulk harvest, disrupt services or bypass access restrictions. This independent project grants no rights to third-party data. Results and continued access are not guaranteed; the MIT warranty/liability disclaimers apply. The notice adds no restrictions to the MIT software license.

Never import credentials, login cookies, browser profiles or authenticated sessions. Any future identity-based workflow requires explicit scoped consent before access, explaining the account, actions, session handling and account/privacy risks. Search permission is not account authorization. Desktop-browser/CUA use requires separate confirmation. Do not create bookings, holds, waitlist entries, payments or account changes. Keep captures and session data out of commits.

The consumer endpoint is `POST https://www.pocket-concierge.jp/graphql` with the public `GUEST_ORIGIN` header and fixed read queries. It is undocumented and may change. [Printing Press Pocket Concierge CLI](https://github.com/mvanhorn/printing-press-library/tree/main/library/travel/pocket-concierge) was used to research the guest endpoint, query fields and session semantics. It is not an installed runtime dependency; this implementation uses Python HTTPX.
