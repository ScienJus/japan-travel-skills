# Cabinet Office public holidays

## Source and request

- Publisher: 内閣府 (Cabinet Office, Government of Japan).
- [Official overview, yearly tables and explanations](https://www8.cao.go.jp/chosei/shukujitsu/gaiyou.html).
- [Official CSV](https://www8.cao.go.jp/chosei/shukujitsu/syukujitsu.csv).
- [Government data catalog entry](https://data.e-gov.go.jp/data/dataset/cao_20190522_0002/resource/d9ad35a5-6c9c-4127-bdbe-aa138fdffe42).
- [Cabinet Office content-use rules](https://www.cao.go.jp/notice/rule.html).

Each query reads the live Shift_JIS CSV (decoded with Python's CP932 codec). Its columns are `国民の祝日・休日月日` and `国民の祝日・休日名称`; dates use `YYYY/M/D`. Coverage is derived from the current response rather than a fixed year range. Newly added complete years are automatically usable on the next query. No search, JavaScript, browser, identity or API key is involved.

The source currently says that the next unpublished year's table is added in February of the preceding year. Its last listed holiday is in November, but its published coverage is through December 31 of that year. The implementation derives complete calendar-year coverage from the CSV's exported years. It validates column names, encoding, ordered unique dates, and the expected January 1 / November 23 boundary holidays in every year. These are schema/truncation checks, not independent proof that every official record is correct. Unexpected formats or incomplete boundary years fail rather than marking missing dates as non-holidays.

The source includes historical one-off changes such as the 2019 accession holidays and the 2020/2021 Olympic holiday moves. Preserve these source rows; do not reconstruct the calendar with today's rules. The label `休日` is used for more than one kind of holiday. For example, the official 2026 table describes May 6 under Article 3(2), and September 22 under Article 3(3), while the CSV labels both `休日`. The tool deliberately returns their common source label rather than deriving legal subtypes.

## Output

- `status`: `ok` if all requested dates are within the exported years, `partial` if some are, otherwise `unavailable`. This is independent of `--holidays-only` output filtering.
- `days`: one record per requested date, or only listed holidays with `--holidays-only`. `is_public_holiday` is true/false inside coverage and null outside it. `holiday_name_ja` is null for both a known unlisted date and an unknown date; inspect `holiday_status` to distinguish them.
- `is_weekend`: Saturday/Sunday, computed from the Gregorian date; it says nothing about a person's work schedule.
- `is_weekend_or_holiday`: true for a weekend or listed holiday, false for a covered weekday without a holiday, null for an uncovered weekday.
- `consecutive_breaks`: locally derived blocks of at least two weekend/listed-holiday dates that overlap the query. Blocks may start before or end after the query. Only dates within official year coverage are used; `boundary_complete=false` identifies a block that may continue beyond coverage. Ordinary two-day weekends are included; `includes_public_holiday` distinguishes them from blocks containing a listed holiday. Do not infer bridge leave days or special Golden Week/Silver Week durations.
- `source`: publisher, URLs, retrieval timestamp in JST, raw HTTP Last-Modified, SHA-256 of the source body, record count and calendar-year coverage. The timestamp is when this command obtained the data. Last-Modified describes the HTTP resource, not a verified legal publication time. Output is processed from the source.
- `usage`: one attempted HTTP read per query, received body bytes for completed body reads, elapsed milliseconds. No retries, persistent storage, offline fallback or polling.

National holidays alone do not establish restaurant/hotel opening, bank/administration schedules, school vacations, transport holiday timetables or actual work leave. In particular, do not label all unlisted year-end or Obon dates as ordinary business days.

## Attribution and maintenance

Attribute normalized results to 内閣府 and link the CSV or overview. The Cabinet Office states that its content is generally governed by the Public Data License (Version 1.0), subject to its exceptions. See the current linked terms when redistributing source-derived data. Project MIT licensing applies to code, not a replacement license for government content.

If requests or schema validation fail, inspect the official overview and CSV with bounded HTTP/web tools. Do not silently replace the source with a third-party API or return an old calendar as a fresh result. No calendar refresh job is needed: every query reads the currently served official CSV.
