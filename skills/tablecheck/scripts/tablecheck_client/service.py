"""Consumer API composition; menus and live inventory keep separate evidence."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, InvalidOperation
import math
import re
from urllib.parse import urlsplit, urlencode
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from .transport import CliError
from .detail_info import practical_info

UNIVERSE_JAPAN = '57e0b91744aea12988000001'


def slug_value(value):
    if '://' in value:
        url = urlsplit(value)
        if url.scheme != 'https' or url.hostname not in ('www.tablecheck.com', 'tablecheck.com') or url.username or url.password:
            raise CliError('invalid_argument', 'Use a public HTTPS TableCheck restaurant URL or slug.')
        match = re.fullmatch(r'/(?:[a-z]{2}(?:-[A-Z]{2})?/)?(?:shops/)?([a-z0-9][a-z0-9-]{0,80})(?:/reserve(?:/landing)?)?/?', url.path)
        value = match[1] if match else ''
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', value):
        raise CliError('invalid_argument', 'Invalid restaurant slug or URL.')
    return value


def translated(values, locale='en'):
    return next((item.get('translation') for item in values or [] if item.get('locale') == locale), None)


def named(value):
    names = value.get('name_translations', [])
    return {'name': translated(names) or translated(names, 'ja'), 'name_ja': translated(names, 'ja')}


def array(value, key):
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        raise CliError('unexpected_response', f'Missing or invalid {key}; data is unknown.')
    return value[key]


def dates(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if last < first or (last-first).days > 30:
        raise CliError('invalid_argument', 'Date ranges must contain 1–31 days.')
    return [(first+timedelta(days=i)).isoformat() for i in range((last-first).days+1)]


def not_elapsed_today(at):
    now = datetime.now(at.tzinfo)
    return at.date() != now.date() or at > now


def booking_url(venue, day=None, clock=None, people=None):
    slug = venue['slug']
    mode = venue.get('booking_page_mode')
    base = (f'https://www.tablecheck.com/en/{slug}/reserve/landing' if mode == 'v2' else
            f'https://www.tablecheck.com/en/shops/{slug}/reserve' if mode == 'v1' else None)
    if base is None:
        return None
    query = {key: value for key, value in [('start_date', day), ('start_time', clock), ('num_people', people)] if value is not None}
    return base + ('?'+urlencode(query) if query else '')


def venue_summary(value):
    result = {key: value.get(key) for key in ('slug', 'country', 'currency', 'time_zone', 'booking_page_mode', 'cuisines', 'distance',
                                             'budget_lunch_min', 'budget_lunch_max', 'budget_dinner_min', 'budget_dinner_max', 'budget_dinner_avg')}
    result.update(named(value), id=value.get('_id'), coordinates=value.get('geocode'), booking_url=booking_url(value))
    return result


class TableCheck:
    def __init__(self, client):
        self.client = client

    def venue(self, target):
        slug = slug_value(target)
        shops = array(self.client.read('GET', '/v2/shops/'+slug, {'locale': 'en'}), 'shops')
        shop = next((item for item in shops if item.get('slug') == slug), None)
        if not shop:
            raise CliError('not_found', 'Restaurant not returned by the public consumer API.')
        if not isinstance(shop.get('_id'), str) or not re.fullmatch(r'[0-9a-f]{24}', shop['_id']):
            raise CliError('unexpected_response', 'Restaurant lacks a valid public shop ID.')
        return shop

    def detail(self, target, start, end, include_courses=True, meal=None, course=None):
        venue = self.venue(target)
        result = venue_summary(venue)
        result.update({key: venue.get(key) for key in ('address', 'alt_address', 'phone', 'service_modes', 'tc_input_service_category')})
        result['policy'] = translated(venue.get('request_policy_translations'))
        result['policy_ja'] = translated(venue.get('request_policy_translations'), 'ja')
        result['seat_categories'] = [{'id': item.get('id'), **named(item)} for item in venue.get('service_categories') or []]
        result['practical_info'] = practical_info(venue, result['booking_url'])
        if not result['practical_info']['reservation']['evidence'] and venue.get('booking_page_mode') == 'v1':
            try:
                page = self.client.read('GET', f"/en/shops/{venue['slug']}/reserve")
                result['practical_info'] = practical_info(venue, result['booking_url'], page)
            except CliError as error:
                result.update(coverage='partial', errors=[{'scope': 'practical_info', **error.as_dict()}])
                if include_courses:
                    result['courses'] = None
                return result
        if include_courses:
            result['course_window'] = {'from': start, 'to': end, 'scope': 'listed_conditions_not_slot_inventory'}
            try:
                result['courses'] = self.courses(target, start, end, meal=meal, course=course)['items']
            except CliError as error:
                if error.code in ('invalid_argument', 'not_found'):
                    raise
                result.update(courses=None, coverage='partial', errors=[{'scope': 'courses', **error.as_dict()}])
        return result

    @staticmethod
    def location(venue):
        try:
            return ZoneInfo(venue['time_zone'])
        except (KeyError, TypeError, ValueError):
            raise CliError('unexpected_response', 'Venue time zone is missing or invalid.') from None

    def courses(self, target, start, end, meal=None, course=None, _venue=None):
        wanted = dates(start, end)
        venue = _venue if _venue is not None else self.venue(target)
        if not isinstance(venue.get('_id'), str) or not re.fullmatch(r'[0-9a-f]{24}', venue['_id']):
            raise CliError('unexpected_response', 'Menu lookup requires a valid public shop ID.')
        tz = self.location(venue)
        body = {'shop_id': venue['_id'], 'locale': 'en', 'has_price': True,
                'date_min': datetime.combine(date.fromisoformat(start), time(), tzinfo=tz).astimezone(timezone.utc).isoformat(),
                'date_max': datetime.combine(date.fromisoformat(end)+timedelta(days=1), time(), tzinfo=tz).astimezone(timezone.utc).isoformat()}
        menus = array(self.client.read('POST', '/v2/hub/menu_items', body=body), 'menu_items')
        if any(not isinstance(item, dict) or not isinstance(item.get('id'), str)
               or not re.fullmatch(r'[0-9a-f]{24}', item['id']) for item in menus):
            raise CliError('unexpected_response', 'Menu identity is missing or invalid; an empty menu is not inferred.')
        if course and not any(item.get('id') == course for item in menus):
            raise CliError('not_found', 'Course not returned for this restaurant and date window.')
        items = []
        for item in menus:
            if course and item.get('id') != course:
                continue
            eligibility = {day: self.course_date(item, day, meal) for day in wanted}
            if all(state is False for state in eligibility.values()):
                continue
            fields = ('id', 'price', 'prev_price', 'price_mode', 'tax_type', 'service_fee_type', 'service_fee_rate', 'price_basis',
                      'availability_status', 'is_active', 'is_hidden', 'is_group_order', 'min_order_qty', 'max_order_qty',
                      'days', 'meals', 'valid_date_ranges', 'valid_time_ranges', 'available_times', 'service_category_ids',
                      'cancel_fee_rules', 'payment_type', 'pax_prices', 'min_time_cutoff_at', 'max_time_cutoff_at')
            summary = {key: item.get(key) for key in fields}
            summary.update(named(item), currency=venue.get('currency'), eligible_dates=eligibility,
                           availability_scope='listed_conditions_not_slot_inventory', computed_total=None)
            for field in ('description', 'fine_print', 'tagline'):
                summary[field] = translated(item.get(field+'_translations'))
                summary[field+'_ja'] = translated(item.get(field+'_translations'), 'ja')
            items.append(summary)
        return {'restaurant': venue_summary(venue), 'from': start, 'to': end, 'items': items}

    @staticmethod
    def course_date(item, day, meal=None):
        for field in ('is_active', 'is_hidden', 'is_holiday', 'is_before_holiday'):
            if item.get(field) is not None and type(item[field]) is not bool:
                raise CliError('unexpected_response', 'Course eligibility flag is invalid.', field=field)
        for field in ('meals', 'days'):
            values = item.get(field)
            if values is not None and (not isinstance(values, list) or any(not isinstance(value, str) for value in values)):
                raise CliError('unexpected_response', 'Course eligibility list is invalid.', field=field)
        weekdays = item.get('days')
        if weekdays and any(value not in ('m', 'tu', 'w', 'th', 'f', 'sa', 'su') for value in weekdays):
            raise CliError('unexpected_response', 'Course weekday code is not recognized.')
        ranges = item.get('valid_date_ranges')
        if ranges is not None:
            try:
                if not isinstance(ranges, list):
                    raise ValueError()
                for entry in ranges:
                    if not isinstance(entry, dict):
                        raise ValueError()
                    for field in ('start_date', 'end_date'):
                        if entry.get(field) not in (None, '') and date.fromisoformat(entry[field]).isoformat() != entry[field]:
                            raise ValueError()
                    if entry.get('start_date') and entry.get('end_date') and entry['start_date'] > entry['end_date']:
                        raise ValueError()
            except (ValueError, TypeError):
                raise CliError('unexpected_response', 'Course date range is invalid.') from None
        if item.get('is_active') is False or item.get('is_hidden') is True:
            return False
        if meal and item.get('meals') and meal not in item['meals']:
            return False
        if ranges and not any((not entry.get('start_date') or day >= entry['start_date']) and
                              (not entry.get('end_date') or day <= entry['end_date']) for entry in ranges):
            return False
        if weekdays and ['m', 'tu', 'w', 'th', 'f', 'sa', 'su'][date.fromisoformat(day).weekday()] not in weekdays:
            return None if item.get('is_holiday') or item.get('is_before_holiday') else False
        return True

    def cuisines(self):
        return {'items': [{'id': item.get('field'), 'name': translated(item.get('text_translations')),
                           'name_ja': translated(item.get('text_translations'), 'ja')}
                          for item in array(self.client.read('GET', '/v2/cuisines'), 'cuisines')]}

    def suggest(self, query):
        value = self.client.read('GET', '/v2/autocomplete', {'shop_universe_id': UNIVERSE_JAPAN, 'locale': 'en', 'text': query})
        return {'items': [{'slug': (item.get('payload') or {}).get('shop_slug'),
                           'name': translated(item.get('text_translations')) or translated(item.get('text_translations'), 'ja') or item.get('text'),
                           'name_ja': translated(item.get('text_translations'), 'ja'),
                           'location_name': translated((item.get('payload') or {}).get('location_name_translations'))}
                          for item in array(value, 'shops')],
                'locations': [{**named({'name_translations': item.get('text_translations')}),
                               'type': item.get('payload', {}).get('location_type'), 'term': item.get('payload', {}).get('term'),
                               'area': translated(item.get('payload', {}).get('area_translations')),
                               'area_ja': translated(item.get('payload', {}).get('area_translations'), 'ja'),
                               'coordinates': item.get('payload', {}).get('geo')}
                              for item in value.get('locations', [])]}

    def resolve_area(self, query):
        places = [place for place in self.suggest(query)['locations'] if place['type'] in ('city', 'ward', 'prefecture')]
        exact = [place for place in places if query.casefold() in
                 [str(place.get(field) or '').casefold() for field in ('name', 'name_ja', 'term')]]
        candidates = exact or places
        cities = [place for place in candidates if place['type'] == 'city']
        if len(cities) == 1:
            candidates = cities
        if len(candidates) != 1:
            raise CliError('ambiguous_location' if candidates else 'not_found',
                           'Use a more specific city/area name or explicit --near coordinates.', candidates=candidates)
        place = candidates[0]
        point = place.get('coordinates') or {}
        try:
            lat, lon = float(point['lat']), float(point['lon'])
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise CliError('unexpected_response', 'Native location lacks valid coordinates.') from None
        return place, (lat, lon)

    def indexed_availability(self, shop, day, people, after, before):
        values = array(shop, 'availability')
        tz = self.location(shop)
        times = set()
        for value in values:
            try:
                at = datetime.fromisoformat(value.replace('Z', '+00:00'))
                if at.tzinfo is None:
                    raise ValueError()
                local = at.astimezone(tz)
                if local.date().isoformat() != day or local.second or local.microsecond:
                    raise ValueError()
            except (ValueError, TypeError, AttributeError):
                raise CliError('unexpected_response', 'Search index returned an invalid or mismatched slot timestamp.') from None
            clock = local.strftime('%H:%M')
            if after <= clock <= before and not_elapsed_today(local):
                times.add(clock)
        return {'people': people, 'scope': 'venue_search_index', 'verification': 'search_index_only',
                'course_linked': False, 'seat_linked': False,
                'index_created_min': shop.get('availability_created_min'), 'index_created_max': shop.get('availability_created_max'),
                'days': [{'date': day, 'status': 'available_hint' if times else 'no_indexed_match', 'offered_times': sorted(times)}]}

    def availability(self, target, start, end, people, after='00:00', before='23:59', course=None, seat=None):
        wanted = dates(start, end)
        venue = self.venue(target)
        tz = self.location(venue)
        if course or seat:
            if course and not seat and venue.get('tc_input_service_category') == 'required':
                return self.course_any_seat(venue, wanted, people, after, before, course)
            return self.constrained(venue, wanted, people, after, before, course, seat)
        lo, hi = [int(s[:2])*60+int(s[3:]) for s in (after, before)]
        if hi < lo:
            raise CliError('invalid_argument', '--before must be at least --after; overnight windows are not supported.')
        # Each native calendar covers its anchor ±2 hours. Actual timestamps are
        # checked below; omitted dates and missing states never become sold out.
        anchors = list(range(lo+120, hi+120, 240)) or [lo+120]
        anchors = [min(value, 23*60+59) for value in anchors]
        rows = {day: {'date': day, 'status': 'unknown', 'offered_times': [], 'coverage': [], 'error': None} for day in wanted}
        failures = []
        for anchor in dict.fromkeys(anchors):
            clock = f'{anchor//60:02}:{anchor%60:02}'
            covered = set()
            # One follow-up window is allowed for sparse/short source coverage;
            # an omitted date does not cause an automatic daily request sweep.
            for attempt in range(2):
                missing = [day for day in wanted if day not in covered]
                if not missing:
                    break
                at = datetime.combine(date.fromisoformat(missing[0]), time.fromisoformat(clock), tzinfo=tz)
                try:
                    raw = self.client.read('POST', '/v2/hub/availability_calendar_v2', body={
                        'shop_id': venue['_id'], 'locale': 'en', 'start_at': at.astimezone(timezone.utc).isoformat(), 'num_people': people})
                    cal = raw.get('availability_calendar') if isinstance(raw, dict) else None
                    if not isinstance(cal, dict) or cal.get('type') != 'success' or not isinstance(cal.get('data'), dict) or cal.get('time_zone') != venue['time_zone']:
                        raise CliError('unexpected_response', 'Calendar status, data or time zone is not recognized.')
                    closed = cal.get('closed_dates', [])
                    if not isinstance(closed, list) or any(not isinstance(day, str) for day in closed):
                        raise CliError('unexpected_response', 'Calendar closed-date list is not recognized.')
                    alternates = cal.get('alternate_timeslots', {})
                    if not isinstance(alternates, dict):
                        raise CliError('unexpected_response', 'Calendar alternate times are not recognized.')
                    for day in wanted:
                        row = rows[day]
                        if day in closed:
                            row['status'] = 'closed'
                            row['coverage'].append({'anchor': clock, 'closed': True})
                            covered.add(day)
                            continue
                        slots = cal['data'].get(day)
                        if not isinstance(slots, dict) or not slots:
                            continue
                        complete = True
                        observed = []
                        for timestamp, state in slots.items():
                            try:
                                at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                if at.tzinfo is None:
                                    raise ValueError()
                                local = at.astimezone(tz)
                                available = state.get('is_available') if isinstance(state, dict) else None
                                if local.date().isoformat() != day or local.second or local.microsecond or type(available) is not bool:
                                    raise ValueError()
                                minute = local.hour*60+local.minute
                                observed.append(minute)
                                if available and lo <= minute <= hi and not_elapsed_today(local):
                                    row['offered_times'].append(local.strftime('%H:%M'))
                            except (ValueError, TypeError, AttributeError):
                                complete = False
                                failures.append({'code': 'unexpected_response', 'date': day,
                                                 'message': 'Calendar slot timestamp or availability state is invalid.'})
                        lower, upper = max(lo, anchor-120), min(hi, anchor+120)
                        expected = {minute for minute in range(anchor-120, anchor+121, 30) if lo <= minute <= hi}
                        complete = complete and bool(expected) and expected.issubset(set(observed))
                        if complete:
                            covered.add(day)
                            row['coverage'].append({'anchor': clock, 'from': f'{lower//60:02}:{lower%60:02}', 'to': f'{upper//60:02}:{upper%60:02}'})
                        # Alternate times are positive suggestions; they do not
                        # establish that missing times or dates were checked.
                        alternate_values = alternates.get(day, [])
                        if not isinstance(alternate_values, list):
                            raise CliError('unexpected_response', 'Calendar alternate times must be an array.', date=day)
                        for timestamp in alternate_values:
                            try:
                                alternate = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                if alternate.tzinfo is None:
                                    raise ValueError()
                                local = alternate.astimezone(tz)
                                if local.date().isoformat() != day or local.second or local.microsecond:
                                    raise ValueError()
                                if after <= local.strftime('%H:%M') <= before and not_elapsed_today(local):
                                    row['offered_times'].append(local.strftime('%H:%M'))
                            except (ValueError, TypeError, AttributeError):
                                failures.append({'code': 'unexpected_response', 'date': day,
                                                 'message': 'Calendar alternate slot timestamp is invalid.'})
                except CliError as error:
                    failures.append(error.as_dict())
                    break
        for row in rows.values():
            row['offered_times'] = sorted(set(row['offered_times']))
            full = len({item['anchor'] for item in row['coverage']}) == len(set(anchors))
            row['complete'] = full
            if not full:
                row['error'] = {'code': 'incomplete_coverage', 'message': 'Required calendar dates or time-grid states were not returned.'}
            if row['offered_times']:
                row['status'] = 'available'
            elif row['status'] != 'closed' and full:
                row['status'] = 'unavailable'
            row['booking_url'] = booking_url(venue, row['date'], row['offered_times'][0] if row['offered_times'] else None, people)
        missing_dates = [day for day, row in rows.items() if not row['complete']]
        if missing_dates:
            failures.append({'code': 'incomplete_coverage', 'dates': missing_dates,
                             'message': 'Required calendar dates or time-grid states were not returned; these dates remain incomplete.'})
        return {'restaurant': venue_summary(venue), 'people': people, 'from': start, 'to': end, 'after': after, 'before': before,
                'scope': 'venue', 'course_linked': False, 'seat_linked': False, 'days': list(rows.values()),
                'coverage_basis': 'returned_calendar_grid_and_closed_dates',
                'coverage': 'complete' if all(row['complete'] for row in rows.values()) and not failures else 'partial',
                'errors': failures, 'note': 'Unavailable means no offered slot on the returned calendar grid; other start times may exist. Unreleased inventory cannot always be distinguished.'}

    def course_any_seat(self, venue, wanted, people, after, before, course):
        menus = self.courses(venue['slug'], wanted[0], wanted[-1], course=course)['items']
        if not menus:
            raise CliError('invalid_argument', 'Course has no eligible date in the requested window.')
        allowed = menus[0].get('service_category_ids') or []
        categories = [item for item in venue.get('service_categories') or [] if not allowed or item.get('id') in allowed]
        if not categories:
            if not allowed and not venue.get('service_categories'):
                # Some shops expose the API's required flag without any seat
                # choices. Let the actual form establish whether a seat
                # selection is exposed, without claiming a particular seat.
                return self.constrained(venue, wanted, people, after, before, course, None)
            raise CliError('unsupported_scope', 'Required seat categories could not be resolved.')
        rows = {day: {'date': day, 'status': 'unknown', 'offered_times': [], 'slots': [], 'complete': True} for day in wanted}
        errors, completed, checked_categories = [], 0, []
        for category in categories:
            try:
                result = self.constrained(venue, wanted, people, after, before, course, category['id'])
                completed += 1
                checked_categories.append({'id': category['id'], **named(category)})
                errors.extend(result['errors'])
                for row in result['days']:
                    merged = rows[row['date']]
                    merged['offered_times'].extend(row['offered_times'])
                    merged['slots'].extend(row['slots'])
                    merged['complete'] = merged['complete'] and row['complete']
            except CliError as error:
                errors.append(error.as_dict())
            if self.client.blocked or self.client.requests >= self.client.max_requests:
                break
        for day, row in rows.items():
            row['complete'] = row['complete'] and completed == len(categories)
            row['offered_times'] = sorted(set(row['offered_times']))
            row['status'] = 'available' if row['offered_times'] else 'unavailable' if row['complete'] else 'unknown'
            row['booking_url'] = booking_url(venue, day, row['offered_times'][0] if row['offered_times'] else None, people)
        return {'restaurant': venue_summary(venue), 'from': wanted[0], 'to': wanted[-1], 'people': people, 'after': after, 'before': before,
                'course_id': course, 'scope': 'course_any_seat_category', 'course_linked': True, 'seat_linked': True,
                'seat_categories_checked': checked_categories,
                'days': list(rows.values()), 'errors': errors,
                'coverage': 'complete' if all(row['complete'] for row in rows.values()) and not errors else 'partial',
                'note': 'The booking form requires a seat category. Each applicable category is checked separately; slots retain their category IDs.'}

    def constrained(self, venue, wanted, people, after, before, course, seat):
        if venue.get('booking_page_mode') != 'v1':
            raise CliError('unsupported_scope', 'Course/seat-specific inventory currently requires a public v1 reservation page.')
        categories = venue.get('service_categories') or []
        selected_seat = None
        if seat:
            matches = [item for item in categories if seat == item.get('id') or
                       any(seat.casefold() == str(value.get('translation', '')).casefold() for value in item.get('name_translations') or [])]
            if len(matches) != 1:
                raise CliError('invalid_argument', 'Seat must match one category ID or exact translated name from detail.')
            selected_seat = matches[0]['id']
        menu = None
        if course:
            menus = self.courses(venue['slug'], wanted[0], wanted[-1], course=course)['items']
            if not menus:
                raise CliError('invalid_argument', 'Course has no eligible date in the requested window.')
            menu = menus[0]
            if selected_seat and menu.get('service_category_ids') and selected_seat not in menu['service_category_ids']:
                raise CliError('invalid_argument', 'Course does not list this seat category.')
        page = self.client.read('GET', f"/en/shops/{venue['slug']}/reserve")
        soup = BeautifulSoup(page, 'html.parser')
        params = {'reservation[num_people_adult]': people, 'reservation[num_people_child]': 0, 'reservation[num_people_baby]': 0}
        seat_controls = soup.select('[name="reservation[service_category]"]')
        if not selected_seat and venue.get('tc_input_service_category') == 'required' and seat_controls:
            raise CliError('unsupported_scope', 'The public form requires a seat choice that could not be resolved.')
        if selected_seat:
            actual = [tag.get('value') for tag in seat_controls]
            if selected_seat not in actual:
                raise CliError('unsupported_scope', 'Seat is not present in the public reservation form.')
            params['reservation[service_category]'] = selected_seat
        if course:
            inputs = [tag for tag in soup.select('input[name]') if tag.get('value') == course and
                      re.fullmatch(r'reservation\[orders_attributes\]\[\d+\]\[menu_item_id\]', tag['name'])]
            if len(inputs) != 1:
                raise CliError('unsupported_scope', 'Course is not uniquely present in the public reservation form.')
            field = inputs[0]['name']
            prefix = field.removesuffix('[menu_item_id]')
            group = soup.find('input', attrs={'name': prefix+'[is_group_order]'})
            if group is None or group.get('value') not in ('true', 'false'):
                raise CliError('unsupported_scope', 'Course order semantics not recognized.')
            params[field] = course
            params[prefix+'[is_group_order]'] = group['value']
            if group['value'] == 'false':
                quantity = soup.find(attrs={'name': prefix+'[quantity]'})
                if quantity is None:
                    raise CliError('unsupported_scope', 'Course quantity semantics not recognized.')
                params[prefix+'[quantity]'] = people
        tz = self.location(venue)
        rows = {day: {'date': day, 'status': 'unknown', 'offered_times': [], 'complete': False, 'slots': []} for day in wanted}
        if menu:
            for day, state in menu['eligible_dates'].items():
                if state is False:
                    rows[day].update(status='ineligible', complete=True)
        failures, attempted = [], set()
        while True:
            missing = [day for day, row in rows.items() if not row['complete'] and day not in attempted]
            if not missing:
                break
            day = missing[0]
            attempted.add(day)
            query = {**params, 'reservation[start_date]': day}
            try:
                value = self.client.read('GET', f"/en/shops/{venue['slug']}/available/timetable", query)
                data = value.get('data') if isinstance(value, dict) else None
                all_slots = data.get('slots') if isinstance(data, dict) else None
                if not isinstance(all_slots, dict) or value.get('queried_date') != day:
                    raise CliError('unexpected_response', 'Timetable lacks matching queried_date and slot data.')
                gained = False
                for slot_day, slots in all_slots.items():
                    if slot_day not in rows or rows[slot_day]['complete']:
                        continue
                    if not isinstance(slots, dict) or not slots:
                        failures.append({'code': 'unexpected_response', 'date': slot_day,
                                         'message': 'Timetable date has no recognizable slot grid.'})
                        continue
                    row = rows[slot_day]
                    parsed, complete = [], True
                    for epoch, slot in slots.items():
                        try:
                            local = datetime.fromtimestamp(int(epoch), tz)
                            if local.date().isoformat() != slot_day or local.second or local.microsecond or not isinstance(slot, dict) or type(slot.get('available')) is not bool:
                                raise ValueError()
                            clock = local.strftime('%H:%M')
                            if after <= clock <= before and slot['available'] and not_elapsed_today(local):
                                parsed.append((epoch, clock))
                        except (ValueError, TypeError, OverflowError, OSError):
                            complete = False
                    if not complete:
                        failures.append({'code': 'unexpected_response', 'date': slot_day,
                                         'message': 'Timetable slot timestamp or availability state is invalid.'})
                        continue
                    gained = True
                    row.update(complete=not parsed, status='unknown' if parsed else 'unavailable', source='filtered_timetable')
                    confirmed = True
                    for epoch, clock in parsed:
                        confirmation = self.client.read('GET', f"/en/shops/{venue['slug']}/available", {**params, 'reservation[start_at_epoch]': epoch})
                        state = confirmation.get('status') if isinstance(confirmation, dict) else None
                        if state == 'success':
                            row['offered_times'].append(clock)
                            row['slots'].append({'time': clock, 'start_at_epoch': epoch, 'status': 'available',
                                                 'course_id': course, 'seat_category_id': selected_seat})
                            row['status'] = 'available'
                        else:
                            confirmed = False
                            row.update(complete=False, status='unknown' if not row['offered_times'] else 'available')
                            failures.append({'code': 'slot_not_confirmed', 'date': slot_day, 'time': clock, 'source_status': state})
                    row['complete'] = confirmed
                if not gained:
                    # Do not turn sparse source output into a per-day sweep.
                    break
            except CliError as error:
                failures.append(error.as_dict())
                break
        for day, row in rows.items():
            row['offered_times'] = sorted(set(row['offered_times']))
            row['booking_url'] = booking_url(venue, day, row['offered_times'][0] if row['offered_times'] else None, people)
        missing_dates = [day for day, row in rows.items() if not row['complete']]
        if missing_dates:
            failures.append({'code': 'incomplete_coverage', 'dates': missing_dates,
                             'message': 'Filtered timetable or slot confirmation did not cover these dates.'})
        return {'restaurant': venue_summary(venue), 'from': wanted[0], 'to': wanted[-1], 'people': people, 'after': after, 'before': before,
                'course_id': course, 'seat_category_id': selected_seat, 'scope': 'filtered_reservation_form',
                'course_linked': bool(course), 'seat_linked': bool(selected_seat), 'days': list(rows.values()),
                'coverage': 'complete' if all(row['complete'] for row in rows.values()) and not failures else 'partial', 'errors': failures,
                'note': 'Positive filtered timetable slots are confirmed with a second read. No reservation or hold is created.' +
                        (' The shop API marks seats as required, but the public form has no seat selector; seat type remains unverified.'
                         if not selected_seat and venue.get('tc_input_service_category') == 'required' else '')}

    def search(self, near, radius, cuisines, budget_min, budget_max, pages, limit, start=None, end=None, people=None, after='00:00', before='23:59', with_courses=False, meal=None, area=None):
        location = None
        if area:
            location, near = self.resolve_area(area)
        radius = radius if radius is not None else 10000 if area else 1000
        lat, lon = near
        native_day = bool(start and start == end)
        params = {'geo_latitude': lat, 'geo_longitude': lon, 'geo_distance': radius, 'shop_universe_id': UNIVERSE_JAPAN,
                  'locale': 'en', 'venue_type': 'tc', 'service_mode': 'dining', 'sort_by': 'distance', 'include_ids': 'true', 'per_page': min(50, max(10, limit))}
        if native_day:
            # Omitting time returns the day's indexed slots. Apply exact-time or
            # meal bounds locally; upstream meal preferences are not exact times.
            params.update(date=start, num_people=people, availability_format='datetime')
        if cuisines:
            params['cuisines[]'] = cuisines
        if budget_min is not None:
            params['budget_dinner_avg_min'] = budget_min
        if budget_max is not None:
            params['budget_dinner_avg_max'] = budget_max
        results, seen, cursors, failures = [], set(), set(), []
        exhausted = False
        for page in range(pages):
            try:
                response = self.client.read('GET', '/v2/shop_search', params)
                shops = array(response, 'shops')
                meta = response.get('meta')
                if not isinstance(meta, dict):
                    raise CliError('unexpected_response', 'Search pagination metadata missing.')
                new = 0
                for shop in shops:
                    slug = shop.get('slug')
                    if not isinstance(slug, str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,80}', slug):
                        raise CliError('unexpected_response', 'Search restaurant identity is missing or invalid.')
                    if slug in seen:
                        continue
                    seen.add(slug)
                    new += 1
                    if cuisines and not all(c in (shop.get('cuisines') or []) for c in cuisines):
                        continue
                    geocode = shop.get('geocode') or {}
                    try:
                        shop_lat, shop_lon = float(geocode['lat']), float(geocode['lon'])
                        if not (-90 <= shop_lat <= 90 and -180 <= shop_lon <= 180):
                            raise ValueError()
                        phi1, phi2 = math.radians(lat), math.radians(shop_lat)
                        delta = math.radians(shop_lon-lon)
                        distance = 6371000*2*math.asin(min(1, math.sqrt(math.sin((phi2-phi1)/2)**2+math.cos(phi1)*math.cos(phi2)*math.sin(delta/2)**2)))
                    except (KeyError, TypeError, ValueError):
                        failures.append({'restaurant': slug, 'code': 'unverified_distance',
                                         'message': 'Missing or invalid coordinates; radius eligibility is unknown.'})
                        continue
                    if distance > radius:
                        continue
                    if budget_min is not None or budget_max is not None:
                        try:
                            price = Decimal(shop['budget_dinner_avg'])
                            if not price.is_finite() or price < 0:
                                raise InvalidOperation()
                            if budget_min is not None and price < budget_min or budget_max is not None and price > budget_max:
                                continue
                        except (KeyError, TypeError, InvalidOperation):
                            failures.append({'restaurant': slug, 'code': 'unverified_budget',
                                             'message': 'Missing or invalid dinner budget; budget eligibility is unknown.'})
                            continue
                    item = venue_summary(shop)
                    item['distance_m'] = round(distance)
                    if start:
                        inventory = (self.indexed_availability(shop, start, people, after, before) if native_day else
                                     self.availability(slug, start, end, people, after, before))
                        if inventory.get('coverage') == 'partial':
                            failures.append({'restaurant': slug, 'code': 'partial_inventory', 'errors': inventory.get('errors', [])})
                        if not any(row['offered_times'] for row in inventory['days']):
                            continue
                        item['availability'] = inventory
                    if with_courses:
                        first = start or datetime.now(ZoneInfo('Asia/Tokyo')).date().isoformat()
                        try:
                            item['courses'] = self.courses(slug, first, end or first, meal=meal, _venue=shop)['items']
                        except CliError as error:
                            item.update(courses=None, coverage='partial', errors=[{'scope': 'courses', **error.as_dict()}])
                            failures.append({'restaurant': slug, 'scope': 'courses', **error.as_dict()})
                    results.append(item)
                    if len(results) >= limit or self.client.blocked:
                        break
                if self.client.blocked:
                    break
                if len(results) >= limit:
                    break
                if shops and not new:
                    raise CliError('unexpected_response', 'Search repeated previously returned restaurants; stopping pagination.')
                cursor = meta.get('search_after')
                if meta.get('last_page') is True or not shops:
                    exhausted = True
                    break
                if not cursor or cursor in cursors:
                    raise CliError('unexpected_response', 'Search cursor missing or repeated; stopping pagination.')
                cursors.add(cursor)
                params = {**params, 'search_after': cursor}
            except CliError as error:
                failures.append(error.as_dict())
                break
        return {'items': results, 'radius_m': radius, 'center': {'lat': lat, 'lon': lon}, 'location': location,
                'geographic_scope': 'center_radius_not_administrative_boundary',
                'availability_verification': 'search_index_only' if native_day else 'venue_calendar' if start else 'not_queried',
                'sort': 'distance', 'budget_basis': 'venue_dinner_average',
                'coverage': 'partial' if failures else 'complete' if exhausted else 'limited', 'errors': failures,
                'limit_reached': len(results) >= limit, 'pages_read': page+1}
