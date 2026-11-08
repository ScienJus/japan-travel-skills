"""JSON CLI for anonymous discovery, menus and availability."""
from importlib.metadata import version
import json
from pathlib import Path
import sys

from .arguments import HelpRequested, parse_arguments
from .service import TableCheck
from .transport import Client, CliError, sanitize, stamp


def run(argv, create_client=Client):
    client = None
    try:
        args = parse_arguments(argv)
        client = create_client(timeout=args.timeout, max_requests=args.max_requests, delay_min_ms=args.delay_min_ms, delay_max_ms=args.delay_max_ms)
        app = TableCheck(client)
        if args.command == 'source':
            if any(value is not None and not isinstance(value, dict) for value in (args.params, args.body)):
                raise CliError('invalid_argument', '--params and --body must be JSON objects.')
            data = sanitize(client.read('POST' if args.body is not None else 'GET', args.target, args.params, args.body))
        elif args.command == 'doctor':
            data = {'python': sys.version.split()[0], 'httpx': version('httpx'), 'beautifulsoup4': version('beautifulsoup4'),
                    'anonymous': True, 'browser_required': False, 'node_required': False, 'api_key_required': False}
        elif args.command == 'usage':
            paths = [Path(path).resolve() for path in args.targets]
            if len(set(paths)) != len(paths):
                raise CliError('invalid_argument', 'Do not count the same file twice.')
            values = [json.loads(path.read_text()) for path in paths]
            if any(not isinstance(value.get('usage'), dict) or value.get('command') == 'usage' for value in values):
                raise CliError('invalid_argument', 'Expected individual CLI result JSON files.')
            fields = ('transport_attempts', 'network_requests_started', 'response_body_bytes', 'cache_hits', 'browser_launches', 'throttle_wait_ms', 'elapsed_ms')
            data = {'commands': len(values), 'totals': {key: sum(value['usage'][key] for value in values) for key in fields},
                    'note': 'Elapsed time is summed command duration; excludes development, tests and this report command.'}
        elif args.command == 'suggest':
            data = app.suggest(args.target)
        elif args.command == 'cuisines':
            data = app.cuisines()
        elif args.command in ('detail', 'courses'):
            data = (app.detail(args.target, args.start, args.end, not args.no_courses, args.meal, args.course)
                    if args.command == 'detail' else app.courses(args.target, args.start, args.end, args.meal, args.course))
        elif args.command == 'search':
            data = app.search(args.near, args.radius_m, args.cuisine, args.budget_min, args.budget_max, args.pages, args.limit,
                              args.start, args.end, args.people, args.after, args.before, args.with_courses, args.meal, area=args.area)
        else:
            data = app.availability(args.target, args.start, args.end, args.people, args.after, args.before, args.course, args.seat)
            if args.command == 'calendar':
                for day in data['days']:
                    day['available_time_count'] = len(day.pop('offered_times'))
        errors = list(data.get('errors') or []) if isinstance(data, dict) and args.command != 'source' else []
        for entry in client.trace:
            if entry.get('status') == 'error':
                errors.append({'scope': 'request', **entry.get('error', {}), 'url': entry['url']})
        partial = (isinstance(data, dict) and args.command != 'source' and data.get('coverage') == 'partial') or bool(errors)
        if partial and not errors:
            errors.append({'code': 'incomplete_result', 'message': 'Some requested data could not be verified; inspect data for unknown fields.'})
        return {'output': {'status': 'partial' if partial else 'ok', 'command': args.command, 'checked_at': stamp(), 'timezone': 'Asia/Tokyo',
                           **({'errors': errors} if partial else {}),
                           'data': data, 'usage': client.usage(), 'trace': client.trace}, 'exit_code': 3 if partial else 0}
    except HelpRequested as help_requested:
        return {'help': str(help_requested), 'exit_code': 0}
    except Exception as error:
        if not isinstance(error, CliError):
            error = CliError('unexpected_response', 'Input or source data was not recognized; no availability inferred.',
                             exception_type=type(error).__name__)
        return {'output': {'status': 'error', 'error': error.as_dict(), 'usage': client.usage() if client else None,
                           'trace': client.trace if client else []}, 'exit_code': 1}
    finally:
        if client:
            client.close()


def main():
    result = run(sys.argv[1:])
    print(result.get('help') or json.dumps(result['output'], ensure_ascii=False, indent=2, allow_nan=False))
    return result['exit_code']
