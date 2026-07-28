"""Wave 9 — the workflow routes, exercised end to end over the real router.

The router is mounted onto a bare FastAPI app here rather than onto server.py:
the ``app.include_router`` line in server.py is integration-owned (documented in
docs/release/WAVE9_INTEGRATION_DIFFS.md), and a test that waited for it would
report Wave 9 as untested for reasons that have nothing to do with Wave 9.

The order of the flow is the property under test: compile writes nothing, save
never approves, run re-validates instead of trusting the stored flag.
"""

import os
import tempfile
import unittest

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api.routes import actions as routes_actions
from backend.services.workflow_store import WorkflowStore

REGISTRY = [{
    "id": "obsidian",
    "display_name": "Obsidian",
    "launch_method": "flatpak",
    "flatpak_id": "md.obsidian.Obsidian",
    "confirmed": True,
}]

CONTEXT = {
    "registry": REGISTRY,
    "profile_ids": ["default", "writing_app"],
    "personas": ["True Janitor"],
    "writing_presets": ["casual"],
}

WORKFLOW = {
    "name": "Studio setup",
    "trigger_phrases": ["open my studio"],
    "steps": [
        {"action": "launch_app", "app_id": "obsidian"},
        {"action": "activate_application_profile", "profile_id": "writing_app"},
    ],
}


class RouteTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.path = os.path.join(self.tmp, "launcher_workflows.json")
        self._original_store = routes_actions._store
        routes_actions._store = lambda: WorkflowStore(path=self.path)
        app = FastAPI()
        app.include_router(routes_actions.router)
        self.client = TestClient(app)

    def tearDown(self):
        routes_actions._store = self._original_store


class VocabularyRouteTests(RouteTestCase):
    def test_the_route_publishes_the_closed_vocabulary_and_the_refusal_reasons(self):
        body = self.client.get("/workflows/vocabulary").json()
        self.assertTrue(body["ok"])
        self.assertIn("launch_app", body["allowed_actions"])
        self.assertIn("shell", body["prohibited_actions"])
        self.assertIn("never runs shell commands", body["prohibited_actions"]["shell"])


class CompileRouteTests(RouteTestCase):
    def test_compile_returns_the_exact_preview_and_writes_nothing(self):
        body = self.client.post(
            "/workflows/compile", json={"workflow": WORKFLOW, "context": CONTEXT},
        ).json()
        self.assertTrue(body["ok"], body)
        self.assertEqual(body["preview_lines"], [
            "1. Launch Obsidian (flatpak run md.obsidian.Obsidian)",
            "2. Switch the application profile to writing_app",
        ])
        self.assertFalse(os.path.exists(self.path))

    def test_a_prohibited_step_is_refused_with_its_reason(self):
        body = self.client.post("/workflows/compile", json={
            "workflow": {"name": "bad", "steps": [{"action": "delete", "path": "~/x"}]},
            "context": CONTEXT,
        }).json()
        self.assertFalse(body["ok"])
        self.assertIn("never change or remove your files", body["refusals"][0]["reason"])

    def test_schema_refusals_and_target_refusals_are_reported_separately(self):
        body = self.client.post("/workflows/compile", json={
            "workflow": {"name": "x", "steps": [{"action": "launch_app", "app_id": "blender"}]},
            "context": CONTEXT,
        }).json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["refusals"], [])
        self.assertEqual(body["validation_refusals"][0]["code"], "unknown_application")


class SaveApproveRunTests(RouteTestCase):
    def save(self, enabled=True):
        return self.client.post("/workflows/save", json={"workflow": WORKFLOW, "enabled": enabled})

    def preview(self):
        return self.client.post(
            "/workflows/compile", json={"workflow": WORKFLOW, "context": CONTEXT},
        ).json()["preview_lines"]

    def test_save_stores_the_workflow_unapproved(self):
        body = self.save().json()
        self.assertTrue(body["ok"])
        self.assertFalse(body["workflow"]["approved"])

    def test_saving_a_prohibited_workflow_returns_400_with_the_refusals_attached(self):
        response = self.client.post("/workflows/save", json={
            "workflow": {"name": "bad", "steps": [{"action": "kill_process", "app_id": "x"}]},
        })
        self.assertEqual(response.status_code, 400)
        detail = response.json()["detail"]
        self.assertEqual(detail["error"], "refused")
        self.assertIn("never close or kill programs", detail["refusals"][0]["reason"])

    def test_run_is_refused_until_the_preview_is_approved(self):
        self.save()
        body = self.client.post(
            "/workflows/run", json={"workflow_id": "studio_setup", "context": CONTEXT},
        ).json()
        self.assertFalse(body["ok"])
        self.assertEqual(body["error"], "not_approved")

    def test_the_full_flow_reaches_a_runnable_workflow(self):
        self.save()
        approve = self.client.post("/workflows/approve", json={
            "workflow_id": "studio_setup", "preview": self.preview(),
        }).json()
        self.assertTrue(approve["ok"])
        run = self.client.post(
            "/workflows/run", json={"workflow_id": "studio_setup", "context": CONTEXT},
        ).json()
        self.assertTrue(run["ok"], run)
        self.assertEqual(len(run["preview"]), 2)

    def test_a_registry_change_after_approval_blocks_the_run(self):
        """Nobody edited the workflow; the launch method behind it changed.

        This is the case approval-by-flag misses entirely: the stored approval
        is intact and the preview it was given for no longer describes what
        would happen.
        """
        self.save()
        self.client.post("/workflows/approve", json={
            "workflow_id": "studio_setup", "preview": self.preview(),
        })
        changed = dict(CONTEXT, registry=[{
            **REGISTRY[0], "launch_method": "executable", "executable": "/usr/bin/obsidian",
        }])
        run = self.client.post(
            "/workflows/run", json={"workflow_id": "studio_setup", "context": changed},
        ).json()
        self.assertFalse(run["ok"])
        self.assertEqual(run["error"], "preview_changed")

    def test_removing_the_application_blocks_the_run_with_validation_refusals(self):
        self.save()
        self.client.post("/workflows/approve", json={
            "workflow_id": "studio_setup", "preview": self.preview(),
        })
        run = self.client.post("/workflows/run", json={
            "workflow_id": "studio_setup", "context": dict(CONTEXT, registry=[]),
        }).json()
        self.assertFalse(run["ok"])
        self.assertEqual(run["error"], "validation_failed")
        self.assertEqual(run["refusals"][0]["code"], "unknown_application")

    def test_a_disabled_workflow_cannot_run(self):
        self.save(enabled=False)
        self.client.post("/workflows/approve", json={
            "workflow_id": "studio_setup", "preview": self.preview(),
        })
        run = self.client.post(
            "/workflows/run", json={"workflow_id": "studio_setup", "context": CONTEXT},
        ).json()
        self.assertFalse(run["ok"])
        self.assertEqual(run["error"], "disabled")


class RecordRunTests(RouteTestCase):
    def setUp(self):
        super().setUp()
        self.client.post("/workflows/save", json={"workflow": WORKFLOW, "enabled": True})

    def test_two_of_two_is_success(self):
        body = self.client.post("/workflows/run/record", json={
            "workflow_id": "studio_setup",
            "results": [{"status": "ok"}, {"status": "ok"}],
        }).json()
        self.assertEqual(body["summary"]["status"], "success")

    def test_one_of_two_is_partial_and_lands_in_history_as_codes(self):
        body = self.client.post("/workflows/run/record", json={
            "workflow_id": "studio_setup",
            "results": [{"status": "ok"}, {"status": "failed"}],
        }).json()
        self.assertEqual(body["summary"]["status"], "partial")
        self.assertFalse(body["summary"]["ok"])

        history = self.client.get("/workflows/history?workflow_id=studio_setup").json()["history"]
        self.assertEqual(len(history), 1)
        self.assertEqual([row["status"] for row in history[0]["steps"]], ["ok", "failed"])
        self.assertNotIn("target", history[0]["steps"][0])

    def test_recording_against_a_missing_workflow_is_a_404(self):
        response = self.client.post("/workflows/run/record", json={
            "workflow_id": "gone", "results": [{"status": "ok"}],
        })
        self.assertEqual(response.status_code, 404)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
