# Travel-plan deliverables

Read this when the user wants a presentation, a map or another structured travel-plan handoff.
Choose the format that serves the request; a normal planning answer needs neither slides nor a map.
For a reusable local HTML/map template or a structured handoff to presentation tools, read
[shared plan records and generation](plan-data.md). The HTML helper uses Python's standard library;
presentation rendering uses the host's tools. Neither output requires hosting or publishing.

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

## Check content before styling

First determine whether the task is to build a plan and deliver it, or only to visualize supplied
content. For the first, apply [the planning loop's coverage guidance](planning-loop.md) before
authoring; for the second, retain the supplied choices and disclose material gaps without silently
expanding the research scope. A new output format does not make an incomplete plan complete.

Make a compact content outline against the brief, using actual place/choice IDs when structured
records are used. For each city, connect its relevant sights, lodging/base and food to the daily
plan. Food coverage should explain the local experience and useful venue choices, not merely include
a restaurant marker. Show why candidates fit and retain consequential conditions. Omit categories
the brief excludes; a day-trip city does not need an overnight property or a dedicated slide for
every category. This outline is an authoring aid, not another required user-facing report.

If a material section contains only placeholders, return to targeted research when authorized.
If the source fails or the user has asked to defer a choice, retain a specific unresolved decision and
state the delivery's limited scope. Do not invent choices or require live inventory to provide
useful candidates. Only then choose layouts and imagery. Data validation and rendered-page checks
cannot establish content adequacy; a hand-enriched demo cannot establish improved skill behavior.

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

Choose the structure for the audience and the plan's maturity, following the user's requested format:

| Purpose | Useful structure |
| --- | --- |
| Explore and compare | Trip overview, city/area introductions, sights, local food, lodging options and decisions still to make. Keep alternatives distinct from the proposed itinerary. |
| Guide travel companions through an agreed plan | Trip overview, then city chapters beginning with the relevant hotel/base, followed by daily route overviews and sights, activities and meals in visiting order. Split a cross-city day at the city handoff; a day-trip city needs no hotel page. |

These structures can be combined. Use real place/property/dish photographs to explain the experience.
For sights, pair an introduction to the place, its cultural/historical context and concrete highlights
with practical visit advice. A duration and access note alone do not introduce a destination.
For meals, show how shortlisted choices fit the day's location, appetite and timing; retain existing
cuisine/rating evidence and its date without making a rating the sole selection rule.

Keep daily overviews readable through morning, lunch, afternoon and evening blocks. Exact appointment
times, last admission and critical boarding/transfer instructions remain visible where needed;
detailed timetable comparisons can go on transport pages or in an appendix. Show conditional choices
and their triggers, such as weather, queues or energy, rather than presenting every candidate as a visit.
Use route maps to check backtracking and meal/access connections. If a map exposes a planning problem,
return to the plan before changing the illustrated route; depiction alone does not verify feasibility.

The on-demand [presentation brief](../assets/presentation.md) supplies page patterns, route-map design
and the asset-provenance workflow. Inspect a supplied reference deck before choosing the design.
Split dense pages; neither slide counts nor numbers of restaurant candidates are fixed quotas.

Keep source links beside changing or consequential facts, with readable qualifications. Identify
historical or illustrative images and preserve their usage rights and attribution. Do not let a
polished layout hide tentative choices or imply that weather, seasonal viewing or admission is assured.
Official publication alone does not grant image reuse permission. Keep media source/creator/license
records alongside the output, and distinguish a licensed third-party illustration from official
travel evidence. Do not invent a hotel or restaurant to complete a page; label area or cuisine
references and preserve the unselected choice. Keep downloaded photos and personal reference decks
outside the public checkout and release bundle.
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
