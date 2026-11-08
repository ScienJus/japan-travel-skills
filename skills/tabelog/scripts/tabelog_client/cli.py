"""Unified JSON command-line interface. No subprocess or browser backend."""
import json
import re
import sys
from importlib.metadata import version

from .arguments import HelpRequested, parse_arguments
from .core import CliError, today_japan, month_ago, stamp, public_url
from .transport import Client
from .service import Tabelog
from .catalog import Catalog
from .geo import geocode
from .reports import aggregate_usage
from .redaction import redact_source


def run(argv, create_client=Client):
    client = None
    try:
        args = parse_arguments(argv)
        command = args.command
        client = create_client(timeout=args.timeout, max_requests=args.max_requests,
                               delay_min_ms=args.delay_min_ms, delay_max_ms=args.delay_max_ms)
        app = Tabelog(client)
        if command == 'usage':
            data = aggregate_usage(args.targets)
        elif command == 'doctor':
            data = {'python': sys.version.split()[0], 'httpx': version('httpx'),
                    'beautifulsoup4': version('beautifulsoup4'), 'jpholiday': version('jpholiday'),
                    'policy': ['verified_api', 'http_html_parser'],
                    'automatic_gui': False, 'browser_required': False, 'node_required': False,
                    'http_backend': 'Python HTTPX pooled Client; environment proxies and anonymous per-command cookies',
                    'note': 'No browser, curl impersonation or Node.js backend is installed or launched by this CLI.'}
        elif command == 'suggest':
            data = {'items': app.suggest(args.target)}
        elif command == 'station':
            data = app.station(args.target)
        elif command == 'hyakumeiten-categories':
            data = app.hyakumeiten_categories()
        elif command == 'geocode':
            data = geocode(client, args.target, provider=args.provider, limit=args.limit)
        elif command == 'areas':
            data = Catalog(app).areas(prefecture=args.prefecture, parent=args.parent, city=args.city)
        elif command == 'stations':
            data = Catalog(app).stations(args.area)
        elif command == 'source':
            public_url(args.target)
            if args.prime:
                client.read(args.prime, 'html', lambda _body, _url: None)
            data = client.read(args.target, 'text', lambda body, url: {
                'url': url, 'body': redact_source(body), 'redaction': 'form_verification_values_and_google_api_keys'})
        elif command == 'search':
            if args.station and (args.near or args.area):
                raise CliError('invalid_argument', '--station is exclusive with --area/--near.')
            data = app.search(area=args.area, station=args.station, near=args.near, radius=args.radius_m,
                              min_rating=args.min_rating, cuisines=args.cuisine, pages=args.pages,
                              limit=args.limit, hyakumeiten=args.hyakumeiten,
                              meal=args.meal, budget_min=args.budget_min,
                              budget_max=args.budget_max, budget_meal=args.budget_meal,
                              open_date=args.open_date, open_at=args.open_at, open_until=args.open_until)
        elif command == 'detail':
            data = app.detail(args.target, include_courses=True)
        elif command == 'awards':
            if args.category and len(args.category) > 1:
                raise CliError('invalid_argument', 'awards accepts one official category slug.')
            data = app.awards(args.target, year=args.year, category=args.category[0] if args.category else None)
        elif command == 'channel':
            data = app.channel(args.target)
        elif command == 'reviews':
            data = app.reviews(args.target, since=args.since or month_ago(), until=args.until or today_japan(),
                               pages=args.pages, limit=args.limit, full=args.full, meal=args.meal)
        elif command == 'review-read':
            data = app.review_read(args.target)
        elif command == 'calendar':
            data = app.calendar_query(args.target, args.date or args.start,
                                      end=args.date or args.end, people=args.people)
        elif command == 'slots':
            if args.date < today_japan():
                raise CliError('invalid_argument', 'Use today or a future date.')
            ident = args.target if re.fullmatch(r'\d{1,12}', args.target) else app.ref(args.target)['id']
            data = {'restaurant_id': ident, 'date': args.date, 'people': args.people, 'anchor_time': args.time}
            if args.people is None:
                data.update(app.all_party_slots(ident, args.date, args.time))
            else:
                data.update(anchor_time=args.time, offered_times=app.slots(ident, args.date, args.people, args.time))
        elif command == 'availability':
            data = app.availability(args.target, start=args.date or args.start, end=args.date or args.end,
                                    people=args.people, time=args.time, after=args.after, before=args.before)
        errors = list(data.get('errors') or []) if command != 'source' else []
        if command != 'source' and data.get('error'):
            errors.append(data['error'])
        for entry in client.trace:
            if entry.get('status') == 'error':
                errors.append({'scope': 'request', **{key: entry[key] for key in
                               ('code', 'message', 'url', 'http_status', 'exception_type') if key in entry}})
        partial = data.get('coverage') == 'partial' or bool(errors)
        if partial and not errors:
            errors.append({'code': 'incomplete_result', 'message': 'Some requested data could not be verified; inspect data for unknown fields.'})
        return {'output': {'status': 'partial' if partial else 'ok', 'command': command,
                           'checked_at': stamp(), 'timezone': 'Asia/Tokyo', 'data': data,
                           **({'errors': errors} if partial else {}),
                           'usage': client.usage(), 'trace': client.trace}, 'exit_code': 3 if partial else 0}
    except HelpRequested as help_requested:
        return {'help': str(help_requested), 'exit_code': 0}
    except Exception as error:
        error = error if isinstance(error, CliError) else CliError('unexpected_error',
                'Input or source data was not recognized; no availability inferred.', exception_type=type(error).__name__)
        return {'output': {'status': 'error', 'error': error.as_dict(),
                           'usage': client.usage() if client else None,
                           'trace': client.trace if client else []}, 'exit_code': 1}
    finally:
        if client:
            client.close()


def main():
    if sys.version_info < (3, 10):
        print('Python >=3.10 is required; use Python 3.12+ and install the project with pip.', file=sys.stderr)
        return 1
    result = run(sys.argv[1:])
    print(result.get('help') or json.dumps(result['output'], ensure_ascii=False, indent=2, allow_nan=False))
    return result['exit_code']
