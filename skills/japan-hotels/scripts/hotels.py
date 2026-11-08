#!/usr/bin/env python3
"""Discover hotels and read static profiles on Jalan, without dates or bookings."""
import argparse
import json
from pathlib import Path
import sys

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path: sys.path.insert(0, HERE)
import jalan as source
import hotel_geo as geo
import hotel_viewport as viewport


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest='command', required=True)
    sub.add_parser('doctor', help='Offline runtime/source-scope check')
    search = sub.add_parser('search', help='Read one undated native landmark-directory page')
    search.add_argument('--directory', required=True, help='Query-free https://www.jalan.net/PREF/spt_guideID/ URL')
    search.add_argument('--expect', required=True, help='Exact native landmark name, excluding 周辺のホテル・旅館・宿泊施設; e.g. ＪＲ金沢駅')
    search.add_argument('--bath', action='store_true', help='Publisher 内湯・大浴場 filter (not natural onsen)')
    search.add_argument('--station5', action='store_true', help='Publisher 駅から徒歩5分以内 filter; independently review access text')
    search.add_argument('--page', type=int, default=1, help='1–10; one source page; radius mode uses native viewport pages when supported')
    search.add_argument('--limit', type=int, default=10, help='1–30 returned hotels; no automatic detail reads')
    search.add_argument('--radius-m', type=float, help='1–20000 m straight-line radius calculated from coordinates; not walking distance')
    search.add_argument('--center-lat', type=float, help='Optional caller-supplied latitude; requires --center-lon and --center-name')
    search.add_argument('--center-lon', type=float, help='Optional caller-supplied longitude')
    search.add_argument('--center-name', help='Label for caller-supplied center; default center is the native Jalan landmark map point')
    detail = sub.add_parser('detail', help='Read one static property profile and optionally its room-type table')
    detail.add_argument('hotel_id', help='Six-digit Jalan ID')
    detail.add_argument('--expect', help='Complete native hotel name from search, including parenthetical qualifiers')
    detail.add_argument('--rooms', action='store_true', help='One additional read of the property-owned room tab')
    return p


def problem(error):
    if isinstance(error, source.SourceError): return {'code': error.code, 'message': str(error), **error.details}
    return {'code': 'source_schema_changed', 'message': 'Unexpected source structure; no hotel facts were guessed.'}


def query(client, args):
    if args.command == 'search':
        if not 1 <= args.limit <= 30: raise source.SourceError('invalid_options', 'Use --limit from 1 to 30.')
        if not source.norm(args.expect): raise source.SourceError('invalid_options', 'Supply the exact native landmark name.')
        center = geo.validate_options(args)
        filters = [key for key in source.FILTERS if getattr(args, key)]
        url = source.directory_url(args.directory, args.page, filters)
        if args.radius_m is not None:
            result, meta, partial = viewport.query(client, args, filters, center)
        else:
            raw, meta = client.read(url)
            result = source.parse_search(raw, args.directory, args.expect, args.page, filters, source.now_jst().date())
            partial = False
        count = len(result['hotels'])
        if 'distance_unknown_hotels' in result:
            unknown_count = len(result['distance_unknown_hotels'])
            result['distance_unknown_hotels'] = result['distance_unknown_hotels'][:args.limit]
            result['distance_unknown_output_truncated'] = len(result['distance_unknown_hotels']) < unknown_count
        result['hotels'] = result['hotels'][:args.limit]
        result['returned_count'] = len(result['hotels'])
        result['output_truncated'] = result['returned_count'] < count
        return {'status': 'partial' if partial else 'ok', 'provider': 'jalan', 'source': meta, **result}
    url = source.hotel_url(args.hotel_id)
    raw, meta = client.read(url)
    result = source.parse_detail(raw, args.hotel_id, args.expect, source.now_jst().date())
    status = 'ok'
    if args.rooms:
        if not result['rooms_link_published']:
            result['rooms'] = {'state': 'unknown', 'room_types': [], 'note': 'Property has no verified native room-tab link.'}
            status = 'partial'
        else:
            room_meta = {'url': source.hotel_url(args.hotel_id, rooms=True), 'retrieved_at': None}
            try:
                raw, room_meta = client.read(room_meta['url'])
                result['rooms'] = source.parse_rooms(raw, args.hotel_id, result['name_ja'])
                if result['rooms']['state'] != 'published': status = 'partial'
            except (source.SourceError, ValueError, KeyError, TypeError, IndexError, RecursionError) as error:
                result['rooms'] = {'state': 'unknown', 'room_types': [], 'error': problem(error)}
                status = 'partial'
            result['rooms']['source'] = room_meta
    return {'status': status, 'provider': 'jalan', 'source': meta, **result}


def main(argv=None):
    args = parser().parse_args(argv)
    client = source.Client(request_limit=4 if getattr(args, 'radius_m', None) is not None else 2)
    try:
        if args.command == 'doctor':
            result = {'status': 'ok', 'python': sys.version.split()[0], 'dependencies': 'Python 3.9+ standard library only',
                      'network_checked': False, 'provider': 'jalan', 'dates_required': False,
                      'scope': 'Native landmark directories, bath/station5 filters, optional coordinate-based straight-line radius, profiles and room types.',
                      'request_budget': {'search': 1, 'radius_search_first_page': 2, 'radius_search_other_page': 3,
                                         'radius_region_fallback_max': 4, 'radius_search_max': 4, 'detail': 1, 'detail_with_rooms': 2},
                      'unsupported': ['free-text city resolution inside CLI', 'availability', 'stay prices', 'booking', 'Yahoo Travel']}
        else: result = query(client, args)
    except source.SourceError as error:
        result = {'status': 'error', 'state': 'unknown', 'provider': 'jalan', 'error': problem(error)}
    except (ValueError, KeyError, TypeError, IndexError, RecursionError):
        result = {'status': 'error', 'state': 'unknown', 'provider': 'jalan',
                  'error': {'code': 'source_schema_changed', 'message': 'Unexpected source structure; no hotel facts were guessed.'}}
    if result['status'] == 'error' and client.last_source is not None: result['source'] = client.last_source
    result['usage'] = client.usage()
    print(json.dumps(result, ensure_ascii=False, separators=(',', ':')))
    return 2 if result['status'] == 'error' else 0


if __name__ == '__main__': sys.exit(main())
