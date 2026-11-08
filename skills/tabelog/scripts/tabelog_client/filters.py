"""List-budget and Japan-local regular opening-hours filters (no network)."""
import re
import unicodedata
from datetime import date, timedelta

import jpholiday

from .core import CliError, date_value, time_value


def budget_range(raw):
    value = unicodedata.normalize('NFKC', raw or '').replace(' ', '')
    amount = r'(?:[0-9]+|[0-9]{1,3}(?:,[0-9]{3})+)'
    match = re.fullmatch(r'(?:JPY(' + amount + r'))?-(?:JPY(' + amount + r'))?', value)
    if not match:
        match = re.fullmatch(r'[¥￥]?(\d+)?[~〜～][¥￥]?(\d+)?', value.replace(',', ''))
    if not match or not any(match.groups()):
        return None
    low, high = match.groups()
    result = {'min_yen': int(low.replace(',', '')) if low else 0,
              'max_yen': int(high.replace(',', '')) if high else None}
    return result if result['max_yen'] is None or result['min_yen'] <= result['max_yen'] else None


def budget_check(item, meal, minimum=None, maximum=None):
    if meal is None:
        checks = [budget_check(item, name, minimum, maximum) for name in ('lunch', 'dinner')]
        matching = [r['meal'] for r in checks if r['status'] == 'matches_list_budget']
        status = 'matches_list_budget' if matching else next(
            (s for s in ('boundary_uncertain', 'unknown') if any(r['status'] == s for r in checks)),
            'outside_budget')
        return {'status': status, 'meal': 'any', 'matching_meals': matching, 'checks': checks,
                'currency': 'JPY', 'source': 'search_list',
                'warning': 'At least one listed meal budget band must fit; matching meals are reported separately.'}
    raw = item.get('budgets', {}).get(meal)
    bounds = budget_range(raw)
    status = 'unknown'
    if bounds:
        low, high = bounds['min_yen'], bounds['max_yen']
        if maximum is not None and low > maximum or minimum is not None and high is not None and high < minimum:
            status = 'outside_budget'
        elif (minimum is None or low >= minimum) and (maximum is None or high is not None and high <= maximum):
            status = 'matches_list_budget'
        else:
            status = 'boundary_uncertain'
    return {'status': status, 'meal': meal, 'currency': 'JPY', 'raw': raw, 'range': bounds,
            'source': 'search_list', 'warning': 'Listed per-person budget band, not a course price or guaranteed bill.'}


def opening_arguments(day=None, at=None, until=None):
    if until and not at:
        raise CliError('invalid_argument', '--open-until requires --open-at.')
    if day:
        date_value(day)
        if not 1949 <= date.fromisoformat(day).year <= 2099:
            raise CliError('invalid_argument', 'Opening-date holiday calculations support years 1949..2099.')
    for value in (at, until):
        if value:
            time_value(value)
    if at and at == until:
        raise CliError('invalid_argument', '--open-at and --open-until must differ.')


def _minute(value):
    h, m = value.split(':')
    return int(h)*60+int(m)


def _rule_ranges(selected):
    if not selected or any(not r.get('closed') and not r.get('rangeList') for r in selected):
        return [], False
    if any(r.get('closed') for r in selected) and any(not r.get('closed') for r in selected):
        return [], False
    return [v for r in selected if not r.get('closed') for v in r.get('rangeList', [])], True


def _day_rules(hours, day):
    kinds = []
    if jpholiday.is_holiday(day):
        kinds.append('holiday')
    if jpholiday.is_holiday(day+timedelta(days=1)):
        kinds.append('before_holiday')
    if jpholiday.is_holiday(day-timedelta(days=1)):
        kinds.append('after_holiday')
    special = [r for r in hours if any(k in r.get('day_types', []) for k in kinds)]
    # Explicit holiday rows override regular weekday rows. Conflicts remain unknown.
    return _rule_ranges(special or [r for r in hours if (day.weekday()+1) % 7 in r.get('dayList', [])])


def opening_check(item, day=None, at=None, until=None, meal=None):
    """Without a date, report weekly rules rather than inventing a visit date."""
    opening_arguments(day, at, until)
    if day:
        return _opening_check(item, day, at, until, meal)
    checks = [_opening_check(item, None, at, until, meal, weekday=n) for n in range(7)]
    matching = [r['weekday'] for r in checks if r['status'] == 'matches_regular_hours']
    unknown = [r['weekday'] for r in checks if r['status'] == 'unknown']
    return {'status': 'matches_regular_hours' if matching else 'unknown' if unknown else 'outside_regular_hours',
            'basis': 'regular_weekdays', 'date': None, 'at': at, 'until': until, 'timezone': 'Asia/Tokyo',
            'matching_weekdays': matching, 'unknown_weekdays': unknown, 'weekday_results': checks,
            'special_rules': [r for r in item.get('hours', []) if r.get('day_types')],
            'notes': checks[0]['notes'], 'source': item.get('url'),
            'warning': 'Weekdays use 0=Sunday through 6=Saturday. Ordinary weekly schedule only; holiday/adjacent-holiday rules, temporary changes and seats are not confirmed.'}


def _opening_check(item, day, at, until, meal, weekday=None):
    d = date.fromisoformat(day) if day else None
    start = _minute(at) if at else None
    end = _minute(until) if until else start
    if until and end < start:
        end += 1440
    hours = item.get('hours', [])
    def rules(offset):
        return _day_rules(hours, d+timedelta(days=offset)) if d else _rule_ranges(
            [r for r in hours if (weekday+offset) % 7 in r.get('dayList', [])])
    current, known = rules(0)
    previous, previous_known = rules(-1)
    intervals = [(r['open'], r['close'], r) for r in current]
    intervals += [(r['open']-1440, r['close']-1440, r) for r in previous if r['close'] > 1440]
    following_known = True
    if end is not None and end > 1440:
        following, following_known = rules(1)
        intervals += [(r['open']+1440, r['close']+1440, r) for r in following]
    # Merge touching sessions, but never bridge a lunch/dinner break.
    merged = []
    for range_start, range_end, _ in sorted(intervals, key=lambda r: r[0]):
        if merged and range_start <= merged[-1][1]:
            merged[-1][1] = max(range_end, merged[-1][1])
        else:
            merged.append([range_start, range_end])
    notes = [r for r in item.get('info', []) if re.search(r'business hours|remarks|reserv|営業時間|定休日|備考|予約', r['label'], re.I)]
    raw_notes = '\n'.join(r['value'] for r in notes if not re.search(r'remarks|備考', r['label'], re.I)
                          or re.search(r'hours|closed|holiday|営業|定休|休業', r['value'], re.I))
    exceptions = bool(re.search(
        r'irregular|temporary|subject to|depending|by reservation|reservations? (?:only|required)|advance reservation|'
        r'not available|not served|not fixed|no lunch|no dinner|except|seasonal|every other|sold out|corresponding to|'
        r'不定休|臨時|完全予約|予約制|要予約|変更|場合|売り切れ|売切|なくなり|次第|'
        r'第[一二三四五1-5]|\b[1-5](?:st|nd|rd|th)\b|年末|年始|お盆|夏季|冬季|停供|休业|休業|隔週|'
        r'\b(?:first|second|third|fourth|fifth|last)(?:\s*(?:and|&|,)\s*(?:first|second|third|fourth|fifth|last))*'
        r'\s+(?:Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)s?\b|'
        r'\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\d{1,2}月\d{1,2}日|'
        r'\b(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d', raw_notes, re.I))
    # Holiday mentions outside structured rows may describe an unparsed override.
    if re.search(r'public holiday|祝日', raw_notes, re.I) and not any(r.get('day_types') for r in hours):
        exceptions = True
    matching = [(a, b, r) for a, b, r in intervals if start is not None and a <= start < b]
    for a, _, r in matching:
        last_order = r.get('lastOrder')
        if last_order:
            values = re.findall(r'(\d{1,2}):([0-5]\d)\s*(AM|PM)?', last_order, re.I)
            if not values:
                exceptions = True
                continue
            deadlines = []
            for h, m, meridiem in values:
                hour = int(h) if not meridiem else int(h) % 12 + (12 if meridiem.upper() == 'PM' else 0)
                last = hour*60+int(m)
                if last < r['open']:
                    last += 1440
                if a < 0:
                    last -= 1440
                deadlines.append(last)
            if start >= min(deadlines):
                exceptions = True
    if start is None:
        lo, hi = (660, 840) if meal == 'lunch' else (1020, 1260) if meal == 'dinner' else (0, 1440)
        matches = any(a < hi and b > lo for a, b in merged)
    else:
        matches = any(a <= start < b and end <= b for a, b in merged)
        if meal:
            lo, hi = (660, 840) if meal == 'lunch' else (1020, 1260)
            matches = matches and any(a < hi and b > lo for a, b in merged)
    uncertain = (exceptions or not known or start is not None and start < 360 and not previous_known and not matches
                 or not following_known and not matches)
    return {'status': 'unknown' if uncertain else 'matches_regular_hours' if matches else 'outside_regular_hours',
            'date': day, **({'weekday': weekday} if weekday is not None else {}),
            'at': at, 'until': until, 'timezone': 'Asia/Tokyo',
            'holiday': jpholiday.is_holiday_name(d) if d else None, 'intervals_minutes': merged,
            'holiday_calendar': {'name': 'jpholiday', 'basis': 'third_party_local_rules',
                                 'official_feed_checked': False} if d else None,
            'notes': notes, 'source': item.get('url'),
            'warning': 'Published regular schedule only; temporary changes and seats are not confirmed. Read notes.'}
