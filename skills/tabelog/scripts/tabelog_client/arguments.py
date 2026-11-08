"""Argparse subcommands with shared request controls and command-local options."""
import argparse

from .core import CliError, date_value, time_value


class HelpRequested(Exception):
    """Return generated help through run() without printing or exiting."""


class Parser(argparse.ArgumentParser):
    def __init__(self, *args, **kwargs):
        kwargs.setdefault('allow_abbrev', False)
        super().__init__(*args, **kwargs)

    def error(self, message):
        raise CliError('invalid_argument', message,
                       usage=self.format_usage().strip(),
                       help_command=self.prog + ' --help')

    def print_help(self, file=None):
        raise HelpRequested(self.format_help())


def bounded(low, high, integer=False):
    def convert(value):
        try:
            number = float(value)
            if not low <= number <= high or integer and not number.is_integer():
                raise ValueError()
            return int(number) if integer else number
        except (ValueError, TypeError):
            raise argparse.ArgumentTypeError(
                f"Expected {'integer' if integer else 'number'} in [{low}, {high}].") from None
    return convert


REQUEST_DEFAULTS = {'timeout': 15, 'max_requests': 80, 'delay_min_ms': 1000, 'delay_max_ms': 2500}


def build_parser():
    common = argparse.ArgumentParser(add_help=False)
    request = common.add_argument_group('request controls')
    # Suppress child defaults so flags before the command survive child parsing.
    request.add_argument('--timeout', type=bounded(.1, 30), default=argparse.SUPPRESS,
                         help='retrieval timeout in seconds (default: 15)')
    request.add_argument('--max-requests', type=bounded(1, 200, True), default=argparse.SUPPRESS,
                         help='top-level read budget (default: 80)')
    request.add_argument('--delay-min-ms', type=bounded(250, 30000, True), default=argparse.SUPPRESS,
                         help='minimum same-site delay in milliseconds (default: 1000)')
    request.add_argument('--delay-max-ms', type=bounded(250, 30000, True), default=argparse.SUPPRESS,
                         help='maximum same-site delay in milliseconds (default: 2500)')
    parser = Parser(prog='tabelog', parents=[common],
                    description='Read-only restaurant CLI (JSON; Japan dates). No login or reservation submission.')
    commands = parser.add_subparsers(dest='command', title='commands')

    def command(name, description, target=None):
        child = commands.add_parser(name, parents=[common], help=description, description=description)
        if target:
            child.add_argument('target', metavar=target)
        return child

    def pagination(child, limit=5):
        child.add_argument('--pages', type=bounded(1, 10, True), default=2, help='page cap (default: 2)')
        child.add_argument('--limit', type=bounded(1, 50, True), default=limit,
                           help=f'maximum returned results (default: {limit})')

    def booking(child):
        child.add_argument('--people', type=bounded(1, 99, True),
                           help='party size; omit to discover selectable sizes (1–99)')

    def date_window(child, required=True):
        window = child.add_mutually_exclusive_group(required=required)
        window.add_argument('--date', type=date_value, metavar='YYYY-MM-DD')
        window.add_argument('--from', dest='start', type=date_value, metavar='YYYY-MM-DD')
        child.add_argument('--to', dest='end', type=date_value, metavar='YYYY-MM-DD')

    command('suggest', 'Suggest areas, stations, cuisines, or restaurants.', 'QUERY')
    command('station', 'Resolve a station and verify its WGS84 coordinates.', 'STATION')
    child = command('geocode', 'Find Japanese place/address coordinate candidates.', 'PLACE_OR_ADDRESS')
    child.add_argument('--provider', choices=('gsi', 'photon'), default='gsi', help='geocoder: official GSI (default), or explicit Photon/OpenStreetMap')
    child.add_argument('--limit', type=bounded(1, 50, True), default=5)

    child = command('areas', 'List prefectures offline, or descend into search areas/municipal neighborhoods.')
    scope = child.add_mutually_exclusive_group()
    scope.add_argument('--prefecture', metavar='CODE_OR_NAME')
    scope.add_argument('--parent', metavar='AREA1_ID')
    scope.add_argument('--city', metavar='CITY_NAME')
    child = command('stations', 'List stations in a Tabelog search area, not municipal boundaries.')
    child.add_argument('--area', required=True, metavar='AREA2_ID')
    command('hyakumeiten-categories', 'List current native Hyakumeiten categories.')

    child = command('search', 'Find restaurants in rating order; stop once enough results match.')
    location = child.add_argument_group('location')
    location.add_argument('--area', help='area name; may also be an explicit fallback for --near')
    location.add_argument('--station', help='station name; exclusive with --area and --near')
    location.add_argument('--near', metavar='LAT,LON', help='WGS84 coordinates')
    location.add_argument('--radius-m', type=bounded(1, 50000), default=1000)
    child.add_argument('--min-rating', type=bounded(0, 5))
    child.add_argument('--cuisine', action='append', default=[])
    child.add_argument('--meal', choices=('lunch', 'dinner'))
    child.add_argument('--hyakumeiten', action='store_true')
    child.add_argument('--budget-meal', choices=('lunch', 'dinner'),
                       help='budget meal; inherits --meal, otherwise matches either meal')
    child.add_argument('--budget-min', type=bounded(0, 100000000, True), metavar='YEN')
    child.add_argument('--budget-max', type=bounded(0, 100000000, True), metavar='YEN')
    child.add_argument('--open-date', type=date_value, metavar='YYYY-MM-DD')
    child.add_argument('--open-at', type=time_value, metavar='HH:MM',
                       help='opening time; without --open-date returns matching regular weekdays')
    child.add_argument('--open-until', type=time_value, metavar='HH:MM')
    pagination(child)

    command('detail', 'Read restaurant details and listed courses.', 'RESTAURANT_URL_OR_ID')
    child = command('awards', 'Verify individual Hyakumeiten badges.', 'RESTAURANT_URL_OR_ID')
    child.add_argument('--year', type=bounded(2000, 2100, True))
    child.add_argument('--category', action='append', help='one official award category slug')
    command('channel', 'Check evidence for a Tabelog online reservation channel.', 'RESTAURANT_URL_OR_ID')
    child = command('reviews', 'Read reviews by visit date, optionally filtered by meal.', 'RESTAURANT_URL_OR_ID')
    child.add_argument('--since', type=date_value, metavar='YYYY-MM-DD')
    child.add_argument('--until', type=date_value, metavar='YYYY-MM-DD')
    child.add_argument('--meal', choices=('all', 'lunch', 'dinner'))
    child.add_argument('--full', action='store_true')
    pagination(child, limit=20)
    command('review-read', 'Read all visits in a full review.', 'REVIEW_URL')

    for name, description in (('calendar', 'Read a date overview; add dates for selectable party-size ranges. No time-slot checks.'),
                              ('slots', 'Check date/party-specific time slots.')):
        child = command(name, description, 'RESTAURANT_URL_OR_ID')
        if name == 'calendar':
            date_window(child, required=False)
        else:
            child.add_argument('--date', required=True, type=date_value, metavar='YYYY-MM-DD')
        booking(child)
        if name == 'slots':
            child.add_argument('--time', type=time_value, metavar='HH:MM', help='optional anchor; otherwise use the upstream default')
    child = command('availability', 'Screen the calendar, then verify candidate dates and time slots.', 'RESTAURANT_URL_OR_ID')
    date_window(child)
    booking(child)
    child.add_argument('--time', type=time_value, metavar='HH:MM', help='optional anchor; otherwise use the upstream default')
    child.add_argument('--after', type=time_value, default='00:00', metavar='HH:MM')
    child.add_argument('--before', type=time_value, default='23:59', metavar='HH:MM')

    child = command('source', 'Read diagnostic source using the same anonymous request policy.', 'HTTPS_URL')
    child.add_argument('--prime', metavar='HTTPS_URL', help='visit this URL first in the same anonymous session')
    command('doctor', 'Check runtime dependencies without network requests.')
    child = command('usage', 'Aggregate recorded CLI usage without network requests.')
    child.add_argument('targets', nargs='+', metavar='RESULT_JSON')
    return parser


def parse_arguments(argv):
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command is None:
        raise HelpRequested(parser.format_help())
    for key, default in REQUEST_DEFAULTS.items():
        if not hasattr(args, key):
            setattr(args, key, default)
    if args.delay_max_ms < args.delay_min_ms:
        raise CliError('invalid_argument', '--delay-max-ms must be at least --delay-min-ms.')
    if args.command in ('calendar', 'availability') and (args.date and args.end or args.start and not args.end or args.end and not args.start):
        raise CliError('invalid_argument', 'Use --date or both --from/--to.')
    return args
