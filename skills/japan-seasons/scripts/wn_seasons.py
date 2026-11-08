"""Weathernews public SSR pages: exact spot discovery and visible seasonal fields."""
import re
from season_common import Page, Nuxt, SourceError, fail, norm, unique, month_day, wn_url

PROVIDER = 'weathernews'
PUBLISHER = 'ウェザーニュース'
SAKURA_STAGES = {1:'つぼみ',2:'ピンクのつぼみ',3:'開花(5,6輪)',4:'ちらほら咲いた(1分咲き)',
                 5:'結構咲いた(3分咲き)',6:'満開間近(5分咲き)',7:'満開(8分咲き)',8:'散り始め',9:'葉桜',99:'情報なし'}


def season_year(page, season):
    title = page.title()
    match = re.search(r'【(\d{4})】',title)
    if not match or ('紅葉' if season == 'foliage' else '桜') not in title:
        fail('Weathernews season/year page identity is missing.')
    return int(match[1])


def area_list(raw, season):
    page = Page(raw)
    page.canonical(wn_url(season))
    year = season_year(page,season)
    rows = {}
    path = '/' + ('koyo' if season == 'foliage' else 'sakura') + '/area/'
    for link in page.root.nodes('a'):
        href = link.attrs.get('href','')
        match = re.fullmatch(re.escape(path)+r'([a-z-]{2,25})/',href)
        if match:
            label = norm(link.text())
            if label: rows[match[1]] = {'area':match[1],'name_ja':label,'url':wn_url(season,'area',match[1])}
    if not rows: fail('No live Weathernews area links found.')
    return {'provider':PROVIDER,'publisher':PUBLISHER,'status':'ok','source_year':year,'areas':list(rows.values())}


def foliage_child_areas(page, area):
    """Recognize a native regional overview, never turn its highlights into spots."""
    mains = list(page.root.nodes('main','main'))
    if not mains: return []
    candidates = []
    for root in unique(mains,'Ambiguous Weathernews main content.').nodes('div','templateRoot'):
        navs = [n for n in root.children if getattr(n,'tag',None) == 'ul'
                and {'searchArea','type03'} <= set(n.attrs.get('class','').split())]
        if navs:
            candidates.append((root,unique(navs,'Duplicate regional prefecture navigation.')))
    if not candidates: return []
    root,nav = unique(candidates,'Ambiguous Weathernews regional overview.')
    links = list(nav.nodes('a'))
    if not 1 <= len(links) <= 47: fail('Unsupported regional prefecture count.')
    headings = {}
    for link in links:
        match = re.fullmatch(r'#([a-z-]{2,25})',link.attrs.get('href',''))
        label = norm(link.text())
        if not match or match[1] == area or match[1] in headings or not label:
            fail('Invalid/duplicate regional prefecture navigation.')
        headings[match[1]] = label
    # Validate the entire native block set, including blocks with broken IDs or
    # classes. Never omit a malformed child and offer the remaining subset.
    blocks = list(root.nodes('article'))
    if len(blocks) != len(headings): fail('Regional navigation and prefecture blocks disagree.')
    rows = {}
    for block in blocks:
        slug = block.attrs.get('id','')
        if slug not in headings or slug in rows or 'block' not in block.attrs.get('class','').split():
            fail('Invalid/duplicate regional prefecture block.')
        section = unique(list(block.nodes('section','card')),'Missing/duplicate regional prefecture card.')
        heading = unique(list(section.nodes('h2','title04')),'Missing/duplicate native prefecture heading.')
        name = norm(heading.text())
        short = name[:-1] if name.endswith(('都','府','県')) else name
        if not re.fullmatch(r'\S{1,20}[都道府県]',name) or headings[slug] not in (name,short):
            fail('Regional prefecture heading and navigation disagree.')
        if name in {row['name_ja'] for row in rows.values()}: fail('Duplicate native prefecture name.')
        button = unique(list(section.nodes('p','buttonRight')),'Missing/duplicate native prefecture directory link.')
        link = unique(list(button.nodes('a')),'Missing/duplicate native prefecture directory link.')
        if (link.attrs.get('href') != '/koyo/area/'+slug+'/'
                or norm(link.text()) != name+'の紅葉名所をもっと見る'):
            fail('Regional prefecture directory identity disagrees with its block.')
        rows[slug] = {'area':slug,'name_ja':name,'url':wn_url('foliage','area',slug)}
    if set(rows) != set(headings): fail('Regional prefecture coverage is incomplete.')
    return list(rows.values())


def spots(raw, season, area, query=''):
    page = Page(raw)
    page.canonical(wn_url(season,'area',area))
    year = season_year(page,season)
    data = Nuxt(page)
    signature = ['pointname','spotid','prefname','cityname','address'] if season == 'foliage' else ['lcid','name','pref_en','pref_jp','cityname']
    objects = data.objects(signature)
    if not objects:
        children = foliage_child_areas(page,area) if season == 'foliage' else []
        if children:
            raise SourceError('unsupported_area','This foliage area is a regional overview, not a spot directory. Choose an exact prefecture from candidate_areas; no child pages were read.',
                              directory_kind='regional_overview',source_year=year,candidate_areas=children)
        fail('Weathernews spot directory is missing; page shell is not a directory.')
    prefix = '/' + ('koyo' if season == 'foliage' else 'sakura') + '/spot/'
    linked_ids = {match[1] for link in page.root.nodes('a')
                  for match in [re.fullmatch(re.escape(prefix)+r'([1-9]\d{0,7})/(?:\?[^#]*)?',link.attrs.get('href',''))] if match}
    if not linked_ids: fail('Weathernews directory has no visible native spot links.')
    rows = {}
    for item in objects:
        if season == 'sakura' and data.value(item,'pref_en') != area:
            continue  # Some prefecture URLs render a regional list; retain only the requested native slug.
        keys = ('spotid','pointname','prefname') if season == 'foliage' else ('lcid','name','pref_jp')
        identity,name,pref = [data.value(item,k) for k in keys]
        if identity not in linked_ids: continue  # Do not expose non-rendered payload entries as listed spots.
        city = data.value(item,'cityname')
        if not isinstance(identity,str) or not re.fullmatch(r'[1-9]\d{0,7}',identity) or any(not isinstance(x,str) or not x.strip() for x in (name,pref,city)):
            fail('Invalid native Weathernews spot identity.')
        row = {'spot_id':identity,'name_ja':name,'prefecture_ja':pref,'city_ja':city,'url':wn_url(season,'spot',identity)}
        if identity in rows and rows[identity] != row: fail('Conflicting Weathernews spot identities.')
        rows[identity] = row
    if not rows: raise SourceError('unsupported_area','No supported spots in this exact area; no neighbouring area was substituted.')
    values = list(rows.values())
    matches = [r for r in values if not query or any(norm(query) in norm(r[k]) for k in ('name_ja','prefecture_ja','city_ja'))]
    return {'provider':PROVIDER,'publisher':PUBLISHER,'status':'ok','source_year':year,
            'spots':matches,'total_area_spots':len(values),'coverage':'Live source directory only; substring matches are suggestions, not automatic selections.'}


def selected_spot(client, season, area, name):
    raw,retrieved = client.read(wn_url(season,'area',area))
    result = spots(raw,season,area)
    matches = [r for r in result['spots'] if norm(r['name_ja']) == norm(name)]
    if len(matches) != 1:
        raise SourceError('unknown_or_ambiguous_spot','Use an exact native spot name or a verified ID; no unique substring was selected.',
                          candidates=[r for r in result['spots'] if norm(name) in norm(r['name_ja'])][:30])
    return matches[0]


def primitive(data, item, key, kind=str):
    value = data.value(item,key)
    if type(value) is not kind: fail('Unexpected Weathernews seasonal field type: '+key)
    return value


def visible(page, cls):
    return [norm(n.text()) for n in page.root.nodes(cls=cls)]


def as_of(raw, year, now, pattern):
    match = re.fullmatch(pattern,norm(raw))
    if not match: fail('Unsupported Weathernews condition date.')
    date = month_day(match[1],year)
    if date > now.date(): fail('Weathernews condition is future-dated or has ambiguous season-year scope.')
    return {'as_of':date.isoformat(),'raw_date':raw,'age_days':(now.date()-date).days}


def foliage(page, data, year, now):
    state = unique(data.objects(['obs','migoro','rakuyoStart','rankText','showContent','showMigoroPrediction','showRakuyoStartPrediction']), 'Weathernews foliage state is missing/duplicated.')
    if not primitive(data,state,'showContent',bool):
        return None, [], 'source_content_hidden'
    obs,label = primitive(data,state,'obs'),primitive(data,state,'rankText')
    condition = None
    if obs and label:
        if norm(label) not in visible(page,'statusInfo__state') or norm(obs) not in visible(page,'statusInfo__date'):
            fail('Weathernews visible foliage condition disagrees with page data.')
        condition = {'kind':'reported_condition','label_ja':label,**as_of(obs,year,now,r'(\d{1,2}月\d{1,2}日)時点')}
    events = []
    for key,flag,label,milestone in [('migoro','showMigoroPrediction','見頃','best_viewing_start'),('rakuyoStart','showRakuyoStartPrediction','落葉はじめ','leaf_fall_start')]:
        shown = primitive(data,state,flag,bool)
        raw = primitive(data,state,key)
        if not shown:
            events.append({'milestone':milestone,'kind':'unavailable','date':None,'reason':'not_displayed_by_source'})
            continue
        date = month_day(raw,year)
        if date.month < 7: fail('Cross-year foliage date needs explicit source-year handling.')
        groups = [n for n in page.root.nodes(cls='statusInfo__content') if label in [norm(x.text()) for x in n.nodes(cls='statusInfo__state')]]
        group = unique(groups,'Missing/duplicate visible Weathernews foliage milestone.')
        texts = [norm(x.text()) for x in group.nodes(cls='statusInfo__date')]
        if len(texts) != 1 or not re.fullmatch(re.escape(norm(raw))+r'頃[〜～~]',texts[0]):
            fail('Weathernews approximate/onward forecast wording changed or disagrees with page data.')
        events.append({'milestone':milestone,'kind':'forecast','date':date.isoformat(),'raw':texts[0],
                       'approximate':True,'relation':'around_then_onward','issued_at':None,'date_has_passed':date < now.date()})
    return condition,events,None


def sakura(page, data, year, now, ended, species):
    state = unique(data.objects(['obsday','obsrank','prediction','kaika','mankai','gobu','fubuki']), 'Weathernews sakura state is missing/duplicated.')
    obs = primitive(data,state,'obsday')
    prediction = primitive(data,state,'prediction',bool)
    rank = primitive(data,state,'obsrank',int)
    if rank not in SAKURA_STAGES: fail('Unsupported Weathernews sakura condition rank.')
    condition = None
    if obs:
        label = unique(visible(page,'kaikaStatus__title'),'Missing/duplicate visible sakura condition.')
        if label != norm(SAKURA_STAGES[rank]): fail('Sakura visible/source condition stages disagree.')
        rawdate = unique(visible(page,'kaikaStatus__date'),'Missing/duplicate visible sakura condition date.')
        mode = primitive(data,state,'shuzai')
        if mode not in ('','data'): fail('Unsupported Weathernews sakura condition provenance.')
        estimated = mode == 'data'
        pattern = r'(\d{1,2}月\d{1,2}日)の推定状況' if estimated else r'最終取材日[:：]\s*(\d{1,2}月\d{1,2}日)'
        parsed = as_of(rawdate,year,now,pattern)
        if month_day(obs,year).isoformat() != parsed['as_of']: fail('Sakura visible/source condition dates disagree.')
        condition = {'kind':'estimated_condition' if estimated else 'reported_condition','label_ja':label,**parsed}
    # Contract traced to the public page's SpotObsFcstCard and date formatter.
    # Read only SSR-rendered milestones; stage-hidden payload values stay hidden.
    fields = [('kaika','開花予想日','flowering',3),('gobu','五分咲き','half_bloom',6),
              ('mankai','満開','full_bloom',7),('fubuki','桜吹雪','petal_blizzard',9)]
    displayed = {}
    for group in page.root.nodes(cls='kaikaList__item'):
        label = unique([norm(n.text()) for n in group.nodes(cls='kaikaList__title')],'Missing/duplicate visible sakura milestone label.')
        raw = unique([norm(n.text()) for n in group.nodes(cls='kaikaList__content')],'Missing/duplicate visible sakura milestone date.')
        if label in displayed or label not in {f[1] for f in fields}: fail('Unknown/duplicate Weathernews sakura milestone.')
        displayed[label] = raw
    events = []
    for key,label,milestone,threshold in fields:
        raw = primitive(data,state,key)
        if ended or label not in displayed:
            events.append({'milestone':milestone,'kind':'unavailable','date':None,
                           'reason':'season_updates_ended' if ended else 'not_displayed_by_source'})
            continue
        if not prediction:
            raise SourceError('unverified_sakura_prediction_kind','Visible sakura dates lack the verified prediction marker.')
        if rank >= threshold: fail('Visible sakura prediction disagrees with source stage visibility.')
        date = month_day(raw,year)
        if not re.fullmatch(r'\d{1,2}/\d{1,2}',raw) or displayed[label] != raw.replace('/','月')+'日':
            fail('Weathernews visible sakura prediction disagrees with page data.')
        if not species.strip(): fail('Weathernews sakura prediction species is missing.')
        events.append({'milestone':milestone,'label_ja':label,'kind':'forecast','date':date.isoformat(),
                       'raw':displayed[label],'species_ja':species,'approximate':False,'issued_at':None,
                       'date_has_passed':date < now.date()})
    return condition,events,None


def parse(raw, season, identity, name, year, now, expected=None):
    page = Page(raw)
    page.canonical(wn_url(season,'spot',identity))
    source_year = season_year(page,season)
    data = Nuxt(page)
    meta = unique(data.objects(['spotid','cityname','kind','contact','name' if season == 'foliage' else 'spotname']), 'Weathernews exact spot metadata is missing/duplicated.')
    actual = primitive(data,meta,'spotid')
    native_name = primitive(data,meta,'name' if season == 'foliage' else 'spotname')
    h1 = [norm(n.text()) for n in page.root.nodes('h1') if norm(n.text())]
    if actual != identity or norm(native_name) != norm(name) or h1 != [norm(native_name)]:
        fail('Requested Weathernews spot ID/name/title do not agree.')
    scope = {'kind':'spot','spot_id':actual,'name_ja':native_name,'city_ja':primitive(data,meta,'cityname'),
             'prefecture_ja':primitive(data,meta,'prefname' if season == 'foliage' else 'pref')}
    if expected and any(norm(scope[k]) != norm(expected[k]) for k in ('name_ja','city_ja','prefecture_ja')):
        fail('Weathernews directory/spot native identities disagree.')
    text = norm(page.root.text())
    ended = bool(re.search(str(source_year)+r'年の桜開花情報の更新は終了しました',text)) if season == 'sakura' else False
    base = {'provider':PROVIDER,'publisher':PUBLISHER,'source_year':source_year,'scope':scope,'issued_at':None,
            'forecast_updates_ended':ended,'species_ja':primitive(data,meta,'kind'),
            'usual_timing_raw':primitive(data,meta,'reinennomigoro' if season == 'foliage' else 'reinen')}
    if season == 'sakura': base['prediction_species_ja'] = primitive(data,meta,'fcst_tree_kind')
    if source_year != year:
        return {**base,'status':'unavailable','reason':'requested_year_not_on_source','events':[],'condition':None}
    condition,events,reason = foliage(page,data,year,now) if season == 'foliage' else sakura(page,data,year,now,ended,base['prediction_species_ja'])
    archived = ended or source_year < now.year
    has_forecast = any(e['kind']=='forecast' for e in events)
    return {**base,'status':'archived' if archived else 'ok' if has_forecast else 'partial' if condition else 'unavailable',
            'condition':condition,'events':events,'reason':reason,
            'warnings':['Forecast issue time is unverified; retrieval time and condition as-of date are not forecast issue time.',
                        'Milestones do not promise a viewing window. Conditions can differ within a spot.',
                        'Community photos/reports, typical seasonal timing and current provider records are distinct.']}
