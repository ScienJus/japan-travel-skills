# Transit sources and interpretation

## Verified integration: Yahoo! 路線情報

Primary entry: <https://transit.yahoo.co.jp/>. Its public homepage's query form and shipped JavaScript provide the observed request contract. This is a consumer website adapter, not a licensed or stable public API. Public readability does not grant redistribution rights. Follow [LY Corporation terms](https://www.lycorp.co.jp/ja/company/terms/) and the result page's timetable rights notice. The output retains that notice and source timetable versions. No complete upstream pages or timetable databases are bundled with the skill.

- `GET /api/suggest?value=<query>` is used by the website autocomplete. The JSON `Result` array mixes `Id=st` station suggestions, `bu` bus stops, and other categories. `stops` returns either/both as `kind=station|bus`, preserving `Suggest`, `Code`, `Address`, and `Yomi`. `stations` retains its railway-category behavior. These are suggestions, not exhaustive search results. A source `st` result can be an airport; route transport flags disable flights.
- `GET /search/result?...` returns HTML with a `__NEXT_DATA__` JSON script. The tool parses `props.pageProps.naviSearchParam`, not rendered CSS classes or private backend endpoints. No JavaScript is executed. Website build hashes/chunks are not required at runtime.
- `from` / `to` retain selected native names; `flatlon=,,<code>` / `tlatlon=,,<code>` retain station identities. Date uses `y,m,d`; time uses `hh,m1,m2`, where minute digits are separate. `type=1/4/3/2` means departure/arrival/first/last. `ticket=normal/ic`, `expkind=1/2/3` means non-reserved/reserved/green preference, `s=0/1/2` means fast/cheap/few transfers. These mappings were read from the website's own form/client code.
- `shin`, `ex` enable Shinkansen/limited express. `hb` and `lb` enable highway/airport and local buses; both are disabled in rail mode and enabled in bus/mixed modes. Bus mode disables `shin` and `ex`. `al` and `sr` disable flights and ferries in all modes. `ws=3` uses the website's 少しゆっくり walking preference. No user commuter pass is supplied (`userpass=0`).

`queryState` must echo requested conditions. `resultInfo.Status` must be 200 and `ForceAverageSearch` false. User-facing `queryState.errorList` is preserved when the source cannot answer. Missing JSON/changed schema/unknown time types are errors, not evidence of no service. HTTP denial, throttling, network errors, and source changes stop without retries or alternative-provider requests. HTTP protocol exceptions (including `IncompleteRead` and `BadStatusLine`) become structured `network_error` results and exit 2, rather than escaping as Python tracebacks. Failed responses are not cached; exception text and partial payloads are not logged.

Some intermediate points use qualified, parenthesized time labels even with `ForceAverageSearch=false`.
The observed native type sequences `[2,4]` and `[5,4]` are recognized but their complete clock semantics
are not interpreted. After validating all relevant fields and embedded alternatives, these return
`timetable_unavailable`, `state=unknown` and exit 2 with the source URL and retrieval metadata; no route,
leg times or connection waits are returned. They do not establish no service. Unknown types, malformed
clocks, unrecognized sequences and other invalid records still fail schema/identity validation;
a known qualification never masks a later invalid alternative. Ordinary time types retain their
calendar/date and ordering checks. Qualified clocks are never converted into ordinary exact times.

Endpoint identities require the same native code and normalized name, except for explicitly verified, code-scoped source aliases. The following code-scoped suggestion/route pairs are supported; terminal/operator qualifiers are not stripped generically. Output legs preserve the route's actual label and the query preserves the selected label.

| Code | Suggestion name | Route name |
| --- | --- | --- |
| `25891` | 関西空港駅(鉄道) | 関西空港(鉄道) |
| `29509` | 羽田空港第1ターミナル(モノレール/JAL) | 羽田空港第１ターミナル(東京モノレール・ＪＡＬ利用) |
| `29510` | 羽田空港第2ターミナル(モノレール/ANA) | 羽田空港第２ターミナル(東京モノレール・ＡＮＡ利用) |
| `29671` | 羽田空港第3ターミナル(モノレール) | 羽田空港第３ターミナル(東京モノレール) |

The suggestion API strips `/` from the complete T1/T2 candidate labels and returns no candidates for those strings. `STATION_LOOKUP_QUERIES` therefore submits the verified base names 羽田空港第1ターミナル / 羽田空港第2ターミナル on the first read, for both station and mixed lookup. It then resolves the original complete candidate name exactly, preserving its code and qualifiers. This is not a retry or a general rule for removing station qualifiers. Reusing a resolved code skips lookup but still checks the code, kind and verified endpoint name/alias.

## Route times and prices

Each `featureInfoList` item has `summaryInfo` and an `edgeInfoList` sequence. `query.weekday_ja` is derived from the requested JST query/service date, not the actual departure date when a connection begins after midnight. Keep the query date and original source URL attached to their returned facts; another weekday's result does not establish the requested day's service. Absolute departure/arrival dates come from `summaryInfo.calendarData.startTime/endTime` (JST); retrieval time is unrelated. Intermediate `timeInfo` type 2 is arrival, 1 departure, and 3 a shared endpoint/through time. The parser anchors clocks to the calendar start, advances midnight monotonically, and requires the final time and total duration to agree. Unverified/incomplete sequences fail rather than guessing. Leg endpoints keep native station codes. Optional intermediate stop clocks remain source clocks and are not converted to dated timestamps.

The result may leave after midnight on the next date, arrive on a later date, or require a long overnight connection. All leg dates and connection waits are explicit. First/last use the website's service-date mode rather than filtering a departure query. The tool returns up to three embedded alternatives without pagination. It does not enumerate all first/last trains by operator or all departures for a day.

`summaryInfo.totalPrice` is the source's total in JPY; `totalPriceDetail` preserves the base/supplement explanation when published. `fare.priced_seat_labels_ja` retains labels on the source's displayed first supplement charges (for example 指定席); these are priced categories, not available inventory or a per-leg allocation. Do not sum `edgeInfoList.priceInfo.price`: the same base fare appears on multiple legs under `edgeGroup`, and supplements can cover combined legs. Detailed output retains these display groups, `expType`, `isExpDisplay`, `isExpFirst`, and source price flags. Seat preferences do not establish actual seat category or inventory. A reserved-only train may appear under a non-reserved preference. Passes, child fares, booking inventory and operator-specific ticket-sale conditions are outside this implementation.

The result's `kousyouResult.detail` supplies JR/private-rail timetable versions and the rights notice; those are preserved as text and do not date bus data. Yahoo is a Japanese transit aggregator, not a transport operator. The checked pages identify JR timetable data from 交通新聞社 and processing involving ヴァル研究所. These results do not independently verify current operations, track changes or availability; use an operator's official status/sales page when that is needed.

## Bus and mixed routes

Yahoo's [2026-09-01 official announcement](https://blog-transit.yahoo.co.jp/info/20260901_bus-timetable.html) documents bus-stop lookup and bus timetables on the website. This adapter queries dated route results, not a complete stop timetable. Yahoo's [coverage help](https://support.yahoo-net.jp/SccTransit/s/article/H000010160) says only some local/highway buses are supported; do not imply universal coverage.

Native bus names often end in `/operator`. Keep that qualifier and native code; the same physical area can have distinct operator stops. Generic `(高速・連絡バス)` stop names do not identify a single operator, so `operator_ja` is null. The suggestion API does not accept some complete operator-qualified labels as search text. Before the first read, bus/all lookup searches the stop-name portion before a slash outside parentheses (or removes the exact generic highway/connection suffix), then resolution compares the complete original name against returned candidates. Parenthetical slashes are not treated as bus-operator separators; Haneda T1/T2 use the explicit station overrides described above, while unrelated railway qualifiers remain intact. This is not a retry, nearest-stop substitution or operator merge. The source's echoed search query is still required to match the actual submitted lookup.

Outgoing `accessInfo.type` maps to 0 rail, 1 walking, 2 local/airport bus and 3 highway bus; both bus types return `leg.transport=bus`. Native highway-bus result sections render type 3 with `icnHighwayBus`. This source field determines transport; service-name text is not used to guess modes. Unknown/missing types fail. Points use adjacent nonwalking leg types to identify rail/bus kind, preserving known endpoint kinds through walking-only connections; unknown intermediate kinds remain explicit. The final node has no outgoing leg and inherits its incoming mode. `ridingPositionInfo` can supply bus `のりば`/`おりば`, which remains native text.

The verified web form has no ordinary-train exclusion. `--transport bus` disables Shinkansen/limited express, enables both bus categories, then filters all embedded alternatives to bus/walking routes with at least one bus leg before applying `--limit`. It rejects railway and walking-only alternatives. It does not perform extra searches to force a bus route or enumerate services. `unavailable_reason=no_matching_embedded_routes` therefore means no matching route among this page's alternatives, not no service. `--transport mixed` allows all supported surface modes but does not force both rail and bus to appear. Original ranks, embedded counts and filtered counts are returned.

Bus timetable version is unknown (`source.bus_timetable_version=null`). Dates/modes must still echo the requested JST conditions, and calendar timestamps must agree with the route. Scheduled bus times and fares are not a guarantee of actual arrival, operating-day exceptions, seats or booking conditions. The tool preserves source notices; check the operator when those details matter. No reservation, live bus-location query or ticket purchase is performed.

Jorudan route data and automatic provider fallback are not supported.
