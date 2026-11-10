# How to check a Japan travel itinerary with Codex

Use the Japan Travel Planner skill to check an existing itinerary for opening and last-entry times,
dated train and bus connections, and enough time for walking, luggage and transfers. Keep booked
hotels, fixed departures and must-visit places in the plan unless the user asks to change them.

## Give the planner the itinerary and fixed dates

[Install the Japan Travel plugin](installation.md) for a review that combines multiple sources.
For a single train, restaurant or hotel question, use the relevant specialist directly.

> Use $japan-travel-planner to check my Japan itinerary below. Keep my booked hotels and fixed
> departure times. Check the attraction's last entry for the actual visit date and whether I can
> get from the preceding stop to the platform in time. Keep the original links. Separate confirmed
> conflicts, suggested changes and things you could not check. Show the revised days if needed.
> [Paste my dates, daily stops, stations and fixed commitments.]

Exact dates, station names, reserved services and intended exhibitions or meal courses help
distinguish sources with similar names or different hours. Booking references and account details
are unnecessary. The planner can retain a booking you report without accessing an account.

## What a useful itinerary review shows

| Finding | Example |
| --- | --- |
| Confirmed conflict | The intended arrival is after the source's last admission. Move the visit and keep the hotel nights. |
| Suggested adjustment | Add time for luggage, a bus connection and the walk to the platform. Label any estimated durations. |
| Unresolved check | The venue publishes ordinary hours, but a temporary closure notice or future admission conditions have not been verified. |

In the [worked Hokuriku example](../skills/japan-travel-planner/examples/hokuriku-six-days.md),
the draft arrives at Kenrokuen after last admission and places a Toyama Glass Art Museum
exhibition on a scheduled closure day. The review moves the garden visit earlier and the named
exhibition to another day while retaining the overnight bases. Luggage storage remains unknown.
The example uses an invented brief and a dated source snapshot; recheck the actual visit dates
for a real trip.

The [planning workflow](../skills/japan-travel-planner/references/planning-loop.md) explains how
to verify a timed chain and make the smallest workable repair. The
[transit skill](../skills/japan-transit/SKILL.md) distinguishes timetable results from live
operation reports. The [city guide](../skills/japan-city-guide/SKILL.md) directs facility checks
to official tourism and operator sources where available. A review covers the facts it checked;
it does not certify the whole trip or make reservations.

To share the revised plan, see [create an interactive itinerary map and PowerPoint](japan-itinerary-map-and-powerpoint.md).
