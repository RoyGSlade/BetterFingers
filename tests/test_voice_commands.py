import unittest

from voice_commands import parse_command

OVERLAY_CTX = {"review_overlay_open": True}
WAKE_CTX = {"post_wake_word": True}
CMD_MODE_CTX = {"command_mode_on": True}


class ParseCommandContextGatingTests(unittest.TestCase):
    def test_no_context_no_prefix_returns_none(self):
        self.assertIsNone(parse_command("send it"))

    def test_command_phrase_inside_paragraph_without_context_is_not_a_command(self):
        text = "I told him to send it to accounting by Friday"
        self.assertIsNone(parse_command(text))

    def test_review_overlay_open_allows_command(self):
        intent = parse_command("send it", OVERLAY_CTX)
        self.assertIsNotNone(intent)
        self.assertEqual(intent.action, "send")

    def test_post_wake_word_allows_command(self):
        intent = parse_command("cancel that", WAKE_CTX)
        self.assertEqual(intent.action, "cancel")

    def test_command_mode_on_allows_command(self):
        intent = parse_command("read that back", CMD_MODE_CTX)
        self.assertEqual(intent.action, "read_back")

    def test_prefix_allows_command_with_no_other_context(self):
        intent = parse_command("BetterFingers, open settings")
        self.assertEqual(intent.action, "open_settings")

    def test_prefix_case_insensitive_and_hey_optional(self):
        intent = parse_command("hey betterfingers: cancel that")
        self.assertEqual(intent.action, "cancel")


class ParseCommandEmergencyStopTests(unittest.TestCase):
    def test_emergency_stop_resolves_with_no_context(self):
        intent = parse_command("emergency stop")
        self.assertEqual(intent.action, "emergency_stop")
        self.assertEqual(intent.kind, "app_action")
        self.assertFalse(intent.requires_confirmation)
        self.assertEqual(intent.confidence, 1.0)

    def test_emergency_stop_resolves_embedded_in_a_sentence(self):
        intent = parse_command("please do an emergency stop now")
        self.assertEqual(intent.action, "emergency_stop")


class ParseCommandVocabularyTests(unittest.TestCase):
    def test_send_requires_confirmation(self):
        intent = parse_command("send it", OVERLAY_CTX)
        self.assertTrue(intent.requires_confirmation)

    def test_delete_history_requires_confirmation(self):
        intent = parse_command("delete all history", OVERLAY_CTX)
        self.assertEqual(intent.action, "delete_history")
        self.assertTrue(intent.requires_confirmation)

    def test_read_back_does_not_require_confirmation(self):
        intent = parse_command("read that back", OVERLAY_CTX)
        self.assertFalse(intent.requires_confirmation)

    def test_make_it_shorter(self):
        intent = parse_command("make it shorter", OVERLAY_CTX)
        self.assertEqual(intent.action, "rewrite_shorter")
        self.assertEqual(intent.kind, "draft_action")

    def test_make_it_clearer(self):
        intent = parse_command("make it clearer", OVERLAY_CTX)
        self.assertEqual(intent.action, "rewrite_clearer")

    def test_try_again(self):
        intent = parse_command("try again", OVERLAY_CTX)
        self.assertEqual(intent.action, "retry")

    def test_copy_it(self):
        intent = parse_command("copy it", OVERLAY_CTX)
        self.assertEqual(intent.action, "copy")

    def test_start_stop_recording(self):
        self.assertEqual(parse_command("start recording", CMD_MODE_CTX).action, "start_recording")
        self.assertEqual(parse_command("stop recording", CMD_MODE_CTX).action, "stop_recording")

    def test_command_with_trailing_filler_words_still_matches(self):
        intent = parse_command("send it please", OVERLAY_CTX)
        self.assertEqual(intent.action, "send")

    def test_unrelated_speech_in_command_context_returns_none(self):
        self.assertIsNone(parse_command("the weather is nice today", OVERLAY_CTX))

    def test_empty_text_returns_none(self):
        self.assertIsNone(parse_command("", OVERLAY_CTX))
        self.assertIsNone(parse_command(None, OVERLAY_CTX))


class ParseCommandSwitchPersonaTests(unittest.TestCase):
    def test_switch_to_formal(self):
        intent = parse_command("switch to formal", OVERLAY_CTX)
        self.assertEqual(intent.action, "switch_persona")
        self.assertEqual(intent.target, "formal")

    def test_use_true_janitor(self):
        intent = parse_command("use true janitor", OVERLAY_CTX)
        self.assertEqual(intent.action, "switch_persona")
        self.assertEqual(intent.target, "true janitor")


class ParseCommandFuzzyMatchTests(unittest.TestCase):
    def test_near_miss_asr_still_resolves(self):
        # "send it" misheard as "sent it" — no exact phrase substring, still resolves via fuzzy match.
        intent = parse_command("sent it", OVERLAY_CTX)
        self.assertEqual(intent.action, "send")
        self.assertLess(intent.confidence, 1.0)

    def test_low_similarity_does_not_resolve(self):
        self.assertIsNone(parse_command("purple elephants dance slowly", OVERLAY_CTX))


# =============================================================================
# Wave 9 — utterance classification
# =============================================================================
#
# The existing parser above is UNCHANGED and every test above still applies;
# these cover the classification layer built on top of it. The load-bearing
# assertions are the ones about `unknown_command`: it must explain itself, offer
# the builder, and never be executable, no matter how command-shaped it sounded.

from voice_commands import (  # noqa: E402  (grouped with the Wave 9 tests on purpose)
    CATEGORIES,
    CATEGORY_BETTERFINGERS_CONTROL,
    CATEGORY_DIRECTED_DICTATION,
    CATEGORY_LAUNCHER_WORKFLOW,
    CATEGORY_ORDINARY_DICTATION,
    CATEGORY_UNKNOWN_COMMAND,
    UNKNOWN_COMMAND_EXPLANATION,
    classify_utterance,
    normalize_workflow_phrase,
)

PHRASES = {"open my studio": "studio_setup", "start streaming": "stream_setup"}


class ParserIsPreservedTests(unittest.TestCase):
    def test_the_conservative_parser_is_still_the_one_deciding_commands(self):
        # Same input, same answer, whether asked directly or through the
        # classifier: the classifier calls parse_command, it does not reimplement it.
        self.assertIsNone(parse_command("send it"))
        self.assertEqual(
            classify_utterance("send it").category, CATEGORY_ORDINARY_DICTATION,
        )
        self.assertEqual(
            classify_utterance("send it", OVERLAY_CTX).category,
            CATEGORY_BETTERFINGERS_CONTROL,
        )


class OrdinaryDictationTests(unittest.TestCase):
    def test_plain_prose_with_no_command_context_is_ordinary_dictation(self):
        result = classify_utterance("The invoice is attached and I will follow up on Monday.")
        self.assertEqual(result.category, CATEGORY_ORDINARY_DICTATION)
        self.assertFalse(result.executable)

    def test_a_command_phrase_inside_a_paragraph_is_still_ordinary_dictation(self):
        result = classify_utterance("I told him to send it to accounting by Friday")
        self.assertEqual(result.category, CATEGORY_ORDINARY_DICTATION)
        self.assertFalse(result.executable)

    def test_a_workflow_trigger_spoken_mid_paragraph_does_not_launch_anything(self):
        result = classify_utterance(
            "I was going to open my studio later this evening", workflow_phrases=PHRASES,
        )
        self.assertEqual(result.category, CATEGORY_ORDINARY_DICTATION)
        self.assertFalse(result.executable)

    def test_empty_input_is_ordinary_dictation_not_a_command(self):
        for text in ("", "   ", None):
            result = classify_utterance(text)
            self.assertEqual(result.category, CATEGORY_ORDINARY_DICTATION)
            self.assertFalse(result.executable)


class DirectedDictationTests(unittest.TestCase):
    def test_tell_someone_something_is_directed_dictation_and_carries_the_body(self):
        result = classify_utterance("Tell Sam that I am running about ten minutes late")
        self.assertEqual(result.category, CATEGORY_DIRECTED_DICTATION)
        self.assertEqual(result.target, "Sam")
        self.assertEqual(result.text, "I am running about ten minutes late")

    def test_directed_dictation_is_never_executable(self):
        for text in (
            "Tell Sam that I am late",
            "reply to Priya saying I will look tonight",
            "text Mom I landed",
        ):
            result = classify_utterance(text, OVERLAY_CTX)
            self.assertEqual(result.category, CATEGORY_DIRECTED_DICTATION, text)
            self.assertFalse(result.executable, text)


class ControlTests(unittest.TestCase):
    def test_a_resolved_command_in_a_clear_context_is_betterfingers_control(self):
        result = classify_utterance("make it shorter", OVERLAY_CTX)
        self.assertEqual(result.category, CATEGORY_BETTERFINGERS_CONTROL)
        self.assertTrue(result.executable)
        self.assertEqual(result.intent.action, "rewrite_shorter")

    def test_the_prefix_alone_is_a_clear_context(self):
        result = classify_utterance("BetterFingers, open settings")
        self.assertEqual(result.category, CATEGORY_BETTERFINGERS_CONTROL)
        self.assertTrue(result.executable)

    def test_emergency_stop_resolves_with_no_context_at_all(self):
        result = classify_utterance("emergency stop")
        self.assertEqual(result.category, CATEGORY_BETTERFINGERS_CONTROL)
        self.assertTrue(result.executable)
        self.assertEqual(result.intent.action, "emergency_stop")


class LauncherWorkflowTests(unittest.TestCase):
    def test_an_exact_trigger_phrase_in_a_clear_context_routes_to_the_workflow(self):
        result = classify_utterance("open my studio", CMD_MODE_CTX, PHRASES)
        self.assertEqual(result.category, CATEGORY_LAUNCHER_WORKFLOW)
        self.assertTrue(result.executable)
        self.assertEqual(result.workflow_id, "studio_setup")

    def test_punctuation_and_case_do_not_break_a_trigger(self):
        result = classify_utterance("BetterFingers, Open My Studio!", None, PHRASES)
        self.assertEqual(result.category, CATEGORY_LAUNCHER_WORKFLOW)
        self.assertEqual(result.workflow_id, "studio_setup")

    def test_a_near_miss_is_an_unknown_command_not_a_fuzzy_launch(self):
        result = classify_utterance("open my studios", CMD_MODE_CTX, PHRASES)
        self.assertEqual(result.category, CATEGORY_UNKNOWN_COMMAND)
        self.assertFalse(result.executable)

    def test_a_trigger_phrase_embedded_in_a_longer_command_does_not_launch(self):
        result = classify_utterance("maybe open my studio and then some", CMD_MODE_CTX, PHRASES)
        self.assertEqual(result.category, CATEGORY_UNKNOWN_COMMAND)
        self.assertFalse(result.executable)

    def test_a_workflow_the_caller_did_not_offer_cannot_be_reached(self):
        result = classify_utterance("start streaming", CMD_MODE_CTX, {})
        self.assertEqual(result.category, CATEGORY_UNKNOWN_COMMAND)
        self.assertFalse(result.executable)


class UnknownCommandTests(unittest.TestCase):
    UNKNOWNS = [
        "open blender",
        "launch my tax app",
        "start my streaming setup",
        "run the backup",
        "do the morning thing",
        "activate turbo mode",
    ]

    def test_an_unknown_command_can_never_execute(self):
        for text in self.UNKNOWNS:
            for context in (OVERLAY_CTX, WAKE_CTX, CMD_MODE_CTX, {"prefixed": True}):
                result = classify_utterance(text, context, PHRASES)
                self.assertEqual(result.category, CATEGORY_UNKNOWN_COMMAND, (text, context))
                self.assertFalse(result.executable, (text, context))
                self.assertEqual(result.workflow_id, "", (text, context))
                self.assertIsNone(result.intent, (text, context))

    def test_an_unknown_command_explains_itself_and_offers_the_builder(self):
        result = classify_utterance("open blender", CMD_MODE_CTX, PHRASES)
        self.assertTrue(result.offers_builder)
        self.assertIn("build one", result.explanation.lower())
        self.assertIn("approve", result.explanation.lower())

    def test_the_launch_shaped_explanation_still_refuses(self):
        launch = classify_utterance("launch obsidian", CMD_MODE_CTX, PHRASES)
        other = classify_utterance("activate turbo mode", CMD_MODE_CTX, PHRASES)
        self.assertNotEqual(launch.explanation, other.explanation)
        self.assertEqual(other.explanation, UNKNOWN_COMMAND_EXPLANATION)
        for result in (launch, other):
            self.assertFalse(result.executable)
            self.assertTrue(result.offers_builder)

    def test_no_explanation_ever_hands_the_user_a_command_line(self):
        # THE rule from the objective: no generated shell command is ever shown
        # as a solution. A refusal that suggests a terminal has just moved the
        # risk somewhere with no preview and no approval.
        forbidden = (
            "sudo", "bash", "powershell", "cmd.exe", "&&", "||", "|", ";",
            "$(", "`", "rm ", "xdg-open", "flatpak run", "terminal",
        )
        for text in self.UNKNOWNS:
            explanation = classify_utterance(text, CMD_MODE_CTX, PHRASES).explanation.lower()
            for token in forbidden:
                self.assertNotIn(token, explanation, (text, token))


class ClassificationContractTests(unittest.TestCase):
    def test_every_classification_uses_a_declared_category(self):
        samples = [
            ("", None), ("hello there", None), ("send it", OVERLAY_CTX),
            ("open my studio", CMD_MODE_CTX), ("tell Sam I am late", None),
            ("open blender", CMD_MODE_CTX), ("emergency stop", None),
        ]
        for text, context in samples:
            result = classify_utterance(text, context, PHRASES)
            self.assertIn(result.category, CATEGORIES, text)

    def test_only_control_and_workflow_categories_are_ever_executable(self):
        samples = [
            ("hello there", None), ("send it", OVERLAY_CTX),
            ("open my studio", CMD_MODE_CTX), ("tell Sam I am late", OVERLAY_CTX),
            ("open blender", CMD_MODE_CTX), ("emergency stop", None),
        ]
        for text, context in samples:
            result = classify_utterance(text, context, PHRASES)
            if result.executable:
                self.assertIn(
                    result.category,
                    (CATEGORY_BETTERFINGERS_CONTROL, CATEGORY_LAUNCHER_WORKFLOW),
                    text,
                )

    def test_phrase_normalisation_matches_the_schemas_own(self):
        from backend.domain.actions import normalize_trigger_phrase

        for phrase in ("Open My Studio!", "  start   streaming  ", "let's go"):
            self.assertEqual(
                normalize_workflow_phrase(phrase), normalize_trigger_phrase(phrase), phrase,
            )

    def test_the_classifier_inherits_parse_commands_switch_persona_over_trigger(self):
        """A KNOWN, PRE-EXISTING over-trigger, pinned here rather than papered over.

        ``_SWITCH_PERSONA_RE`` is a ``search``, not an anchored match, so inside
        a clear command context any sentence containing "use …" resolves to
        switch_persona with whatever followed. That is today's shipped
        behaviour of ``parse_command`` and Wave 9 deliberately does not change
        it: the classifier's contract is that it *calls* the conservative
        parser rather than reimplementing or second-guessing it, and quietly
        diverging here would mean two different answers to "is this a command"
        depending on which entry point a caller used.

        Reported upward as a finding. The fix belongs in ``parse_command``
        (anchor the pattern, or require the target to name a known persona),
        which is a change to behaviour every existing caller sees.
        """
        result = classify_utterance("launch the thing I use for taxes", OVERLAY_CTX, PHRASES)
        self.assertEqual(result.category, CATEGORY_BETTERFINGERS_CONTROL)
        self.assertEqual(result.intent.action, "switch_persona")
        # It cannot reach a launcher workflow, which is the Wave 9 boundary.
        self.assertEqual(result.workflow_id, "")

    def test_to_dict_carries_no_transcript(self):
        payload = classify_utterance("Tell Sam that I am late").to_dict()
        self.assertNotIn("text", payload)
        self.assertNotIn("intent", payload)


if __name__ == "__main__":
    unittest.main()
