"""Command-local argparse options matching the Tabelog CLI where meaningful."""
import argparse
from datetime import date, datetime, timedelta
import json
import math
from zoneinfo import ZoneInfo

from .transport import CliError


class HelpRequested(Exception):
    pass


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, allow_abbrev=False, **kwargs)

    def error(self, message):
        raise CliError('invalid_argument', message)

    def print_help(self, file=None):
        raise HelpRequested(self.format_help())


def bounded(low, high, integer=False):
    def convert(value):
        try:
            number = float(value)
            if not math.isfinite(number) or not low <= number <= high or integer and not number.is_integer():
                raise ValueError()
            return int(number) if integer else number
        except (ValueError, TypeError):
            raise argparse.ArgumentTypeError(f'Expected a number in [{low}, {high}].') from None
    return convert


def date_value(value):
    try:
        if date.fromisoformat(value).isoformat() != value:
            raise ValueError()
        return value
    except ValueError:
        raise argparse.ArgumentTypeError('Expected YYYY-MM-DD.') from None


def time_value(value):
    try:
        if datetime.strptime(value, '%H:%M').strftime('%H:%M') != value:
            raise ValueError()
        return value
    except ValueError:
        raise argparse.ArgumentTypeError('Expected HH:MM.') from None


def coordinates(value):
    try:
        lat, lon = map(float, value.split(','))
        if not (-90 <= lat <= 90 and -180 <= lon <= 180):
            raise ValueError()
        return lat, lon
    except ValueError:
        raise argparse.ArgumentTypeError('Expected WGS84 LAT,LON.') from None


def parse_arguments(argv):
    common = argparse.ArgumentParser(add_help=False)
    for flag, convert, help_text in (
        ('timeout', bounded(.1, 30), 'seconds per request (default: 15)'),
        ('max-requests', bounded(1, 80, True), 'HTTP attempt budget (default: 20)'),
        ('delay-min-ms', bounded(250, 30000, True), 'minimum delay (default: 1000 ms)'),
        ('delay-max-ms', bounded(250, 30000, True), 'maximum delay (default: 2500 ms)'),
    ):
        common.add_argument('--'+flag, type=convert, default=argparse.SUPPRESS, help=help_text)
    parser = Parser(prog='tablecheck', parents=[common], description='Anonymous read-only TableCheck CLI (JSON; venue local dates). No login or reservation submission.')
    commands = parser.add_subparsers(dest='command')

    def command(name, description, target=None):
        child = commands.add_parser(name, parents=[common], help=description, description=description)
        if target:
            child.add_argument('target', metavar=target)
        return child

    def window(child, required=False):
        group = child.add_mutually_exclusive_group(required=required)
        group.add_argument('--date', type=date_value)
        group.add_argument('--from', dest='start', type=date_value)
        child.add_argument('--to', dest='end', type=date_value)

    def clock(child):
        child.add_argument('--meal', choices=('lunch', 'dinner'), help='lunch 11:00–15:00; dinner 17:00–21:00 local')
        child.add_argument('--time', type=time_value, help='one exact requested time')
        child.add_argument('--after', type=time_value)
        child.add_argument('--before', type=time_value)

    command('suggest', 'Find restaurants and native location suggestions by name.', 'QUERY')
    command('cuisines', 'List native cuisine keys and labels.')
    for name in ('detail', 'courses'):
        child = command(name, 'Read restaurant details and courses.' if name == 'detail' else 'Read courses and their listed conditions.', 'RESTAURANT_URL_OR_SLUG')
        window(child)
        child.add_argument('--meal', choices=('lunch', 'dinner'))
        child.add_argument('--course', help='exact course ID from this restaurant')
        if name == 'detail':
            child.add_argument('--no-courses', action='store_true')
    child = command('search', 'Find restaurants and native single-date availability in a location radius.')
    location = child.add_mutually_exclusive_group(required=True)
    location.add_argument('--near', type=coordinates)
    location.add_argument('--area', help='native city/area suggestion; searches around its center, not administrative boundaries')
    child.add_argument('--radius-m', type=bounded(1, 50000), help='default: 1000 with --near, 10000 with --area')
    child.add_argument('--cuisine', action='append', default=[])
    child.add_argument('--budget-min', type=bounded(0, 100000000, True))
    child.add_argument('--budget-max', type=bounded(0, 100000000, True))
    child.add_argument('--pages', type=bounded(1, 10, True), default=2)
    child.add_argument('--limit', type=bounded(1, 50, True), default=5)
    child.add_argument('--with-courses', action='store_true')
    child.add_argument('--people', type=bounded(1, 99, True))
    window(child)
    clock(child)
    for name in ('calendar', 'slots', 'availability'):
        child = command(name, 'Read party-specific dates and times; optionally constrain a course or seat.', 'RESTAURANT_URL_OR_SLUG')
        if name == 'slots':
            child.add_argument('--date', required=True, type=date_value)
        else:
            window(child, required=True)
        child.add_argument('--people', required=True, type=bounded(1, 99, True), help='explicit adults; no automatic party-size sweep')
        child.add_argument('--course', help='exact course ID')
        child.add_argument('--seat', help='exact seat category ID or its English/Japanese name')
        clock(child)
    child = command('source', 'Read an allowed public endpoint for diagnostics.', 'READ_ENDPOINT_PATH')
    child.add_argument('--params', type=json.loads)
    child.add_argument('--body', type=json.loads)
    command('doctor', 'Check dependencies without network requests.')
    child = command('usage', 'Sum recorded CLI costs offline.')
    child.add_argument('targets', nargs='+', metavar='RESULT_JSON')
    args = parser.parse_args(argv)
    if not args.command:
        raise HelpRequested(parser.format_help())
    for key, value in {'timeout': 15, 'max_requests': 20, 'delay_min_ms': 1000, 'delay_max_ms': 2500}.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    if args.delay_min_ms > args.delay_max_ms:
        raise CliError('invalid_argument', '--delay-max-ms must be at least --delay-min-ms.')
    if hasattr(args, 'start'):
        if args.start and not args.end or args.end and not args.start or args.date and args.end:
            raise CliError('invalid_argument', 'Use --date or both --from/--to.')
    if hasattr(args, 'date'):
        args.start = args.date or getattr(args, 'start', None)
        args.end = args.date or getattr(args, 'end', None)
        args.window_requested = bool(args.start)
        if args.start and (date.fromisoformat(args.end)-date.fromisoformat(args.start)).days not in range(31):
            raise CliError('invalid_argument', 'Date ranges must contain 1–31 days.')
        today = datetime.now(ZoneInfo('Asia/Tokyo')).date()
        if args.command in ('search', 'calendar', 'slots', 'availability') and args.start and args.start < today.isoformat():
            raise CliError('invalid_argument', 'Use today or future availability dates.')
        if args.command in ('detail', 'courses') and not args.start:
            args.start, args.end = today.isoformat(), (today+timedelta(days=30)).isoformat()
    if args.command == 'detail' and args.no_courses and (args.course or args.meal or args.window_requested):
        raise CliError('invalid_argument', '--no-courses cannot be combined with course filters.')
    if args.command == 'search':
        if args.budget_min is not None and args.budget_max is not None and args.budget_min > args.budget_max:
            raise CliError('invalid_argument', '--budget-min exceeds --budget-max.')
        if bool(args.start) != bool(args.people):
            raise CliError('invalid_argument', 'Date-filtered search requires --people, and --people requires dates.')
        if not args.start and any(getattr(args, field) for field in ('meal', 'time', 'after', 'before')):
            raise CliError('invalid_argument', 'Meal/time inventory filters require dates and --people.')
    if hasattr(args, 'time'):
        if args.time and (args.meal or args.after or args.before):
            raise CliError('invalid_argument', '--time cannot be combined with --meal/--after/--before.')
        lower, upper = {'lunch': ('11:00', '15:00'), 'dinner': ('17:00', '21:00')}.get(args.meal, ('00:00', '23:59'))
        args.after, args.before = (args.time, args.time) if args.time else (args.after or lower, args.before or upper)
        if args.before < args.after or args.meal and not (lower <= args.after <= args.before <= upper):
            raise CliError('invalid_argument', 'Invalid time range; meal bounds must remain inside the documented meal window.')
    return args
