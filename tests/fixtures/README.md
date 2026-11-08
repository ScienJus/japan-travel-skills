# Regression fixture provenance

These are necessary structural excerpts or recorded responses from public pages/frontend APIs on 2026-10-29–30, not a full-site mirror or a promise that live data remains unchanged. Tests read this directory without network access or local research captures.

| Fixture | Source and purpose |
| --- | --- |
| `ebitei-detail*` | 海老亭別館 public English details: structured data, hours, and expected parsing |
| `ecoutieres-courses.html` | restaurant ecoutieres public `party/` course-page excerpts |
| `ecoutieres-members.json` | 2026-10-30 excerpt of `find_vacancy_member_by_date?rst_id=17013984&svd=20261201`: selectable sizes 1–4 use status 2; disabled sizes use 0 |
| `yumeri-review-cards.html` | 味楽 ゆめり public English review-card structure; nicknames/profiles/avatars/photos removed or anonymized and text replaced with synthetic content; public review links retained for identity parsing |
| `review-meal-links.html` | Actual meal navigation: lunch=1, dinner=2; independent parameter-mapping evidence |
| `catalog-*` | `/xml/list_area1`, `list_area2`, `list_stations`, and Kanazawa City navigation excerpts; parent validation, complete option reads, and pagination scope |
| `hyakumeiten-categories.json` | Observed `/web-api/v1/hyakumeiten-category-list` catalog, not a runtime constant |
| `hyakumeiten-*.xml` | Native filtered map responses around Kanazawa Station; coordinates/ratings/budgets retained, irrelevant reviewer/promotional/image fields removed |
| `*-calendar-2026-10-29.json` | Offline replay of two restaurants' calendar/slot history; screening matches the daily reference without creating reservations |

CSRF/form verification values, service API keys (including keys embedded in map URLs), login state, browser cookies, and local paths are not fixture data. Public restaurant names, addresses, phone numbers, IDs/URLs, and coordinates are retained for parsing verification, not as user profile data.
