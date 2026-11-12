# Shared records for visual handoffs

Read this only when a requested HTML/map or presentation needs structured plan records. Ordinary
planning and reviews do not require JSON, this reference or the assets. See
[deliverables](deliverables.md) for research, content and verification requirements.

## Generate a local guide

Resolve `<skill-dir>` from the installed skill catalog. Python 3.9+ standard library is sufficient;
no server, pip package, account, API key or browser automation is required by the helper.

```bash
python3 "<skill-dir>/scripts/render_plan.py" \
  --input /absolute/path/to/plan.json --output /absolute/path/outside-the-checkout/guide.html
python3 "<skill-dir>/scripts/render_plan.py" --format brief \
  --input /absolute/path/to/plan.json --output /absolute/path/outside-the-checkout/presentation.md
```

Use new output paths; existing files are never overwritten. Generated files must stay outside the
source checkout and installed skill. The helper validates records before writing and makes no
network requests. Its generic CLI errors do not echo supplied values or filesystem paths.
It validates structure and relationships, not content coverage, actual service operation, opening
times or privacy. Successful generation is not acceptance of the itinerary or its recommendations;
complete the delivery guide's content check before using the records as an authoring handoff.
Review free-text fields and source URLs for sensitive content before generating or sharing. The
HTML and JSON download contain the complete plan; visual filters do not remove or redact records.

The HTML is a single file with embedded styles, code and plan records. Date selection synchronizes
daily visits and connections. City/category filters affect only places and the map. The list
retains places without sourced coordinates; shared coordinates remain individually selectable
in the list. The default map is a coordinate-based location view, not road routing or navigation.
Selecting a place recenters it; zoom and fit controls change the visible area.

Opening the guide automatically loads live GSI pale-map image tiles at zoom
9–16 from `cyberjapandata.gsi.go.jp`. Broader views retain the offline location plot; choose a city
or zoom in for a basemap. The source receives the visible tile area and network metadata, not
the plan JSON. **Hide basemap** stops new tile requests; requests already started may finish.
A failed image stops basemap loading without automatic retry; the location plot, list and links
remain usable. No tile caching, prefetching, geocoding or route service is bundled. Retain the
[GSI attribution and tile-use guidance](https://maps.gsi.go.jp/development/ichiran.html).
External source links and user-downloaded JSON are separate from the basemap.

## Data contract

Use [the public demo](../examples/kyoto-nara-demo.json) as a data-format example, not a researched
answer to another trip or proof that an agent follows the planning workflow. All listed
top-level fields are required; unsupported fields are rejected to reduce accidental inclusion
of account or booking records. Limits are 2 MiB, 60 days, 50 cities, 200 places and 500 connections.
Free text is limited to 2,000 characters per field; names/labels should remain concise for display.

| Field | Content |
| --- | --- |
| `schema_version` | Integer `1`; a data-format marker, separate from plugin version. |
| `title`, `language`, `revision` | Title, UI language (`en`, `zh-CN`, or `ja`) and exact plan snapshot label. Never use a local path as a revision. |
| `demo`, `notice` | Boolean demo flag and a visible scope/uncertainty notice. A demo must disclose fictional planning data. |
| `cities` | `{id, name, summary}`. Include day-trip cities; overnight counts derive from days, not city membership. |
| `places` | `{id, city_id, kind, name, role, evidence, notes, sources, coordinates?}`. Kind is `hotel`, `attraction`, `restaurant` or `transport`. |
| `days` | `{id, date, title, city_ids, base_city_id, base_place_id, summary, visits, leg_ids}`. Dates are distinct, increasing `YYYY-MM-DD` in Japan time. Use null for no overnight base or no specified property. A proposed base may reference a candidate hotel; its role and evidence remain visible and do not establish a booking. |
| `days[].visits` | `{place_id, time, notes}` in intended order. Times are source times or explicitly labelled estimates; free text does not certify chronology. |
| `legs` | `{id, day_id, from_place_id, to_place_id, mode, time, role, evidence, notes, sources}`. Both endpoints must exist in that day's cities; each connection belongs to exactly one day. |
| `open_questions` | List of unresolved decisions or material checks, carried into every handoff. |

Identifiers use letters, digits, underscores and hyphens (at most 64 characters). A base property
must be a hotel in the overnight city. Each day must list its connections and all visit/endpoints
must resolve. Duplicate IDs, unknown references, mismatched days and extra fields are rejected.
The helper does not optimize a route or certify time allowances; review feasibility first.

Keep `role` (`fixed`, `selected`, `candidate`, `backup`) separate from `evidence` (`verified`,
`unverified`, `illustrative`). Verified records require sources but may cover only specific facts.
`sources` is a list of `{title, url, checked_on?, scope?}`; use HTTPS without credentials.
Record publisher/query dates and consequential conditions in `notes`/`scope`, rather than treating
a retrieved URL as proof that every property detail or proposed visit date has been checked.

Optional `coordinates` are `{lat, lon, source_url, checked_on, precision}`. Use finite numeric
latitude/longitude in that named order and a source-specific precision description. Omit or use
null when unknown. Latitude is bounded to ±85 for Web Mercator; longitude to ±180. A sourced point
does not establish an entrance or walking time. Do not copy coordinates from the illustrative
example into an unrelated trip.

## Presentation handoff

Generate `--format brief` from the same JSON used for HTML. It combines the lightweight
[presentation layout brief](../assets/presentation.md) with complete records, including sources
and conditions. Give it to the host's available presentation-authoring skill/tool to create the
requested deck. The brief is not a PPTX; the travel plugin installs no slide-rendering dependency.
The brief includes illustrated page patterns and a media-provenance workflow. Keep its image
storyboard/asset list beside the output, separate from this schema. These rendering annotations
do not change visits or source-verification status; new travel facts or choices require a plan
update. The HTML helper does not load these photographs or make automatic image requests.
Inspect the actual export and rendered slides under [deliverables](deliverables.md). A subsequent
change requires regenerating affected outputs from the current records; mark older files as stale
when they cannot be updated. Keep the JSON snapshot with the user's files for later revisions.
