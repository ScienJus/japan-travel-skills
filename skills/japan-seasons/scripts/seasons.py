#!/usr/bin/env python3
"""Compare independently attributed Japanese seasonal source records."""
import argparse
import json
import re
import sys
from pathlib import Path

HERE = str(Path(__file__).resolve().parent)
if HERE not in sys.path: sys.path.insert(0,HERE)
from season_common import Client, SourceError, error_record, now_jst, wn_url, jmc_url
import wn_seasons as wn
import jmc_seasons as jmc


def parser():
    root = argparse.ArgumentParser(description=__doc__)
    sub = root.add_subparsers(dest='command',required=True)
    sub.add_parser('doctor',help='Offline runtime/capability check')
    for name in ('areas','spots','cities','query'):
        p = sub.add_parser(name)
        p.add_argument('--season',choices=('foliage','sakura'),required=True)
        if name == 'spots':
            p.add_argument('--area',required=True,help='Weathernews slug from areas; foliage regional overviews return candidate_areas for prefecture selection')
            p.add_argument('search',nargs='?',default='')
        if name == 'query':
            p.add_argument('--year',type=int,help='Requested source season year; default current JST year')
            p.add_argument('--city',required=True,help='Exact JMC public-table city; a distinct city reference, not the Weathernews spot')
            p.add_argument('--spot',required=True,help='Exact native Weathernews spot name from spots')
            choice = p.add_mutually_exclusive_group(required=True)
            choice.add_argument('--area',help='Resolve exact spot in a live Weathernews prefecture directory')
            choice.add_argument('--spot-id',help='Previously verified Weathernews spot ID for this season; never reuse another season\'s ID')
    return root


def source_query(client, provider, season, args, year, now):
    page, retrieved = None, None
    try:
        if provider == 'jmc':
            page = jmc_url(season)
            raw,retrieved = client.read(page)
            result = jmc.parse(raw,season,args.city,year,retrieved)
        else:
            if args.area:
                page = wn_url(season,'area',args.area)
            expected = wn.selected_spot(client,season,args.area,args.spot) if args.area else None
            identity = expected['spot_id'] if expected else args.spot_id
            page = wn_url(season,'spot',identity)
            raw,retrieved = client.read(page)
            result = wn.parse(raw,season,identity,args.spot,year,retrieved,expected)
        result['source'] = {'url':page,'retrieved_at':retrieved.isoformat(),
                            'processing':'Selected and normalized by japan-travel-skills; provider records remain independent.'}
        return result
    except (SourceError,KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,RecursionError) as error:
        return {**error_record(provider,error),'publisher':wn.PUBLISHER if provider=='weathernews' else jmc.PUBLISHER,
                'source':{'url':page,'retrieved_at':retrieved.isoformat() if retrieved else None}}


def main(argv=None):
    args = parser().parse_args(argv)
    client = Client()
    discovery_source = None
    try:
        now = now_jst()
        if args.command == 'doctor':
            result = {'status':'ok','python':sys.version.split()[0],'dependencies':'Python standard library only','network_checked':False,
                      'providers':['weathernews','jmc'], 'comparison_scope':'Weathernews spots versus JMC public city/species references',
                      'sakura_limit':'Weathernews visible forecast contract checked against publisher page code; active-season live verification pending. Ended seasons stay archived; unpublished years unavailable.'}
        else:
            for name in ('city','spot','search'):
                text = getattr(args,name,None)
                if text is not None and (len(text)>100 or any(ord(c)<32 for c in text) or (name != 'search' and not text.strip())):
                    raise SourceError('invalid_options','Use native names of 1–100 printable characters.')
            if getattr(args,'area',None) and not re.fullmatch(r'[a-z-]{2,25}',args.area):
                raise SourceError('invalid_options','Use an exact native area slug returned by areas.')
            if getattr(args,'spot_id',None) and not re.fullmatch(r'[1-9]\d{0,7}',args.spot_id):
                raise SourceError('invalid_options','Use a previously verified numeric spot ID.')
            if args.command == 'query':
                year = args.year if args.year is not None else now.year
                if not 1900 <= year <= 2100: raise SourceError('invalid_options','Use a four-digit season year from 1900 to 2100.')
                # Both providers were explicitly requested by this command.
                # An error is retained as its own record, never used as fallback.
                records = [source_query(client,p,args.season,args,year,now) for p in ('weathernews','jmc')]
                states = [r['status'] for r in records]
                status = states[0] if len(set(states)) == 1 else 'partial'
                result = {'status':status,'query':{'season':args.season,'year':year,'city':args.city,'spot':args.spot,'timezone':'Asia/Tokyo'},
                          'providers':records,
                          'comparison':{'scope':'spot_vs_city_reference','same_location_and_metric':False,
                                        'instruction':'Show both providers, exact locations, species, milestone meanings and times. Do not average dates, choose a winner or imply agreement/disagreement on the same spot.'}}
            else:
                address = jmc_url(args.season) if args.command == 'cities' else wn_url(args.season,'area',args.area) if args.command == 'spots' else wn_url(args.season)
                discovery_source = {'url':address,'retrieved_at':None}
                raw,retrieved = client.read(address)
                discovery_source['retrieved_at'] = retrieved.isoformat()
                if args.command == 'cities': result = jmc.cities(raw,args.season,now)
                elif args.command == 'spots': result = wn.spots(raw,args.season,args.area,args.search)
                else: result = wn.area_list(raw,args.season)
                result['source'] = discovery_source
        result['usage'] = client.usage()
        print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
        return 2 if result['status']=='error' or (args.command=='query' and all(r['status']=='error' for r in result['providers'])) else 0
    except (SourceError,KeyError,TypeError,ValueError,IndexError,AttributeError,OverflowError,RecursionError) as error:
        provider = 'weathernews' if args.command in ('areas','spots') else 'jmc' if args.command == 'cities' else 'query'
        result = error_record(provider,error)
        if discovery_source is not None: result['source'] = discovery_source
        result['usage'] = client.usage()
        print(json.dumps(result,ensure_ascii=False,separators=(',',':')))
        return 2


if __name__=='__main__': sys.exit(main())
