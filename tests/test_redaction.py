"""Diagnostic source retains structure without publishing live form verification values."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import unittest

from tabelog_client.cli import run
from tabelog_client.redaction import redact_source
from tabelog_client.transport import Client


class SourceRedactionTests(unittest.TestCase):
    def test_attributes_order_quotes_and_case_do_not_leak_values(self):
        body = '''<meta content="fixture-csrf" name="csrf-token">
        <INPUT VALUE='fixture-form' type='hidden' NAME='authenticity_token'>
        <input id="csrfToken" value="fixture-id"/>
        <meta name="csrf-param" content="authenticity_token">
        <input name="rst_id" value="16010357">'''
        result = redact_source(body)
        for value in ('fixture-csrf', 'fixture-form', 'fixture-id'):
            self.assertNotIn(value, result)
        self.assertEqual(result.count('[REDACTED]'), 3)
        self.assertIn('content="authenticity_token"', result)
        self.assertIn('value="16010357"', result)

    def test_cli_source_redacts_output_without_altering_measured_body_size(self):
        body = '<input name="authenticity_token" value="fixture-private-form">'
        result = run(['source', 'https://tabelog.com/en/'], create_client=lambda **_:
                     Client(reader=lambda url: {'url': url, 'http_status': 200, 'body': body,
                            'metrics': {'network_requests_started': 1, 'response_body_bytes': len(body.encode())}},
                            delay_min_ms=0, delay_max_ms=0))
        self.assertEqual(result['exit_code'], 0)
        self.assertNotIn('fixture-private-form', result['output']['data']['body'])
        self.assertEqual(result['output']['usage']['response_body_bytes'], len(body.encode()))

    def test_xml_and_javascript_without_token_fields_are_preserved(self):
        for body in ('<items><item optval="17" name="石川"/></items>',
                     'const tokenName = "csrf-token";', '{"hyakumeitenCategoryList":[{"id":212,"name":"寿司 WEST"}]}'):
            self.assertEqual(redact_source(body), body)
