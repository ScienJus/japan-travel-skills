# Source scope and interpretation

## Tateyama from Toyama City

Weathernews's [立山眺望予報](https://homerun.wni.co.jp/TOKS/view.html) identifies the viewpoint as 富山市内. Each of its seven date cards has a probability printed on an image. The parser pairs each month/day and weekday with the image in that same card. The reviewed summer and winter icon sets cover 0–100% in ten-point steps. Other image paths give an unknown value for that card. The CLI reads the page once and does not download artwork.

The year is inferred from a consecutive seven-day panel starting today or tomorrow in JST, checking all seven weekdays across year boundaries. Dates outside that panel are unavailable. The page supplies no verified issue timestamp. Report a single daily value even for a question about a morning or afternoon stop. The [Amaharashi live camera](https://www.youtube.com/watch?v=vOFQt1JWSgE) shows a separate coastal viewpoint in Takaoka. Check the stream time when using it for current conditions.

## Sea of clouds from Twin Terrace

The [Fuefuki tourism portal](https://www.fuefuki-kanko.jp/scontents/fujiyamatwinterrace/index.html) credits Weathernews. Its public three-hour forecast table reads the same-origin [forecast response](https://www.fuefuki-kanko.jp/weathernews/ajax/forecast.cfm) by anonymous GET. Only the displayed short-range SRF product is used. TSTR is the JST target time and INDEX is the probability of a sea of clouds. The website uses -9999 for missing data. Preserve zero, keep unpublished times unavailable and never interpolate. The site's update clock is computed from a schedule, so the CLI leaves the actual issue time unknown.

With no dates, the CLI selects upcoming source slots. A date alone selects its eight three-hour slots, including explicit unavailable entries where coverage ends. A passed slot is marked elapsed. A facility closure, shuttle timetable or view of Mount Fuji itself requires a separate check.

## Access and output

Each query uses one fixed HTTPS destination, a 15-second socket timeout and a 128 KiB body cap. No retries, redirects, account sessions or persistent cache. Operational or invalid-source errors return JSON with unknown state and exit 2. A completed query may return partial, unavailable or unknown records. Source links and retrieval time remain attached to the query. Data and camera content retain their publishers' terms.
