"""Privacy gates use synthetic canaries and never print a matching value."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_privacy import REVIEWED_SITE_MEDIA, check_archive, check_root, scan_bytes


class PrivacyTests(unittest.TestCase):
    def test_examples_and_public_attribution_are_allowed(self):
        content = b"fixture@example.org https://github.com/public-project /home/runner/work/project"
        self.assertEqual(scan_bytes("README.md", content), [])

    def test_reviewed_pages_media_requires_the_exact_path_and_bytes(self):
        for build_path in REVIEWED_SITE_MEDIA:
            with self.subTest(asset=build_path):
                source_path = "site/" + build_path
                content = (ROOT / source_path).read_bytes()
                self.assertEqual(scan_bytes(source_path, content), [])
                self.assertEqual(scan_bytes(build_path, content), [])
                self.assertEqual([item["rule"] for item in scan_bytes("other/" + build_path, content)],
                                 ["non_text_requires_review"])
                for data in (content + b"changed", b"replacement text"):
                    self.assertEqual([item["rule"] for item in scan_bytes(source_path, data)],
                                     ["reviewed_media_checksum_mismatch"])

    def test_private_paths_and_emails_are_detected_without_the_value(self):
        email = "fixture-recipient" + "@" + "mail-provider.com"
        private_path = "/Users/" + "fixture-person/project"
        findings = scan_bytes("README.md", (email + "\n" + private_path).encode())
        self.assertEqual([(r["line"], r["rule"]) for r in findings],
                         [(1, "email_address"), (2, "personal_home_path")])
        self.assertNotIn(email, json.dumps(findings))
        self.assertNotIn(private_path, json.dumps(findings))

    def test_common_credentials_are_detected_without_values(self):
        values = ["ghp_" + "a" * 36, "AIza" + "b" * 35,
                  "sk-proj-" + "c" * 40, "xoxb-" + "d" * 30,
                  "-----BEGIN " + "PRIVATE KEY-----"]
        findings = scan_bytes("fixture.txt", "\n".join(values).encode())
        self.assertEqual(len(findings), len(values))
        for value in values:
            self.assertNotIn(value, json.dumps(findings))

    def test_unicode_and_space_home_names_are_detected_without_prefix_exemptions(self):
        for user in ("演练用户", "fixture person", "runner-演练", "runner 演练"):
            for prefix, separator in (("/Users/", "/"), ("/home/", "/"),
                                      ("C:" + "\\Users\\", "\\")):
                private_path = prefix + user + separator + "project"
                for content in (private_path, '"' + private_path + '"', prefix + user):
                    with self.subTest(user=user, separator=separator):
                        findings = scan_bytes("fixture.txt", content.encode())
                        self.assertEqual([r["rule"] for r in findings], ["personal_home_path"])
                        self.assertNotIn(user, json.dumps(findings, ensure_ascii=False))
                # A matching path used as a filename must also be withheld.
                findings = scan_bytes(private_path, b"fixture")
                self.assertEqual(findings[0]["path"], "[redacted-path]")

    def test_exact_example_home_names_remain_allowed(self):
        for user in ("user", "runner", "username", "example"):
            for prefix, separator in (("/Users/", "/"), ("/home/", "/"),
                                      ("C:" + "\\Users\\", "\\")):
                for suffix in ("", separator + "project"):
                    with self.subTest(user=user, separator=separator, suffix=suffix):
                        self.assertEqual(scan_bytes("fixture.txt", (prefix + user + suffix).encode()), [])

    def test_quoted_and_unquoted_credential_fields_are_detected(self):
        value = "synthetic-canary-" + "q" * 24
        for key in ("password", "api_key", "API-KEY", "access_token", "secret",
                    "sessionid", "authenticity_token"):
            for content in (json.dumps({key: value}), key + " = '" + value + "'",
                            "'" + key + "': '" + value + "'"):
                with self.subTest(key=key):
                    findings = scan_bytes("fixture.txt", content.encode())
                    self.assertEqual([r["rule"] for r in findings], ["credential_literal"])
                    self.assertNotIn(value, json.dumps(findings))
        for key in ("not_password", "public_api_key_description", "secretary"):
            self.assertEqual(scan_bytes("fixture.txt", json.dumps({key: value}).encode()), [])
        self.assertEqual(scan_bytes("fixture.txt", json.dumps({"password": "short"}).encode()), [])

    def test_source_and_archive_cli_reject_new_canaries_without_disclosure(self):
        value = "synthetic-canary-" + "q" * 24
        private_path = "/Users/" + "演练用户/project"
        content = json.dumps({"api_key": value}) + "\n" + private_path
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "source"
            source.mkdir()
            (source / "fixture.txt").write_text(content, encoding="utf-8")
            archive = Path(temporary) / "fixture.zip"
            with ZipFile(archive, "w") as bundle:
                bundle.writestr("fixture.txt", content)
            for arguments in (("--root", str(source)), ("--archive", str(archive))):
                with self.subTest(mode=arguments[0]):
                    result = subprocess.run([sys.executable, str(ROOT / "scripts/check_privacy.py"),
                                             *arguments], capture_output=True, text=True)
                    self.assertEqual(result.returncode, 1)
                    report = json.loads(result.stdout)
                    self.assertEqual([(r["line"], r["rule"]) for r in report["findings"]],
                                     [(1, "credential_literal"), (2, "personal_home_path")])
                    for private in (value, private_path, temporary):
                        self.assertNotIn(private, result.stdout + result.stderr)
                        self.assertNotIn(private, json.dumps(report, ensure_ascii=False))

    def test_private_filename_is_redacted_too(self):
        path = "notes/fixture" + "@" + "mail-provider.com.txt"
        findings = scan_bytes(path, b"test")
        self.assertEqual(findings[0]["path"], "[redacted-path]")
        self.assertNotIn(path, json.dumps(findings))

    def test_scan_does_not_follow_a_symlink(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "source"
            root.mkdir()
            target = Path(temporary) / "outside.txt"
            target.write_text("never read this")
            (root / "link").symlink_to(target)
            findings = check_root(root)
            self.assertEqual([r["rule"] for r in findings], ["symlink_requires_review"])

    def test_ignored_but_tracked_files_are_still_scanned(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            subprocess.run(["git", "init", "-q", str(root)], check=True, capture_output=True)
            (root / ".gitignore").write_text(".env\n")
            (root / ".env").write_text("fixture=true\n")
            subprocess.run(["git", "add", "-f", ".env"], cwd=root, check=True, capture_output=True)
            self.assertIn("sensitive_filename", [r["rule"] for r in check_root(root)])

    def test_archive_traversal_and_private_contents_are_rejected_without_extraction(self):
        with tempfile.TemporaryDirectory() as temporary:
            archive = Path(temporary) / "fixture.zip"
            with ZipFile(archive, "w") as bundle:
                bundle.writestr("../outside.txt", "not extracted")
                bundle.writestr("README.md", "/home/" + "fixture-person/project")
            findings = check_archive(archive)
            self.assertEqual([r["rule"] for r in findings],
                             ["unsafe_archive_path", "personal_home_path"])
            self.assertFalse((Path(temporary) / "outside.txt").exists())

    def test_cli_failure_reports_only_location_and_rule(self):
        with tempfile.TemporaryDirectory() as temporary:
            email = "fixture-recipient" + "@" + "mail-provider.com"
            (Path(temporary) / "README.md").write_text(email)
            result = subprocess.run([sys.executable, str(ROOT / "scripts/check_privacy.py"),
                                     "--root", temporary], capture_output=True, text=True)
            self.assertEqual(result.returncode, 1)
            self.assertIn("email_address", result.stdout)
            self.assertNotIn(email, result.stdout + result.stderr)
            self.assertNotIn(temporary, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
