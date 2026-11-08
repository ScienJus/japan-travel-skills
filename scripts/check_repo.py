#!/usr/bin/env python3
"""Check skill metadata, package identity and local document links without network access."""

import argparse
import json
from pathlib import Path
import re

import yaml


ROOT = Path(__file__).resolve().parents[1]


def check(root):
    root = Path(root).resolve()
    errors = []

    def problem(path, message):
        errors.append("{}: {}".format(path.relative_to(root), message))

    try:
        manifest = json.loads((root / "plugin.json").read_text(encoding="utf-8"))
        marketplace = json.loads((root / ".agents/plugins/marketplace.json").read_text(encoding="utf-8"))
        entries = marketplace.get("plugins", [])
        if not isinstance(manifest.get("name"), str) or not manifest["name"].strip():
            problem(root / "plugin.json", "plugin name must be a nonempty string")
        elif len(entries) != 1 or entries[0].get("name") != manifest.get("name"):
            problem(root / "plugin.json", "plugin and marketplace identities disagree")
        elif entries[0].get("source") != {"source": "local", "path": "./"}:
            problem(root / ".agents/plugins/marketplace.json", "expected the checkout-root local source")
    except (OSError, ValueError, AttributeError, TypeError) as error:
        errors.append("Plugin metadata could not be read: {}".format(type(error).__name__))

    skills = sorted((root / "skills").glob("*/SKILL.md"))
    if not skills:
        errors.append("No skills found")
    for entry in skills:
        text = entry.read_text(encoding="utf-8")
        match = re.match(r"\A---\r?\n(.*?)\r?\n---(?:\r?\n|\Z)", text, re.S)
        try:
            metadata = yaml.safe_load(match.group(1)) if match else None
        except yaml.YAMLError:
            metadata = None
        if not isinstance(metadata, dict):
            problem(entry, "missing or invalid YAML frontmatter")
            continue
        if metadata.get("name") != entry.parent.name:
            problem(entry, "name must match the skill directory")
        description = metadata.get("description")
        if not isinstance(description, str) or not description.strip() or len(description) > 1024:
            problem(entry, "description must be a nonempty string of at most 1024 characters")

        ui = entry.parent / "agents/openai.yaml"
        if ui.is_file():
            try:
                data = yaml.safe_load(ui.read_text(encoding="utf-8"))
                interface = data["interface"]
                for field in ("display_name", "short_description", "default_prompt"):
                    if not isinstance(interface.get(field), str) or not interface[field].strip():
                        problem(ui, "missing interface.{}".format(field))
                short = interface.get("short_description", "")
                if isinstance(short, str) and not 25 <= len(short) <= 64:
                    problem(ui, "short_description must contain 25 to 64 characters")
                prompt = interface.get("default_prompt", "")
                if isinstance(prompt, str) and "$" + entry.parent.name not in prompt:
                    problem(ui, "default_prompt must name this skill")
            except (OSError, yaml.YAMLError, KeyError, TypeError, AttributeError):
                problem(ui, "invalid skill interface metadata")

    documents = [*sorted(root.glob("*.md")), *sorted((root / "docs").rglob("*.md")),
                 *sorted((root / "skills").rglob("*.md"))]
    for document in documents:
        text = document.read_text(encoding="utf-8")
        for link in re.findall(r"\[[^\]]*\]\(([^)]+)\)", text):
            if "://" in link or link.startswith("#"):
                continue
            target = (document.parent / link.split("#", 1)[0]).resolve()
            if root not in target.parents or not target.is_file():
                problem(document, "missing or external local link: {}".format(link))
                continue
            relative = document.relative_to(root).parts
            if relative[0] == "skills" and root / "skills" / relative[1] not in target.parents:
                problem(document, "standalone skill link escapes its directory: {}".format(link))
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()
    errors = check(args.root)
    for error in errors:
        print(error)
    if errors:
        return 1
    print("Skill metadata, package identity and local document links are valid.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
