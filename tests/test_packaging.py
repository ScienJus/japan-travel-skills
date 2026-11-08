"""Offline distribution checks: relocation, bundled data and executable entry points."""

import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zipfile import ZipFile


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
SPEC = importlib.util.spec_from_file_location("build_plugin", ROOT / "scripts/build_plugin.py")
BUILDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BUILDER)
COMMANDS = {"japan-weather": "weather.py", "japan-transit": "transit.py",
            "japan-holidays": "holidays.py", "japan-daylight": "daylight.py", "japan-seasons": "seasons.py",
            "japan-fuji": "fuji.py", "japan-hotels": "hotels.py", "japan-passes": "passes.py",
            "tabelog": "tabelog.py", "tablecheck": "tablecheck.py", "pocket-concierge": "pocket_concierge.py"}
GUIDANCE_SKILLS = {"japan-city-guide", "japan-travel-planner"}
SKILLS = set(COMMANDS) | GUIDANCE_SKILLS


def copy_source(destination):
    destination.mkdir()
    for name in BUILDER.ROOT_FILES:
        target = destination / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ROOT / name, target)
    for directory in ("bin", "skills"):
        shutil.copytree(ROOT / directory, destination / directory,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


class PackagingTests(unittest.TestCase):
    def test_private_release_content_fails_before_overwriting_an_artifact(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            source = temporary / "source"
            copy_source(source)
            original = (source / "README.md").read_text()
            value = "synthetic-canary-" + "q" * 24
            canaries = ("fixture-owner" + "@" + "mail-provider.com",
                        "/Users/" + "演练用户/project",
                        json.dumps({"password": value}), json.dumps({"api_key": value}))
            output = temporary / "existing.zip"
            output.write_bytes(b"previous reviewed artifact")
            for index, canary in enumerate(canaries):
                with self.subTest(case=index):
                    (source / "README.md").write_text(original + "\n" + canary + "\n", encoding="utf-8")
                    with self.assertRaisesRegex(ValueError, "Privacy check failed") as caught:
                        BUILDER.build(source, output)
                    self.assertNotIn(canary, str(caught.exception))
                    self.assertNotIn(value, str(caught.exception))
                    self.assertEqual(output.read_bytes(), b"previous reviewed artifact")

    def test_default_output_uses_external_user_artifact_directory(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(Path, "home", return_value=Path(temporary)):
            version = json.loads((ROOT / "plugin.json").read_text())["version"]
            output = BUILDER.default_output()
            self.assertEqual(output, Path(temporary) / ".local/share/japan-travel-skills/artifacts" /
                             ("japan-travel-{}.zip".format(version)))
            self.assertNotIn(ROOT, output.parents)

    def test_source_tree_outputs_are_rejected_before_writes(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "checkout"
            root.mkdir()
            for output in (root / "dist/plugin.zip", root / "skills/plugin.zip"):
                with self.subTest(output=output), self.assertRaisesRegex(ValueError, "outside the source"):
                    BUILDER.build(root, output)
                self.assertFalse(output.parent.exists())
            linked = Path(temporary) / "linked-checkout"
            linked.symlink_to(root, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "outside the source"):
                BUILDER.build(root, linked / "plugin.zip")
            self.assertFalse((root / "plugin.zip").exists())

    def test_extracted_plugin_runs_without_checkout(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bundle = BUILDER.build(ROOT, temporary / "plugin.zip")
            extracted = temporary / "extracted"
            with ZipFile(bundle) as archive:
                archive.extractall(extracted)
                # Python's ZIP extractor does not restore Unix executable bits.
                for name in COMMANDS:
                    executable = extracted / "bin" / name
                    executable.chmod(archive.getinfo("bin/" + name).external_attr >> 16 & 0o777)
            marketplace = json.loads((extracted / ".agents/plugins/marketplace.json").read_text())
            entry, = marketplace["plugins"]
            plugin = (extracted / entry["source"]["path"]).resolve()
            self.assertEqual(plugin, extracted.resolve())
            manifest = json.loads((plugin / "plugin.json").read_text())
            self.assertEqual(entry["name"], manifest["name"])
            self.assertTrue(manifest["extensions"]["com.openai"]["requires_local_executor"])
            self.assertEqual({p.parent.name for p in (plugin / "skills").glob("*/SKILL.md")}, SKILLS)
            for skill in SKILLS:
                self.assertTrue((plugin / "skills" / skill / "agents/openai.yaml").is_file())
            for name, script in COMMANDS.items():
                # Each skill must work with no sibling skills or root resources.
                isolated = temporary / "independent" / name
                shutil.copytree(plugin / "skills" / name, isolated)
                self.assertEqual((isolated / "LICENSE").read_bytes(), (plugin / "LICENSE").read_bytes())
                for command, working in (([str(plugin / "bin" / name)], temporary),
                                         ([sys.executable, str(isolated / "scripts" / script)], temporary)):
                    arguments = ("doctor", "--help", "lines") if name == "japan-transit" else ("doctor", "--help")
                    for argument in arguments:
                        with self.subTest(skill=name, command=command, argument=argument):
                            environment = dict(os.environ, TABELOG_PYTHON=sys.executable,
                                               TABLECHECK_PYTHON=sys.executable, POCKET_CONCIERGE_PYTHON=sys.executable)
                            result = subprocess.run(command + [argument], cwd=working, env=environment,
                                                    capture_output=True, text=True, timeout=10)
                            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
                            if argument == "lines":
                                value = json.loads(result.stdout)
                                self.assertEqual((len(value["lines"]), value["usage"]["http_requests"]), (10, 0))

    def test_missing_skill_licenses_fail_before_overwriting_output(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            fixture = temporary / "source"
            copy_source(fixture)
            output = temporary / "existing.zip"
            output.write_bytes(b"preserve previous artifact")
            for name in SKILLS:
                license_path = fixture / "skills" / name / "LICENSE"
                original = license_path.read_bytes()
                license_path.unlink()
                with self.subTest(skill=name), self.assertRaisesRegex(ValueError, "LICENSE"):
                    BUILDER.build(fixture, output)
                self.assertEqual(output.read_bytes(), b"preserve previous artifact")
                license_path.write_bytes(original)

    def test_guidance_skill_is_relocatable_without_a_cli_or_root_resources(self):
        import re
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            bundle = BUILDER.build(ROOT, temporary / "plugin.zip")
            with ZipFile(bundle) as archive:
                for name in GUIDANCE_SKILLS:
                    self.assertNotIn("bin/" + name, archive.namelist())
                    prefix = "skills/" + name + "/"
                    isolated = temporary / "independent" / name
                    for member in archive.namelist():
                        if member.startswith(prefix):
                            target = isolated / member[len(prefix):]
                            target.parent.mkdir(parents=True, exist_ok=True)
                            target.write_bytes(archive.read(member))
                    self.assertEqual((isolated / "LICENSE").read_bytes(), (ROOT / "LICENSE").read_bytes())
                    self.assertTrue((isolated / "SKILL.md").is_file())
                    for document in isolated.rglob("*.md"):
                        for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text()):
                            if "://" not in target and not target.startswith("#"):
                                path = (document.parent / target.split("#", 1)[0]).resolve()
                                self.assertIn(isolated.resolve(), path.parents)
                                self.assertTrue(path.is_file(), target)

    def test_new_skill_requires_explicit_release_registration(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            fixture = temporary / "source"
            copy_source(fixture)
            extra = fixture / "skills" / "japan-example"
            extra.mkdir()
            (extra / "SKILL.md").write_text("synthetic unregistered skill")
            output = temporary / "plugin.zip"
            with self.assertRaisesRegex(ValueError, "unregistered.*japan-example"):
                BUILDER.build(fixture, output)
            self.assertFalse(output.exists())

    def test_release_file_and_parent_directory_symlinks_are_rejected(self):
        for directory_link in (False, True):
            with self.subTest(directory_link=directory_link), tempfile.TemporaryDirectory() as temporary:
                temporary = Path(temporary)
                fixture = temporary / "source"
                copy_source(fixture)
                target = fixture / "skills/japan-passes" / ("references" if directory_link else "LICENSE")
                moved = temporary / target.name
                target.rename(moved)
                target.symlink_to(moved, target_is_directory=directory_link)
                output = temporary / "plugin.zip"
                with self.assertRaisesRegex(ValueError, "symlinks"):
                    BUILDER.build(fixture, output)
                self.assertFalse(output.exists())

    def test_reproducible_and_excludes_development_files(self):
        with tempfile.TemporaryDirectory() as temporary:
            temporary = Path(temporary)
            fixture = temporary / "source"
            copy_source(fixture)
            unwanted = ["research/capture.json", "docs/hotel-discovery-source-audit.md",
                        "docs/installation-validation.md", ".git/config", "tests/test_private.py",
                        "skills/japan-weather/scripts/__pycache__/weather.pyc",
                        "skills/.DS_Store", "bin/.env.local", "bin/debug.log", "bin/unregistered-cli",
                        "skills/japan-weather/.env.local", "skills/japan-weather/.pytest_cache/state",
                        "skills/japan-hotels/debug.log", "skills/japan-weather/scripts/capture.json",
                        "skills/japan-weather/scripts/scratch.py", "skills/japan-weather/references/capture.md"]
            for name in unwanted:
                path = fixture / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("not for distribution", encoding="utf-8")
            first = BUILDER.build(fixture, temporary / "first.zip")
            for path in fixture.rglob("*"):
                if path.is_file():
                    os.utime(path, (1234567890, 1234567890))
            second = BUILDER.build(fixture, temporary / "second.zip")
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with ZipFile(first) as archive:
                self.assertTrue(set(unwanted).isdisjoint(archive.namelist()))


if __name__ == "__main__":
    unittest.main()
