"""Public discovery and calendar-screened inventory with separate evidence scopes."""
from datetime import date, datetime, timedelta, timezone
import math
import re
from urllib.parse import urlsplit

from .transport import CliError
from .detail_info import practical_info

JAPAN = timezone(timedelta(hours=9))


def now_japan():
    return datetime.now(JAPAN)


def source_id(value):
    if not isinstance(value, str) or not re.fullmatch(r'[0-9]{1,12}', value):
        raise CliError('unexpected_response', 'Source identity is missing or invalid.')
    return value


def restaurant_id(value):
    try:
        if '://' in value:
            url = urlsplit(value)
            if url.scheme != 'https' or url.hostname not in ('www.pocket-concierge.jp', 'pocket-concierge.jp') or url.port not in (None, 443) or url.username or url.password:
                raise ValueError()
            match = re.fullmatch(r'/(?:ja/|en/)?restaurants/([0-9]{1,12})/?', url.path)
            value = match[1] if match else ''
        if not re.fullmatch(r'[0-9]{1,12}', value):
            raise ValueError()
        return value
    except (ValueError, TypeError):
        raise CliError('invalid_argument', 'Use a public HTTPS Pocket Concierge restaurant URL or numeric ID.') from None


def array(value, key):
    if not isinstance(value, dict) or not isinstance(value.get(key), list):
        raise CliError('unexpected_response', f'Missing or invalid {key}; data is unknown.')
    return value[key]


def identity(value):
    if not isinstance(value, dict) or not isinstance(value.get('name'), str) or not value['name'].strip():
        raise CliError('unexpected_response', 'Source restaurant/course identity is missing.')
    source_id(value.get('id'))
    return value


def mode(value):
    if value is not None and type(value) is not bool:
        raise CliError('unexpected_response', 'Booking mode is not recognized.')
    return 'instant_confirmation' if value is True else 'reservation_request' if value is False else None


def summary(value, lang):
    identity(value)
    return {'id': value['id'], 'name': value['name'], 'name_ja': value['name'] if lang == 'ja' else None,
            'url': f"https://www.pocket-concierge.jp/{lang}/restaurants/{value['id']}",
            'booking_mode': mode(value.get('realTimeBooking')), 'area': value.get('area'),
            'cuisines': value.get('cuisines'), 'price_ranges': value.get('priceRanges')}


def course_view(value):
    identity(value)
    for field in ('costPerGuest', 'fixedPrice'):
        number = value.get(field)
        if number is not None and (type(number) not in (int, float) or not math.isfinite(number) or number < 0):
            raise CliError('unexpected_response', 'Course price is invalid.')
    return {'id': value['id'], 'name': value['name'], 'meal': value.get('serviceType'),
            'price': {'currency': 'JPY', 'per_guest': value.get('costPerGuest'), 'fixed_per_group': value.get('fixedPrice'),
                      'fixed_title': value.get('fixedTitle'), 'all_in_total': None},
            'summary': value.get('summary'), 'supplementary_information': value.get('supplementaryInformation'),
            'scope': 'listed_course_not_slot_inventory'}


def date_list(values):
    if not isinstance(values, list):
        raise CliError('unexpected_response', 'Calendar date arrays are missing.')
    try:
        if any(not isinstance(day, str) or date.fromisoformat(day).isoformat() != day for day in values):
            raise ValueError()
    except ValueError:
        raise CliError('unexpected_response', 'Calendar returned an invalid date.') from None
    return set(values)


def days(start, end):
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if not 0 <= (last-first).days <= 30:
        raise CliError('invalid_argument', 'Date ranges must contain 1–31 days.')
    return [(first+timedelta(days=index)).isoformat() for index in range((last-first).days+1)]


class PocketConcierge:
    def __init__(self, client, lang='ja'):
        self.client, self.lang = client, lang

    def read(self, operation, variables=None):
        return self.client.read(operation, variables, self.lang)

    def venue(self, value, ident):
        venue = value.get('venue')
        if venue is None:
            raise CliError('not_found', 'Restaurant not returned by the public source.')
        identity(venue)
        if venue['id'] != ident:
            raise CliError('unexpected_response', 'Restaurant identity does not match the request.')
        mode(venue.get('realTimeBooking'))
        return venue

    def filters(self):
        value = self.read('filters')
        result = {key: array(value, key) for key in ('areas', 'cuisines')}
        for items in result.values():
            for item in items:
                identity(item)
        return result

    def resolve(self, value, dimension):
        if re.fullmatch(r'[0-9]{1,12}', value):
            return value
        matches = [item for item in self.filters()[dimension] if item['name'].casefold() == value.casefold()]
        if len(matches) != 1:
            raise CliError('invalid_argument', f'Use a native {dimension} ID or exact label from the catalog.')
        return matches[0]['id']

    def search(self, keyword=None, area=None, cuisines=None, meal=None, budget_min=None, budget_max=None,
               day=None, people=None, instant=False, pages=2, limit=5):
        variables = {'keyword': keyword, 'areas': [self.resolve(area, 'areas')] if area else None,
                     'cuisines': [self.resolve(value, 'cuisines') for value in cuisines or []] or None,
                     'meal': [meal.upper()] if meal else None, 'min': budget_min, 'max': budget_max,
                     'date': day, 'people': people, 'instant': True if instant else None}
        variables = {key: value for key, value in variables.items() if value is not None}
        items, seen, errors, metadata = [], set(), [], None
        exhausted, read_pages = False, 0
        for page in range(1, pages+1):
            try:
                value = self.read('search', {**variables, 'page': {'page': page, 'limit': max(10, limit)}})
                result = value.get('venuesSearch')
                collection = array(result, 'collection')
                metadata = result.get('metadata')
                if not isinstance(metadata, dict) or any(type(metadata.get(key)) is not int or metadata[key] < 0 for key in ('currentPage', 'limitValue', 'totalCount', 'totalPages')) or metadata['currentPage'] != page or metadata['limitValue'] < 1:
                    raise CliError('unexpected_response', 'Search pagination metadata does not match the requested page.')
                read_pages += 1
                new = 0
                for venue in collection:
                    item = summary(venue, self.lang)
                    if item['id'] in seen:
                        continue
                    seen.add(item['id'])
                    new += 1
                    if instant and item['booking_mode'] != 'instant_confirmation':
                        raise CliError('unexpected_response', 'Instant-confirmation filter was not reflected in the response.')
                    items.append(item)
                    if len(items) >= limit:
                        break
                exhausted = not collection or page >= metadata['totalPages']
                if exhausted or len(items) >= limit:
                    break
                if not new:
                    raise CliError('unexpected_response', 'Search repeated previously returned restaurants; pagination stopped.')
            except CliError as error:
                errors.append(error.as_dict())
                break
        return {'items': items, 'filters': variables, 'pages_read': read_pages, 'source_metadata': metadata,
                'coverage': 'partial' if errors else 'limited' if len(items) >= limit else 'complete' if exhausted else 'limited', 'errors': errors,
                'limit_reached': len(items) >= limit, 'verification': 'search_results_only',
                'note': 'Native search results include request booking. Date/party filters do not confirm course/seat-specific sessions; use slots. Areas are provider search regions, not municipal boundaries.'}

    def detail(self, target, include_courses=True, meal=None, course=None, only_courses=False):
        ident = restaurant_id(target)
        operation = 'courses' if only_courses else 'detail' if include_courses else 'detail_basic'
        venue = self.venue(self.read(operation, {'id': ident}), ident)
        result = summary(venue, self.lang)
        result.update({key: venue.get(field) for key, field in (
            ('address', 'localizedAddress'), ('address_hidden', 'addressHidden'), ('business_hours', 'businessHours'),
            ('holidays', 'holidays'), ('description', 'longDescription'), ('nearest_stations', 'nearestStations'),
            ('reservation_terms', 'reservationTerms'), ('services', 'services'),
            ('transactions_allowed', 'transactionsAllowed'), ('faq', 'frequentlyAskedQuestions'))})
        if include_courses:
            courses = [course_view(item) for item in array(venue, 'courses')]
            if course and not any(item['id'] == course for item in courses):
                raise CliError('not_found', 'Course not listed for this restaurant.')
            result['courses'] = [item for item in courses if (not course or item['id'] == course) and (not meal or item['meal'] == meal.upper())]
        result['price_note'] = 'Course and restaurant fee statements may differ; retain both. No all-in total or date eligibility is inferred.'
        if not only_courses:
            result['practical_info'] = practical_info(venue, result['url'])
        return result

    def calendar(self, target, start=None, end=None):
        ident = restaurant_id(target)
        venue = self.venue(self.read('calendar', {'id': ident}), ident)
        cal = venue.get('availabilityCalendar')
        reservation = date_list(cal.get('reservationDates') if isinstance(cal, dict) else None)
        waitlist = date_list(cal.get('waitlistDates'))
        today = now_japan().date().isoformat()
        requested = days(start, end) if start else sorted(day for day in reservation | waitlist if day >= today)
        rows = [{'date': day, 'reservation_hint': day in reservation, 'waitlist_hint': day in waitlist} for day in requested]
        return {'restaurant': summary(venue, self.lang), 'days': rows, 'people': None,
                'scope': 'restaurant_date_signals', 'coverage': 'complete' if start else 'returned_overview',
                'verification': 'calendar_only', 'note': 'Dates are not party, course or seat specific. A missing reservation hint does not establish sold-out or closed status.'}

    def slots(self, target, day, people=None, meal=None, course=None, seat=None, after='00:00', before='23:59'):
        ident = restaurant_id(target)
        value = self.read('slots', {'id': ident, 'date': day})
        venue = self.venue(value, ident)
        if course and not any(item.get('id') == course for item in array(venue, 'courses')):
            raise CliError('not_found', 'Course not listed for this restaurant.')
        booking_mode = mode(venue.get('realTimeBooking'))
        slots, waitlist, unverified, errors, seen = [], [], [], [], set()
        for raw in array(value, 'availabilitySearch'):
            try:
                if not isinstance(raw, dict) or raw.get('__typename') not in ('ReservableAvailability', 'WaitlistableAvailability'):
                    raise CliError('unexpected_response', 'Availability type is not recognized.')
                is_waitlist = raw['__typename'] == 'WaitlistableAvailability'
                menu = course_view(raw.get('course'))
                if course and menu['id'] != course or meal and menu['meal'] is not None and menu['meal'] != meal.upper():
                    continue
                start_value, end_value = raw.get('startTime'), raw.get('endTime')
                if not isinstance(start_value, str) or end_value is not None and not isinstance(end_value, str):
                    raise ValueError()
                start_at = datetime.fromisoformat(start_value.replace('Z', '+00:00'))
                end_at = datetime.fromisoformat(end_value.replace('Z', '+00:00')) if end_value is not None else None
                if start_at.tzinfo is None or start_at.second or start_at.microsecond or start_at.astimezone(JAPAN).date().isoformat() != day or end_at and (end_at.tzinfo is None or end_at < start_at):
                    raise ValueError()
                local = start_at.astimezone(JAPAN)
                if local <= now_japan() or not after <= local.strftime('%H:%M') <= before:
                    continue
                minimum, maximum = raw.get('minPartySize'), raw.get('maxPartySize')
                if any(bound is not None and (type(bound) is not int or bound < 1) for bound in (minimum, maximum)) or minimum is not None and maximum is not None and minimum > maximum:
                    raise CliError('unexpected_response', 'Party-size bounds are invalid.')
                if people is not None and (minimum is not None and people < minimum or maximum is not None and people > maximum):
                    continue
                seating = raw.get('seatingType')
                if seat and seating is not None and seating != seat:
                    continue
                session = None if is_waitlist else source_id(raw.get('id'))
                key = (session, menu['id'], raw['startTime'], raw.get('endTime'), seating, minimum, maximum, raw['__typename'])
                if key in seen:
                    continue
                seen.add(key)
                unknown = []
                if minimum is None or maximum is None:
                    unknown.append('party_bounds')
                if seat and seating is None:
                    unknown.append('seat')
                if meal and menu['meal'] is None:
                    unknown.append('meal')
                if not is_waitlist and booking_mode is None:
                    unknown.append('booking_mode')
                item = {'session_id': session, 'course_id': menu['id'], 'course': menu, 'seating_type': seating,
                        'start_time': raw['startTime'], 'end_time': raw.get('endTime'), 'source_type': raw['__typename'],
                        'min_people': minimum, 'max_people': maximum,
                        'people_match': True if people is not None and minimum is not None and maximum is not None else None,
                        'status': 'waitlist' if is_waitlist else booking_mode, 'unknown': unknown}
                if unknown:
                    errors.append({'code': 'unverified_session', 'session_id': session, 'course_id': menu['id'],
                                   'fields': unknown, 'message': 'Required session fields are missing; eligibility is unknown.'})
                if is_waitlist:
                    waitlist.append(item)
                elif unknown:
                    unverified.append(item)
                else:
                    slots.append(item)
            except (KeyError, TypeError, ValueError):
                errors.append({'code': 'unexpected_response', 'message': 'Invalid source slot timestamp or structure; inventory remains unknown.'})
            except CliError as error:
                errors.append(error.as_dict())
        complete = not errors and not unverified and not any(item['unknown'] for item in waitlist)
        state = ('available' if booking_mode == 'instant_confirmation' else 'requestable') if slots else 'unknown' if not complete else 'waitlist_only' if waitlist else 'no_matching_session'
        return {'restaurant': summary(venue, self.lang), 'date': day, 'people': people,
                'meal': meal, 'course_id': course, 'seat': seat, 'after': after, 'before': before,
                'status': state, 'slots': slots, 'waitlist': waitlist, 'unverified': unverified,
                'coverage': 'complete' if complete else 'partial', 'errors': errors,
                'verification': 'public_sessions', 'coverage_basis': 'returned_sessions_and_start_times',
                'note': 'Party bounds are supported group sizes, not remaining seats. Time filters apply to source startTime only; endTime is not a promised meal end or an invitation to invent intermediate starts. No reservation is created.'}

    def availability(self, target, start, end, **filters):
        requested = days(start, end)
        if len(requested) == 1:
            row = self.slots(target, start, **filters)
            return {**row, 'from': start, 'to': end, 'query_plan': 'single_date_sessions'}
        overview = self.calendar(target, start, end)
        rows, errors = [], []
        for hint in overview['days']:
            day = hint['date']
            if not hint['reservation_hint']:
                rows.append({**hint, 'status': 'calendar_waitlist_hint' if hint['waitlist_hint'] else 'calendar_no_reservation_signal',
                             'verification': 'calendar_only', 'slots': None, 'people_match': None})
                continue
            try:
                result = self.slots(target, day, **filters)
                rows.append(result)
                if result['coverage'] == 'partial':
                    errors.append({'date': day, 'code': 'partial_sessions', 'errors': result['errors']})
            except CliError as error:
                errors.append({'date': day, **error.as_dict()})
                rows.append({'date': day, 'status': 'unknown', 'verification': 'failed', 'slots': None})
                if self.client.blocked or error.code in ('request_budget', 'not_found'):
                    for remaining in overview['days'][len(rows):]:
                        rows.append({**remaining, 'status': 'unknown', 'verification': 'not_queried', 'slots': None})
                    break
        return {'restaurant': overview['restaurant'], 'from': start, 'to': end, 'people': filters.get('people'),
                'filters': filters, 'days': rows, 'coverage': 'partial' if errors else 'complete', 'errors': errors,
                'query_plan': 'calendar_then_candidate_dates', 'coverage_basis': 'calendar_exclusions_and_returned_sessions',
                'note': 'Calendar-only rows are not party/course/seat checks. Unknowns, request booking and waitlists are not confirmed reservations.'}
