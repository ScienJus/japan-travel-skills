"""Group published venue policies without turning prose into eligibility."""
import re
from urllib.parse import parse_qsl, urlsplit

from bs4 import BeautifulSoup

from .transport import CliError


def practical_info(venue, booking_url, page=None):
    source = f"https://production.tablecheck.com/v2/shops/{venue['slug']}"
    evidence = []
    policies = [{'field': 'request_policy_translations', 'locale': item.get('locale'), 'text': item.get('translation'), 'source_url': source}
                for item in venue.get('request_policy_translations') or [] if item.get('locale') in ('en', 'ja')]
    if page is not None:
        form = BeautifulSoup(page, 'html.parser')
        for notice in form.select('.reserveform-bookingpolicy-text'):
            policies.append({'field': 'public_form.notice', 'text': notice.decode_contents(), 'source_url': booking_url})
    for policy in policies:
        if not isinstance(policy.get('text'), str):
            if policy.get('text') is not None:
                raise CliError('unexpected_response', 'Published reservation policy text is invalid.')
            continue
        text = re.sub(r'<br\s*/?>', '\n', policy['text'], flags=re.I)
        text = re.sub(r'</(?:p|div|li)>', '\n\n', text, flags=re.I)
        text = BeautifulSoup(text, 'html.parser').get_text().strip()
        for paragraph in re.split(r'\n\s*\n', text):
            if paragraph.strip():
                evidence.append({**policy, 'text': paragraph.strip()})
    payment = [item for item in evidence if re.search(r'現金|カード|支払|決済|電子マネー|cash\b|credit|payment|paypay', item['text'], re.I)]
    children = [item for item in evidence if re.search(r'お子|子供|子ども|乳児|幼児|未就学|小学生|child(?:ren)?|infants?|bab(?:y|ies)|kids?', item['text'], re.I)]
    links = []
    if booking_url:
        links.append({'kind': 'booking_entry', 'platform': 'tablecheck', 'url': booking_url,
                      'source_url': source, 'field': 'booking_page_mode', 'verification': 'platform_listing'})
    website = venue.get('url')
    if isinstance(website, str):
        try:
            parsed = urlsplit(website)
            if (parsed.scheme in ('http', 'https') and parsed.hostname and not parsed.username and not parsed.password
                    and not any(re.search(r'token|secret|key|auth|session|password|signature', key, re.I) for key, _ in parse_qsl(parsed.query))):
                links.append({'kind': 'website', 'platform': None, 'url': website, 'source_url': source,
                              'field': 'url', 'verification': 'listed_link'})
        except ValueError:
            pass
    return {'reservation': {'accepted': None, 'required': None, 'evidence': evidence, 'availability_checked': False},
            'payment': {'cash_only': None, 'credit_cards_accepted': None, 'electronic_money_accepted': None,
                        'qr_payments_accepted': None, 'evidence': payment},
            'children': {'evidence': children, 'eligibility_checked': False}, 'links': links}
