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

from approval_support import workflow_ticket
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

    def approve(self, **overrides):
        """Approve the way the Electron broker does: ask the backend for the exact
        preview, 'show it', sign a ticket bound to what was shown, post it."""
        shown = self.client.post(
            "/workflows/preview", json={"workflow_id": "studio_setup", "context": CONTEXT},
        ).json()
        record = WorkflowStore(path=self.path).get("studio_setup")
        ticket = workflow_ticket("studio_setup", shown["preview_lines"], record["steps"])
        body = {"workflow_id": "studio_setup", "preview": shown["preview_lines"], "approval": ticket}
        body.update(overrides)
        return self.client.post("/workflows/approve", json=body)

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
        approve = self.approve().json()
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
        self.assertEqual(self.approve().status_code, 200)
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
        self.assertEqual(self.approve().status_code, 200)
        run = self.client.post("/workflows/run", json={
            "workflow_id": "studio_setup", "context": dict(CONTEXT, registry=[]),
        }).json()
        self.assertFalse(run["ok"])
        self.assertEqual(run["error"], "validation_failed")
        self.assertEqual(run["refusals"][0]["code"], "unknown_application")

    def test_a_disabled_workflow_cannot_run(self):
        self.save(enabled=False)
        self.assertEqual(self.approve().status_code, 200)
        run = self.client.post(
            "/workflows/run", json={"workflow_id": "studio_setup", "context": CONTEXT},
        ).json()
        self.assertFalse(run["ok"])
        self.assertEqual(run["error"], "disabled")


class ApprovalGateRouteTests(RouteTestCase):
    """Phase 0 item 1: nobody who merely holds the bearer token can approve."""

    def setUp(self):
        super().setUp()
        self.client.post("/workflows/save", json={"workflow": WORKFLOW, "enabled": True})
        self.shown = self.client.post(
            "/workflows/preview", json={"workflow_id": "studio_setup", "context": CONTEXT},
        ).json()
        self.record = WorkflowStore(path=self.path).get("studio_setup")

    def post_approve(self, **fields):
        body = {"workflow_id": "studio_setup", "preview": self.shown["preview_lines"]}
        body.update(fields)
        return self.client.post("/workflows/approve", json=body)

    def assert_still_unapproved(self):
        self.assertFalse(WorkflowStore(path=self.path).get("studio_setup")["approved"])
        run = self.client.post("/workflows/run", json={"workflow_id": "studio_setup", "context": CONTEXT}).json()
        self.assertFalse(run["ok"])

    def test_the_preview_route_returns_the_exact_lines_and_their_digests(self):
        from backend.services import approvals

        self.assertTrue(self.shown["ok"])
        self.assertEqual(self.shown["preview_sha256"], approvals.preview_digest(self.shown["preview_lines"]))
        self.assertEqual(self.shown["steps_sha256"], approvals.steps_digest(self.record["steps"]))

    def test_approving_with_the_replayed_preview_and_no_ticket_is_refused(self):
        """The review's exploit: save, compile, copy the preview lines back into
        /workflows/approve. Compile and run both hand the lines out, so they are
        not proof of anything."""
        response = self.post_approve()
        self.assertEqual(response.status_code, 403)
        self.assertIn("needs your approval", response.json()["detail"])
        self.assert_still_unapproved()

    def test_a_forged_boolean_or_flag_in_the_body_is_ignored(self):
        for extra in ({"approved": True}, {"consent": True}, {"confirm": True}, {"approval": True}):
            response = self.post_approve(**extra)
            self.assertIn(response.status_code, (403, 422), extra)
        self.assert_still_unapproved()

    def test_a_ticket_signed_with_a_key_the_caller_guessed_is_refused(self):
        forged = workflow_ticket("studio_setup", self.shown["preview_lines"], self.record["steps"], secret=b"\x09" * 32)
        self.assertEqual(self.post_approve(approval=forged).status_code, 403)
        self.assert_still_unapproved()

    def test_a_genuine_ticket_approves_and_only_then_can_the_workflow_run(self):
        ticket = workflow_ticket("studio_setup", self.shown["preview_lines"], self.record["steps"])
        self.assertEqual(self.post_approve(approval=ticket).status_code, 200)
        run = self.client.post("/workflows/run", json={"workflow_id": "studio_setup", "context": CONTEXT}).json()
        self.assertTrue(run["ok"], run)

    def test_a_ticket_cannot_be_replayed(self):
        ticket = workflow_ticket("studio_setup", self.shown["preview_lines"], self.record["steps"])
        self.assertEqual(self.post_approve(approval=ticket).status_code, 200)
        self.client.post("/workflows/save", json={"workflow": {**WORKFLOW, "steps": WORKFLOW["steps"][:1]}, "enabled": True})
        again = self.post_approve(approval=ticket)
        self.assertEqual(again.status_code, 403)

    def test_a_ticket_for_a_different_preview_is_refused(self):
        """The person saw X; the caller submits Y with the ticket for X."""
        ticket = workflow_ticket("studio_setup", self.shown["preview_lines"], self.record["steps"])
        swapped = list(self.shown["preview_lines"])
        swapped[0] = swapped[0] + " "  # a single character
        self.assertEqual(self.post_approve(preview=swapped, approval=ticket).status_code, 403)
        self.assert_still_unapproved()

    def test_a_ticket_minted_before_the_steps_changed_is_refused(self):
        ticket = workflow_ticket("studio_setup", self.shown["preview_lines"], self.record["steps"])
        edited = {**WORKFLOW, "steps": [{"action": "launch_app", "app_id": "obsidian"}]}
        self.client.post("/workflows/save", json={"workflow": edited, "enabled": True})
        self.assertEqual(self.post_approve(approval=ticket).status_code, 403)
        self.assert_still_unapproved()

    def test_a_ticket_for_another_workflow_is_refused(self):
        other = workflow_ticket("other_workflow", self.shown["preview_lines"], self.record["steps"])
        self.assertEqual(self.post_approve(approval=other).status_code, 403)

    def test_a_malformed_or_oversized_ticket_is_a_clean_refusal_not_a_crash(self):
        for bad in ({"payload": "x", "sig": "y"}, {"payload": "a" * 5000, "sig": "0" * 64}, {"payload": "x", "sig": "0" * 64, "extra": 1}):
            self.assertIn(self.post_approve(approval=bad).status_code, (403, 422), bad)

    def test_without_a_configured_key_the_route_says_approvals_are_unavailable(self):
        from backend.services import approvals

        approvals.reset()
        ticket = workflow_ticket("studio_setup", self.shown["preview_lines"], self.record["steps"])
        self.assertEqual(self.post_approve(approval=ticket).status_code, 503)

    def test_an_oversized_preview_is_refused_not_clipped(self):
        response = self.post_approve(preview=["x" * 9000])
        self.assertEqual(response.status_code, 400)
        self.assertIn("too long", response.json()["detail"])

    def test_a_long_preview_line_change_is_caught_end_to_end(self):
        """Item 2 through the HTTP gate: the registry entry's launch description
        differs only past character 240 and the approved workflow stops running."""
        long_reg = [{**REGISTRY[0], "launch_method": "executable", "executable": "/opt/" + "a" * 250 + "/obsidian"}]
        ctx_a = dict(CONTEXT, registry=long_reg)
        ctx_b = dict(CONTEXT, registry=[{**long_reg[0], "executable": "/opt/" + "a" * 250 + "/EVIL"}])
        shown_a = self.client.post("/workflows/preview", json={"workflow_id": "studio_setup", "context": ctx_a}).json()
        self.assertTrue(any(len(line) > 240 for line in shown_a["preview_lines"]))
        ticket = workflow_ticket("studio_setup", shown_a["preview_lines"], self.record["steps"])
        self.assertEqual(self.post_approve(preview=shown_a["preview_lines"], approval=ticket).status_code, 200)
        run_a = self.client.post("/workflows/run", json={"workflow_id": "studio_setup", "context": ctx_a}).json()
        self.assertTrue(run_a["ok"], run_a)
        run_b = self.client.post("/workflows/run", json={"workflow_id": "studio_setup", "context": ctx_b}).json()
        self.assertFalse(run_b["ok"])
        self.assertEqual(run_b["error"], "preview_changed")


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
