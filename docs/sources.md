# Source classification and selection

This project combines public institutions, responsible operators, commercial first-party products
and explicitly identified third-party helpers. It is not an all-government or all-operator data
feed. Source identity is separate from accuracy, freshness, geographic fit and usage permission.

| Class | Integrated sources and use | Boundary |
| --- | --- | --- |
| Public institutions | JMA forecasts, warnings and climate; Cabinet Office holidays; NAOJ daylight; GSI geocoding | Preserve each product's location, dates and meaning; official status does not extend its forecast horizon |
| Responsible operators and official tourism bodies | JR/IR reports and pass catalogs; municipal/prefectural tourism portals and linked facility operators | A tourism listing is discovery evidence, not proof of dated opening, admission or a particular train's operation |
| Commercial first-party products | Weathernews and JMC seasons/weather, AMECS Fuji index, Yahoo transit, Jalan hotels, Tabelog, TableCheck and Pocket Concierge | These are their publishers' own products or platform records, not government or independent facility verification; platform reviews remain user opinions |
| Community data | Photon geocoding using OpenStreetMap | Explicit `--provider photon` only; retain attribution and candidate ambiguity; never call it official or entrance-accurate |
| Third-party local calculations | `jpholiday` in Tabelog's regular-hours filter | Offline library rules, not a read of the Cabinet Office feed; temporary changes and actual opening remain unverified |

## Defaults and independent use

Tabelog `geocode` defaults to GSI, particularly for Japanese addresses. Photon is an explicit option
for name/address discovery when appropriate; choosing it does not certify a result. Neither an
empty result nor a failed read triggers automatic provider rotation. Check names, locality and
point type before using coordinates. Hotel coordinates continue to come from Jalan or explicitly
labelled caller input, not from an implicit geocoding fallback.

The holiday CLI reads the Cabinet Office CSV online. Tabelog's independent opening-hours checks
instead use the pinned `jpholiday` package so that the restaurant skill remains self-contained.
The output identifies this local calendar basis; use the holiday skill or official source when
the holiday itself is the decision being verified. A regular-hours match never confirms admission
or restaurant availability.

The relevant skill references are the maintained endpoint and field contracts. City guides identify
the responsible tourism bodies and their geographic scope. For an additional source, establish its
publisher and suitability before using it; do not promote a search snippet, unattributed repost or
an inaccessible page into verified evidence. Keep independently requested sources separate and
honor each one's stopping rules.

## Rights, stability and claims

Public frontend JSON and HTML are not contracted APIs. Schemas, access policies and availability
can change. Use bounded anonymous reads, retain original links and unknown states, and do not
bypass denial or import authenticated sessions. No integrated source grants project endorsement.

MIT covers project code and instructions. It does not relicense provider information, photos,
reviews or maps. Preserve applicable attribution, including OpenStreetMap's ODbL attribution.
AMECS's [use notice](https://www.amecs.co.jp/index.html#contact) restricts secondary use without
permission. Do not distribute copied feeds, forecasts, images or capture archives as open data;
assess the applicable source terms for any separately proposed reuse.

Validation claims must identify what ran: offline tests, a dated live read, installation checks
and agent output reviews are different evidence. A manually polished itinerary, map or PPTX is not
proof of improved skill behavior. Do not advertise a measured quality or token-cost advantage
without a completed, applicable comparison. Weathernews sakura forecasts still await in-season
live validation. Producing files and verifying their rendered/interactive behavior are separate checks.
