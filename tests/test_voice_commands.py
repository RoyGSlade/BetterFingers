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


if __name__ == "__main__":
    unittest.main()
