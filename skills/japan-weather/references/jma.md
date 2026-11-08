# JMA source and field notes

## Primary sources

- [Official forecast interface](https://www.jma.go.jp/bosai/forecast/): the source of the public JSON routes and weather-code labels.
- [Weekly forecast explanation](https://www.jma.go.jp/jma/kishou/know/kurashi/shukan.html): seven-day horizon, A/B/C precipitation reliability, representative regions and seasonal subdivisions.
- [JMA content-use terms](https://www.jma.go.jp/jma/kishou/info/coment.html): attribution, processing notices and source conditions.

These JSON files support the public web interface; they are not a versioned developer API. The bundled catalog records its own actual retrieval time, source URLs, and response SHA-256 digests.

## Routing

The bundled `scripts/data/catalog.json` selects municipality and ancestor fields from `common/const/area.json`. Lookup walks `class20s -> class15s -> class10s -> offices`. Forecast queries use `forecast/data/forecast/{office_path}.json`; JMA combines the Tokachi office (`014030 -> 014100`) and Amami office (`460040 -> 460100`) in its web interface's `Forecast.Common.getPathCode` function.

`forecast/const/forecast_area.json` maps short-range weather regions to representative temperature station codes. The tool uses the first explicitly listed station as a regional reference and always reports its source name/code. It does not estimate the nearest station to arbitrary coordinates.

`forecast/const/week_area05.json` supplies permissible weekly regions for each short-range region. `forecast/const/week_area.json` links weekly regions to temperature station codes. The tool matches these mappings against the actual response, including seasonal region changes. If no unique mapping is available, it returns an error instead of choosing a neighboring region. The static metadata needs a maintainer refresh when JMA changes the area hierarchy/mapping.

Weather-code labels are extracted from the official interface's `Forecast.Const.TELOPS` numeric keys and string arrays, without executing JavaScript. Unknown codes retain their numeric code and generate a warning. The processed labels and routing metadata are attributed to JMA; no past or future forecasts are bundled.

## Products and merging

The source returns a short-range product followed by a weekly product. All joins use actual JST dates from each series' `timeDefines`; indices from different series are not interchangeable. Short-range products take precedence where they publish values. Weekly data supplies later dates. Blank values are retained as null. Short-range temperature timestamps at midnight/09:00 identify minimum/maximum slots; the morning/11:00 product can contain today's maximum as well as tomorrow's pair. Historical minimums are not inferred.

Weather, precipitation and temperature retain separate issue times and areas/stations. Weekly temperature uncertainty bounds are not carried into a short-range temperature record. Today may have incomplete temperature/precipitation coverage because only remaining-day values are published. Six-hour probability intervals are kept as intervals, including elapsed intervals if requesting today; they are not presented as all-day probabilities.

`status=ok` means the requested dates have weather, min/max temperature and some published precipitation information. `partial` means at least one requested field/date is missing. `unavailable` means no weather was published for the requested date(s). Status does not mean accuracy, full-day interval coverage, or freshness. A product over 36 hours old receives a warning; this threshold is a tool convention, not a JMA service guarantee. No stale-source refetch or fallback provider is attempted.

## JSON shape

The top-level envelope contains `status`, `retrieved_at`, `requested_dates`, `catalog_retrieved_at`, `format`, `forecasts` and `usage`. Each forecast contains the resolved `city`, `status`, `timezone`, `available_dates`, `issued_at`, `warnings`, `source` and `days`.

The default `format=compact` deduplicates provenance under each forecast's `field_sources`; each day's `sources` references those records. Days contain `date`, `status`, `weather_ja`, `weather_code`, `temperature_c` ([minimum, maximum]), `precipitation_percent`, `reliability`, optional `precipitation_6h` and `missing_fields` when fields are missing. Six-hour `hours` strings are half-open JST intervals on that day, with `24:00` denoting the next midnight.

With `--detail`, each day contains `date`, `status`, `missing_fields` and:

- `weather`: code, Japanese/English description, area, product kind, issue time; short-range wind prose when supplied.
- `temperature`: station, min/max Celsius, optional source uncertainty ranges, product kind and issue time.
- `precipitation`: published daily percent or six-hour periods, area, product kind and issue time.
- `reliability`: source A/B/C for weekly weather dates, otherwise null.

This forecast adapter normalizes regional forecasts; it does not supply historical weather, hourly point forecasts, mountain forecasts or visibility predictions. Current warning snapshots use the separate `alerts` mode described in [JMA warnings](jma-alerts.md).
