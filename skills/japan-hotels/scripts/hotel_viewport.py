"""Buffered native map candidates, followed by local straight-line filtering."""
import math
import re
import urllib.parse as urls
import xml.etree.ElementTree as ET

import hotel_geo as geo
import jalan as source

# Conservative sizing policy, not a publisher guarantee of the server's bounds.
# Deliberately smaller than the sampled native search extent at zoom 14.
HALF_LATITUDE_AT_Z14 = .0135
HALF_LONGITUDE_AT_Z14 = .027
MIN_ZOOM = 11
MAX_ZOOM = 20


def plan(center, radius):
    buffered = radius + min(.5 * radius, 1000)
    angle = buffered / geo.EARTH_RADIUS_M
    latitude_span = math.degrees(angle)
    longitude_span = math.degrees(math.asin(math.sin(angle) / math.cos(math.radians(center['latitude']))))
    scale = min(HALF_LATITUDE_AT_Z14 / latitude_span, HALF_LONGITUDE_AT_Z14 / longitude_span)
    zoom = min(MAX_ZOOM, math.floor(14 + math.log2(scale)))
    return {'policy': 'r + min(0.5*r, 1000 m)', 'radius_m': buffered,
            'extra_m': buffered - radius, 'zoom': zoom, 'supported': zoom >= MIN_ZOOM,
            'coverage_guaranteed': False,
            'note': 'Conservative viewport sizing policy; native search bounds are provider-defined, not a contracted circular radius.'}


def params(directory, filters, center, zoom):
    match = re.fullmatch(source.DIRECTORY, urls.urlsplit(directory).path)
    if not match: raise source.SourceError('invalid_options', 'Unsupported landmark directory.')
    result = {'spotId': match[2], 'kenCd': match[1], 'distCd': '10',
              'dateUndecided': '1', 'activeSort': '10', 'genreTypeYad': '1', 'reShFlg': '1',
              'centerPosX': str(center['longitude']), 'centerPosY': str(center['latitude']),
              'zoomLevel': str(zoom), 'resetZoomLevel': str(zoom)}
    for key in filters: result[source.FILTERS[key][0]] = '1'
    return result


def hotel(hotel_id, name, introduction, filters):
    return {'hotel_id': hotel_id, 'name_ja': name, 'url': source.hotel_url(hotel_id),
            'introduction_ja': introduction, 'access_ja': None,
            'walking_review': source.walking_review(None, filters),
            'operating_status': source.opening_notice(name, introduction, source.now_jst().date())}


def parse_first(raw, expected, filters):
    points, total = geo.parse_map(raw, expected)
    page = source.Page(raw)
    form = source.one((n for n in page.root.nodes('form') if n.attrs.get('name') == 'pagingForm'), 'Missing native viewport form.')
    for field in ('genreTypeSpot', 'genreTypeEvent'):
        values = {n.attrs.get('value', '') for n in form.nodes('input') if n.attrs.get('name') == field}
        if values - {''}: source.fail('Native viewport unexpectedly includes non-hotel results.')
    for node in form.nodes('input'):
        field = node.attrs.get('name', '')
        if field.startswith('care') and field not in expected and node.attrs.get('value', ''):
            source.fail('Native viewport applied an unrequested facility filter.')
    if 'Jmap.reShFlg = "1";' not in page.html: source.fail('Native map did not use viewport re-search.')
    initialized = source.one(re.findall(r'Jmap\.initialize1\(\s*([0-9.]+),\s*([0-9.]+),\s*([0-9]+)\s*\)', page.html), 'Missing native viewport center/zoom.')
    if (float(initialized[0]) != float(expected['centerPosX']) or float(initialized[1]) != float(expected['centerPosY'])
            or initialized[2] != expected['zoomLevel']): source.fail('Native viewport center/zoom changed.')
    cards = []
    nodes = [n for n in page.root.nodes('div', 'pack') if re.fullmatch(r'listresult-[0-9]+', n.attrs.get('id', ''))]
    for index, node in enumerate(nodes, 1):
        if node.attrs['id'] != 'listresult-' + str(index): source.fail('Native map card order changed.')
        heading = source.one(node.nodes('p', 'name'), 'Missing/duplicate native map hotel name.')
        link = source.one(heading.nodes('a'), 'Missing native map hotel identity.')
        match = re.fullmatch(r"javascript:openYadoSyosai\('([0-9]{6})'\)", link.attrs.get('href', ''))
        if not match or match[1] in {h['hotel_id'] for h in cards}: source.fail('Invalid/duplicate native map hotel ID.')
        name = source.text(link.text())
        if not name: source.fail('Empty native map hotel name.')
        point = points.get(match[1])
        if point is None or source.norm(name) != source.norm(point['name_ja']): source.fail('Native map card and marker identity disagree.')
        cards.append(hotel(match[1], name, source.class_text(node, 'exp'), filters))
    if len(cards) != len(points) or {h['hotel_id'] for h in cards} != set(points): source.fail('Native map cards and markers disagree.')
    return cards, points, total


def parse_page(raw, total, page_number, zoom, filters):
    points = geo.parse_map_page(raw, total, (page_number - 1) * 30)
    root = ET.fromstring(raw.decode('utf-8-sig'))  # nosec B314 -- geo.parse_map_page already rejects NUL/DTD/entities and invalid UTF-8.
    if root.get('zoomLevel') != str(zoom): source.fail('Map zoom changed between pages.')
    cards = []
    for node in root.findall('./searchResultYadList/searchResultYad'):
        name = geo.decode_name(node.get('yadName', ''))
        if not source.norm(name): source.fail('Empty native map hotel name.')
        introduction = source.text(geo.decode_name(node.get('yadCopy', ''))) or None
        cards.append(hotel(node.get('yadNo'), name, introduction, filters))
    return cards, points


def query(client, args, filters, custom_center):
    url = geo.landmark_url(args.directory)
    raw, landmark_source = client.read(url)
    prefecture = re.fullmatch(source.DIRECTORY, urls.urlsplit(args.directory).path)[1]
    landmark = geo.parse_landmark(raw, url, args.expect, prefecture=prefecture)
    landmark['source'] = landmark_source
    center = custom_center if custom_center is not None else landmark
    prefilter = plan(center, args.radius_m)
    if not prefilter['supported']:
        # Native re-search does not support the wider zoom; never interpret its
        # empty response as an empty area. Retain the bounded region-map path.
        raw, meta = client.read(source.directory_url(args.directory, args.page, filters))
        result = source.parse_search(raw, args.directory, args.expect, args.page, filters, source.now_jst().date())
        partial = geo.augment(client, args, raw, result, filters, center)
        result['radius_filter']['prefilter'] = {**prefilter, 'mode': 'regional_coordinate_lookup', 'reason': 'native_zoom_unsupported'}
        return result, meta, partial
    fields = params(args.directory, filters, center, prefilter['zoom'])
    raw, first_meta = client.read(geo.map_url(fields))
    cards, points, total = parse_first(raw, fields, filters)
    meta = first_meta
    if args.page > 1:
        if (args.page - 1) * 30 >= total:
            raise source.SourceError('page_out_of_range', 'Requested native viewport page is outside the published results.', source_total=total)
        paging = {**fields, 'screenId': 'UWW1701', 'idx': '0', 'nowPage': str(args.page), 'searchResultYadCount': str(total)}
        raw, meta = client.read(geo.map_url(paging, paging=True))
        cards, points = parse_page(raw, total, args.page, prefilter['zoom'], filters)
    for point in points.values(): point['source'] = meta
    result = {'landmark_ja': landmark['name_ja'], 'directory_url': args.directory,
              'source_total': total, 'source_total_scope': 'buffered_map_viewport', 'page': args.page,
              'page_size': 30, 'source_cards_on_page': len(cards), 'hotels': cards,
              'selected_filters': [source.FILTERS[k][1] for k in sorted(filters)],
              'has_next_page': args.page * 30 < total, 'candidate_source': 'jalan_native_viewport',
              'landmark_source': landmark_source}
    incomplete = args.page > 1 or result['has_next_page']
    lookup = {'sources': [meta], 'publisher_map_total': total, 'mapped_hotel_count': len(points),
              'publisher_map_truncated': incomplete, 'errors': []}
    partial = geo.apply_radius(result, points, center, args.radius_m, lookup)
    result['radius_filter']['prefilter'] = {**prefilter, 'mode': 'native_viewport_candidates'}
    result['coverage'] = 'One buffered native viewport candidate page, then local straight-line filtering. Source total/pagination refer to the viewport, not all hotels in the radius. No exhaustive geographic coverage is claimed.'
    return result, meta, partial or incomplete
