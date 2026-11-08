"""JMC public city tables: preserve per-cell prediction/observation distinctions."""
import datetime as dt
import re
from season_common import Page, SourceError, fail, norm, unique, month_day, jmc_url

PROVIDER = 'jmc'
PUBLISHER = '日本気象株式会社'
HEADERS = {
 'red_leaves': ['都市','紅葉予想日','平年差','平年紅葉日','品種'],
 'yellow_leaves': ['都市','黄葉予想日','平年差','平年黄葉日','品種'],
 'sakura': ['都市','開花予想日','開花平年差','満開予想日','満開平年差','平年開花日'],
}
ALIASES = {'金泽':'金沢','金澤':'金沢','东京':'東京','长野':'長野','广岛':'広島','福冈':'福岡'}


def publication(page, season, now):
    product = '紅葉・黄葉見頃予想' if season == 'foliage' else '桜の開花・満開予想'
    expression = re.compile(r'(\d{4})年'+re.escape(product)+r'\(第(\d+)回\)を発表')
    titles = {norm(n.text()) for n in page.root.nodes() if n.tag in ('h2','div') and expression.fullmatch(norm(n.text()))}
    title = unique(list(titles), 'JMC season, edition or title is missing/ambiguous.')
    match = expression.fullmatch(title)
    year, edition = int(match[1]), int(match[2])
    dates = [norm(n.text()) for n in page.root.nodes(cls='date') if re.fullmatch(r'\d{4}年\d{1,2}月\d{1,2}日',norm(n.text()))]
    release = unique(list(set(dates)), 'JMC release publication date is missing/ambiguous.')
    parts = list(map(int,re.findall(r'\d+',release)))
    published = dt.date(*parts)
    if published > now.date() or not year-1 <= published.year <= year: fail('Invalid/future JMC release date.')
    text = norm(page.root.text())
    ended = season == 'sakura' and bool(re.search(r'今シーズンの桜開花予想の発表は.{0,8}今回で最後',text))
    return year, {'edition':edition,'release_published_on':published.isoformat(),'cell_updated_at':None,
                  'forecast_announcements_ended':ended,'publication_note':'Release date does not date every rendered cell; observed cells may have been updated later.'}


def cells(page):
    tables = {}
    for table in page.root.nodes('table'):
        rows = [[n for n in tr.children if getattr(n,'tag',None) in ('th','td')] for tr in table.nodes('tr')]
        if not rows: continue
        header = [norm(n.text()) for n in rows[0]]
        for kind, expected in HEADERS.items():
            if header == expected:
                if kind in tables: fail('Duplicate JMC seasonal table.')
                if len(rows) < 2 or any(len(r) != len(header) for r in rows): fail('Incomplete JMC city table.')
                names = [norm(r[0].text()) for r in rows[1:]]
                if any(not name for name in names) or len(names) != len(set(names)): fail('Missing/duplicate JMC city identity.')
                tables[kind] = rows[1:]
    return tables


def document(raw, season, now):
    page = Page(raw)
    year, release = publication(page,season,now)
    tables = cells(page)
    expected = {'red_leaves','yellow_leaves'} if season == 'foliage' else {'sakura'}
    if not expected <= tables.keys(): fail('Required JMC seasonal tables are missing.')
    if season == 'foliage' and {norm(r[0].text()) for r in tables['red_leaves']} != {norm(r[0].text()) for r in tables['yellow_leaves']}:
        fail('JMC red/yellow city coverage differs.')
    if '実況値' not in page.root.text(): fail('JMC observed-value legend is missing.')
    return year, release, tables


def event(cell, milestone, year, now, season):
    raw = norm(cell.text())
    markers = set(cell.attrs.get('class','').split()) & ({'autumn01','autumn02'} if season == 'foliage' else {'sakura01','sakura02'})
    if raw in ('','--','---','未発表'):
        return {'milestone':milestone,'kind':'unavailable','date':None,'raw':raw}
    if len(markers) != 1: fail('Missing/ambiguous JMC forecast/observed cell marker.')
    marker = next(iter(markers))
    kind = 'observed' if marker.endswith('02') else 'forecast'
    cleaned = re.sub(r'(開花|満開)$','',raw)
    date = month_day(cleaned,year)
    if kind == 'observed' and date > now.date(): fail('JMC observed event is future-dated.')
    if season == 'foliage' and date.month < 7: fail('Cross-year autumn event date needs explicit source-year handling.')
    return {'milestone':milestone,'kind':kind,'date':date.isoformat(),'raw':raw,
            'approximate':False,'date_has_passed':date < now.date(),'cell_updated_at':None}


def cities(raw, season, now):
    year, release, tables = document(raw,season,now)
    rows = tables['red_leaves' if season == 'foliage' else 'sakura']
    return {'provider':PROVIDER,'publisher':PUBLISHER,'status':'ok','source_year':year,'release':release,
            'cities':[{'name_ja':norm(r[0].text()),'scope':'city_reference'} for r in rows],
            'coverage':'Only cities in this public release table, not all cities or paid spot data.'}


def parse(raw, season, city, year, now):
    source_year, release, tables = document(raw,season,now)
    base = {'provider':PROVIDER,'publisher':PUBLISHER,'source_year':source_year,'release':release,
            'scope':{'kind':'city_reference','requested_city':city}, 'issued_at':None,
            'metric_scope':'City/species phenological dates; not a named garden viewing window.'}
    if source_year != year:
        return {**base,'status':'unavailable','reason':'requested_year_not_on_source','events':[]}
    canonical = ALIASES.get(norm(city),norm(city))
    key = 'red_leaves' if season == 'foliage' else 'sakura'
    names = [norm(r[0].text()) for r in tables[key]]
    if canonical not in names:
        raise SourceError('unsupported_city','No exact city in the public JMC table; no nearby city was chosen.', candidates=names)
    base['scope']['name_ja'] = canonical
    events = []
    if season == 'foliage':
        for key in ('red_leaves','yellow_leaves'):
            row = unique([r for r in tables[key] if norm(r[0].text()) == canonical],'Missing/duplicate JMC selected city.')
            value = event(row[1],key,year,now,season)
            value.update(species_ja=norm(row[4].text()),normal_month_day=norm(row[3].text()),normal_difference_raw=norm(row[2].text()))
            if not value['species_ja']: fail('JMC foliage species is missing.')
            # Validate the month/day but keep it without a fabricated current-year event.
            month_day(value['normal_month_day'],2000)
            events.append(value)
    else:
        row = unique([r for r in tables[key] if norm(r[0].text()) == canonical],'Missing/duplicate JMC selected city.')
        for i,milestone in ((1,'flowering'),(3,'full_bloom')):
            value = event(row[i],milestone,year,now,season)
            value.update(species_ja='ソメイヨシノ',normal_difference_raw=norm(row[i+1].text()))
            events.append(value)
        base['normal_flowering_month_day'] = norm(row[5].text())
        month_day(base['normal_flowering_month_day'],2000)
    archived = release['forecast_announcements_ended'] or source_year < now.year
    return {**base,'status':'archived' if archived else 'ok','events':events,
            'warnings':['Predicted and observed cells remain separate. Passed forecast dates do not automatically become observed.',
                        'Release publication is known; per-cell last-update time and forecast issue time are unverified.']}
