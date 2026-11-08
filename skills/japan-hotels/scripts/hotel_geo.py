"""Jalan map-point provenance and local straight-line radius filtering."""
from html import unescape
import math
import re
import urllib.parse as urls
import xml.etree.ElementTree as ET

import jalan as source

MAP_PATH = '/uw/uwp1700/uww1701.do'
PAGING_PATH = '/uw/uwp1700/uww1702.do'
EARTH_RADIUS_M = 6371008.8
MAP_PAGE_LIMIT = 30
MAX_MAP_PAGES = 2


def coordinates(lat, lon):
    if isinstance(lat, bool) or isinstance(lon, bool): source.fail('Invalid map coordinates.')
    try: lat, lon = float(lat), float(lon)
    except (ValueError, TypeError, OverflowError): source.fail('Invalid map coordinates.')
    if not math.isfinite(lat) or not math.isfinite(lon) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
        source.fail('Invalid map coordinates.')
    return {'latitude': lat, 'longitude': lon, 'coordinate_system': 'WGS84', 'units': 'decimal_degrees'}


def publisher_point(lat, lon):
    point = coordinates(lat, lon)
    if not 20 <= point['latitude'] <= 46 or not 122 <= point['longitude'] <= 154:
        source.fail('Jalan map point is outside supported domestic coordinates.')
    return point


def distance_m(first, second):
    lat1, lon1 = map(math.radians, [first['latitude'], first['longitude']])
    lat2, lon2 = map(math.radians, [second['latitude'], second['longitude']])
    a = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, max(0, a))))


def validate_options(args):
    fields = [args.center_lat, args.center_lon, args.center_name]
    if args.radius_m is None:
        if any(v is not None for v in fields): raise source.SourceError('invalid_options', 'Center options require --radius-m.')
        return None
    if not math.isfinite(args.radius_m) or not 1 <= args.radius_m <= 20000:
        raise source.SourceError('invalid_options', 'Use a finite --radius-m from 1 to 20000 metres; straight-line distance only.')
    if any(v is not None for v in fields):
        if any(v is None for v in fields) or not source.norm(args.center_name):
            raise source.SourceError('invalid_options', 'Supply --center-lat, --center-lon and --center-name together.')
        try: point = coordinates(args.center_lat, args.center_lon)
        except source.SourceError: raise source.SourceError('invalid_options', 'Center latitude/longitude must be valid finite coordinates.') from None
        if not 20 <= point['latitude'] <= 46 or not 122 <= point['longitude'] <= 154:
            raise source.SourceError('invalid_options', 'Custom center must be within the supported Japan coordinate bounds (20–46 N, 122–154 E).')
        return {**point, 'name_ja': args.center_name, 'kind': 'user_supplied_coordinates', 'source': None,
                'note': 'Caller-supplied point; the CLI does not verify that it identifies this place or an entrance.'}
    return None


def landmark_url(directory):
    m = re.fullmatch(source.DIRECTORY, urls.urlsplit(directory).path)
    if not m: raise source.SourceError('invalid_options', 'Unsupported landmark directory.')
    return source.HOME + '/kankou/spt_' + m[2] + '/'


def parse_landmark(raw, url, expected, prefecture=None):
    p = source.Page(raw)
    canonical = source.one((n.attrs.get('href') for n in p.root.nodes('link') if n.attrs.get('rel') == 'canonical'), 'Missing/duplicate landmark canonical URL.')
    if canonical != url: source.fail('Landmark canonical identity mismatch.')
    if prefecture is not None:
        codes = re.findall(r'"kenCd"\s*:\s*"([0-9]{6})"', p.html)
        if codes != [prefecture]: source.fail('Landmark prefecture does not match the directory URL.')
    node = source.one((n for n in p.root.nodes('div') if n.attrs.get('id') == 'detailMap-canvas'), 'Missing/duplicate landmark map point.')
    name = node.attrs.get('data-name', '')
    if source.norm(name) != source.norm(expected): raise source.SourceError('location_mismatch', 'Landmark map name does not match the requested location.', expected=expected, actual=name)
    point = publisher_point(node.attrs.get('data-lat'), node.attrs.get('data-lng'))
    return {**point, 'name_ja': name, 'kind': 'jalan_landmark_reference',
            'note': 'Publisher landmark map point, not a verified station exit, entrance or route endpoint.'}


def map_params(raw, directory, filters):
    p = source.Page(raw)
    form = source.one((n for n in p.root.nodes('form') if n.attrs.get('id') == 'jalan_form'), 'Missing native search form.')
    m = re.fullmatch(source.DIRECTORY, urls.urlsplit(directory).path)
    params = {'spotId': m[2], 'distCd': '10', 'kenCd': m[1], 'dateUndecided': '1', 'activeSort': '10'}
    for field in ('lrgCd', 'smlCd'):
        values = {n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name') == field}
        if len(values) != 1 or not re.fullmatch(r'[0-9]{6}', next(iter(values)) or ''):
            source.fail('Missing native map-region scope; map coordinates unavailable.')
        params[field] = next(iter(values))
    for key in filters: params[source.FILTERS[key][0]] = '1'
    return params


def map_url(params, paging=False):
    return source.HOME + (PAGING_PATH if paging else MAP_PATH) + '?' + urls.urlencode(params)


def integer(value, message):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,5}', value): source.fail(message)
    return int(value)


def decode_name(value):
    # Only native Unicode escapes, not evaluation of JavaScript or arbitrary codecs.
    value = re.sub(r'\\u([0-9a-fA-F]{4})', lambda m: chr(int(m[1], 16)), value)
    try: value.encode('utf-8')
    except UnicodeError: source.fail('Unsupported surrogate in native map name.')
    return value


def literal(value):
    escapes = {"'": "'", '"': '"', '\\': '\\', '/': '/', 'n': '\n', 'r': '\r', 't': '\t', 'b': '\b', 'f': '\f'}
    out, i = [], 0
    while i < len(value):
        if value[i] != '\\': out.append(value[i]); i += 1; continue
        if i+1 >= len(value): source.fail('Truncated native map name.')
        char = value[i+1]
        if char == 'u' and re.fullmatch(r'[0-9a-fA-F]{4}', value[i+2:i+6]):
            out.append(chr(int(value[i+2:i+6], 16))); i += 6
        elif char in escapes: out.append(escapes[char]); i += 2
        else: source.fail('Unsupported native map string escape.')
    result = ''.join(out)
    try: result.encode('utf-8')
    except UnicodeError: source.fail('Unsupported surrogate in native map name.')
    return result


def parse_map(raw, params):
    p = source.Page(raw)
    form = source.one((n for n in p.root.nodes('form') if n.attrs.get('name') == 'pagingForm'), 'Missing native map paging form.')
    for field, expected in params.items():
        actual = {n.attrs.get('value') for n in form.nodes('input') if n.attrs.get('name') == field}
        if actual != {expected}: source.fail('Map did not preserve directory context or filters.')
    for field in ('careBath', 'careStation5'):
        actual = {n.attrs.get('value', '') for n in form.nodes('input') if n.attrs.get('name') == field}
        if actual != {params.get(field, '')} and not (field not in params and not actual): source.fail('Unexpected native map filter.')
    script = source.one(re.findall(r'function initMap\(\)\s*\{([\s\S]*?)\n\s*function renderPageCtrl', p.html), 'Missing/duplicate native map initialization.')
    if 'Jmap.screenId = "UWW1701";' not in script: source.fail('Unsupported native map product.')
    def number(field):
        return integer(source.one(re.findall(r'Jmap\.' + field + r'\s*=\s*parseInt\(([0-9]+)\)', script), 'Missing native map counter.'), 'Invalid native map counter.')
    total, size, index = number('count'), number('pageLimit'), number('idx')
    if total > 9000 or size != MAP_PAGE_LIMIT or index != 0: source.fail('Unsupported native map pagination.')
    starts = list(re.finditer(r"name\s*=\s*'((?:\\.|[^'\\])*)';\s*id\s*=\s*'([0-9]{6})';\s*no\s*=\s*([0-9]+);", script))
    points = {}
    for i, m in enumerate(starts):
        block = script[m.end():starts[i+1].start() if i+1 < len(starts) else len(script)]
        match = source.one(re.findall(r'new Jmap\.MarkerData\(\s*([0-9.]+)\s*,\s*([0-9.]+)\s*,\s*id\s*,\s*name\s*,\s*content\s*,\s*"A"\s*\+\s*no\s*\)', block), 'Unsupported native hotel map point.')
        if m[2] in points or int(m[3]) != i+1: source.fail('Duplicate/reordered native map identity.')
        # The script name is inserted into popup HTML; decode that layer once,
        # after JavaScript escapes, to match the HTML card's visible full name.
        points[m[2]] = {'name_ja': unescape(literal(m[1])), **publisher_point(*match)}
    if len(points) != min(total, MAP_PAGE_LIMIT): source.fail('Native map point count disagrees with page count.')
    return points, total


def parse_map_page(raw, expected_total, index):
    if b'\x00' in raw: source.fail('NUL/UTF-16 XML is not supported.')
    if re.search(br'<!\s*(?:DOCTYPE|ENTITY)', raw, re.I): source.fail('XML declarations are not allowed in map data.')
    try: root = ET.fromstring(raw.decode('utf-8-sig'))  # nosec B314 -- UTF-8, NUL and DTD/entities checked; regression-tested.
    except (UnicodeError, ET.ParseError): source.fail('Invalid UTF-8 map paging XML.')
    if root.tag != 'searchResult' or root.get('count') != str(expected_total) or root.get('idx') != str(index) or root.get('pageLimit') != str(MAP_PAGE_LIMIT):
        source.fail('Map count or page changed between reads.')
    records = list(root.findall('./userDataArray/userData'))
    hotels = list(root.findall('./searchResultYadList/searchResultYad'))
    if len(records) != min(MAP_PAGE_LIMIT, max(0, expected_total-index)) or len(hotels) != len(records): source.fail('Incomplete native map paging records.')
    ids = [n.get('yadNo') for n in hotels]
    points = {}
    for n in records:
        hotel_id = n.get('id', '')
        if not re.fullmatch(r'[0-9]{6}', hotel_id) or hotel_id in points or n.get('type') != 'YAD': source.fail('Invalid native map hotel identity.')
        point = publisher_point(n.get('y'), n.get('x'))
        points[hotel_id] = {'name_ja': decode_name(n.get('name', '')), **point}
    if len(set(ids)) != len(ids) or set(ids) != set(points): source.fail('Map markers and native hotel records disagree.')
    for n in hotels:
        point = points[n.get('yadNo')]
        if source.norm(decode_name(n.get('yadName', ''))) != source.norm(point['name_ja']) or publisher_point(n.get('y'), n.get('x')) != {k: point[k] for k in ('latitude', 'longitude', 'coordinate_system', 'units')}:
            source.fail('Map marker and property coordinate/name mismatch.')
    return points


def apply_radius(result, points, center, radius, lookup):
    matched, unknown, outside = [], [], []
    for rank, hotel in enumerate(result['hotels'], (result['page']-1)*30+1):
        hotel['source_rank'] = rank
        point = points.get(hotel['hotel_id'])
        if point is None or source.norm(point['name_ja']) != source.norm(hotel['name_ja']):
            hotel['distance'] = {'kind': 'straight_line', 'state': 'unknown', 'metres': None,
                                 'reason': 'missing_point' if point is None else 'map_name_mismatch'}
            unknown.append(hotel)
            continue
        value = distance_m(center, point)
        hotel['coordinates'] = point
        hotel['distance'] = {'kind': 'straight_line', 'state': 'calculated', 'metres': round(value, 1),
                             'within_radius': value <= radius, 'near_boundary': abs(value-radius) <= 50}
        (matched if value <= radius else outside).append(hotel)
    result['hotels'] = matched
    result['distance_unknown_hotels'] = unknown
    result['radius_filter'] = {'kind': 'straight_line', 'radius_m': radius, 'center': center,
                             'method': 'Haversine', 'earth_radius_m': EARTH_RADIUS_M,
                             'membership_uses_unrounded_distance': True, 'boundary_flag_tolerance_m': 50,
                             'matched_on_page': len(matched), 'outside_on_page': len(outside), 'unknown_on_page': len(unknown),
                             'coordinate_lookup': lookup,
                             'note': 'Approximate distance between publisher/caller map points, not walking/driving distance or entrance-to-entrance accuracy. The 50 m boundary flag is a review aid, not an error bound.'}
    result['coverage'] = 'Radius applied only to this directory page; source total and pagination remain unfiltered. Missing map points are unknown, never outside.'
    return bool(unknown or lookup['errors'])


def augment(client, args, raw, result, filters, center):
    if center is None:
        url = landmark_url(args.directory)
        raw_center, meta = client.read(url)
        center = parse_landmark(raw_center, url, args.expect)
        center['source'] = meta
    points, total = {}, None
    lookup = {'sources': [], 'map_page_limit': MAX_MAP_PAGES, 'publisher_map_total': None, 'errors': []}
    try:
        params = map_params(raw, args.directory, filters)
        raw_map, meta = client.read(map_url(params))
        lookup['sources'].append(meta)
        points, total = parse_map(raw_map, params)
        for p in points.values(): p['source'] = meta
        if total > MAP_PAGE_LIMIT:
            raw_page, meta = client.read(map_url({**params, 'idx': '30'}, paging=True))
            lookup['sources'].append(meta)
            more = parse_map_page(raw_page, total, 30)
            if set(points) & set(more): source.fail('Map paging repeated hotel IDs.')
            for p in more.values(): p['source'] = meta
            points.update(more)
    except source.SourceError as error:
        lookup['errors'].append({'code': error.code, 'message': str(error), 'source': client.last_source, **error.details})
    lookup.update(publisher_map_total=total, mapped_hotel_count=len(points),
                  publisher_map_truncated=total is not None and total > MAX_MAP_PAGES*MAP_PAGE_LIMIT)
    return apply_radius(result, points, center, args.radius_m, lookup)
