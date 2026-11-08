# Recent reviews

Use a confirmed restaurant ID/URL and explicit visit-date window. The CLI filters by **visit date**, not publication date. A missing publication date cannot establish that a review was recently published.

“The last month” defaults to one calendar month before today through query time; “the last 30 days” is a 30-day window. Interpret dates in Asia/Tokyo and state the exact cutoff. Preserve month-only precision rather than inventing a day.

## Retrieval

- `reviews` reads visit-sorted list excerpts; `--full` expands selected records. Defaults are 2 pages and at most 20 reviews. `review-read` reads one full review with all visits.
- `--meal all|lunch|dinner` filters meal evidence; default is all. The CLI sends `use_type=0|1|2` and verifies returned icons. Missing meal icons are unknown, not proof of a match.
- With `--full`, each visit has its own meal and date window. `visits` retains matching-meal passages; `unverified_visits` retains unknown meals. A list icon does not label every visit in a full review.
- Keep `in_window`, `boundary_uncertain`, `undated`, and future-anomaly classifications. A partially overlapping month cannot count as strictly within the window. Full reviews can include old visits; use each passage's window.
- Deduplicate by review ID/URL and distinguish repeat visits. Do not include the author's other restaurants or count list/detail copies twice. Page caps and unavailable data limit coverage.

## Reporting

State the date basis, window, sample size, date precision, and excerpt/full-text coverage. Summarize observed food, service, price, and booking themes without copying full reviews. Retain qualifications and negative evidence; label older context separately.

Rating-only records do not support claims about food/service. Sample averages are not the restaurant's overall score, and small samples do not establish trends or satisfaction percentages. Reviewer spending and booking experiences are not current official prices or reservation policies. If recent evidence is insufficient, say so rather than extending the window.
