#!/usr/bin/env python3
"""Query AMECS's published north/south Mount Fuji viewing indices."""
import argparse
import datetime as dt
import json
from pathlib import Path
import re
import sys

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path: sys.path.insert(0,HERE)
import fuji_source as source


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor',help='Offline runtime and source-scope check')
    p = sub.add_parser('forecast',help='Live broad north/south foothill viewing indices; no spot-specific forecast')
    p.add_argument('--side',choices=('north','south','both'),default='both')
    group = p.add_mutually_exclusive_group()
    group.add_argument('--date',help='One JST date, YYYY-MM-DD; unavailable outside the published panel')
    group.add_argument('--from',dest='start',help='First JST date; requires --to')
    group.add_argument('--days',type=int,help='1–7 requested dates starting tomorrow; default 7')
    p.add_argument('--to',dest='end',help='Last JST date, inclusive; requires --from')
    return root


def requested_dates(args,now):
    def date(value):
        if not isinstance(value,str) or not re.fullmatch(r'\d{4}-\d{2}-\d{2}',value):
            raise source.SourceError('invalid_options','Use a valid date in YYYY-MM-DD format.')
        try: return dt.date.fromisoformat(value)
        except ValueError: raise source.SourceError('invalid_options','Use a valid calendar date.') from None
    if bool(args.start) != bool(args.end): raise source.SourceError('invalid_options','Supply --from and --to together.')
    if args.date:
        return [date(args.date)]
    if args.start:
        start,end = date(args.start),date(args.end)
    else:
        days = args.days if args.days is not None else 7
        if not 1 <= days <= 7: raise source.SourceError('invalid_options','Use --days from 1 to 7.')
        start = now.date()+dt.timedelta(days=1)
        end = start+dt.timedelta(days=days-1)
    if not 0 <= (end-start).days <= 6: raise source.SourceError('invalid_options','Choose an inclusive range of 1–7 dates.')
    return [start+dt.timedelta(days=i) for i in range((end-start).days+1)]


def error_record(error,side=None):
    if isinstance(error,source.SourceError): problem = {'code':error.code,'message':str(error),**error.details}
    else: problem = {'code':'source_schema_changed','message':'Unexpected Fuji source structure; no viewing result was guessed.'}
    result = {'provider':'amecs','publisher':source.PUBLISHER,'status':'error','state':'unknown','error':problem,'days':[]}
    if side: result['scope'] = {'side':side,'label_ja':source.LABELS[side],'kind':'broad_foothill_direction','specific_viewpoint':None}
    return result


def query(client,args,dates):
    raw,page_meta = client.read(source.HOME)
    script_url = source.panel_contract(raw)
    raw,script_meta = client.read(script_url)
    contract = source.script_contract(raw)
    sides = ['north','south'] if args.side == 'both' else [args.side]
    records = []
    for side in sides:
        metadata = {'url':source.DATA[side],'retrieved_at':None}
        try:
            raw,metadata = client.read(source.DATA[side])
            record = source.parse_csv(raw,side,dates,source.now_jst())
        except (source.SourceError,ValueError,TypeError,KeyError,IndexError,OverflowError) as error:
            record = error_record(error,side)
        record['source'] = {'page_url':source.HOME,**metadata}
        records.append(record)
    # Recheck after all reads; one direction must not hide a failure in the other.
    checked = source.now_jst()
    for i,record in enumerate(records):
        if record['status'] != 'error':
            try: source.check_fresh(dt.datetime.fromisoformat(record['source_initialization_time']),checked)
            except source.SourceError as error: records[i] = {**error_record(error,record['scope']['side']),'source':record['source']}
    states = [r['status'] for r in records]
    initial = [r.get('source_initialization_time') for r in records]
    comparable = len(records)==2 and None not in initial and len(set(initial))==1
    status = states[0] if len(set(states))==1 else 'partial'
    if len(records)==2 and None not in initial and not comparable: status = 'partial'
    return {'status':status,
            'query':{'side':args.side,'dates':[d.isoformat() for d in dates],'timezone':'Asia/Tokyo'},
            'records':records,'contract':{**contract,'page':page_meta,'script':script_meta},
            'comparison':{'same_initialization':comparable,'instruction':'Keep direction and initialization separate. Compare only matching source runs; never substitute a specific park or hotel.'},
            'checked_at':checked.isoformat(),
            'limitations':['Broad north/south foothill reference, not a forecast for a particular camera, hotel or park.',
                           '1–10 is the publisher index, not 10–100% probability; no current visibility is established.',
                           'AM/PM are source periods. CSV 09:00/15:00 references are not exact viewing appointments.',
                           'Initialization, HTTP Last-Modified and retrieval times are not a verified forecast issue time.',
                           'No camera image interpretation, climbing conditions or travel-safety assessment.']}


def main(argv=None):
    args = parser().parse_args(argv)
    client = source.Client()
    try:
        if args.command == 'doctor':
            result = {'status':'ok','python':sys.version.split()[0],'dependencies':'Python standard library only','network_checked':False,
                      'provider':'amecs','source_url':source.HOME,'sides':['north','south'],'visible_days':7,
                      'scope':'Broad north/south foothill AM/PM viewing index; not a specific viewpoint or current observation.',
                      'request_budget':{'one_side':3,'both_sides':4},'initialization_max_age_hours':source.MAX_AGE_HOURS}
        else:
            dates = requested_dates(args,source.now_jst())
            result = query(client,args,dates)
    except (source.SourceError,ValueError,TypeError,KeyError,IndexError,OverflowError) as error:
        result = error_record(error)
    result['usage'] = client.usage()
    print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
    return 2 if result['status']=='error' else 0


if __name__=='__main__': sys.exit(main())
