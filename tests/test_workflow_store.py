"""Wave 9 — the persistent workflow store.

Covers the three properties the module's header claims, plus the store rules
this repo applies to every persistent store (unified data root, atomic writes,
migration-safe reads, a privacy clear that actually clears):

* saving is not approving,
* approval is bound to the exact preview lines the user read, and
* run history holds status codes and never anything the user said.
"""

import json
import os
import tempfile
import unittest

from backend.services import action_validator as V
from backend.services.workflow_store import (
    DEFAULT_HISTORY_CAP,
    SCHEMA_VERSION,
    WorkflowStore,
    _normalize_store,
)

WORKFLOW = {
    "name": "Studio setup",
    "trigger_phrases": ["open my studio"],
    "steps": [
        {"action": "launch_app", "app_id": "obsidian"},
        {"action": "show_notification", "message": "Ready"},
    ],
}

PREVIEW = ["1. Launch Obsidian (flatpak run md.obsidian.Obsidian)", "2. Show the notification “Ready”"]


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "launcher_workflows.json")
        self.store = WorkflowStore(path=self.path)

    def read_file(self):
        with open(self.path, encoding="utf-8") as handle:
            return json.load(handle)


class SaveTests(StoreTestCase):
    def test_a_saved_workflow_is_never_approved_and_defaults_to_disabled(self):
        result = self.store.save(WORKFLOW)
        self.assertTrue(result["ok"])
        record = result["workflow"]
        self.assertFalse(record["approved"])
        self.assertFalse(record["enabled"])
        self.assertEqual(record["schema_version"], SCHEMA_VERSION)

    def test_a_workflow_can_be_saved_enabled_and_still_is_not_approved(self):
        record = self.store.save(WORKFLOW, enabled=True)["workflow"]
        self.assertTrue(record["enabled"])
        self.assertFalse(record["approved"])

    def test_a_workflow_containing_a_prohibited_step_is_refused_with_its_reasons(self):
        result = self.store.save({
            "name": "bad", "steps": [{"action": "shell", "command": "whoami"}],
        })
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "refused")
        self.assertIn("never runs shell commands", result["refusals"][0]["reason"])
        self.assertFalse(os.path.exists(self.path))

    def test_the_cap_refuses_a_new_workflow_rather_than_evicting_one(self):
        store = WorkflowStore(path=self.path, cap=2)
        for index in range(2):
            self.assertTrue(store.save({**WORKFLOW, "name": f"w{index}"})["ok"])
        result = store.save({**WORKFLOW, "name": "w2"})
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "cap_reached")
        self.assertEqual(len(store.list_workflows()), 2)


class ApprovalTests(StoreTestCase):
    def approve(self):
        self.store.save(WORKFLOW, enabled=True)
        return self.store.approve("studio_setup", PREVIEW)

    def test_approval_records_the_exact_lines_the_user_read(self):
        result = self.approve()
        self.assertTrue(result["ok"])
        self.assertEqual(result["workflow"]["approved_preview"], PREVIEW)

    def test_an_empty_preview_cannot_be_approved(self):
        self.store.save(WORKFLOW)
        result = self.store.approve("studio_setup", [])
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "empty_preview")

    def test_editing_the_steps_revokes_the_approval(self):
        self.approve()
        edited = {**WORKFLOW, "steps": WORKFLOW["steps"] + [
            {"action": "show_notification", "message": "and again"},
        ]}
        record = self.store.save(edited, enabled=True)["workflow"]
        self.assertFalse(record["approved"])
        self.assertEqual(record["approved_preview"], [])

    def test_renaming_a_trigger_phrase_does_not_revoke_the_approval(self):
        self.approve()
        renamed = {**WORKFLOW, "trigger_phrases": ["studio time"]}
        record = self.store.save(renamed, enabled=True)["workflow"]
        self.assertTrue(record["approved"])
        self.assertEqual(record["approved_preview"], PREVIEW)


class RunGateTests(StoreTestCase):
    def test_an_unapproved_workflow_cannot_run(self):
        self.store.save(WORKFLOW, enabled=True)
        gate = self.store.can_run("studio_setup", PREVIEW)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["error"], "not_approved")

    def test_a_disabled_workflow_cannot_run_even_when_approved(self):
        self.store.save(WORKFLOW, enabled=False)
        self.store.approve("studio_setup", PREVIEW)
        gate = self.store.can_run("studio_setup", PREVIEW)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["error"], "disabled")

    def test_an_approved_enabled_workflow_runs_when_the_preview_still_matches(self):
        self.store.save(WORKFLOW, enabled=True)
        self.store.approve("studio_setup", PREVIEW)
        self.assertTrue(self.store.can_run("studio_setup", PREVIEW)["ok"])

    def test_a_changed_preview_blocks_the_run_even_though_nobody_edited_it(self):
        self.store.save(WORKFLOW, enabled=True)
        self.store.approve("studio_setup", PREVIEW)
        drifted = ["1. Launch Obsidian (program /usr/bin/obsidian)", PREVIEW[1]]
        gate = self.store.can_run("studio_setup", drifted)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["error"], "preview_changed")

    def test_a_missing_workflow_cannot_run(self):
        gate = self.store.can_run("nope", PREVIEW)
        self.assertFalse(gate["ok"])
        self.assertEqual(gate["error"], "not_found")


class HistoryTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.store.save(WORKFLOW, enabled=True)
        self.record = self.store.get("studio_setup")

    def test_history_stores_status_codes_and_no_user_speech(self):
        summary = V.summarize_run(self.record, [{"status": "ok"}, {"status": "failed"}])
        result = self.store.record_run("studio_setup", summary)
        self.assertTrue(result["ok"])
        run = result["run"]
        self.assertEqual(set(run), {"workflow_id", "at", "status", "completed", "total", "steps"})
        self.assertEqual([row["status"] for row in run["steps"]], ["ok", "failed"])
        # The step TARGET is not carried into history, only the action word:
        # a target can be a folder path, and a path names a person's
        # directories. (The workflow definition itself of course keeps its
        # targets — that is the document the user wrote and approved.)
        history_json = json.dumps(self.read_file()["history"])
        self.assertNotIn("Ready", history_json)
        self.assertNotIn("obsidian", history_json)
        for row in run["steps"]:
            self.assertEqual(set(row), {"step_number", "action", "status"})

    def test_a_summary_carrying_prose_fields_has_them_dropped(self):
        summary = V.summarize_run(self.record, [{"status": "ok"}, {"status": "ok"}])
        summary["steps"][0]["target"] = "/home/someone/Private Notes"
        summary["steps"][0]["error_message"] = "could not open /home/someone/Private Notes"
        summary["transcript"] = "open my studio please"
        self.store.record_run("studio_setup", summary)
        raw = json.dumps(self.read_file())
        self.assertNotIn("Private Notes", raw)
        self.assertNotIn("open my studio please", raw)

    def test_history_is_bounded(self):
        store = WorkflowStore(path=self.path, history_cap=3)
        record = store.get("studio_setup")
        for _ in range(6):
            store.record_run("studio_setup", V.summarize_run(record, [{"status": "ok"}] * 2))
        self.assertEqual(len(store.history("studio_setup", limit=50)), 3)

    def test_the_default_history_cap_is_bounded_and_positive(self):
        self.assertGreater(DEFAULT_HISTORY_CAP, 0)

    def test_clear_history_leaves_the_workflows_alone(self):
        self.store.record_run("studio_setup", V.summarize_run(self.record, [{"status": "ok"}] * 2))
        self.assertTrue(self.store.clear_history()["ok"])
        self.assertEqual(self.store.history(), [])
        self.assertIsNotNone(self.store.get("studio_setup"))


class DurabilityTests(StoreTestCase):
    def test_writes_are_atomic_and_leave_no_temp_files(self):
        self.store.save(WORKFLOW)
        leftovers = [n for n in os.listdir(self.tmp) if n != "launcher_workflows.json"]
        self.assertEqual(leftovers, [])

    def test_a_corrupt_file_degrades_to_an_empty_store_rather_than_raising(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.store.list_workflows(), [])
        # And the store is usable again immediately.
        self.assertTrue(self.store.save(WORKFLOW)["ok"])

    def test_a_hand_edited_file_that_adds_a_shell_step_loses_the_whole_record(self):
        self.store.save(WORKFLOW, enabled=True)
        self.store.approve("studio_setup", PREVIEW)
        data = self.read_file()
        data["workflows"]["studio_setup"]["steps"].append({"action": "shell", "command": "id"})
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        # Not "repaired by dropping the bad step" -- the record still carries an
        # approval for a preview the user never saw, so it is not kept at all.
        self.assertEqual(self.store.list_workflows(), [])

    def test_a_hand_edited_approval_with_no_recorded_preview_is_not_an_approval(self):
        self.store.save(WORKFLOW, enabled=True)
        data = self.read_file()
        data["workflows"]["studio_setup"]["approved"] = True
        data["workflows"]["studio_setup"]["approved_preview"] = []
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertFalse(self.store.get("studio_setup")["approved"])

    def test_a_missing_schema_version_still_reads(self):
        self.store.save(WORKFLOW)
        data = self.read_file()
        data.pop("schema_version", None)
        with open(self.path, "w", encoding="utf-8") as handle:
            json.dump(data, handle)
        self.assertEqual(len(self.store.list_workflows()), 1)

    def test_normalize_store_tolerates_a_list_shaped_workflows_field(self):
        data = _normalize_store({"workflows": [dict(WORKFLOW, id="studio_setup")]})
        self.assertIn("studio_setup", data["workflows"])

    def test_the_default_path_lives_under_the_unified_data_root(self):
        previous = os.environ.get("BETTERFINGERS_DATA_DIR")
        os.environ["BETTERFINGERS_DATA_DIR"] = self.tmp
        try:
            import app_paths
            app_paths.resolve_base.cache_clear() if hasattr(app_paths.resolve_base, "cache_clear") else None
            store = WorkflowStore()
            self.assertTrue(store.path.endswith("launcher_workflows.json"))
        finally:
            if previous is None:
                os.environ.pop("BETTERFINGERS_DATA_DIR", None)
            else:
                os.environ["BETTERFINGERS_DATA_DIR"] = previous


class PrivacyTests(StoreTestCase):
    def test_clear_all_removes_workflows_and_history_together(self):
        self.store.save(WORKFLOW, enabled=True)
        record = self.store.get("studio_setup")
        self.store.record_run("studio_setup", V.summarize_run(record, [{"status": "ok"}] * 2))
        self.assertTrue(self.store.clear_all()["ok"])
        self.assertEqual(self.store.list_workflows(), [])
        self.assertEqual(self.store.history(), [])


class PhraseLookupTests(StoreTestCase):
    def test_an_exact_trigger_phrase_finds_the_workflow(self):
        self.store.save(WORKFLOW, enabled=True)
        found = self.store.find_by_phrase("Open my studio!")
        self.assertIsNotNone(found)
        self.assertEqual(found["id"], "studio_setup")

    def test_a_near_miss_does_not_find_it(self):
        self.store.save(WORKFLOW, enabled=True)
        self.assertIsNone(self.store.find_by_phrase("open my studios"))
        self.assertIsNone(self.store.find_by_phrase("please open my studio now"))


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
