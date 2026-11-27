# Itinerary weather reports

Use this format for a trip-wide forecast or a daily update to an existing itinerary. A question about one outing can be answered with its relevant hours. Honor an explicit request for different hours, a particular provider or a source comparison.

## Follow the traveler

Start with the weather that matters most to a planned activity. For example, if the forecast shows rain at arrival and dry conditions by a timed garden visit, give both times and what each means for the plan. Identify the city reference point or forecast region when applying it to a venue.

Work through the itinerary in date order, including dates still outside published coverage. Within each date, list the cities where the traveler will spend that part of the day. A transfer day might read “Saturday afternoon · City A”, “Sunday morning · City A”, then “Sunday afternoon · City B”. Include transit stops when weather there affects the trip. Anchor advice to the actual arrival or visit time, even when the city table starts earlier.

## Choose one forecast for each date and city

| Published coverage for the intended visit | Forecast to present |
| --- | --- |
| Weathernews has usable hourly rows for any of the visit window | Use the hourly forecast. Mark gaps and give the exact cutoff if the sequence ends during the visit. For example, if it ends at noon, mark 13:00–20:00 as awaiting publication. |
| The visit falls outside hourly coverage and JMA covers the date | Use the JMA daily forecast for the applicable region and temperature station. |
| The date is beyond JMA coverage but within Weathernews daily coverage | Use the Weathernews daily forecast for the municipality reference point. |
| Beyond published daily coverage | Keep the date in the itinerary and mark the forecast as pending. |

Select by the actual timestamps and dates returned. The approximate three-, seven- and fourteen-day horizons help plan reads. Follow the skill's stop rules on request failures. Keep missing fields explicit within the selected product.

## Show the values that support the decision

- **Hourly.** Use JST morning 07:00–12:00 and afternoon 12:00–20:00 as the default sightseeing windows. Show noon once for the same city. Extend the window for a planned early departure or late activity. Use columns for time, weather, temperature (°C), hourly precipitation (mm) and wind speed (m/s). Combine consecutive hours only when all displayed values and their availability match. Highlight the arrival, visit or weather-change hour.
- **Daily.** Use one compact table with date, itinerary city, product, weather, daily low–high (°C), precipitation probability and the provider's confidence grade when published. On a transfer day, “morning” or “afternoon” identifies the traveler's location. Label whole-day values accordingly and retain any six-hour probabilities with their own time intervals.
- **Sources and times.** Link each block to its original forecast. Give the retrieval time in JST and the provider's issue time when known. For a visit between two forecast hours, identify the neighboring published hours used.

## Show what changed since yesterday

Use the previous report or a dated snapshot when available. Compare the same target date, location or region, provider, product, time interval and metric. **Bold material changes** and show their direction and effect on the plan, for example “rain now ends at 18:00 (previously 16:00), during the garden visit.” Keep unchanged rows brief.

When a date first enters weekly or hourly coverage, label the transition separately. A move from a daily rain probability to an hourly rain amount has no numeric day-over-day delta. If yesterday's comparable value is unavailable, say so and present today's forecast on its own.
