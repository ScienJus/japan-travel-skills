"""Offline checks for isolated, blind behavior-test preparation; no model or network calls."""

import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import prepare_behavior_check as behavior


class BehaviorPreparationTests(unittest.TestCase):
    def test_blind_task_has_relocatable_skills_and_separate_unscored_rubric(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'run'
            task = behavior.prepare('distant-weather', run, today=dt.date(2026, 12, 10))
            text = task.read_text()
            self.assertIn('2027-01-14', text)
            self.assertNotIn(str(ROOT), text)
            rubric = json.loads((run / 'review.json').read_text())
            self.assertEqual(rubric['status'], 'unreviewed')
            self.assertTrue(all(value is None for value in rubric['evaluation_caps'].values()))
            self.assertIsNone(rubric['resource_usage']['elapsed_seconds'])
            self.assertIsNone(rubric['resource_usage']['monetary_cost'])
            self.assertTrue(all(item['score'] is None for item in rubric['criteria']))
            for item in rubric['criteria']:
                self.assertNotIn(item['criterion'], text)
            for skill in (run / 'installed/skills').iterdir():
                self.assertIn(str(skill / 'SKILL.md'), text)
                self.assertTrue((skill / 'LICENSE').is_file())
            self.assertFalse((run / 'installed/AGENTS.md').exists())
            self.assertFalse((run / 'installed/tests').exists())
            self.assertTrue((run / 'installed/skills/japan-transit/scripts/transit_network.py').is_file())

    def test_research_directory_cannot_mask_relative_installed_calls(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'run'
            task = behavior.prepare('hotel-radius', run)
            rubric = json.loads((run / 'review.json').read_text())
            workspace = Path(rubric['working_directory'])
            self.assertEqual(workspace, run.resolve() / 'research')
            self.assertEqual(list(workspace.iterdir()), [])
            self.assertIn(str(workspace), task.read_text())
            self.assertFalse((workspace / 'skills').exists())
            self.assertFalse((workspace / '.agents/skills').exists())
            self.assertTrue((run / 'installed/skills/japan-hotels/scripts/hotels.py').is_file())

    def test_full_trip_has_no_evaluation_cap_and_uses_next_autumn(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'run'
            task = behavior.prepare('hokuriku-six-day-plan', run, today=dt.date(2026, 12, 10))
            review = json.loads((run / 'review.json').read_text())
            self.assertIn('2027 年 11 月 28 日', review['request'])
            self.assertTrue(all(value is None for value in review['evaluation_caps'].values()))
            self.assertTrue(all(value is None for value in review['resource_usage']['tokens'].values()))
            text = task.read_text()
            self.assertNotIn('at most 40', text)
            self.assertNotIn('within 15 minutes', text)
            self.assertIn("honor each source's request limits", text)

    def test_source_tree_and_resolved_alias_are_rejected_without_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            alias = Path(temporary) / 'source'
            alias.symlink_to(ROOT, target_is_directory=True)
            for output in (ROOT / 'behavior-run', alias / 'behavior-run'):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, 'outside'):
                    behavior.prepare('hotel-radius', output)
                self.assertFalse(output.exists())

    def test_existing_records_and_invalid_preparations_are_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            run = Path(temporary) / 'run'
            run.mkdir()
            record = run / 'review.json'
            record.write_text('preserve review')
            with self.assertRaises(FileExistsError):
                behavior.prepare('hotel-radius', run)
            self.assertEqual(record.read_text(), 'preserve review')
            self.assertEqual(list(run.iterdir()), [record])
            for case, python in [('missing-case', sys.executable), ('hotel-radius', str(run / 'missing-python'))]:
                output = Path(temporary) / 'uncreated'
                with self.subTest(case=case), self.assertRaises(ValueError):
                    behavior.prepare(case, output, python=python)
                self.assertFalse(output.exists())


if __name__ == '__main__':
    unittest.main()
