# Weathernews website adapter

## Source provenance

- [National two-week page](https://weathernews.jp/onebox/tenki/week/): its inline `setWeather` function reads anonymous `site.weathernews.jp/lba/wxdata/api_data_ss1/v2?lat=...&lon=...` JSON and displays the `mrf` daily rows.
- [Kanazawa two-week page](https://weathernews.jp/onebox/tenki/ishikawa/17201/week.html): consumer result link, local context and reliability explanation.
- [Published forecast code table](https://wxtech.weathernews.com/products/data/api/table/wxcode-forecast/): provider-specific numeric codes and Japanese labels. Labels are local metadata; no documentation sample icons are copied or displayed.
- [Icon explanation](https://weathernews.jp/about_forecast/faq/qa08.html): some icons share multiple descriptive meanings; the adapter uses the full numeric forecast table instead of guessing from graphics or JMA codes.
- [Consumer terms](https://weathernews.jp/ip/kiyaku/202603/index.html): restrictions on reproduction, reuse and service use. Anonymous access is not permission to redistribute forecasts. This project has no provider endorsement or service agreement.

This is a consumer website adapter, not a client for the paid WxTech API. No key, login cookie, browser session, JS execution or form submission is used. tenki.jp is not implemented; its [help explicitly asks users not to scrape or use unofficial programmatic clients](https://tenkijp.tayori.com/q/tenkijp-faq/detail/1083842/).

## Location resolution

Use the bundled JMA municipality catalog to resolve Japanese/English names, limited aliases and ambiguity offline. Then strip JMA-only subdivision suffixes to obtain the municipality name and request `https://weathernews.jp/onebox/api_search.cgi?query=...&lang=`. The endpoint returns plain JSON without a callback argument. Do not execute JSONP or import browser history.

Only native HTTPS `weathernews.jp/onebox/tenki/{prefecture}/{five_digit_code}/` result URLs with the expected municipality code are accepted. The JMA municipality code's first five digits identify that municipality; remaining digits can describe JMA subdivisions. Multiple different reference points remain unresolved. Result query parameters are dropped from the human link.

The adapter reads v2 forecast JSON using the returned coordinates and verifies both `geo.JCODE` and coordinates before accepting values. A designated city's reference point can be reverse-geocoded to a ward: accept that code only if the same native search explicitly lists the ward under the selected city. City codes have no assumed suffix; the native ward name must identify the selected city, and its code and URL must retain that city's prefecture. Output keeps the selected municipality `jcode` and actual `point_jcode` separately. No neighboring city is substituted on lookup failure. Subdivision-to-municipality changes are disclosed. A forecast point is the website's municipality reference, not a guarantee about every location or elevation in that municipality. If a municipality cannot be matched, use a more explicit supported catalog location or the JMA source; no provider is switched automatically.

## Daily data and times

`mrf` contains `tm`, `WX`, `MAXT`, `MINT`, `POP` and `reliability`, among other fields. `tm` is an epoch timestamp for the JST forecast day; join by that date, not list index. `WX` is interpreted only through Weathernews's code table; `999` is No Data. Unknown codes yield a partial weather field. Temperature and probability blanks remain null, and out-of-range/sentinel values fail explicitly. `PREC` is not exposed because this adapter has not verified its units and semantics for all days.

The JSON's `mrf_attr.time` is a sequence-start marker, not a verified forecast issue time. `issued_at.daily` and field-level issue times therefore remain null. The CLI records its actual retrieval time separately. No source-age guarantee is made; an entirely past-dated response is flagged and cannot supply future dates. A request time cannot establish that a source updated its forecast recently.

Weathernews can return today plus fourteen future dates (15 rows). The CLI's default requests tomorrow through day 14, and limits date ranges to 14 requested dates. Published gaps and out-of-horizon dates stay unavailable. The adapter caps exposure at today +14 days even if the source later extends its range. It never converts longer-range data into extra supported dates.

The A-E grade describes confidence in precipitation occurrence (A highest), primarily on later days. Empty earlier-day grades are null, not A. Do not compare grades numerically to JMA's A-C scale. `--source both` returns separate records, retaining disagreements and each provider's gaps.

## Costs, output and maintenance

Typically two reads per municipality: location search and v2 JSON. Repeated URLs share command-local memory; no persistent location or forecast cache is used. Both Weathernews hosts share a one-second minimum interval between request starts. Requests are serial, have bounded timeouts and a 2 MiB response cap, and stop without retries on failures/denials/throttling. Total invocation budget is 30 request attempts, including JMA reads when comparing sources. Honor returned Retry-After guidance across later commands; do not switch identities/clients to continue.

Default compact output retains source identity, resolved coordinates, source links, date coverage, reliability scale and shared `field_sources`. Point provenance stays distinct from JMA's forecast area and temperature station provenance. `--detail` retains the nested fields and provider code-label origin. Numeric code equality across sources does not establish identical descriptions.

`scripts/refresh_weathernews_codes.py` is a separate maintainer command with one documentation request. It extracts only numeric code/short-label table rows into `scripts/data/weathernews_codes.json`, with the URL, retrieval timestamp and response SHA-256. No source forecasts, icons or long descriptive passages are bundled. Runtime queries do not refresh it. Review the metadata diff and run offline tests after refreshing.
