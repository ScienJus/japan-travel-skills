"""Published practical details; no inventory checks or outbound-link requests."""
import re
from urllib.parse import parse_qsl, urljoin, urlsplit


def public_link(value, base):
    try:
        value = urljoin(base, value)
        parsed = urlsplit(value)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            return None
        if any(re.search(r'token|secret|key|auth|session|password|signature', key, re.I) for key, _ in parse_qsl(parsed.query)):
            return None
        return value
    except ValueError:
        return None


def practical_info(doc, info, url):
    def evidence(rows):
        return [{'field': row['label'], 'text': row['value'], 'source_url': url} for row in rows]

    reservation_rows = [row for row in info if re.search(r'予約可否|reservation availability', row['label'], re.I)]
    payment_rows = [row for row in info if re.search(r'支払[い]?方法|payment methods?', row['label'], re.I)]
    payment_notes = [row for row in info if row not in payment_rows and re.search(r'現金|カード|支払|決済|電子マネー|cash\b|credit cards?|payment|paypay', row['value'], re.I)]
    children_rows = [row for row in info if re.search(r'お子様|子供|子ども|乳児|幼児|未就学|小学生|family friendly|child(?:ren)?|infants?|bab(?:y|ies)|kids?', row['label']+'\n'+row['value'], re.I)]
    states = {'予約可': (True, False), '予約不可': (False, False), '完全予約制': (True, True), '予約制': (True, True),
              'reservation only': (True, True), 'reservations available': (True, False),
              'reservations accepted': (True, False), 'reservations not accepted': (False, False),
              'reservations unavailable': (False, False)}
    observed = {states.get(row['value'].splitlines()[0].strip().rstrip('。.!').casefold(), (None, None)) for row in reservation_rows}
    accepted, required = observed.pop() if len(observed) == 1 else (None, None)
    # "予約可" does not establish that walk-ins are accepted.
    if required is False and accepted is True:
        required = None
    payment_text = '\n'.join(row['value'] for row in payment_rows)

    def method(pattern):
        values = set()
        for match in re.finditer(pattern, payment_text, re.I | re.M):
            values.add(match[1].casefold() in ('可', 'accepted'))
        return values.pop() if len(values) == 1 else None

    cards = method(r'^[ \t]*(?:カード|credit cards?)[ \t]*(不可|可|not accepted|accepted)[ \t]*$')
    electronic = method(r'^[ \t]*(?:電子マネー|electronic money)[ \t]*(不可|可|not accepted|accepted)[ \t]*$')
    qr = method(r'^[ \t]*(?:QRコード決済|QR code payments?)[ \t]*(不可|可|not accepted|accepted)[ \t]*$')
    cash_only = True if any(re.fullmatch(r'(?:現金のみ|cash only)[。.!]?', row['value'].strip(), re.I) for row in payment_rows) else None
    if any(value is True for value in (cards, electronic, qr)):
        cash_only = None if cash_only else False
    if payment_notes:
        # Remarks may qualify or contradict the dedicated payment table.
        cash_only = cards = electronic = qr = None

    links = [{'kind': 'platform_listing', 'platform': 'tabelog', 'url': url, 'source_url': url,
              'field': 'restaurant', 'verification': 'listed_link'}]
    for row in doc.select('.rstinfo-table tr, .rstinfo-table__table tr'):
        label = row.find('th', recursive=False)
        label = label.get_text(' ', strip=True) if label else ''
        website = bool(re.search(r'ホームページ|公式サイト|website|homepage', label, re.I))
        reservation = bool(re.search(r'予約|reserv', label, re.I))
        for anchor in row.select('td a[href]'):
            target = public_link(anchor['href'], url)
            if not target:
                continue
            parsed = urlsplit(target)
            host = parsed.hostname
            platform = ('tablecheck' if host in ('tablecheck.com', 'www.tablecheck.com') and re.search(r'/reserve(?:/|$)', parsed.path)
                        else 'pocket_concierge' if host in ('pocket-concierge.jp', 'www.pocket-concierge.jp') and re.search(r'/restaurants/[0-9]+/?$', parsed.path)
                        else None)
            if platform or website or reservation:
                item = {'kind': 'booking_entry' if platform else 'reservation_reference' if reservation else 'website', 'platform': platform,
                        'url': target, 'source_url': url, 'field': label, 'verification': 'listed_link'}
                if not any(old['url'] == target for old in links):
                    links.append(item)
    return {'reservation': {'accepted': accepted, 'required': required, 'evidence': evidence(reservation_rows), 'availability_checked': False},
            'payment': {'cash_only': cash_only, 'credit_cards_accepted': cards, 'electronic_money_accepted': electronic,
                        'qr_payments_accepted': qr, 'evidence': evidence(payment_rows+payment_notes)},
            'children': {'evidence': evidence(children_rows), 'eligibility_checked': False}, 'links': links}
