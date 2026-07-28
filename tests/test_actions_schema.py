"""Wave 9 — the restricted action schema (backend/domain/actions.py).

These tests are the written form of D-0011's first clause: *store only versioned
restricted actions*. They are deliberately paranoid about the two failure modes
that do not look like failures:

* a prohibited verb that is silently DROPPED rather than refused (the workflow
  saves, and quietly does less than the user described), and
* a prohibited verb that gets through because it arrived spelled slightly
  differently than the blocklist expected.
"""

import unittest

from backend.domain import actions as A


class VocabularyTests(unittest.TestCase):
    def test_allowed_vocabulary_is_exactly_the_ten_approved_verbs(self):
        self.assertEqual(
            set(A.ALLOWED_ACTIONS),
            {
                "launch_app", "focus_app", "open_uri", "open_folder",
                "wait_for_process", "activate_application_profile",
                "activate_persona", "activate_writing_preset",
                "show_notification", "speak_confirmation",
            },
        )
        # Every allowed verb has a declared parameter; a verb with no parameter
        # vocabulary would accept anything.
        for action in A.ALLOWED_ACTIONS:
            self.assertIn(action, A.ACTION_PARAM, action)

    def test_prohibited_list_is_exactly_the_release_plan_set(self):
        self.assertEqual(
            set(A.PROHIBITED_ACTIONS),
            {
                "shell", "bash", "powershell", "cmd", "delete", "move",
                "rename", "install", "close_app", "kill_process",
                "edit_registry", "type_password", "purchase",
                "send_hidden_message", "generated_code",
            },
        )

    def test_no_verb_is_both_allowed_and_prohibited(self):
        self.assertEqual(set(A.ALLOWED_ACTIONS) & set(A.PROHIBITED_ACTIONS), set())

    def test_every_prohibition_carries_a_reason_a_person_can_read(self):
        for action, reason in A.PROHIBITED_ACTIONS.items():
            self.assertTrue(reason.endswith("."), action)
            self.assertGreater(len(reason), 40, action)
            # A refusal must not double as a how-to.
            for leak in ("sudo", "rm -rf", "cmd.exe", "powershell -", "bash -c"):
                self.assertNotIn(leak, reason.lower(), action)

    def test_prohibited_aliases_all_resolve_to_a_real_prohibition(self):
        for alias, canonical in A.PROHIBITED_ALIASES.items():
            self.assertIn(canonical, A.PROHIBITED_ACTIONS, alias)


class ClassifyTests(unittest.TestCase):
    def test_spelling_variants_of_an_allowed_verb_canonicalise(self):
        for spelling in ("launch_app", "Launch App", "launch-app", " LAUNCH_APP "):
            self.assertEqual(A.classify_action(spelling), ("allowed", "launch_app"), spelling)

    def test_spelling_variants_of_a_prohibited_verb_are_still_prohibited(self):
        for spelling in ("shell", "Shell", "SHELL", "run_command", "run command", "exec"):
            kind, canonical = A.classify_action(spelling)
            self.assertEqual(kind, "prohibited", spelling)
            self.assertIn(canonical, A.PROHIBITED_ACTIONS, spelling)

    def test_an_unheard_of_verb_is_unknown_not_allowed(self):
        kind, _ = A.classify_action("summon_a_daemon")
        self.assertEqual(kind, "unknown")


class RefusalTests(unittest.TestCase):
    def test_a_prohibited_step_is_refused_with_its_reason_and_not_dropped(self):
        result = A.compile_workflow({
            "name": "Morning",
            "steps": [
                {"action": "launch_app", "app_id": "obsidian"},
                {"action": "shell", "command": "rm -rf ~"},
            ],
        })
        self.assertFalse(result.ok)
        self.assertEqual(len(result.refusals), 1)
        refusal = result.refusals[0]
        self.assertEqual(refusal.step_index, 1)
        self.assertEqual(refusal.action, "shell")
        self.assertEqual(refusal.code, "prohibited_action")
        self.assertIn("never runs shell commands", refusal.reason)
        # The surviving step is still returned so the builder can show exactly
        # which line is the problem -- but ok is False, so nothing saves.
        self.assertEqual(len(result.workflow["steps"]), 1)

    def test_every_prohibited_verb_is_refused_when_it_appears_as_a_step(self):
        for verb in A.PROHIBITED_ACTIONS:
            result = A.compile_workflow({"name": "x", "steps": [{"action": verb}]})
            self.assertFalse(result.ok, verb)
            self.assertEqual(result.refusals[0].reason, A.PROHIBITED_ACTIONS[verb], verb)
            self.assertEqual(result.workflow["steps"], [], verb)

    def test_a_prohibited_step_never_survives_into_the_compiled_steps(self):
        result = A.compile_workflow({
            "name": "x",
            "steps": [{"action": alias} for alias in A.PROHIBITED_ALIASES],
        })
        self.assertFalse(result.ok)
        self.assertEqual(result.workflow["steps"], [])

    def test_an_unknown_verb_is_refused_with_the_closed_vocabulary_sentence(self):
        result = A.compile_workflow({"name": "x", "steps": [{"action": "teleport"}]})
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "unknown_action")
        self.assertEqual(result.refusals[0].reason, A.UNKNOWN_ACTION_REASON)

    def test_unknown_fields_are_reported_rather_than_silently_kept(self):
        result = A.compile_workflow({
            "name": "x",
            "steps": [{"action": "show_notification", "message": "hi"}],
            "run_as_root": True,
            "approved": True,
        })
        self.assertTrue(result.ok)
        self.assertEqual(result.dropped_fields, ["approved", "run_as_root"])
        self.assertNotIn("approved", result.workflow)


class UriTests(unittest.TestCase):
    def test_plain_web_and_mail_links_normalise(self):
        for uri in ("https://example.com/a?b=c", "http://example.com", "mailto:a@example.com"):
            value, reason = A.normalize_uri(uri)
            self.assertEqual(reason, "", uri)
            self.assertEqual(value, uri)

    def test_code_bearing_schemes_are_refused_by_name(self):
        for uri in ("javascript:alert(1)", "data:text/html,<script>", "vbscript:x", "file:///etc/passwd"):
            value, reason = A.normalize_uri(uri)
            self.assertEqual(value, "", uri)
            self.assertTrue(reason, uri)

    def test_a_schemeless_string_is_refused_rather_than_guessed(self):
        value, reason = A.normalize_uri("example.com")
        self.assertEqual(value, "")
        self.assertIn("scheme", reason)

    def test_a_link_with_a_space_is_refused_not_silently_encoded(self):
        value, reason = A.normalize_uri("https://example.com/a b")
        self.assertEqual(value, "")
        self.assertIn("space", reason)

    def test_control_characters_cannot_survive_in_a_link(self):
        value, reason = A.normalize_uri("https://example.com/a\nDROP")
        # The newline is stripped, not tolerated: whatever survives is a single
        # line or nothing.
        self.assertNotIn("\n", value)
        self.assertNotIn("\n", reason)

    def test_a_link_longer_than_the_bound_is_refused(self):
        value, reason = A.normalize_uri("https://example.com/" + "a" * A.MAX_URI_LEN)
        self.assertEqual(value, "")
        self.assertIn("longer than", reason)

    def test_a_registry_scheme_passes_the_schema_and_is_the_validators_problem(self):
        # The schema does not know what this machine has installed, so it only
        # checks the shape; action_validator decides whether anything handles it.
        value, reason = A.normalize_uri("steam://rungameid/252950")
        self.assertEqual(reason, "")
        self.assertEqual(value, "steam://rungameid/252950")


class PathTests(unittest.TestCase):
    def test_a_home_relative_folder_expands_to_an_absolute_path(self):
        import os
        value, reason = A.normalize_folder_path("~/Documents")
        self.assertEqual(reason, "")
        self.assertTrue(os.path.isabs(value))
        self.assertTrue(value.endswith("Documents"))

    def test_dot_dot_is_refused_rather_than_resolved(self):
        value, reason = A.normalize_folder_path("~/Documents/../../..")
        self.assertEqual(value, "")
        self.assertIn("..", reason)

    def test_a_relative_folder_is_refused(self):
        value, reason = A.normalize_folder_path("Documents")
        self.assertEqual(value, "")
        self.assertIn("full path", reason)

    def test_an_over_long_folder_path_is_refused(self):
        value, reason = A.normalize_folder_path("/" + "a" * (A.MAX_PATH_LEN + 10))
        self.assertEqual(value, "")
        self.assertTrue(reason)


class CompileTests(unittest.TestCase):
    def test_a_complete_workflow_is_a_v1_document_with_exactly_the_declared_fields(self):
        result = A.compile_workflow({
            "id": "Studio Setup",
            "name": "Studio setup",
            "trigger_phrases": ["Open my studio!", "open my studio", "start the studio"],
            "steps": [
                {"action": "launch_app", "app_id": "obsidian"},
                {"action": "wait_for_process", "app_id": "obsidian", "timeout_ms": 999999},
                {"action": "activate_persona", "persona": "True Janitor"},
                {"action": "speak_confirmation", "message": "Studio ready"},
            ],
        })
        self.assertTrue(result.ok, [r.to_dict() for r in result.refusals])
        workflow = result.workflow
        self.assertEqual(set(workflow), set(A.WORKFLOW_FIELDS))
        self.assertEqual(workflow["schema_version"], A.SCHEMA_VERSION)
        self.assertEqual(workflow["id"], "studio_setup")
        # Duplicate trigger phrases collapse after normalisation.
        self.assertEqual(workflow["trigger_phrases"], ["open my studio", "start the studio"])
        self.assertEqual(workflow["steps"][1]["timeout_ms"], A.MAX_WAIT_MS)

    def test_a_workflow_with_no_steps_is_refused(self):
        result = A.compile_workflow({"name": "empty", "steps": []})
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "empty_workflow")

    def test_a_workflow_with_no_name_is_refused(self):
        result = A.compile_workflow({"steps": [{"action": "show_notification", "message": "hi"}]})
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "invalid_id")

    def test_too_many_steps_is_refused_rather_than_truncated_silently(self):
        result = A.compile_workflow({
            "name": "long",
            "steps": [{"action": "show_notification", "message": str(i)}
                      for i in range(A.MAX_STEPS + 3)],
        })
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "too_many_steps")

    def test_a_step_missing_its_target_is_refused_with_a_specific_reason(self):
        result = A.compile_workflow({"name": "x", "steps": [{"action": "launch_app"}]})
        self.assertFalse(result.ok)
        self.assertEqual(result.refusals[0].code, "invalid_target")

    def test_garbage_input_does_not_raise(self):
        for payload in (None, "", [], 7, {"steps": "nope"}):
            result = A.compile_workflow(payload)
            self.assertFalse(result.ok)

    def test_step_target_reads_the_declared_parameter_for_each_verb(self):
        self.assertEqual(A.step_target({"action": "open_uri", "uri": "https://x"}), "https://x")
        self.assertEqual(A.step_target({"action": "launch_app", "app_id": "a"}), "a")
        self.assertEqual(A.step_target({"action": "nope"}), "")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
