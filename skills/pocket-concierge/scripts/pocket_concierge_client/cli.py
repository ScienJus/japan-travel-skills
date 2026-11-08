"""JSON CLI with no browser, identity, booking or arbitrary GraphQL operations."""
from importlib.metadata import version
import json
import sys

from .arguments import HelpRequested, parse_arguments
from .reports import aggregate_usage
from .service import PocketConcierge
from .transport import Client, CliError, stamp


def offline_usage():
    return {'runtime': {'python': sys.version.split()[0]}, 'elapsed_ms': 0, 'transport_attempts': 0,
            'network_requests_started': 0, 'response_body_bytes': 0, 'cache_hits': 0, 'browser_launches': 0,
            'throttle_wait_ms': 0, 'throttle_waits': 0, 'metrics_complete': True, 'dependencies': []}


def run(argv, create_client=Client):
    client = None
    try:
        args = parse_arguments(argv)
        if args.command == 'doctor':
            data = {'python': sys.version.split()[0], 'httpx': version('httpx'), 'anonymous': True,
                    'browser_required': False, 'node_required': False, 'api_key_required': False}
        elif args.command == 'usage':
            data = aggregate_usage(args.targets)
        else:
            client = create_client(timeout=args.timeout, max_requests=args.max_requests,
                                   delay_min_ms=args.delay_min_ms, delay_max_ms=args.delay_max_ms)
            app = PocketConcierge(client, args.lang)
            if args.command in ('filters', 'areas', 'cuisines'):
                catalog = app.filters()
                data = catalog if args.command == 'filters' else {'items': catalog[args.command]}
            elif args.command == 'search':
                data = app.search(args.keyword, args.area, args.cuisine, args.meal, args.budget_min, args.budget_max,
                                  args.date, args.people, args.instant, args.pages, args.limit)
            elif args.command in ('detail', 'courses'):
                data = app.detail(args.target, args.command == 'courses' or not args.no_courses, args.meal, args.course,
                                  only_courses=args.command == 'courses')
                if args.command == 'courses':
                    data = {'restaurant': {key: data[key] for key in ('id', 'name', 'name_ja', 'url', 'booking_mode')},
                            'items': data['courses'], 'reservation_terms': data['reservation_terms'], 'price_note': data['price_note']}
            elif args.command == 'calendar':
                data = app.calendar(args.target, args.start, args.end)
            else:
                filters = {'people': args.people, 'meal': args.meal, 'course': args.course,
                           'seat': args.seat, 'after': args.after, 'before': args.before}
                data = (app.slots(args.target, args.date, **filters) if args.command == 'slots' else
                        app.availability(args.target, args.start, args.end, **filters))
        errors = list(data.get('errors') or [])
        for entry in client.trace if client else []:
            if entry.get('status') == 'error':
                errors.append({'scope': 'request', **entry.get('error', {}), 'operation': entry['operation']})
        partial = data.get('coverage') == 'partial' or bool(errors)
        if partial and not errors:
            errors.append({'code': 'incomplete_result', 'message': 'Some requested data could not be verified; inspect data for unknown fields.'})
        return {'output': {'status': 'partial' if partial else 'ok', 'command': args.command, 'checked_at': stamp(),
                           **({'errors': errors} if partial else {}),
                           'timezone': 'Asia/Tokyo', 'language': args.lang, 'data': data,
                           'usage': client.usage() if client else offline_usage(), 'trace': client.trace if client else []},
                'exit_code': 3 if partial else 0}
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
