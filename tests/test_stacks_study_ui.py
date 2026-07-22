"""Wave-6B part 4 client UI tests (docs/INFINITE_STACKS_CONTRACTS.md S5.11):
the study room screen and the converse ceremony, driven against a REAL wire
fixture captured from the actual engine (tests/fixtures/stacks_ui/
study_gothic_living_study.json, captured the same way
puzzle_mystery_chamber.json was for wave 3 -- see that file's own
`description` field for exactly how). Follows the
tests/stacks_client_check/j12_legal_actions_check.mjs node-harness pattern:
this Python test shells out to tests/stacks_client_check/study_check.mjs,
which imports and runs the REAL client modules (core/store.js's
reduceServerMessage, core/selectors.js's selectActiveScreen/selectStudyView/
selectConverseView, core/commands.js's interactCommand/converseCommand)
against that fixture -- proving the exact code path the browser uses, not a
Python reimplementation of it.

Also includes static fixture-shape sanity checks (mirrors
tests/test_stacks_ui.py's Wave5FixtureContractTests style) so a future
re-capture that accidentally narrows the fixture fails loudly here too.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FIXTURE_PATH = ROOT / "tests" / "fixtures" / "stacks_ui" / "study_gothic_living_study.json"
STUDY_CHECK_SCRIPT = ROOT / "tests" / "stacks_client_check" / "study_check.mjs"


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


class StudyFixtureShapeTests(unittest.TestCase):
    """Static sanity checks on the fixture itself -- fails loudly if a future
    re-capture accidentally narrows the shape the node harness depends on."""

    def setUp(self):
        self.fixture = _load_fixture()

    def test_fixture_has_required_top_level_keys(self):
        for key in ("heroId", "otherHeroId", "roomId", "beforeInteractSnapshotMessage", "snapshotMessage", "socialCheckResolvedEvent"):
            with self.subTest(key=key):
                self.assertIn(key, self.fixture)

    def test_before_snapshot_has_empty_promoted_ledgers(self):
        room = self.fixture["beforeInteractSnapshotMessage"]["view"]["study"][self.fixture["roomId"]]
        self.assertEqual(room["promoted_object_ids"], [])
        self.assertEqual(room["promoted_fact_ids"], [])
        self.assertFalse(room["resolved"])

    def test_final_snapshot_has_npc_with_only_public_party_objectives(self):
        room = self.fixture["snapshotMessage"]["view"]["study"][self.fixture["roomId"]]
        objective_ids = {o["id"] for o in room["npc"]["objectives"]}
        self.assertNotIn("objective_hidden_avoid_confronting_death", objective_ids)
        self.assertTrue(objective_ids)

    def test_social_check_event_is_a_real_wire_payload(self):
        payload = self.fixture["socialCheckResolvedEvent"]["payload"]
        for field in ("npc_id", "dc", "modifier", "evidence_tier", "motive_alignment", "die_rolls", "total", "margin", "outcome"):
            with self.subTest(field=field):
                self.assertIn(field, payload)
        # Standing rule #5 (no client-supplied modifiers): the wire event's
        # own motive_alignment is engine-derived, and there is no separate
        # client-claimed field alongside it in a real payload.
        self.assertNotIn("client_motive_alignment", payload)


class StudyRealModuleClientTests(unittest.TestCase):
    """Runs the REAL client modules against the fixture via Node (see
    study_check.mjs's header for exactly what each check proves)."""

    def setUp(self):
        if shutil.which("node") is None:
            self.skipTest("node is not available on PATH")

    def _run_js_check(self, payload: dict) -> dict:
        result = subprocess.run(
            ["node", str(STUDY_CHECK_SCRIPT)],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )
        try:
            parsed = json.loads(result.stdout)
        except json.JSONDecodeError:
            self.fail(f"study_check.mjs produced non-JSON stdout (exit {result.returncode}):\n{result.stdout}\n{result.stderr}")
        self.assertEqual(
            result.returncode,
            0,
            f"study_check.mjs reported failure: {parsed.get('reason')}\nfull output: {parsed}\nstderr: {result.stderr}",
        )
        self.assertTrue(parsed.get("ok"))
        return parsed

    def test_study_screen_appeal_picker_and_ceremony_against_real_fixture(self):
        fixture = _load_fixture()
        result = self._run_js_check(fixture)
        self.assertEqual(result["heroId"], fixture["heroId"])
        self.assertEqual(result["activeScreen"], "study")
        self.assertGreater(result["objectCount"], 0)
        self.assertGreater(result["appealOptionCount"], 0)
        # The real command builder's envelope, round-tripped through the
        # subprocess boundary as JSON -- sanity-check its shape here too.
        self.assertEqual(result["interactCmd"]["type"], "interact")
        self.assertEqual(result["interactCmd"]["payload"]["object_id"], "study_rug")
        self.assertEqual(result["converseCmd"]["type"], "converse")
        self.assertNotIn("motive_alignment", result["converseCmd"]["payload"])

    def test_missing_snapshot_message_fails_loudly_not_silently(self):
        # Sanity check on the harness's own error path: malformed input must
        # exit non-zero with a JSON reason, never a silent pass.
        result = subprocess.run(
            ["node", str(STUDY_CHECK_SCRIPT)],
            input=json.dumps({"heroId": "hero_x"}),
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertNotEqual(result.returncode, 0)
        parsed = json.loads(result.stdout)
        self.assertFalse(parsed["ok"])
        self.assertIn("snapshotMessage", parsed["reason"])


if __name__ == "__main__":
    unittest.main()
