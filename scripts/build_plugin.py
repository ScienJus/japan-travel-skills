#!/usr/bin/env python3
"""Build a relocatable skills-only plugin ZIP without development captures."""

import argparse
import json
import stat
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

from check_privacy import scan_bytes


ROOT = Path(__file__).resolve().parents[1]
ROOT_FILES = ("plugin.json", "README.md", "AGENTS.md", "CONTRIBUTING.md", "SECURITY.md", "LICENSE",
              ".agents/plugins/marketplace.json", "requirements.lock", "docs/http-client.md",
              "docs/installation.md", "docs/releasing.md", "docs/sources.md",
              "docs/check-japan-itinerary.md", "docs/japan-itinerary-map-and-powerpoint.md")
GUIDANCE_ONLY_SKILLS = {"japan-city-guide", "japan-travel-planner"}

# Exact release contents. Adding a runtime resource requires an explicit entry;
# local files remain excluded regardless of their extension or Git availability.
SKILL_FILES = {
    "japan-travel-planner": (
        "SKILL.md", "LICENSE", "agents/openai.yaml", "references/deliverables.md",
        "references/planning-loop.md", "examples/hokuriku-six-days.md",
        "references/plan-data.md", "examples/kyoto-nara-demo.json", "scripts/render_plan.py",
        "assets/guide.html", "assets/guide.css", "assets/guide.js", "assets/presentation.md"),
    "japan-city-guide": (
        "SKILL.md", "LICENSE", "references/ishikawa.md", "references/toyama.md",
        "references/nagano.md", "references/tokyo.md", "references/osaka.md",
        "references/kyoto.md", "references/hokkaido.md", "references/fukuoka.md",
        "references/aichi.md", "references/kanagawa.md", "references/hyogo.md",
        "references/nara.md", "references/okinawa.md", "agents/openai.yaml"),
    "japan-weather": (
        "SKILL.md", "LICENSE", "scripts/weather.py", "scripts/weather_common.py",
        "scripts/weathernews.py", "scripts/jma_alerts.py", "scripts/jma_climate.py",
        "scripts/refresh_catalog.py", "scripts/refresh_weathernews_codes.py",
        "scripts/data/catalog.json", "scripts/data/weathernews_codes.json",
        "references/jma.md", "references/weathernews.md", "references/jma-alerts.md",
        "references/jma-climate.md", "agents/openai.yaml"),
    "japan-transit": (
        "SKILL.md", "LICENSE", "scripts/transit.py", "scripts/rail_operations.py", "scripts/transit_network.py",
        "scripts/transit_source.py", "scripts/transit_transport.py",
        "references/sources.md", "references/operations.md", "references/ir-ishikawa.md", "agents/openai.yaml"),
    "japan-holidays": ("SKILL.md", "LICENSE", "scripts/holidays.py", "references/sources.md", "agents/openai.yaml"),
    "japan-daylight": ("SKILL.md", "LICENSE", "scripts/daylight.py", "references/sources.md", "agents/openai.yaml"),
    "japan-seasons": (
        "SKILL.md", "LICENSE", "scripts/seasons.py", "scripts/season_common.py",
        "scripts/wn_seasons.py", "scripts/jmc_seasons.py", "references/sources.md", "agents/openai.yaml"),
    "japan-fuji": (
        "SKILL.md", "LICENSE", "scripts/fuji.py", "scripts/fuji_source.py", "references/sources.md", "agents/openai.yaml"),
    "japan-hotels": (
        "SKILL.md", "LICENSE", "scripts/hotels.py", "scripts/jalan.py",
        "scripts/hotel_geo.py", "scripts/hotel_viewport.py", "references/jalan.md", "agents/openai.yaml"),
    "japan-passes": (
        "SKILL.md", "LICENSE", "scripts/passes.py", "scripts/pass_source.py",
        "scripts/pass_providers.py", "references/sources.md", "agents/openai.yaml"),
    'tabelog': (
        'LICENSE',
        'README.md',
        'SKILL.md',
        'agents/openai.yaml',
        'references/access.md',
        'references/availability.md',
        'references/catalog.md',
        'references/costs.md',
        'references/reviews.md',
        'references/search.md',
        'scripts/requirements.txt',
        'scripts/tabelog.py',
        'scripts/tabelog_client/__init__.py',
        'scripts/tabelog_client/__main__.py',
        'scripts/tabelog_client/arguments.py',
        'scripts/tabelog_client/catalog.py',
        'scripts/tabelog_client/cli.py',
        'scripts/tabelog_client/core.py',
        'scripts/tabelog_client/detail_info.py',
        'scripts/tabelog_client/filters.py',
        'scripts/tabelog_client/geo.py',
        'scripts/tabelog_client/hyakumeiten.py',
        'scripts/tabelog_client/licenses/tabelog-cli.provenance.json',
        'scripts/tabelog_client/licenses/tabelog-cli.txt',
        'scripts/tabelog_client/parsers.py',
        'scripts/tabelog_client/redaction.py',
        'scripts/tabelog_client/reports.py',
        'scripts/tabelog_client/service.py',
        'scripts/tabelog_client/transport.py',
    ),
    'tablecheck': (
        'references/guide.md',
        'LICENSE',
        'SKILL.md',
        'agents/openai.yaml',
        'scripts/requirements.txt',
        'scripts/tablecheck.py',
        'scripts/tablecheck_client/__init__.py',
        'scripts/tablecheck_client/arguments.py',
        'scripts/tablecheck_client/cli.py',
        'scripts/tablecheck_client/detail_info.py',
        'scripts/tablecheck_client/service.py',
        'scripts/tablecheck_client/transport.py',
    ),
    'pocket-concierge': (
        'references/guide.md',
        'LICENSE',
        'SKILL.md',
        'agents/openai.yaml',
        'scripts/pocket_concierge.py',
        'scripts/pocket_concierge_client/__init__.py',
        'scripts/pocket_concierge_client/arguments.py',
        'scripts/pocket_concierge_client/cli.py',
        'scripts/pocket_concierge_client/detail_info.py',
        'scripts/pocket_concierge_client/queries.py',
        'scripts/pocket_concierge_client/reports.py',
        'scripts/pocket_concierge_client/service.py',
        'scripts/pocket_concierge_client/transport.py',
        'scripts/requirements.txt',
    ),

}


def build(root, output):
    root = Path(root).resolve()
    output = Path(output).expanduser().resolve()
    if output == root or root in output.parents:
        raise ValueError("Build output must be outside the source directory.")
    skills_directory = root / "skills"
    if not skills_directory.is_dir() or skills_directory.is_symlink():
        raise ValueError("Expected a regular skills directory.")
    discovered = {path.name for path in skills_directory.iterdir()
                  if path.is_dir() and (path / "SKILL.md").is_file()}
    if discovered != set(SKILL_FILES):
        raise ValueError("Skill directories differ from the release file list; update SKILL_FILES. "
                         "Missing: {}; unregistered: {}".format(
                             sorted(set(SKILL_FILES) - discovered), sorted(discovered - set(SKILL_FILES))))
    files = [root / name for name in ROOT_FILES]
    for skill, resources in SKILL_FILES.items():
        if skill not in GUIDANCE_ONLY_SKILLS:
            files.append(root / "bin" / skill)
        files.extend(root / "skills" / skill / name for name in resources)
    # Read before opening the output so a bad source cannot leave a partial ZIP.
    members = []
    for path in sorted(files):
        current = root
        for part in path.relative_to(root).parts:
            current = current / part
            if current.is_symlink():
                raise ValueError("Package must not contain symlinks: {}".format(current.relative_to(root)))
        if not path.is_file():
            raise ValueError("Expected a regular package file: {}".format(path.relative_to(root)))
        members.append((path.relative_to(root).as_posix(), path.read_bytes(), path.stat().st_mode))
    findings = [item for name, data, _ in members for item in scan_bytes(name, data)]
    if findings:
        locations = ["{path}:{line} ({rule})".format(**item) for item in findings]
        raise ValueError("Privacy check failed: " + "; ".join(locations))
    output.parent.mkdir(parents=True, exist_ok=True)
    with ZipFile(output, "w", compression=ZIP_DEFLATED) as archive:
        for name, data, mode in members:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            info.compress_type = ZIP_DEFLATED
            permissions = 0o755 if mode & stat.S_IXUSR else 0o644
            info.external_attr = (stat.S_IFREG | permissions) << 16
            archive.writestr(info, data)
    return output


def default_output(root=ROOT):
    version = json.loads((Path(root) / "plugin.json").read_text(encoding="utf-8"))["version"]
    return Path.home() / ".local/share/japan-travel-skills/artifacts" / ("japan-travel-{}.zip".format(version))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path,
                        help="Output ZIP outside the checkout (default: ~/.local/share/japan-travel-skills/artifacts/japan-travel-VERSION.zip)")
    args = parser.parse_args()
    try:
        print(build(ROOT, args.output or default_output()))
    except ValueError as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
