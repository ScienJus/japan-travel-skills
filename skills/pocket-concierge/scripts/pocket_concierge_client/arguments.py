"""Command-local options; invalid combinations fail before any request."""
import argparse
from datetime import date, datetime
import math

from .service import now_japan, restaurant_id
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


def source_id(value):
    if not value.isascii() or not value.isdigit() or len(value) > 12:
        raise argparse.ArgumentTypeError('Expected a numeric source ID (1–12 digits).')
    return value


def parse_arguments(argv):
    common = argparse.ArgumentParser(add_help=False)
    for name, convert, help_text in (
        ('timeout', bounded(.1, 30), 'request timeout in seconds (default: 15)'),
        ('max-requests', bounded(1, 80, True), 'HTTP attempt budget (default: 20)'),
        ('delay-min-ms', bounded(250, 30000, True), 'minimum delay (default: 1000 ms)'),
        ('delay-max-ms', bounded(250, 30000, True), 'maximum delay (default: 2500 ms)'),
    ):
        common.add_argument('--'+name, type=convert, default=argparse.SUPPRESS, help=help_text)
    common.add_argument('--lang', choices=('ja', 'en'), default=argparse.SUPPRESS, help='source language; default ja, no extra translation requests')
    parser = Parser(prog='pocket-concierge', parents=[common], description='Anonymous read-only Pocket Concierge CLI. JSON; Japan dates. No login or booking.')
    commands = parser.add_subparsers(dest='command')

    def command(name, description, target=False):
        child = commands.add_parser(name, parents=[common], help=description, description=description)
        if target:
            child.add_argument('target', type=restaurant_id, metavar='RESTAURANT_URL_OR_ID')
        return child

    def window(child, required=False):
        group = child.add_mutually_exclusive_group(required=required)
        group.add_argument('--date', type=date_value)
        group.add_argument('--from', dest='start', type=date_value)
        child.add_argument('--to', dest='end', type=date_value)

    def course(child):
        child.add_argument('--meal', choices=('lunch', 'dinner'), help='source course service type')
        child.add_argument('--course', type=source_id, help='course ID from this restaurant')

    for name in ('filters', 'areas', 'cuisines'):
        command(name, 'Read native area and/or cuisine IDs and labels.')
    child = command('search', 'Find restaurants; optionally apply native date/party filters.')
    child.add_argument('--keyword')
    child.add_argument('--area', help='native area ID or exact label from areas; not a city boundary')
    child.add_argument('--cuisine', action='append', default=[], help='native cuisine ID or exact label')
    child.add_argument('--budget-min', type=bounded(0, 100000000, True))
    child.add_argument('--budget-max', type=bounded(0, 100000000, True))
    child.add_argument('--meal', choices=('lunch', 'dinner'))
    child.add_argument('--date', type=date_value)
    child.add_argument('--people', type=bounded(1, 99, True))
    child.add_argument('--instant', action='store_true', help='only native instant-confirmation restaurants')
    child.add_argument('--pages', type=bounded(1, 10, True), default=2)
    child.add_argument('--limit', type=bounded(1, 50, True), default=5)
    for name in ('detail', 'courses'):
        child = command(name, 'Read restaurant details and listed courses.', target=True)
        course(child)
        if name == 'detail':
            child.add_argument('--no-courses', action='store_true')
    child = command('calendar', 'Read restaurant-level date hints; no party or slot verification.', target=True)
    window(child)
    for name in ('slots', 'availability'):
        child = command(name, 'Read course-linked public slots and party ranges; waitlists stay separate.', target=True)
        if name == 'slots':
            child.add_argument('--date', required=True, type=date_value)
        else:
            window(child, required=True)
        course(child)
        child.add_argument('--people', type=bounded(1, 99, True), help='optional; omitted returns source min/max per slot')
        child.add_argument('--seat', help='exact source seatingType, e.g. COUNTER or TABLE')
        child.add_argument('--time', type=time_value, help='match exactly the reported startTime; does not expand source windows')
        child.add_argument('--after', type=time_value, help='inclusive reported startTime lower bound')
        child.add_argument('--before', type=time_value, help='inclusive reported startTime upper bound')
    command('doctor', 'Check dependencies without network requests.')
    child = command('usage', 'Sum saved CLI costs offline.')
    child.add_argument('targets', nargs='+', metavar='RESULT_JSON')
    args = parser.parse_args(argv)
    if not args.command:
        raise HelpRequested(parser.format_help())
    for key, value in {'timeout': 15, 'max_requests': 20, 'delay_min_ms': 1000, 'delay_max_ms': 2500, 'lang': 'ja'}.items():
        if not hasattr(args, key):
            setattr(args, key, value)
    if args.delay_min_ms > args.delay_max_ms:
        raise CliError('invalid_argument', '--delay-max-ms must be at least --delay-min-ms.')
    if hasattr(args, 'date'):
        if args.date and getattr(args, 'end', None) or bool(getattr(args, 'start', None)) != bool(getattr(args, 'end', None)):
            raise CliError('invalid_argument', 'Use --date or both --from/--to.')
        args.start = args.date or getattr(args, 'start', None)
        args.end = args.date or getattr(args, 'end', None)
        if args.start:
            if (date.fromisoformat(args.end)-date.fromisoformat(args.start)).days not in range(31):
                raise CliError('invalid_argument', 'Date ranges must contain 1–31 days.')
            if args.start < now_japan().date().isoformat():
                raise CliError('invalid_argument', 'Use today or future inventory dates.')
    if args.command == 'search':
        if args.people is not None and args.date is None:
            raise CliError('invalid_argument', '--people requires --date for search.')
        if args.budget_min is not None and args.budget_max is not None and args.budget_min > args.budget_max:
            raise CliError('invalid_argument', '--budget-min exceeds --budget-max.')
    if args.command == 'detail' and args.no_courses and (args.course or args.meal):
        raise CliError('invalid_argument', '--no-courses cannot be combined with course filters.')
    if hasattr(args, 'time'):
        if args.time and (args.after or args.before):
            raise CliError('invalid_argument', '--time cannot be combined with --after/--before.')
        args.after, args.before = (args.time, args.time) if args.time else (args.after or '00:00', args.before or '23:59')
        if args.after > args.before:
            raise CliError('invalid_argument', 'Overnight start-time windows are not supported.')
    return args
