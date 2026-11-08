# IR Ishikawa official line reports

Read this reference for `operations --operator ir-ishikawa`. This adapter is independent of Yahoo timetable searches and JR West reports.

```bash
python3 "<skill-dir>/scripts/transit.py" lines --operator ir-ishikawa
python3 "<skill-dir>/scripts/transit.py" operations --operator ir-ishikawa --line IRいしかわ鉄道線
```

Resolve `<skill-dir>` to the installed skill's absolute directory as described in [SKILL.md](../SKILL.md).

## Scope and selection

The integrated operator is IRいしかわ鉄道 and the section reference is 大聖寺–倶利伽羅. The [official station list](https://www.ishikawa-railway.jp/) identifies those endpoints. The data's native operator/railway identities are `odpt.Operator:IRIshikawa` and `odpt.Railway:IRIshikawa.IRIshikawa`. Keep them distinct from the former JR Hokuriku line, JR七尾線, ハピラインふくい and あいの風とやま鉄道. Through-service prose can mention neighbouring sections; that is not status coverage of another operator.

The catalog name is `IRいしかわ鉄道線`. Explicit aliases `IRいしかわ線`, `ＩＲいしかわ線` and `IR石川铁道线` resolve to that same identity. Partial names and mismatched operator/line pairs fail without a request. Multiple aliases in one command are deduplicated. `lines` is an offline integration catalog, not an operating-state source. Omitting its operator filter lists all integrated sections.

## Provenance and reads

The operator's homepage links to its own [IR運行情報 application](https://www.ishikawa-railway.jp/ishi-train/). Its production JavaScript references these anonymous GET routes:

1. `https://www.ishikawa-railway.jp/api/v1/message`: generated summary records plus native operator/railway label mappings.
2. `https://www.ishikawa-railway.jp/api/v1/messages`: complete `operation_information` records shown in the application's list view.
3. `https://www.ishikawa-railway.jp/api/v1/operation_news`: the application's supplementary notice.

These are undocumented website routes, not a contracted API. Runtime uses the fixed data routes; it does not fetch deployment-specific JavaScript, image assets, analytics or train locations. The homepage `train_state.json` banner alone and `operation_news` alone are not substitutes for the complete report set. Empty placeholder HTML is not operating-state evidence.

One query makes three serial reads, shared by duplicate line aliases. There is at least one second between request starts, a 15-second socket timeout, a 2 MiB body limit per response and no retry or redirect. Allowlisted URLs and budgets remain separate by operator: JR West still permits only its original single snapshot GET. No account, cookies, browser, persistent capture, polling loop or fallback is used.

## Times, validity and failure behavior

Summary records supply native `dc:date`, `dct:valid` and `odpt:timeOfOrgin` (the publisher's spelling). Preserve the original records. `dc:date` is the generated summary time, not necessarily when an incident began; the origin field can be much older in a fresh summary. Do not convert it into a train's departure or recovery time.

Require explicit JST timestamps, a generated summary no more than ten minutes old and no future time, an origin no later than generation, and a publisher validity deadline later than both generation and the check time. The adapter reads the actual publisher deadline rather than assuming or extending a fixed validity interval. Validate once after the summary read and again after the other reads, so a summary cannot expire unnoticed during a query. Multiple summary records retain their individual native times; top-level `snapshot_at` and `valid_until` conservatively use the earliest respective times.

Complete-list records retain their own `dc:date` values and text, including multiple affected sections or ongoing older notices. They must not have future timestamps. The list is a separate product, so its dates need not equal the summary time. The supplement exposes no verified generation timestamp: `supplemental_notice_snapshot_at` stays null. Summary freshness does not establish the age of either context product. Read dates and wording separately; conflicting text requires official verification, not an invented merged normal/disrupted state.

The adapter does not assert fixed IR reporting hours, continuous availability or a delay threshold. Freshness and the publisher validity deadline gate each result; JR West's service window is not applied to IR. A missing/expired summary, wrong identity, duplicate identity/mapping, missing or empty complete-list product, malformed supplemental notice, unsupported schema or request error returns exit 2 and `report_state=unknown`, without partial sections or an empty normal result. No alternate operator fills a failure.

## Output and interpretation

The existing `sources[]`/`reports[]` shape is retained. `bulletins` contains native summary records. `context.operation_information` contains all complete-list entries, and `context.supplemental_notice` retains the supplement. The result uses `state=reports_listed`, including when the native summary says normal operation. It does not expose a punctuality boolean. Source metadata separates generation, validity, retrievals and the final validity check. Never apply the summary timestamp to undated context.

Report the requested operator/section, native summary wording, significant complete and supplemental notices, their distinct times or unknown times, and the official source link. Include the command and measured usage for tool-use, reproducibility, efficiency or technical-failure questions. A normal summary label is not proof of zero delay, an unaffected connecting operator, or an individual train's punctuality. Notices can concern future planned work: publication alone does not make them a current suspension. Timetable route searches remain separate evidence; no automatic route-to-status matching is implemented.

Attribute results to IRいしかわ鉄道. Public accessibility is not an unrestricted redistribution license or permission for frequent polling. Retain small requested reports and source links; do not mirror a feed or bundle captured prose. Project MIT licensing covers code only.
