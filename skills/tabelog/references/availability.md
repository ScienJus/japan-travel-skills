# Reservation channels and availability

Use a confirmed restaurant ID/URL and any requested time range. `calendar` may omit dates for a one-read overview; `slots` and `availability` require a date/window. `--people` is optional for all three. Dates/times use Asia/Tokyo; state the exact range and whether it includes today. Explicit calendar/availability windows support up to 31 days. `availability` excludes elapsed same-day times from matches. Omitted `--time` is not sent upstream; it uses the API default anchor. `--after`/`--before` filter availability times independently of that anchor.

## Party sizes

- Without dates, `calendar` returns the complete response window controlled by the upstream, with `coverage=returned_overview`, `member_coverage=not_queried`, and null people ranges. It does not expand the whole calendar into member/slot reads, even if `--people` is supplied.
- With `--date` or `--from/--to`, `calendar` reads one restaurant-wide overview, then calls `find_vacancy_member_by_date` once per candidate date to get all returned party-size options. It never checks time slots. Optional `--people N` annotates `requested_people_hint`; it does not filter the overview or suppress other returned sizes.
- The native member response uses `svpsOpts[].member_num/status`; only status **2** is selectable. Status 0 is disabled. Other codes remain unknown. This is a different contract from the date overview's statuses.
- `selectable_people` and `selectable_people_ranges` are date-wide hints across meals, not confirmed times. No separate one-person/two-person calendar requests are needed: the overview does not use `svps`.
- `slots` or `availability` with `--people N` checks that party directly. Without it, fetch the date's member options once, then check slots for each selectable size. Do not probe every number from 1 to 99 or assume capacity is monotonic.
- `available_people_ranges` groups verified matching sizes; each `time_options` entry has its own `people_ranges`. Ranges are inclusive and merge only consecutive observed sizes: `[1,2,4]` means **1–2 or 4**, not 1–4. These are supported party sizes, not free-seat counts, table capacity, or seat types.
- Missing sizes are not inferred. Failed/unchecked sizes stay in `unknown_people` and `people_results`; known matches can coexist with partial coverage. Request budgets and denials stop further checks. Prefer `calendar` for cheap date-level monitoring and specify `--people` when the actual party is known and time verification is needed.

## Channel and inventory

- `channel` checks the English-site calendar and restaurant reservation policy. A calendar establishes an online channel, not seats for a particular date or party.
- `予約可`, `完全予約制`, or a phone number do not prove Tabelog online booking. Identify TableCheck or other intermediaries as their actual channels.
- English/Japanese-site inventory and courses may differ. A listed course does not establish availability for that course, seat type, or booking mode.

## Calendar screening

`availability` reads the overview, then checks candidate dates using the same English channel without a specified course. The overview is restaurant-wide; date and party size apply to the member/slot endpoints. Overview states are:

| State | Meaning | Range-query action |
| --- | --- | --- |
| 0 | Not selectable online | Exclude online date |
| 1 | Limited | Check slots |
| 2 | Available hint | Check slots |
| 3 | Closed hint | Exclude online date |
| 4 | Telephone inquiry | Exclude online date; do not call it fully booked |
| Missing / unknown | Unknown | Check slots |

Single-date availability with a fixed party always checks actual slots; without a party it checks slots for returned selectable sizes. Missing dates, empty overviews, or malformed data cannot justify exclusions; failures use conservative checks unless access/rate/request limits stop the query. Slot responses must echo the requested date and party size before their times count.

- `calendar_excluded`: overview evidence only; `offered_times=null` means no slot request was made.
- `ok`: the required member/slot checks completed; `matching_times` applies the requested time window. When no size is selectable, no slot checks are needed; inspect `verification`, `people_results`, and `query_plan`.
- `unknown`: failed or not queried; `matching_times=null` does not mean no seats.
- `coverage=complete`: every date has overview-exclusion or the required member/slot evidence for returned sizes, with no request failures or calendar/slot contradictions. A failed overview followed by successful slot reads retains the known slots but returns partial with errors. `query_plan` and `coverage_basis` distinguish the evidence; complete does not establish full restaurant inventory.

Report party size, dates, available times, sources, observation time, and unknowns. Empty slots describe this online response, not all restaurant inventory. Sequential responses are snapshots and do not hold seats. Availability checks need no personal information and must not submit reservations, accept binding terms, or pay. Follow the [request policy](access.md#request-policy).
