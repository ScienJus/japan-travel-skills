"""Metadata and links must survive distribution and independent-skill use."""

import importlib.util
from pathlib import Path
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("check_repo", ROOT / "scripts/check_repo.py")
CHECKER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CHECKER)


def fixture(root):
    files = {
        "README.md": "[skill](skills/example/SKILL.md)\n",
        "AGENTS.md": "Instructions\n",
        "plugin.json": '{"name":"example"}',
        ".agents/plugins/marketplace.json": '{"plugins":[{"name":"example","source":{"source":"local","path":"./"}}]}',
        "skills/example/SKILL.md": "---\nname: example\ndescription: Example skill\n---\n[notes](references/notes.md)\n",
        "skills/example/references/notes.md": "Notes\n",
        "skills/example/agents/openai.yaml": 'interface:\n  display_name: "Example"\n  short_description: "A useful example of skill metadata"\n  default_prompt: "Use $example to answer my question."\n',
    }
    for name, text in files.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")


class RepositoryChecksTests(unittest.TestCase):
    def test_independent_runtime_pins_agree_with_bundle_lock(self):
        canonical = {line.strip() for line in (ROOT / 'requirements.lock').read_text().splitlines()
                     if line.strip() and not line.startswith('#')}
        for requirements in (ROOT / 'skills').glob('*/scripts/requirements.txt'):
            for line in requirements.read_text().splitlines():
                if line.strip() and not line.startswith('#'):
                    with self.subTest(file=requirements.parent.parent.name, requirement=line):
                        self.assertIn(line.strip(), canonical)

    def test_current_repository(self):
        self.assertEqual(CHECKER.check(ROOT), [])

    def test_broken_reference_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            (root / "skills/example/references/notes.md").unlink()
            self.assertTrue(any("missing or external local link" in error for error in CHECKER.check(root)))

    def test_missing_plugin_identity_is_not_a_match(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            (root / "plugin.json").write_text("{}", encoding="utf-8")
            (root / ".agents/plugins/marketplace.json").write_text('{"plugins":[{}]}', encoding="utf-8")
            self.assertTrue(any("plugin name" in error for error in CHECKER.check(root)))

    def test_skill_cannot_depend_on_root_document(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            path = root / "skills/example/references/notes.md"
            path.write_text("[setup](../../../README.md)", encoding="utf-8")
            self.assertTrue(any("escapes its directory" in error for error in CHECKER.check(root)))

    def test_malformed_frontmatter_and_wrong_name_are_reported(self):
        for body in ("---\nname: [\n---\n", "---\nname: other\ndescription: Valid\n---\n"):
            with self.subTest(body=body), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                fixture(root)
                (root / "skills/example/SKILL.md").write_text(body, encoding="utf-8")
                self.assertTrue(CHECKER.check(root))

    def test_wrong_ui_invocation_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture(root)
            path = root / "skills/example/agents/openai.yaml"
            path.write_text(path.read_text().replace("$example", "$other"), encoding="utf-8")
            self.assertTrue(any("must name this skill" in error for error in CHECKER.check(root)))


if __name__ == "__main__":
    unittest.main()
