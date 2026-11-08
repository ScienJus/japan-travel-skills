# JMA monthly station climate normals

Use this reference for `climate-regions`, `climate-stations` and `climate`. These commands read historical climate normals separately from forecasts and warning snapshots. They do not extend the forecast horizon or answer what will happen on a particular trip date.

## Commands and station selection

```bash
python3 "<skill-dir>/scripts/weather.py" climate-regions
python3 "<skill-dir>/scripts/weather.py" climate-stations --prefecture 石川県
python3 "<skill-dir>/scripts/weather.py" climate --prefecture 石川県 --station 金沢 --month 11 --month 12
python3 "<skill-dir>/scripts/weather.py" climate --prefecture 石川県 --station 金沢 --prec-no 56 --block-no 47605 --month 11
```

Resolve `<skill-dir>` to the installed skill's absolute directory as described in [SKILL.md](../SKILL.md).

Region and station menus are read online from JMA. Use exact native names returned by those menus. Hokkaido uses named subregions, not a single Hokkaido entry. Discovery excludes Antarctica and includes only surface stations whose native callback kind is `s`; AMeDAS kind `a` uses a different table format and is not integrated. Historical station discovery does not imply that a station still operates or that every metric has a normal.

A normal named query makes three serial GETs: region menu, selected region's station map, then the station's annual/monthly normals table. Discovery alone makes one or two reads. After resolving a native station, supply both returned `--prec-no` and `--block-no` together with the exact native region/station names to use one table read. Codes are not guessed or substituted: the response heading and native station-code link must still match. A partial/ambiguous name or a mismatch returns an error. This catalog is separate from forecast municipality codes and representative temperature stations; do not reuse those IDs here.

Repeat `--month` up to twelve times; omit it for all twelve months. Repeated months are deduplicated. All selected months share one annual table read. There is no trip year/date parameter, local climate database, menu refresh command or fallback to captured pages.

## Meaning and output

JMA's [normals explanation](https://www.jma.go.jp/jma/kishou/know/stats/dounyu_5.html) describes long-term averages used to characterize climate. Current standard normals use 1991–2020, but the adapter reads each field's published statistical period and sample years rather than pinning every response to that interval. Some fields can have shorter samples or reference values. Retain those distinctions.

The output has `kind=climate_normals`, an explicit native station identity, selected months, per-metric values and `metric_definitions`. Quantities are:

- Monthly mean temperature and monthly means of daily maximum/minimum temperature, in degrees Celsius. Daily high/low means are not monthly extremes or a guaranteed range.
- Monthly precipitation total in millimetres. It is neither the chance of rain nor the number of rainy days.
- Monthly sunshine duration in hours, which differs from astronomical daylight length.
- Monthly total snowfall depth, normal monthly maximum snow depth, and normal monthly snow-day count. These are historical station statistics, not a snow forecast or a trail condition report.

Each metric retains `raw`, `value`, `quality`, `statistical_period` and `sample_years`. The official [symbol explanation](https://www.data.jma.go.jp/stats/data/mdrr/man/remark.html) defines source flags. The adapter keeps normal numeric zero distinct from no-phenomenon dashes. Blank, `///`, `×`, `#` and dash-only values remain null with their respective quality flags. `///` can mean missing or unobserved; do not narrow it to one cause. Numeric `@`, `)` and `]` values retain reference, quasi-normal and insufficient-data flags. Do not use insufficient-data values as trustworthy typical conditions. Reference normals are not suitable for computing normal differences/ratios.

A month is `ok` only when all returned quantities are unflagged numeric values. Missing or qualified fields produce `partial`; all missing fields produce `unavailable`. Top-level status summarizes the selected months. Exit 0 only means the query completed; inspect statuses and quality flags. Failures return exit 2, `climate_state=unknown`, a source link and measured usage, without partial months or invented zeroes.

Report station, selected month, statistical period, source URL and relevant quality limitations. Include the command and measured usage for tool-use, reproducibility, efficiency or technical-failure questions. A monthly table can summarize typical temperature and precipitation. Do not label it a forecast, apply it to an entire prefecture, replace mountain conditions with a nearby city station, estimate foliage dates, or fill missing forecasts automatically. `source.retrieved_at` is client retrieval time; `issued_at` is null because no verified publication timestamp is exposed.

## Provenance and validation

The public [region menu](https://www.data.jma.go.jp/stats/etrn/select/prefecture00.php?prec_no=&block_no=&year=&month=&day=&view=) links to regional station maps. Those maps publish native station names, IDs and callback kinds. The surface monthly table is linked from the operator's own navigation, for example [Kanazawa monthly normals](https://www.data.jma.go.jp/stats/etrn/view/nml_sfc_ym.php?prec_no=56&block_no=47605&year=&month=&day=&view=). These are website HTML routes, not a contracted API. The adapter parses UTF-8 HTML without executing scripts or fetching image assets.

Validate the exact region/station/product heading and station-code link, one complete table, header quantities and units, rowspan/colspan grid, statistical metadata and all twelve distinct month rows. Bind quantities by their full header paths rather than column positions. Unsupported schemas/markers and missing or duplicate rows fail; maintenance HTML is not an empty climate result. Retain field-specific statistical periods/sample years.

The client allows only the three configured HTTPS routes on `www.data.jma.go.jp`, with bounded numeric code parameters. It caps each command at three attempts, each body at 2 MiB and each socket timeout at 15 seconds, and leaves at least one second between request starts. It rejects redirects and never retries, changes identity or uses an alternate source. Cache reuse is in memory for one command only. HTTP denials retain Retry-After where available; stop rather than switching clients. When discussing efficiency, report `usage` as measured body bytes, attempts and time, not tokens or monetary cost.

Attribute normalized output to 気象庁, link the original and identify processing by this tool. Follow [JMA's content-use terms](https://www.jma.go.jp/jma/kishou/info/coment.html). Project MIT licensing covers code; the project does not claim JMA endorsement or issue independent forecasts.
