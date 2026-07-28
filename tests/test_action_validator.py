"""Wave 9 — target validation, exact previews, partial-failure reporting.

The three properties under test are the ones Gate 9 is written against:

* a workflow cannot name an application the user did not confirm — there is no
  spelling of a step that reaches outside the registry;
* the preview says exactly what will run, in order, with resolved targets; and
* launching two of three is reported as *partial*, never as success.
"""

import os
import tempfile
import unittest

from backend.domain.actions import compile_workflow
from backend.services import action_validator as V

REGISTRY = [
    {
        "id": "obsidian",
        "display_name": "Obsidian",
        "launch_method": "flatpak",
        "flatpak_id": "md.obsidian.Obsidian",
        "confirmed": True,
    },
    {
        "id": "steam_rl",
        "display_name": "Rocket League",
        "launch_method": "steam",
        "steam_uri": "steam://rungameid/252950",
        "uri_scheme": "steam",
        "uri": "steam://rungameid/252950",
        "confirmed": True,
    },
    {
        "id": "no_method",
        "display_name": "Half Confirmed",
        "launch_method": "",
        "confirmed": True,
    },
    # Discovered but never confirmed: present in the list, invisible to a
    # workflow. This entry is the whole point of index_registry().
    {
        "id": "spotify",
        "display_name": "Spotify",
        "launch_method": "flatpak",
        "flatpak_id": "com.spotify.Client",
        "confirmed": False,
    },
]

KNOWN = dict(
    known_profile_ids=["default", "writing_app"],
    known_personas=["True Janitor"],
    known_writing_presets=["casual"],
)


def build(steps, name="test"):
    result = compile_workflow({"name": name, "steps": steps})
    assert result.ok, [r.to_dict() for r in result.refusals]
    return result.workflow


class RegistryEscapeTests(unittest.TestCase):
    def test_an_unconfirmed_application_cannot_be_launched(self):
        workflow = build([{"action": "launch_app", "app_id": "spotify"}])
        result = V.validate_workflow(workflow, REGISTRY, **KNOWN)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "unknown_application")
        self.assertEqual(result.preview, [])

    def test_an_application_that_is_not_in_the_registry_at_all_is_refused(self):
        workflow = build([{"action": "launch_app", "app_id": "blender"}])
        result = V.validate_workflow(workflow, REGISTRY, **KNOWN)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "unknown_application")

    def test_focus_and_wait_are_gated_by_the_same_registry(self):
        for action in ("focus_app", "wait_for_process"):
            workflow = build([{"action": action, "app_id": "spotify"}])
            result = V.validate_workflow(workflow, REGISTRY, **KNOWN)
            self.assertFalse(result.ok, action)
            self.assertEqual(result.refusals[0].code, "unknown_application", action)

    def test_a_confirmed_entry_with_no_launch_method_cannot_be_launched(self):
        workflow = build([{"action": "launch_app", "app_id": "no_method"}])
        result = V.validate_workflow(workflow, REGISTRY, **KNOWN)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "no_launch_method")

    def test_index_registry_keeps_only_confirmed_entries(self):
        index = V.index_registry(REGISTRY)
        self.assertEqual(set(index), {"obsidian", "steam_rl", "no_method"})


class UriSchemeTests(unittest.TestCase):
    def test_the_three_unconditional_schemes_pass_without_any_registry(self):
        for uri in ("https://example.com", "http://example.com", "mailto:a@example.com"):
            workflow = build([{"action": "open_uri", "uri": uri}])
            result = V.validate_workflow(workflow, [], **KNOWN)
            self.assertTrue(result.ok, uri)

    def test_a_registered_scheme_passes_only_because_a_confirmed_entry_declares_it(self):
        workflow = build([{"action": "open_uri", "uri": "steam://rungameid/252950"}])
        self.assertTrue(V.validate_workflow(workflow, REGISTRY, **KNOWN).ok)

        without = V.validate_workflow(workflow, [], **KNOWN)
        self.assertFalse(without.ok)
        self.assertEqual(without.refusals[0].code, "unregistered_scheme")

    def test_an_unconfirmed_entrys_scheme_does_not_count(self):
        workflow = build([{"action": "open_uri", "uri": "spotify:track:x"}])
        result = V.validate_workflow(workflow, REGISTRY, **KNOWN)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "unregistered_scheme")


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.inside = os.path.join(self.tmp, "notes")
        os.makedirs(self.inside)

    def test_a_folder_inside_an_allowed_root_passes(self):
        workflow = build([{"action": "open_folder", "path": self.inside}])
        result = V.validate_workflow(
            workflow, REGISTRY, allowed_folder_roots=[self.tmp], **KNOWN,
        )
        self.assertTrue(result.ok, [r.to_dict() for r in result.refusals])

    def test_a_folder_outside_every_allowed_root_is_refused(self):
        workflow = build([{"action": "open_folder", "path": "/etc"}])
        result = V.validate_workflow(
            workflow, REGISTRY, allowed_folder_roots=[self.tmp], **KNOWN,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "folder_out_of_bounds")

    def test_a_sibling_directory_with_a_shared_prefix_is_not_inside_the_root(self):
        # /tmp/x/notes-evil must not pass containment for the root /tmp/x/notes.
        sibling = self.inside + "_evil"
        os.makedirs(sibling)
        workflow = build([{"action": "open_folder", "path": sibling}])
        result = V.validate_workflow(
            workflow, REGISTRY, allowed_folder_roots=[self.inside], **KNOWN,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "folder_out_of_bounds")

    def test_a_missing_folder_is_refused_rather_than_opened_hopefully(self):
        workflow = build([{"action": "open_folder", "path": os.path.join(self.tmp, "gone")}])
        result = V.validate_workflow(
            workflow, REGISTRY, allowed_folder_roots=[self.tmp], **KNOWN,
        )
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "folder_not_found")


class FailClosedTests(unittest.TestCase):
    def test_a_persona_step_is_refused_when_the_caller_supplied_no_persona_list(self):
        workflow = build([{"action": "activate_persona", "persona": "True Janitor"}])
        result = V.validate_workflow(workflow, REGISTRY)
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "unknown_persona")

    def test_an_unknown_profile_preset_or_persona_is_refused(self):
        cases = [
            ({"action": "activate_application_profile", "profile_id": "nope"}, "unknown_profile"),
            ({"action": "activate_persona", "persona": "Nobody"}, "unknown_persona"),
            ({"action": "activate_writing_preset", "preset": "nope"}, "unknown_writing_preset"),
        ]
        for step, code in cases:
            result = V.validate_workflow(build([step]), REGISTRY, **KNOWN)
            self.assertFalse(result.ok, step)
            self.assertEqual(result.refusals[0].code, code, step)

    def test_known_targets_pass_case_insensitively(self):
        workflow = build([
            {"action": "activate_application_profile", "profile_id": "writing_app"},
            {"action": "activate_persona", "persona": "true janitor"},
            {"action": "activate_writing_preset", "preset": "Casual"},
        ])
        self.assertTrue(V.validate_workflow(workflow, REGISTRY, **KNOWN).ok)


class PreviewTests(unittest.TestCase):
    def test_the_preview_is_ordered_and_names_the_resolved_launch_target(self):
        workflow = build([
            {"action": "launch_app", "app_id": "obsidian"},
            {"action": "wait_for_process", "app_id": "obsidian", "timeout_ms": 3000},
            {"action": "activate_application_profile", "profile_id": "writing_app"},
            {"action": "speak_confirmation", "message": "Ready"},
        ])
        result = V.validate_workflow(workflow, REGISTRY, **KNOWN)
        self.assertTrue(result.ok)
        lines = V.preview_lines(result.preview)
        self.assertEqual(lines, [
            "1. Launch Obsidian (flatpak run md.obsidian.Obsidian)",
            "2. Wait for Obsidian to be running (up to 3s)",
            "3. Switch the application profile to writing_app",
            "4. Say “Ready” out loud",
        ])
        self.assertEqual([row["position"] for row in result.preview], [0, 1, 2, 3])

    def test_the_preview_names_the_exact_command_shape_not_a_paraphrase(self):
        workflow = build([{"action": "launch_app", "app_id": "steam_rl"}])
        preview = V.build_preview(workflow, REGISTRY, **KNOWN)
        self.assertIn("steam://rungameid/252950", preview[0]["summary"])

    def test_no_preview_is_produced_when_anything_was_refused(self):
        workflow = build([
            {"action": "launch_app", "app_id": "obsidian"},
            {"action": "launch_app", "app_id": "spotify"},
        ])
        self.assertEqual(V.build_preview(workflow, REGISTRY, **KNOWN), [])


class PartialFailureTests(unittest.TestCase):
    def setUp(self):
        self.workflow = build([
            {"action": "launch_app", "app_id": "obsidian"},
            {"action": "launch_app", "app_id": "steam_rl"},
            {"action": "show_notification", "message": "Done"},
        ])

    def test_two_of_three_is_partial_and_never_ok(self):
        summary = V.summarize_run(self.workflow, [
            {"status": "ok"}, {"status": "ok"}, {"status": "failed"},
        ])
        self.assertEqual(summary["status"], V.RUN_PARTIAL)
        self.assertFalse(summary["ok"])
        self.assertEqual(summary["completed"], 2)
        self.assertEqual(summary["total"], 3)
        self.assertIn("2 of 3", V.describe_run(summary))

    def test_all_ok_is_success(self):
        summary = V.summarize_run(self.workflow, [{"status": "ok"}] * 3)
        self.assertEqual(summary["status"], V.RUN_SUCCESS)
        self.assertTrue(summary["ok"])

    def test_steps_that_never_ran_are_reported_as_skipped_not_omitted(self):
        summary = V.summarize_run(self.workflow, [{"status": "ok"}, {"status": "failed"}])
        self.assertEqual(len(summary["steps"]), 3)
        self.assertEqual(summary["steps"][2]["status"], "skipped")
        self.assertEqual(summary["status"], V.RUN_PARTIAL)

    def test_nothing_ran_at_all_is_blocked_rather_than_failed(self):
        summary = V.summarize_run(self.workflow, [])
        self.assertEqual(summary["status"], V.RUN_BLOCKED)
        self.assertEqual(V.describe_run(summary), "Nothing ran.")

    def test_every_step_failing_is_failed(self):
        summary = V.summarize_run(self.workflow, [{"status": "failed"}] * 3)
        self.assertEqual(summary["status"], V.RUN_FAILED)

    def test_an_unrecognised_status_code_is_read_as_failed_not_as_success(self):
        summary = V.summarize_run(self.workflow, [
            {"status": "ok"}, {"status": "probably_fine"}, {"status": "ok"},
        ])
        self.assertEqual(summary["steps"][1]["status"], "failed")
        self.assertEqual(summary["status"], V.RUN_PARTIAL)

    def test_a_run_summary_carries_only_codes_from_the_declared_vocabulary(self):
        summary = V.summarize_run(self.workflow, [
            {"status": "ok"}, {"status": "timeout"}, {"status": "not_found"},
        ])
        for row in summary["steps"]:
            self.assertIn(row["status"], V.STEP_STATUS_CODES)
        self.assertIn(summary["status"], V.RUN_STATUS_CODES)


class LaunchMethodParityTests(unittest.TestCase):
    def test_the_launch_method_table_matches_the_electron_side(self):
        # Read as text rather than imported: this is a Python test asserting a
        # JS constant, and the point is that the two lists cannot drift.
        path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            "app", "src", "main", "applicationRegistry.js",
        )
        with open(path, encoding="utf-8") as handle:
            source = handle.read()
        for method in V.LAUNCH_METHODS:
            self.assertIn(f"'{method}'", source, method)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
