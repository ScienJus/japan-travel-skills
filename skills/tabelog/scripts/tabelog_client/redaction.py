"""Redact form verification values and Google API keys from diagnostic source."""
import re

GOOGLE_API_KEY = re.compile(r'AIza[0-9A-Za-z_-]{35}')


def redact_source(body):
    def redact_tag(match):
        tag = match[0]
        if not re.search(r'''\b(?:name|id)\s*=\s*(["'])(?:csrf[-_]?token|authenticity_token|access_token|refresh_token)\1''', tag, re.I):
            return tag
        return re.sub(r'''(\b(?:content|value)\s*=\s*)(["'])(.*?)\2''',
                      lambda m: m[1] + m[2] + '[REDACTED]' + m[2], tag, flags=re.I | re.S)
    body = re.sub(r'<(?:meta|input)\b[^>]*>', redact_tag, body, flags=re.I)
    return GOOGLE_API_KEY.sub('[REDACTED]', body)
