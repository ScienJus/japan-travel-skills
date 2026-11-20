# Published sources and coverage

Hot Pepper Gourmet is Recruit's commercial restaurant platform. Profiles and course information are platform listings. Publication does not independently establish current opening hours, final charges or seat availability. Compare the exact branch and report discrepancies where relevant. [Hot Pepper Gourmet](https://www.hotpepper.jp/)

| Command | Accepted input | What the result covers |
| --- | --- | --- |
| `list` | The national index (`/`), a published area path beginning with `/SA…/` or its canonical HTTPS URL. Prefecture, large area, subarea and optional `G…` genre directories are supported. | The national and wider area pages may list child areas. Follow their URLs. On a shop listing, coverage is the first page only. Optional `--match` filters published names on this page. Exact duplicate shop URLs count once, using their first position. Limit 1–20, default 5. The source may promote restaurants. Distances and walking times are publisher descriptions. |
| `detail` | A shop ID (J and nine digits) or its canonical `https://www.hotpepper.jp/strJ…/` URL. | Published profile fields with Japanese source labels. Missing values stay null. Lunch and dinner budget ranges are distinct from a course quote. |
| `detail --date` | Same shop plus a calendar date in Japan. | Matches the exact month and day on the profile and reads the page legend. The site distinguishes immediate booking, request booking, telephone inquiry, unavailable and closed days. A missing date, missing legend or conflicting marker stays unknown. |
| `courses` | Same shop, optionally `--limit 1..20`. | Listed course links and price strings, published party/dish counts and booking deadlines when present. Course eligibility alone does not verify availability. An unreadable course listing stays unknown. |
| `slots` | Shop, a published `--course` ID, `--date`, `--time HH:MM` and `--people`. | The single-date course detail widget's anonymous seat lookup. Each available option links back to the requested shop, course, date, party and start. An explicit empty result applies only to that combination. A mismatched response, missing evidence or unexpected layout returns an error. |

For discovery, get the native URL from the provider or web search. Check the heading, e.g. [金沢駅](https://www.hotpepper.jp/SA63/Y841/X841/). The CLI accepts canonical paths without tracking parameters. Indexed snippets can be stale. Verify short-listed shops with a direct profile read.

The CLI makes one anonymous HTTPS GET per online command with a 15-second socket timeout and a 2 MiB body limit. It rejects redirects and validates the canonical URL of each full page. For the seat widget it validates the returned conditions and seat links. It reads a single stock fragment and never opens a reservation action. JSON includes request count, response bytes and elapsed time. Source failures produce a nonzero exit and a structured error. Limit repeated queries to the user's shortlist. Keep downloaded pages outside the repository.

Recruit also publishes a keyed Web Service API. This skill uses public web pages. Respect the publisher's terms and any access restrictions. [Web Service documentation](https://webservice.recruit.co.jp/doc/hotpepper/reference.html) · [Hot Pepper Gourmet terms](https://cdn.p.recruit.co.jp/terms/hpg-t-1002/index.html)
