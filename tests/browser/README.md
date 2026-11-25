# Optional visual-guide browser checks

Generate paired map and daily HTML files with reciprocal `--peer` filenames from the planner's public `kyoto-nara-demo.json`, then run the headless check below.
It uses a fresh browser profile, blocks external requests and saves screenshots/downloads outside
the checkout. It does not inspect a desktop browser or use personal profiles. The basemap-failure
and automatic-basemap checks are mocked; a passing result does not establish upstream availability or itinerary feasibility.

Use a development Node environment with Playwright (locally checked with 1.62.1) and its installed
Chromium, or supply an existing Chrome executable via `--browser /absolute/path/to/chrome`.
These are optional development dependencies, not installed-skill requirements or automatic CI.

```bash
node tests/browser/check_guide.cjs \
  --html /absolute/path/outside-the-checkout/guide.html \
  --daily /absolute/path/outside-the-checkout/daily.html \
  --output /absolute/path/outside-the-checkout/browser-check
```

For Playwright installed outside this repository, expose its `node_modules` through `NODE_PATH`.
The check covers day/transport synchronization, list/map filtering (including IDs named `all`),
candidate-hotel labels, unknown coordinates, JSON round-trip, automatic tile loading, hiding the basemap, bounded failed tile loading without
retries, and 390/320-pixel layouts. With `--daily` it also checks offline day order, stable map numbering and a cross-city round trip between the two files. Review the
screenshots as well. Use the public demo; do not put private itineraries in shared QA artifacts.
