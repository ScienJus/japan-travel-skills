"""Small forward-geocoding adapter; candidates remain separate from restaurant search."""
from urllib.parse import urlencode

from .core import CliError, point_value


def parse_locations(raw, provider, source, limit):
    if provider == 'photon':
        if not isinstance(raw, dict) or raw.get('type') != 'FeatureCollection' or not isinstance(raw.get('features'), list):
            raise CliError('unexpected_response', 'Expected Photon GeoJSON FeatureCollection.')
        features = raw['features']
    else:
        if not isinstance(raw, list):
            raise CliError('unexpected_response', 'Expected GSI geographic features.')
        features = raw
    items, seen, invalid, outside = [], set(), 0, 0
    for feature in features:
        if not isinstance(feature, dict) or not isinstance(feature.get('properties'), dict) or not isinstance(feature.get('geometry'), dict):
            invalid += 1
            continue
        p, g = feature['properties'], feature['geometry']
        coords = g.get('coordinates')
        if g.get('type') != 'Point' or not isinstance(coords, list) or len(coords) != 2:
            invalid += 1
            continue
        try:
            point = point_value([coords[1], coords[0]])
        except CliError:
            invalid += 1
            continue
        if provider == 'photon' and str(p.get('countrycode', '')).upper() != 'JP':
            outside += 1
            continue
        name = p.get('name') if provider == 'photon' else p.get('title')
        if not isinstance(name, str) or not name.strip():
            # A numbered address can legitimately lack an OSM name.
            name = ' '.join(str(p[k]) for k in ('city', 'district', 'street', 'housenumber') if p.get(k)) if provider == 'photon' else None
        if not name:
            invalid += 1
            continue
        ident = f"{p.get('osm_type')}:{p.get('osm_id')}" if provider == 'photon' and p.get('osm_id') is not None else None
        key = (ident, name, point['latitude'], point['longitude'])
        if key in seen:
            continue
        seen.add(key)
        address = {k: p[k] for k in ('country', 'countrycode', 'state', 'county', 'city', 'district', 'postcode', 'street', 'housenumber') if p.get(k)}
        items.append({'name': name, **point, 'near': f"{point['latitude']},{point['longitude']}",
                      'address': address, 'provider_id': ident, 'location_type': p.get('type') or p.get('osm_value'),
                      'osm_tag': {k: p[k] for k in ('osm_key', 'osm_value') if p.get(k)},
                      'coordinate_source': source, 'coordinate_reference_system': 'WGS84',
                      'precision': 'provider_representative_point; entrance/rooftop accuracy not verified'})
    if invalid and not items:
        raise CliError('unexpected_response', 'No usable named location points; response cannot establish an empty result.')
    return {'items': items[:limit], 'provider': provider, 'country': 'JP', 'source_url': source,
            'attribution': '© OpenStreetMap contributors (ODbL)' if provider == 'photon' else '国土地理院 地名・住所検索',
            'attribution_url': 'https://www.openstreetmap.org/copyright' if provider == 'photon' else 'https://maps.gsi.go.jp/',
            'invalid_records': invalid, 'outside_japan_records': outside,
            'selection': 'Choose a candidate by its name, address and type; the first hit is not automatically verified.',
            'coverage': 'partial' if invalid else 'returned_candidates',
            'warning': 'Results can be incomplete or ambiguous; area points may be centroids. Not walking distance or device location.'}


def geocode(client, query, provider='gsi', limit=5):
    if not isinstance(query, str) or not query.strip() or len(query) > 500:
        raise CliError('invalid_argument', 'Provide a nonempty place name/address of at most 500 characters.')
    if provider not in ('photon', 'gsi'):
        raise CliError('invalid_argument', '--provider must be photon or gsi.')
    if provider == 'photon':
        url = 'https://photon.komoot.io/api/?'+urlencode({'q': query.strip(), 'countrycode': 'JP', 'limit': limit})
    else:
        url = 'https://msearch.gsi.go.jp/address-search/AddressSearch?'+urlencode({'q': query.strip()})
    data = client.read(url, 'json', lambda raw, final: parse_locations(raw, provider, final, limit))
    return {**data, 'query': query.strip()}
