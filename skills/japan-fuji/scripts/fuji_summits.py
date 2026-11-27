"""The Weathernews public Fuji-view map, queried for selected summits."""
import datetime as dt
import json
import re
from urllib.parse import urlencode

import fuji_source as source

MAP = 'https://weathernews.jp/mountain/fuji_viewable/'
API = 'https://site.weathernews.jp/api/mountain/list'
# Selected names from the map's point list. Other map points can be queried by ID.
NAMES = {'高尾山': '30858', '三ツ峠山': '40501', '金時山': '31110', '大菩薩嶺': '30849',
         '丹沢山': '30910', '塔ノ岳': '30903', '蛭ヶ岳': '30902', '筑波山': '30204'}
GRADES = (('×', '難しい'), ('×', '難しい'), ('△', 'わずかにチャンスあり'),
          ('○', 'チャンスあり'), ('◎', 'よく見える'), ('◎', 'よく見える'))


def dates_on_map(now):
    first = now.date() + dt.timedelta(days=int(now.hour >= 18))
    return [first, first + dt.timedelta(days=1)]


def summit_record(point_id, point, dates, panel, today):
    result = {'mountain_id': point_id, 'summit': None, 'days': []}
    indices = []
    base = None
    if point is not None:
        if not isinstance(point, dict) or not isinstance(point.get('name'), str) or not point['name'].strip():
            source.fail('Weathernews summit identity is missing.')
        result['summit'] = point['name']
        if point_id in NAMES.values() and NAMES.get(point['name']) != point_id:
            source.fail('Weathernews summit identity changed.')
        if 'fuji_viewable_index' not in point:
            source.fail('Weathernews Fuji-view field is missing.')
        indices = point['fuji_viewable_index']
        if indices is None:
            indices = []
        if not isinstance(indices, list) or (indices and len(indices) != 3):
            source.fail('Unexpected Weathernews Fuji-view index series.')
        if indices:
            if type(point.get('day0')) is not int:
                source.fail('Weathernews map base date is missing.')
            stamp = dt.datetime.fromtimestamp(point['day0'], source.JST)
            base = stamp.date()
            if stamp.time() != dt.time() or (today-base).days not in (0, 1):
                raise source.SourceError('invalid_base_date', 'Weathernews map base date is stale or invalid.')
            if panel[-1] > base + dt.timedelta(days=2):
                raise source.SourceError('stale_base_date', 'Weathernews series predates the evening map window.')
    for date in dates:
        day = {'date': date.isoformat(), 'status': 'unavailable', 'symbol': None, 'label_ja': None}
        if indices and date in panel:
            value = indices[(date-base).days]
            if value is not None:
                if type(value) is not int or not 0 <= value < len(GRADES):
                    source.fail('Unrecognized Weathernews Fuji-view grade.')
                day.update(status='ok', symbol=GRADES[value][0], label_ja=GRADES[value][1])
        result['days'].append(day)
    statuses = {day['status'] for day in result['days']}
    result['status'] = statuses.pop() if len(statuses) == 1 else 'partial'
    return result


def query(client, args):
    points = list(dict.fromkeys(NAMES.get(value, value) for value in args.summit))
    if len(points) > 8 or not all(re.fullmatch(r'[0-9]{5}', p) for p in points):
        raise source.SourceError('invalid_options', 'Use up to eight listed summit names or five-digit Weathernews map IDs.')
    date = None
    if args.date:
        try:
            date = dt.date.fromisoformat(args.date)
            if date.isoformat() != args.date:
                raise ValueError
        except ValueError:
            raise source.SourceError('invalid_options', 'Expected a JST date in YYYY-MM-DD format.') from None
    url = API + '?' + urlencode({'ids': ','.join(sorted(points))})
    raw, meta = client.read(url)
    payload = json.loads(raw)
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not set(data).issubset(points):
        source.fail('Weathernews summit map response changed.')
    now = source.now_jst()
    panel = dates_on_map(now)
    records = []
    for point_id in points:
        try:
            records.append(summit_record(point_id, data.get(point_id), [date] if date else panel, panel, now.date()))
        except (source.SourceError, OSError, OverflowError, ValueError) as error:
            records.append({'mountain_id': point_id, 'status': 'error', 'state': 'unknown',
                            'error': getattr(error, 'code', 'invalid_source_value'), 'days': []})
    statuses = {r['status'] for r in records}
    return {'provider': 'weathernews', 'scope': 'view_from_mountain_summit', 'page_url': MAP,
            'source': meta, 'issued_at': None, 'timezone': 'Asia/Tokyo',
            'published_dates': [d.isoformat() for d in panel], 'records': records,
            'status': statuses.pop() if len(statuses) == 1 else 'partial'}
