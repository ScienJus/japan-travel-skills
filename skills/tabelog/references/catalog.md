# Area and station catalogs

Use catalogs to enumerate available options; keyword suggestions are not complete directories.

| Command | Source | Scope |
| --- | --- | --- |
| `areas` | Built-in stable prefecture-code directory; no request | All 47 prefectures, codes 1–47 |
| `areas --prefecture 17` | `/xml/list_area1?type=search&pcd=17` | Search regions such as `A1701` |
| `areas --parent A1701` | `/xml/list_area2?type=search&area1=A1701` | Search subareas such as `A170101` |
| `stations --area A170101` | `/xml/list_stations?type=search&area2=A170101` | Stations within that search scope |
| `areas --city 金沢市` | Suggestions plus municipal navigation | Listed municipal neighborhoods |

Prefectures accept codes 1–47 or names. The three `areas` scope options are optional and mutually exclusive. Omitting them returns prefectures without fetching subareas. `stations` requires an Area2 ID; municipal `C` codes are not supported station scopes.

XML catalogs have no pagination; the CLI reads all valid options and omits the all/zero option. `coverage=all_entries_in_response` describes that response, not an administrative census. Malformed or empty catalogs remain unknown rather than proof that no options exist.

Municipal neighborhoods come from same-city navigation links, without opening each neighborhood page. Preserve the returned municipal ID separately from suggestion IDs. Neighborhoods without listed restaurants may be absent.

Tabelog search areas can cross city boundaries. Do not describe `stations --area` as all stations physically within a municipality; `stations --city` is unsupported. Keep `relation`, `administrative_completeness`, and coverage when explaining scope.
