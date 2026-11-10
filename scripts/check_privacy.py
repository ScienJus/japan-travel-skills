#!/usr/bin/env python3
"""Check publishable source files or a ZIP; report locations/rules, never matching values."""

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
from zipfile import BadZipFile, ZipFile


ROOT = Path(__file__).resolve().parents[1]
EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@([A-Za-z0-9.-]+\.[A-Za-z]{2,})")
# Read the entire username component, including Unicode and spaces. In particular,
# an allowed example prefix must not hide a different user's full name.
HOME = re.compile(r"/(?:Users|home)/([^/\\\r\n\"'<>`]+?)(?=/|[\"'<>`\r\n]|$)")
WINDOWS_HOME = re.compile(
    r"(?i)\b[A-Z]:\\+Users\\+([^/\\\r\n\"'<>`]+?)(?=[/\\]|[\"'<>`\r\n]|$)")
TOKENS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA |ENCRYPTED )?PRIVATE KEY-----"),
    "github_token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{50,})\b"),
    "cloud_access_key": re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),
    "google_api_key": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "api_token": re.compile(r"\bsk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{32,}\b"),
    "slack_token": re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    "credential_literal": re.compile(
        r"(?i)(?<![\w-])(?P<key_quote>[\"']?)"
        r"(?:api[_-]?key|password|access[_-]?token|secret|sessionid|authenticity_token)"
        r"(?P=key_quote)\s*[:=]\s*(?P<value_quote>[\"'])"
        r"[A-Za-z0-9_+/=-]{20,}(?P=value_quote)"),
    "url_credentials": re.compile(r"https?://[^\s/@:]+:[^\s/@]+@"),
}
EXAMPLE_USERS = {"user", "runner", "username", "example"}
SKIP_DIRS = {".git", ".venv", "venv", "env", "__pycache__", ".pytest_cache",
             ".mypy_cache", ".ruff_cache", ".tox", ".nox", "node_modules"}
MAX_FILE_BYTES = 8 * 1024 * 1024
# Public Manrope font reviewed for the Pages source and build. See site/README.md.
SITE_FONT_PATHS = {"site/assets/manrope.woff2", "assets/manrope.woff2"}
SITE_FONT_SHA256 = "8bd97e6bbbc1f602a8f791530eed1064c9a357d5731bbc76e3fc587fb068728f"


def example_domain(domain):
    domain = domain.lower().rstrip(".")
    return any(domain == suffix or domain.endswith("." + suffix)
               for suffix in ("example.com", "example.net", "example.org", "example", "invalid", "test"))


def private_matches(text):
    for match in EMAIL.finditer(text):
        if not example_domain(match[1]):
            yield "email_address", match.span()
    for pattern in (HOME, WINDOWS_HOME):
        for match in pattern.finditer(text):
            if match[1].lower() not in EXAMPLE_USERS:
                yield "personal_home_path", match.span()
    for rule, pattern in TOKENS.items():
        for match in pattern.finditer(text):
            yield rule, match.span()


def display_path(path):
    # Even a filename can contain a token or email. Do not put it in a diagnostic.
    return "[redacted-path]" if any(private_matches(path)) else path


def finding(path, line, rule):
    return {"path": display_path(str(path)), "line": line, "rule": rule}


def scan_bytes(path, data):
    name = PurePosixPath(str(path)).name.lower()
    findings = []
    if (name.startswith(".env") and name not in (".env.example", ".env.sample")
            or name in ("id_rsa", "id_ed25519", ".netrc", ".npmrc", ".pypirc",
                        ".git-credentials", "cookies.txt", "cookies.json")
            or name.endswith((".p12", ".pfx", ".pem", ".key"))):
        findings.append(finding(path, 1, "sensitive_filename"))
    if any(private_matches(str(path))):
        findings.append(finding(path, 1, "sensitive_filename_content"))
    if len(data) > MAX_FILE_BYTES:
        return findings + [finding(path, 1, "oversized_file_requires_review")]
    if str(path) in SITE_FONT_PATHS:
        if sha256(data).hexdigest() != SITE_FONT_SHA256:
            findings.append(finding(path, 1, "reviewed_media_checksum_mismatch"))
        return findings
    try:
        if b"\0" in data:
            raise UnicodeError()
        text = data.decode("utf-8-sig")
    except UnicodeError:
        return findings + [finding(path, 1, "non_text_requires_review")]
    for number, line in enumerate(text.splitlines(), 1):
        findings.extend(finding(path, number, rule) for rule in
                        sorted({rule for rule, _ in private_matches(line)}))
    return findings


def source_files(root):
    if (root / ".git").exists():
        # Include untracked release candidates and tracked files even if now ignored.
        result = subprocess.run(
            ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
            cwd=root, capture_output=True, check=True)
        return sorted({os.fsdecode(p) for p in result.stdout.split(b"\0") if p})
    files = []
    for current, directories, names in os.walk(root, followlinks=False):
        for name in list(directories):
            path = Path(current) / name
            if path.is_symlink():
                files.append(path.relative_to(root).as_posix())
                directories.remove(name)
            elif name in SKIP_DIRS:
                directories.remove(name)
        files.extend((Path(current) / name).relative_to(root).as_posix() for name in names)
    return sorted(files)


def check_root(root):
    root = Path(root).resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Expected a source directory")
    findings = []
    for relative in source_files(root):
        path = root / relative
        # Do not follow files or parent-directory links outside the source tree.
        parents = path.relative_to(root).parts
        if any((root.joinpath(*parents[:n])).is_symlink() for n in range(1, len(parents) + 1)):
            findings.append(finding(relative, 1, "symlink_requires_review"))
        elif path.exists():
            if not path.is_file():
                findings.append(finding(relative, 1, "non_regular_file"))
            elif path.stat().st_size > MAX_FILE_BYTES:
                findings.append(finding(relative, 1, "oversized_file_requires_review"))
            else:
                findings.extend(scan_bytes(relative, path.read_bytes()))
    return findings


def check_archive(path):
    findings = []
    with ZipFile(path) as archive:
        if len(archive.infolist()) > 5000 or sum(m.file_size for m in archive.infolist()) > 32 * 1024 * 1024:
            return [finding("[archive]", 1, "archive_limit_requires_review")]
        for member in archive.infolist():
            name = PurePosixPath(member.filename)
            if name.is_absolute() or ".." in name.parts or "\\" in member.filename:
                findings.append(finding(member.filename, 1, "unsafe_archive_path"))
            elif member.is_dir():
                continue
            elif (member.external_attr >> 16) & 0o170000 == 0o120000:
                findings.append(finding(member.filename, 1, "symlink_requires_review"))
            elif member.file_size > MAX_FILE_BYTES:
                findings.append(finding(member.filename, 1, "oversized_file_requires_review"))
            else:
                findings.extend(scan_bytes(member.filename, archive.read(member)))
    return findings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    inputs = parser.add_mutually_exclusive_group()
    inputs.add_argument("--root", type=Path, default=ROOT)
    inputs.add_argument("--archive", type=Path)
    args = parser.parse_args()
    try:
        findings = check_archive(args.archive) if args.archive else check_root(args.root)
    except (OSError, ValueError, BadZipFile, RuntimeError, subprocess.SubprocessError):
        print(json.dumps({"status": "error", "reason": "scan_incomplete"}))
        return 2
    print(json.dumps({"status": "fail" if findings else "pass", "findings": findings}, ensure_ascii=True))
    return 1 if findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
