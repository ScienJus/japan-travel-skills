#!/usr/bin/env python3
"""Prepare a blind agent task and separate review rubric outside the checkout. No queries."""

import argparse
import datetime as dt
import json
from pathlib import Path
import sys
from zipfile import ZipFile

import yaml

from build_plugin import ROOT, build

CASES = ROOT / "tests/behavior/cases.json"


def load_cases():
    return json.loads(CASES.read_text(encoding="utf-8"))


def prepare(case_id, output, *, today=None, python=sys.executable):
    case = next((case for case in load_cases() if case["id"] == case_id), None)
    if case is None:
        raise ValueError("Unknown case: {}".format(case_id))
    output = Path(output).expanduser().resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("Behavior artifacts must stay outside the checkout.")
    interpreter = Path(python).expanduser().absolute()
    if not interpreter.is_file():
        raise ValueError("Choose an existing Python interpreter.")
    today = today or dt.datetime.now(dt.timezone(dt.timedelta(hours=9))).date()
    autumn_year = today.year + (today > dt.date(today.year, 11, 28))
    request = case["request"].format(
        future_date=(today + dt.timedelta(days=35)).isoformat(),
        route_date=(today + dt.timedelta(days=7)).isoformat(), year=today.year,
        autumn_year=autumn_year)
    output.mkdir(parents=True, exist_ok=False)
    bundle = build(ROOT, output / "plugin.zip")
    # The ZIP was just built from explicit, validated release paths. Expose only skills:
    # the evaluator must not receive checkout routing or the hidden review rubric.
    with ZipFile(bundle) as archive:
        for name in archive.namelist():
            if name.startswith("skills/"):
                target = output / "installed" / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(archive.read(name))
    catalog = []
    for path in sorted((output / "installed/skills").glob("*/SKILL.md")):
        metadata = yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])
        catalog.append("- {}: {} (file: {})".format(metadata["name"], metadata["description"], path))
    workspace = output / "research"
    workspace.mkdir()
    prompt = (
        "Complete the user's travel-planning request using the available skills below. "
        "Read the actual installed skill instructions as needed.\n\n"
        "User request:\n{}\n\nEnvironment:\n"
        "- Current Japanese date: {} (Asia/Tokyo).\n"
        "- Python with bundle dependencies: {}\n"
        "- Work outside the source checkout: {}\n"
        "- Read the exposed skills and public sources; keep research files in that working directory. "
        "Do not inspect its parent, hidden review files or other runs.\n"
        "- Anonymous read-only queries only; no GUI, accounts, reservations or purchases.\n"
        "- No evaluation cap on model calls, total external reads or research duration. "
        "Choose useful queries to complete the request; honor each source's request limits, "
        "pacing and stopping rules. Do not retry failed sources.\n\n"
        "Available skill catalog:\n{}\n"
    ).format(request, today.isoformat(), interpreter, workspace, "\n".join(catalog))
    (output / "task.txt").write_text(prompt, encoding="utf-8")
    review = {
        "case_id": case_id, "date_jst": today.isoformat(), "request": request,
        "working_directory": str(workspace),
        "evaluation_caps": {"model_calls": None, "external_reads": None, "duration_seconds": None},
        "criteria": [{"criterion": check, "score": None, "evidence": None} for check in
                     [*case["checks"], "Invoke every CLI entry script by its absolute installed path."]],
        "critical_failures": case["critical_failures"], "critical_failure_observed": None,
        "upstream_reads": None, "read_count_qualification": None,
        "resource_usage": {
            "elapsed_seconds": None,
            "tokens": {"input": None, "cached_input": None, "noncached_input": None,
                       "output_including_reasoning": None},
            "tool_calls": None, "cli_http_attempts": None, "cli_response_body_bytes": None,
            "web_backend_http_attempts": None, "monetary_cost": None,
        },
        "status": "unreviewed", "model_and_host": None,
    }
    (output / "review.json").write_text(json.dumps(review, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return output / "task.txt"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="List cases without creating files")
    parser.add_argument("--case", choices=[case["id"] for case in load_cases()])
    parser.add_argument("--output", type=Path, help="New run directory outside the checkout")
    parser.add_argument("--python", default=sys.executable, help="Python with installed runtime dependencies")
    args = parser.parse_args()
    if args.list:
        print("\n".join(case["id"] for case in load_cases()))
        return
    if not args.case or not args.output:
        parser.error("--case and --output are required unless using --list")
    try:
        print(prepare(args.case, args.output, python=args.python))
    except (ValueError, OSError) as error:
        parser.error(str(error))


if __name__ == "__main__":
    main()
