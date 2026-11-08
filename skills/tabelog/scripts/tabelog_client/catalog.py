"""Bounded Tabelog search-area/station catalogs and municipal neighborhood lists."""
import re
import xml.etree.ElementTree as ET
from urllib.parse import urlsplit, urljoin

from .core import BASE, CliError, endpoint
from .parsers import soup, text_of


CATALOGS = {
    'area1': ('/xml/list_area1', 'pcd', r'A\d{4}', 'search_region'),
    'area2': ('/xml/list_area2', 'area1', r'A\d{6}', 'search_area'),
    'station': ('/xml/list_stations', 'area2', r'\d+', 'station'),
}

# Stable prefecture codes 1–47, also used by the Tabelog area catalog.
PREFECTURES = (
    '北海道', '青森県', '岩手県', '宮城県', '秋田県', '山形県', '福島県',
    '茨城県', '栃木県', '群馬県', '埼玉県', '千葉県', '東京都', '神奈川県',
    '新潟県', '富山県', '石川県', '福井県', '山梨県', '長野県', '岐阜県',
    '静岡県', '愛知県', '三重県', '滋賀県', '京都府', '大阪府', '兵庫県',
    '奈良県', '和歌山県', '鳥取県', '島根県', '岡山県', '広島県', '山口県',
    '徳島県', '香川県', '愛媛県', '高知県', '福岡県', '佐賀県', '長崎県',
    '熊本県', '大分県', '宮崎県', '鹿児島県', '沖縄県',
)


def parse_catalog(body, level, parent, source):
    """Read every option in the response, excluding the explicit all/zero option."""
    if '\x00' in body or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b', body, re.I):
        raise CliError('unexpected_response', 'DTD/entities are not accepted in catalog XML.')
    try:
        root = ET.fromstring(body)  # nosec B314 -- NUL and DTD/entities rejected above; regression-tested.
    except ET.ParseError:
        raise CliError('unexpected_response', 'Expected catalog XML.') from None
    if root.tag != 'items' or any(n.tag != 'item' for n in root):
        raise CliError('unexpected_response', 'Expected an items catalog, not restaurant data or an access page.')
    pattern, kind = CATALOGS[level][2:]
    entries = {}
    for node in root:
        ident, name = node.get('optval', ''), node.get('name', '').strip()
        if ident == '0':
            continue
        if not name or not re.fullmatch(pattern, ident):
            raise CliError('unexpected_response', 'Catalog entry has a missing name or unexpected identifier.')
        if level == 'area1' and ident[1:3] != parent['id'].zfill(2):
            raise CliError('unexpected_response', 'Catalog entry belongs to another prefecture.')
        if level == 'area2' and not ident.startswith(parent['id']):
            raise CliError('unexpected_response', 'Catalog entry belongs to another parent area.')
        if ident in entries and entries[ident]['name'] != name:
            raise CliError('unexpected_response', 'Conflicting catalog entries.')
        entries[ident] = {'id': ident, 'name': name, 'type': kind, 'source': source}
    if not entries:
        raise CliError('unexpected_response', 'No usable catalog entries; empty or unsupported scope is unknown, not proof of no areas/stations.')
    return list(entries.values())


def parse_neighborhoods(body, municipality, slug, source):
    doc = soup(body)
    nav = doc.select_one('#js-leftnavi-area-scroll')
    if nav is None:
        raise CliError('unexpected_response', 'Municipal neighborhood navigation is missing.')
    pattern = re.compile(rf'/{re.escape(slug)}/{re.escape(municipality)}/(C\d+)/rstLst/?$')
    entries = {}
    for anchor in nav.select('a[href]'):
        url = urlsplit(urljoin(source, anchor['href']))
        match = pattern.fullmatch(url.path)
        if url.scheme != 'https' or url.hostname != 'tabelog.com' or url.port not in (None, 443) or url.username or url.password or not match:
            continue
        name = text_of(anchor)
        if not name:
            raise CliError('unexpected_response', 'Neighborhood name is missing.')
        ident = match[1]
        if ident in entries and entries[ident]['name'] != name:
            raise CliError('unexpected_response', 'Conflicting neighborhood entries.')
        entries[ident] = {'id': ident, 'name': name, 'type': 'municipal_neighborhood',
                          'url': f'{BASE}{url.path}', 'parent_id': municipality, 'source': source}
    if not entries:
        raise CliError('unexpected_response', 'No municipal neighborhoods recognized; coverage is unknown.')
    return list(entries.values())


class Catalog:
    def __init__(self, app):
        self.app, self.client = app, app.client

    def _xml(self, level, parent):
        path, key, _, _ = CATALOGS[level]
        url = endpoint(path, {'type': 'search', key: parent['id']})
        items = self.client.read(url, 'xml', lambda body, final: parse_catalog(body, level, parent, final))
        return {'parent': parent, 'items': items, 'meta': {
            'source': 'tabelog_xml_catalog', 'source_url': url, 'count': len(items), 'coverage': 'all_entries_in_response',
            'relation': 'tabelog_search_hierarchy', 'administrative_completeness': 'not_verified',
            'warnings': ['Lists Tabelog search options, not an administrative census. A search area can cross municipal borders; do not describe its stations as all stations physically within a city.']}}

    def areas(self, prefecture=None, parent=None, city=None):
        scopes = [v for v in (prefecture, parent, city) if v is not None]
        if len(scopes) > 1 or any(not isinstance(v, str) or not v.strip() for v in scopes):
            raise CliError('invalid_argument', 'Use at most one nonempty --prefecture, --parent or --city.')
        if not scopes:
            return {'parent': {'id': 'JP', 'name': 'Japan', 'type': 'country'},
                    'items': [{'id': str(n), 'name': name, 'type': 'prefecture'} for n, name in enumerate(PREFECTURES, 1)],
                    'meta': {'source': 'built_in_prefecture_codes', 'count': 47, 'coverage': 'all_47_prefectures',
                             'relation': 'prefecture_code_directory', 'network_requests': 0}}
        if city:
            return self.neighborhoods(city)
        if parent:
            if not re.fullmatch(r'A\d{4}', parent):
                raise CliError('invalid_argument', '--parent must be an Area1 identifier, such as A1701.')
            return self._xml('area2', {'id': parent, 'type': 'search_region'})
        if re.fullmatch(r'\d+', prefecture):
            code = int(prefecture)
            if not 1 <= code <= 47:
                raise CliError('invalid_argument', 'Prefecture code must be 1..47.')
            resolved = {'id': str(code), 'type': 'prefecture'}
        else:
            candidates = [r for r in self.app.suggest(prefecture) if r['datatype'] == 'Prefecture']
            candidates = [r for r in candidates if r.get('exact_match') is True] or candidates
            if len(candidates) != 1 or not str(candidates[0].get('id_in_datatype', '')).isdigit() or not 1 <= int(candidates[0]['id_in_datatype']) <= 47:
                raise CliError('ambiguous_prefecture', 'Prefecture could not be resolved uniquely.', candidates=candidates)
            resolved = {'id': str(int(candidates[0]['id_in_datatype'])), 'name': candidates[0]['name'], 'type': 'prefecture'}
        return self._xml('area1', resolved)

    def stations(self, area):
        if not isinstance(area, str) or not re.fullmatch(r'A\d{6}', area):
            raise CliError('invalid_argument', 'stations requires --area with an Area2 identifier, such as A170101. Municipal C-codes are not a verified station-catalog scope.')
        return self._xml('station', {'id': area, 'type': 'search_area'})

    def neighborhoods(self, city):
        candidates = [r for r in self.app.suggest(city) if r['datatype'] == 'AddressMaster' and re.fullmatch(r'C\d{5}', str(r.get('LstPrf', ''))) and re.fullmatch(r'[a-z]+', str(r.get('pal', '')))]
        candidates = [r for r in candidates if r.get('exact_match') is True] or candidates
        if len(candidates) != 1:
            raise CliError('ambiguous_city', 'Municipality could not be resolved uniquely.', candidates=candidates)
        item = candidates[0]
        municipality, slug = item['LstPrf'], item['pal']
        url = f'{BASE}/{slug}/{municipality}/rstLst/'
        def parse(body, final):
            path = urlsplit(final).path
            if not re.fullmatch(rf'/{re.escape(slug)}/{municipality}/(?:rstLst/)?', path):
                raise CliError('unexpected_response', 'Municipal catalog redirected to another scope.')
            return parse_neighborhoods(body, municipality, slug, final)
        entries = self.client.read(url, 'html', parse)
        return {'parent': {'id': municipality, 'name': item['name'], 'type': 'municipality', 'suggestion_id': str(item['id_in_datatype'])},
                'items': entries, 'meta': {'source': 'tabelog_municipal_navigation', 'source_url': url, 'count': len(entries),
                'coverage': 'all_matching_links_in_municipal_navigation', 'relation': 'municipal_neighborhoods', 'administrative_completeness': 'not_verified',
                'warnings': ['Lists neighborhoods exposed by Tabelog for this municipality; places without listed restaurants may be absent. This is not an official complete administrative gazetteer or a station list.']}}
