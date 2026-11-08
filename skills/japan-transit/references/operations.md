# Official line reports

Read this reference for `lines` and `operations`. These commands are independent of Yahoo timetable searches. They do not infer which train a user will board or alter a route based on notices.

For IRいしかわ鉄道, read the separate [IR scope, generated-report validity and full-notice reference](ir-ishikawa.md). It uses its own three-read source and publisher validity deadline. The JR West details below are specific to JR West. `lines` lists both operators offline unless filtered; `operations` always requires one explicit operator.

## JR West commands and coverage

```bash
python3 "<skill-dir>/scripts/transit.py" lines --operator jr-west
python3 "<skill-dir>/scripts/transit.py" lines 大糸
python3 "<skill-dir>/scripts/transit.py" operations --operator jr-west --line 北陸新幹線
python3 "<skill-dir>/scripts/transit.py" operations --operator jr-west --line 大糸線 --line 七尾線
python3 "<skill-dir>/scripts/transit.py" operations --operator jr-west --line 高山線 --line 氷見線 --line 城端線
```

Resolve `<skill-dir>` as described in [SKILL.md](../SKILL.md). `lines [QUERY] --operator jr-west` lists JR West integration coverage offline; it contains no operating state. `operations` requires explicit `--operator jr-west`. There is no `all` option or automatic fallback to another operator. Repeat `--line` up to ten times to share one product read. Unsupported/partial line names fail instead of selecting a nearby line. Limited Chinese aliases are accepted; returned identities remain Japanese. `越美北線` and `九頭竜線` are explicit aliases for `越美北線（九頭竜線）`; fullwidth or ASCII parentheses resolve to that same native identity. `北陸本線` and `高山本線` are deliberately unsupported to avoid implying broader sections.

| Supported line | Operator | Infrastructure section reference |
| --- | --- | --- |
| 北陸新幹線 | JR西日本 | 上越妙高–敦賀 |
| 北陸線 | JR西日本 | 近江塩津–敦賀 |
| 大糸線 | JR西日本 | 南小谷–糸魚川 |
| 高山線 | JR西日本 | 猪谷–富山 |
| 氷見線 | JR西日本 | 高岡–氷見 |
| 城端線 | JR西日本 | 高岡–城端 |
| 七尾線 | JR西日本 | 津幡–和倉温泉 |
| 越美北線（九頭竜線） | JR西日本 | 越前花堂–九頭竜湖 |
| 小浜線 | JR西日本 | 東舞鶴–敦賀 |

The endpoints come from the operator's [service coverage table](https://trafficinfo.westjr.co.jp/static-pages/readme.html). They identify integration scope, not filters on through-service prose or a guarantee that a report concerns every station. Keep actual affected sections from the source. JR East's sections of 北陸新幹線 and 大糸線, connecting lines, named express-service queries, other private/third-sector railways and bus operation reports are outside the JR West adapter. IRいしかわ鉄道 has a separate adapter; its status is never inferred from JR West data. In particular, a 大糸線 result does not establish conditions between 松本 and 南小谷, and a 北陸新幹線 result does not establish conditions between Tokyo/Nagano and 上越妙高. 北陸線 uses the Hokuriku area's native ID 27, not the same-named Kinki-area ID 1; neither expands this integration to the historical Kanazawa/Toyama route. 高山線 does not cover JR Central's 岐阜–猪谷 section.

## Output and interpretation

Top-level `status=ok` means the requested official product passed validation. `reports[]` retains each native line, operator, section reference, source identity, native bulletins and wider context. `sources[]` separates the publisher snapshot time from client retrieval time. Event publication/update times remain inside native bulletins; an old event can remain valid in a fresh snapshot.

| Per-section `state` | Meaning |
| --- | --- |
| `reports_listed` | The current-date source lists selected-line records. Read their wording, dates and sections; a notice need not be a current disruption. |
| `no_listed_reports` | Validated current-date data has no selected-line report or review context. This is not a normal-operation or punctuality assertion. |
| `review_required` | Wider context needs review, such as area-level planned work or no-effect notices. It is not automatically a selected-line incident. |

Failures return exit 2, `status=error`, **`report_state=unknown`**, the official link and measured usage. They do not return partial sections or an empty `reports` array. Missing, stale, future, malformed or unsupported data never becomes normal operation. No local capture, history item or other provider fills a gap.

Report snapshot times in JST, the requested operator sections, native conditions and important qualifications, and source links. Include the actual command and measured usage for tool-use, reproducibility, efficiency or technical-failure questions. Do not infer that a specific departure, individual train or entire itinerary is unaffected. A timetable result remains separate evidence.

Area announcements and conventional-delay metadata are retained as context, without guessed line matching. An announcement can describe future work or an unrelated line. Publication time is not its effective date. Read the stated dates and affected section before describing any service change. Historical `trafficHistories` and future date buckets are not active current reports.

## Source and validation

The site's own production client references `GET https://trafficinfo.westjr.co.jp/api/v1/trafficinfo.json`. This is an undocumented website route, not a contracted API. Corresponding pages are [Hokuriku](https://trafficinfo.westjr.co.jp/hokuriku.html) and [Hokuriku Shinkansen](https://trafficinfo.westjr.co.jp/h_shinkansen.html). Their HTML is a client-rendered shell and cannot establish state by itself. The CLI reads the JSON without executing JavaScript. Deployment-specific chunk hashes are not runtime dependencies.

Validate generation time, explicit maintenance/site-notice flags, master/current identities, native name/ID agreement, known state codes, required report/detail arrays and three ordered date buckets. Only today's bucket supplies current reports. An empty native detail placeholder is not an incident; a nonempty state code without details is rejected. Preserve native selected records, including event times, stations, direction and prose. An unsupported active system notice requires direct official-page review and returns unknown. Missing or duplicate requested sections are unknown, not no reports.

The fixed snapshot age limit is **ten minutes**, with future snapshots rejected. It is a client policy, not a publisher delivery guarantee. Report publication/update times must not be later than the snapshot. Python 3.9 comparisons truncate fractional seconds to microseconds; original nanosecond strings remain in output.

The official [service policy](https://trafficinfo.westjr.co.jp/static-pages/readme.html) normally reports multiple-train delays of at least 15 minutes, with a 10-minute threshold for Hokuriku Shinkansen; some train-position areas report more frequently. This adapter supports 06:00–24:00 JST and conservatively returns unknown outside those hours even if reporting is exceptionally extended. No listed report is not proof of zero delay.

Related operator links in master data are not operating-state coverage. IRいしかわ鉄道, あいの風とやま鉄道, ハピラインふくい and のと鉄道 remain outside the JR West data source. Only IR has a separate integrated source; the others are not integrated.

## Requests and content reuse

One anonymous HTTPS GET serves every selected line in a command. It has a fixed 15-second socket timeout and 2 MiB body limit, rejects redirects and never retries. HTTP failures preserve Retry-After when available. There is no persistent feed, history cache, polling service, cookie jar or browser dependency. `lines` and `doctor` make zero requests. Coordinate separate commands, stop on denials, and do not use parallel runs or identity changes to evade upstream restrictions.

JR West's [service terms](https://trafficinfo.westjr.co.jp/static-pages/readme.html) restrict copying, republication and electronic/secondary use. Public readability is not a redistribution license. Do not mirror a feed, distribute an operations database or ship captured prose/pages with this project. Use small user-requested lookups and retain source attribution. MIT licensing covers project code only.
