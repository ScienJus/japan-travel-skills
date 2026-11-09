"""Offline visual-handoff records, safe embedding and installed-helper behavior."""

import copy
from html.parser import HTMLParser
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills/japan-travel-planner"
SPEC = importlib.util.spec_from_file_location("render_plan", SKILL / "scripts/render_plan.py")
RENDERER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDERER)


def fixture():
    return json.loads((SKILL / "examples/kyoto-nara-demo.json").read_text(encoding="utf-8"))


class EmbeddedData(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.collect = False
        self.parts = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.collect = tag == "script" and dict(attrs).get("id") == "plan-data"

    def handle_endtag(self, tag):
        if tag == "script":
            self.collect = False

    def handle_data(self, data):
        if self.collect:
            self.parts.append(data)

    def plan(self):
        return json.loads("".join(self.parts))


class PlanRenderingTests(unittest.TestCase):
    def test_html_and_presentation_handoff_keep_the_same_complete_snapshot(self):
        plan = fixture()
        plan["revision"] = "revised-example"
        plan["days"][0]["date"] = "2027-04-09"
        html = RENDERER.render_html(plan)
        brief = RENDERER.presentation_brief(plan)
        records = brief.split("## Plan records\n\n```json\n", 1)[1].rsplit("\n```", 1)[0]
        self.assertEqual(EmbeddedData(html).plan(), plan)
        self.assertEqual(json.loads(records), plan)

    def test_external_text_cannot_break_out_of_embedded_data_or_replace_template_slots(self):
        plan = fixture()
        hostile = '</script><script>alert("fixture")</script> @@SCRIPT@@ & \u2028'
        plan["title"] = hostile
        plan["places"][0]["notes"] = hostile
        html = RENDERER.render_html(plan)
        self.assertNotIn('</script><script>alert', html)
        self.assertEqual(EmbeddedData(html).plan(), plan)
        self.assertIn("script-src 'sha256-", html)

    def test_unknown_coordinates_are_preserved_without_geocoding(self):
        plan = fixture()
        for place in plan["places"]:
            place.pop("coordinates", None)
        self.assertEqual(EmbeddedData(RENDERER.render_html(plan)).plan(), plan)

    def test_text_limits_include_surrounding_whitespace(self):
        plan = fixture()
        plan["notice"] = " " * 1999 + "x"
        self.assertEqual(EmbeddedData(RENDERER.render_html(plan)).plan(), plan)
        for value in (" " * 2000 + "x", "x" + " " * 2000, " " * 2000):
            plan["notice"] = value
            with self.subTest(length=len(value)), self.assertRaises(RENDERER.PlanError):
                RENDERER.validate(plan)

    def test_coordinate_bounds_types_and_provenance_are_required(self):
        for field, value in (("lat", True), ("lat", float("nan")), ("lat", 135),
                             ("lon", -181), ("lat", 10 ** 400), ("checked_on", "not-a-date"),
                             ("source_url", "javascript:fixture"), ("precision", "")):
            plan = fixture()
            plan["places"][0]["coordinates"][field] = value
            with self.subTest(field=field), self.assertRaises(RENDERER.PlanError):
                RENDERER.validate(plan)

    def test_invalid_place_day_and_leg_relationships_are_rejected(self):
        mutations = [
            lambda p: p["places"].append(copy.deepcopy(p["places"][0])),
            lambda p: p["days"][0]["visits"][0].update(place_id="unknown"),
            lambda p: p["days"][0].update(base_place_id="kyoto-station"),
            lambda p: p["days"][1].update(city_ids=["nara"]),
            lambda p: p["days"][1].update(date=p["days"][0]["date"]),
            lambda p: p["days"][0]["leg_ids"].append("outbound"),
            lambda p: p["days"][1]["leg_ids"].append("unknown"),
            lambda p: p["legs"][0].update(day_id="day-3"),
            lambda p: p["places"][0].update(city_id=[]),
        ]
        for index, mutate in enumerate(mutations):
            plan = fixture()
            mutate(plan)
            with self.subTest(case=index), self.assertRaises(RENDERER.PlanError):
                RENDERER.validate(plan)

    def test_role_does_not_promote_evidence_and_verification_needs_sources(self):
        plan = fixture()
        place = plan["places"][0]
        place.update(role="fixed", evidence="unverified", sources=[])
        self.assertEqual(RENDERER.validate(plan)["places"][0]["evidence"], "unverified")
        place["evidence"] = "verified"
        with self.assertRaises(RENDERER.PlanError):
            RENDERER.validate(plan)

    def test_credential_urls_and_unexpected_private_fields_are_rejected(self):
        for mutate in (lambda p: p.update(booking_reference="synthetic-value"),
                       lambda p: p["places"][0]["sources"][0].update(url="https://" + "user:fixture" + "@example.org/")):
            plan = fixture()
            mutate(plan)
            with self.assertRaises(RENDERER.PlanError):
                RENDERER.validate(plan)

    def test_existing_output_and_source_tree_are_protected(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "existing.html"
            output.write_text("preserve existing file")
            with self.assertRaises(FileExistsError):
                RENDERER.write_output(fixture(), output, "html")
            self.assertEqual(output.read_text(), "preserve existing file")
            for target in (ROOT / "new-guide.html", SKILL / "new-guide.html"):
                with self.subTest(target=target.name), self.assertRaises(RENDERER.PlanError):
                    RENDERER.write_output(fixture(), target, "html")
                self.assertFalse(target.exists())

    def test_invalid_cli_input_reports_no_values_or_local_paths(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            private = "fixture-private-" + "q" * 30
            plan = fixture()
            plan["booking_reference"] = private
            source = path / "input.json"
            source.write_text(json.dumps(plan), encoding="utf-8")
            output = path / "guide.html"
            result = subprocess.run([sys.executable, str(SKILL / "scripts/render_plan.py"),
                                     "--input", str(source), "--output", str(output)],
                                    capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 1)
            self.assertEqual(json.loads(result.stdout)["reason"], "invalid_plan_or_output")
            self.assertIn("unexpected fields", json.loads(result.stdout)["detail"])
            self.assertNotIn("booking_reference", result.stdout)
            self.assertNotIn(private, result.stdout + result.stderr)
            self.assertNotIn(temporary, result.stdout + result.stderr)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
