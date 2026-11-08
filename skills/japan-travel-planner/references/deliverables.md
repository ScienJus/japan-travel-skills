# Travel-plan deliverables

Read this when the user wants a presentation, a map or another structured travel-plan handoff.
Choose the format that serves the request; a normal planning answer needs neither slides nor a map.
This is a content and handoff guide, not a bundled presentation renderer, map service or publishing CLI.

## One plan, several views

Use the same current plan for all outputs. Keep stable place and leg identifiers when producing
multiple files so dates, hotel choices, restaurant conditions and connections stay consistent.
After a change, update affected views together or identify which deliverables still show an older
revision. A file's generation date is separate from the plan snapshot and source-verification dates.

Keep these dimensions separate:

- **Plan role:** fixed commitment, selected option, candidate or backup. A user-reported booking is
  a planning constraint; it is not an independently checked reservation or a booking made by this tool.
- **Evidence:** what was verified, for which dates/conditions, from which source, and what remains
  unknown. A selected venue can still have unverified opening conditions.

Do not invent missing choices, prices, routes or coordinates to make a deliverable look complete.
Keep useful pending decisions visible. A reviewed plan retains unresolved findings in its handoff.

## Information hierarchy

| View | Useful content |
| --- | --- |
| Trip overview | Date range, city sequence, nights by base, major arrival/departure constraints and the main route; distinguish overnight bases from day trips and optional excursions |
| Intercity connections | Travel date, exact origin/destination stations or terminals, mode/operator, transfers, relevant departure/arrival times and duration; distinguish selected services from illustrative options |
| City overview | Stay dates, hotel/base, daily areas or attraction groups, key appointments, local movement and suitable alternatives |
| City details | Hotels, attractions and restaurants with native names, reasons they fit, relevant conditions and original links; include stations as orientation points when useful |
| Open decisions | Confirmed conflicts, suggested adjustments and unresolved checks that still affect the trip |

For intercity legs, include station/hotel access, luggage and transfer allowances where material.
Separate published service duration from your door-to-door estimate. Include quoted fares or pass
coverage only when checked for the relevant section and seat category. A schematic city-to-city
line shows sequence, not the physical railway or a verified timetable connection.

Group nearby attractions to support daily choices without making every candidate mandatory.
For hotels, carry practical access, facilities and applicable stay details. For restaurants,
distinguish a destination meal from a flexible nearby alternative, independently of booking status;
retain relevant meal/course times, party sizes and advance-order conditions. Refer to the relevant
specialist for live verification instead of turning the deliverable into a new source database.

## Presentation or PPTX

Use an available presentation-authoring skill/tool when requested; follow its creation and visual
verification workflow. Do not assume that this travel plugin includes that capability.

A useful sequence is a trip overview, a compact intercity travel table, city sections and remaining
decisions. Each city section can combine its hotel/base, daily areas, attractions, food and selected
restaurants; split pages where density harms readability. Add a local map only when it explains
location or movement. Adapt the number of pages to the trip rather than enforcing one slide per day.

Keep source links beside changing or consequential facts, with readable qualifications. Identify
historical or illustrative images and preserve their usage rights and attribution. Do not let a
polished layout hide tentative choices or imply that weather, seasonal viewing or admission is assured.
Keep the critical boarding/transfer instructions visible on the slides; speaker notes can add detail
but must not be the only place containing them. Make source links clickable in the exported file.
Use a simplified map suited to slide size rather than a screenshot of crowded interactive controls.
Check rendered pages for legibility, overflow and missing labels; reconcile dates, nights and
connections against the underlying plan before handing off the file.

## Interactive map

Use a suitable available map/web tool, or create a local HTML deliverable when supported. Hosting
is a separate action; do not publish or upload a private itinerary without a user request covering it.
Exclude reservation references, room numbers, contact details and other private booking data from
shareable files unless specifically requested and appropriate for the intended audience.

Provide a trip overview and city/area selection, then filters for hotels, attractions, restaurants
and transport reference points. Keep day trips distinct from overnight bases. Pair markers with
a readable place list; a detail card can show the native name, plan role, date/meal conditions,
address, source links and an external-map link. Keep text labels alongside colors and show useful
empty states. Cuisine or meal-role filters are optional, not a required taxonomy for every trip.

When a date control selects a day's view, update its itinerary and transport alongside its places;
do not leave another day's schedule beside the selected markers. Explain narrower place-only
filters. For overlapping markers, keep each place discoverable through grouping, selection or the
list without implying greater coordinate precision.

Use sourced coordinates, recording their provenance, precision and check date. A building or area
point is not necessarily its entrance. Keep locations without verified coordinates in the list
rather than inventing pins. Never turn straight-line distance into walking distance/time or draw
an inferred route as a navigable path. Label schematic connectors; use sourced routes for actual
walking/transit guidance and retain their date, mode and verification scope.

For custom maps, maintain place records once and derive views/exports from them. A lightweight
record can carry an ID, city/area, kind, name, plan role, relevant dates, sources and optional
coordinates with provenance. GeoJSON or KML may provide portable point exports when useful;
their availability does not imply compatibility with every map host or a routing capability.
Retain map-library, tile and coordinate-source attribution and applicable licenses.

Check the actual day/city/category controls, marker-to-list correspondence, links and coordinate
order for the chosen format. At a phone-sized viewport, check that details and controls remain
readable and reachable without clipped content. Size image derivatives for their displayed use,
preserving attribution; avoid shipping full-resolution originals merely as small thumbnails.
Open the packaged copy when checking companion-file links and assets, so development-only paths
do not mask broken delivery. Explain network requirements. If the basemap fails, keep place details
and external links usable; do not promise offline tiles or live navigation without implementing them.
