"""Current native search categories; numeric IDs always come from the live catalog."""
from .core import CliError

CATALOG_URL = 'https://tabelog.com/web-api/v1/hyakumeiten-category-list'
FILTER_KEY = 'chk_hyakumeiten_genres[]'
def parse_categories(raw, source):
    rows = raw.get('hyakumeitenCategoryList') if isinstance(raw, dict) else None
    if not isinstance(rows, list) or not rows:
        raise CliError('unexpected_response', 'Expected a nonempty Hyakumeiten category catalog.')
    items, ids, names = [], set(), set()
    for row in rows:
        if not isinstance(row, dict) or type(row.get('id')) is not int or row['id'] <= 0 or not isinstance(row.get('name'), str):
            raise CliError('unexpected_response', 'Invalid Hyakumeiten category identifier or name.')
        name = ' '.join(row['name'].split())
        if not name or row['id'] in ids or name in names:
            raise CliError('unexpected_response', 'Empty or duplicate Hyakumeiten category.')
        ids.add(row['id'])
        names.add(name)
        items.append({'id': row['id'], 'name': name})
    return {'items': items, 'meta': {'source': 'native_hyakumeiten_category_api', 'source_url': source,
            'count': len(items), 'scope': 'current_search_categories', 'year': None,
            'warning': 'The catalog does not expose award years. Search automatically includes all current categories.'}}


def filter_params(params, category_ids=None):
    """Repeated native parameters mean OR; never serialize IDs as a Python list."""
    return list(params.items()) + [(FILTER_KEY, ident) for ident in category_ids or []]
