"""Command boundaries and generated help; no external requests."""
import restaurant_test_support  # Resolve the copied skill packages, not an installed checkout.
import io
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import Mock

from tabelog_client.arguments import parse_arguments
from tabelog_client.cli import run
from tabelog_client.transport import Client


class CommandArgumentTests(unittest.TestCase):
    def assert_rejected_before_client(self, args):
        create = Mock(side_effect=AssertionError('Invalid arguments must not create a client'))
        result = run(args, create_client=create)
        self.assertEqual(result['exit_code'], 1)
        self.assertEqual(result['output']['error']['code'], 'invalid_argument')
        self.assertIsNone(result['output']['usage'])
        create.assert_not_called()

    def test_cross_command_options_are_rejected_before_client_creation(self):
        cases = [
            ['search', '--near', '36.58,136.65', '--date', '2099-01-01', '--people', '2'],
            ['search', '--area', 'Ginza', '--after', '18:00'],
            ['search', '--area', 'Ginza', '--full'],
            ['search', '--area', 'Ginza', '--hyakumeiten', '--year', '2026'],
            ['search', '--area', 'Ginza', '--hyakumeiten', '--category', 'sushi_west'],
            ['reviews', '17005534', '--min-rating', '3.5'],
            ['review-read', 'https://tabelog.com/', '--meal', 'dinner'],
            ['detail', '17005534', '--cuisine', '寿司'],
            ['awards', '17005534', '--hyakumeiten'],
            ['channel', '17005534', '--people', '2'],
            ['calendar', '17005534', '--date', '2099-01-01', '--people', '2', '--time', '19:00'],
            ['slots', '17005534', '--date', '2099-01-01', '--people', '2', '--after', '18:00'],
            ['availability', '17005534', '--date', '2099-01-01', '--people', '2', '--pages', '2'],
            ['geocode', 'Kanazawa', '--station', '金沢駅'],
            ['suggest', 'Kanazawa', '--limit', '5'],
            ['station', '金沢駅', '--radius-m', '1000'],
            ['areas', '--prefecture', '17', '--min-rating', '3.5'],
            ['stations', '--area', 'A170101', '--pages', '2'],
            ['hyakumeiten-categories', '--category', 'sushi_west'],
            ['source', 'https://tabelog.com/', '--full'],
            ['doctor', '--limit', '5'],
            ['usage', 'result.json', '--full'],
        ]
        for args in cases:
            with self.subTest(args=args):
                self.assert_rejected_before_client(args)

    def test_required_targets_and_options_are_enforced(self):
        for args in (['detail'], ['suggest'], ['usage'], ['stations'], ['calendar'],
                     ['slots', '17005534', '--people', '2'],
                     ['availability', '17005534', '--people', '2'],
                     ['doctor', 'extra']):
            with self.subTest(args=args):
                self.assert_rejected_before_client(args)

    def test_invalid_station_catalog_call_returns_local_command_guidance(self):
        create = Mock()
        result = run(['stations', '京都駅'], create_client=create)
        self.assertEqual(result['exit_code'], 1)
        error = result['output']['error']
        self.assertIn('--area', error['usage'])
        self.assertEqual(error['help_command'], 'tabelog stations --help')
        create.assert_not_called()

    def test_exclusive_options_are_enforced(self):
        for args in (['areas', '--prefecture', '17', '--city', '金沢市'],
                     ['availability', '17005534', '--date', '2099-01-01',
                      '--from', '2099-01-01', '--to', '2099-01-02', '--people', '2']):
            with self.subTest(args=args):
                self.assert_rejected_before_client(args)

    def test_unknown_commands_options_and_abbreviations_are_rejected(self):
        for args in (['unknown'], ['search', '--unknown'], ['search', '--min-r', '3.5']):
            with self.subTest(args=args):
                self.assert_rejected_before_client(args)

    def test_invalid_values_are_rejected_before_client_creation(self):
        for args in (['search', '--area', 'Ginza', '--pages', '0'],
                     ['search', '--area', 'Ginza', '--min-rating', 'NaN'],
                     ['reviews', '17005534', '--meal', 'breakfast'],
                     ['calendar', '17005534', '--date', '2099-02-30', '--people', '2'],
                     ['doctor', '--delay-min-ms', '2000', '--delay-max-ms', '1000']):
            with self.subTest(args=args):
                self.assert_rejected_before_client(args)

    def test_common_options_work_before_and_after_command(self):
        variants = [
            ['--timeout', '7', '--max-requests', '3', 'doctor', '--delay-min-ms', '300', '--delay-max-ms', '400'],
            ['doctor', '--timeout', '7', '--max-requests', '3', '--delay-min-ms', '300', '--delay-max-ms', '400'],
        ]
        for args in variants:
            with self.subTest(args=args):
                create = Mock(side_effect=lambda **kwargs: Client(**kwargs))
                result = run(args, create_client=create)
                self.assertEqual(result['exit_code'], 0)
                create.assert_called_once_with(timeout=7, max_requests=3, delay_min_ms=300, delay_max_ms=400)
                self.assertEqual(result['output']['usage']['network_requests_started'], 0)

    def test_later_common_option_takes_precedence(self):
        args = parse_arguments(['--timeout', '7', 'doctor', '--timeout', '9'])
        self.assertEqual(args.timeout, 9)

    def test_help_is_generated_for_each_command_without_a_client(self):
        for args in ([], ['--help'], ['-h'], ['search', '--help'], ['calendar', '-h'], ['slots', '--help']):
            with self.subTest(args=args):
                create = Mock()
                output, errors = io.StringIO(), io.StringIO()
                with redirect_stdout(output), redirect_stderr(errors):
                    result = run(args, create_client=create)
                self.assertEqual(result['exit_code'], 0)
                self.assertIn('usage: tabelog', result['help'])
                self.assertEqual(output.getvalue(), '')
                self.assertEqual(errors.getvalue(), '')
                create.assert_not_called()
        search = run(['search', '--help'])['help']
        calendar = run(['calendar', '--help'])['help']
        self.assertIn('--min-rating', search)
        self.assertIn('--timeout', search)
        self.assertNotIn('--people', search)
        self.assertNotIn('--date ', search)
        self.assertNotIn('--category', search)
        self.assertNotIn('--year', search)
        self.assertIn('--people', calendar)
        self.assertNotIn('--time ', calendar)

    def test_command_specific_defaults_and_repeatable_filters(self):
        search = parse_arguments(['search', '--near', '36.58,136.65', '--area', '金沢',
                                  '--cuisine', '寿司', '--cuisine', '天ぷら', '--hyakumeiten'])
        self.assertEqual(search.cuisine, ['寿司', '天ぷら'])
        self.assertTrue(search.hyakumeiten)
        self.assertEqual((search.pages, search.limit, search.radius_m), (2, 5, 1000))
        reviews = parse_arguments(['reviews', '17005534'])
        self.assertEqual((reviews.pages, reviews.limit), (2, 20))
        slots = parse_arguments(['slots', '17005534', '--people', '2', '--date', '2099-01-01'])
        self.assertIsNone(slots.time)
        for name in ('calendar', 'slots', 'availability'):
            self.assertIsNone(parse_arguments([name, '17005534', '--date', '2099-01-01']).people)


if __name__ == '__main__':
    unittest.main()
