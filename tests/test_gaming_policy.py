"""Gaming policy constants (Wave 7).

The numbers are asserted literally on purpose. They are the release plan's
values, not tuning knobs someone can drift by a factor of ten in a refactor
without anyone noticing -- and every one of them is a promise about what happens
while a game is running.
"""

import unittest

from backend.domain import gaming_policy as gp
from backend.stores.app_profiles import builtin_profiles


class ConstantsTests(unittest.TestCase):
    def test_the_declared_values(self):
        self.assertEqual(gp.MAX_COMPLETION_TOKENS, 50)
        self.assertEqual(gp.MAX_TTS_SENTENCES, 2)
        self.assertFalse(gp.QUEUE_TTS)
        self.assertFalse(gp.AUTO_SUBMIT)
        self.assertTrue(gp.REVIEW_ONLY)
        self.assertTrue(gp.CLIPBOARD_FALLBACK)
        self.assertTrue(gp.MINIMAL_OVERLAY)

    def test_the_policy_dict_matches_the_constants(self):
        self.assertEqual(gp.GAMING_POLICY["max_completion_tokens"], gp.MAX_COMPLETION_TOKENS)
        self.assertEqual(gp.GAMING_POLICY["max_tts_sentences"], gp.MAX_TTS_SENTENCES)
        self.assertEqual(gp.GAMING_POLICY["queue_tts"], gp.QUEUE_TTS)
        self.assertEqual(gp.GAMING_POLICY["auto_submit"], gp.AUTO_SUBMIT)

    def test_the_policy_names_no_recipient_concept(self):
        for key in gp.GAMING_POLICY:
            for term in ("recipient", "contact", "conversation", "intent"):
                self.assertNotIn(term, key)


class ProfileOptInTests(unittest.TestCase):
    def test_the_three_game_profiles_opt_in_and_the_rest_do_not(self):
        by_id = {p["id"]: p for p in builtin_profiles()}
        for pid in ("game_generic", "rocket_league", "world_of_warcraft"):
            self.assertTrue(gp.is_gaming_profile(by_id[pid]), pid)
        for pid in ("default", "discord", "email", "writing_app"):
            self.assertFalse(gp.is_gaming_profile(by_id[pid]), pid)

    def test_junk_is_not_a_gaming_profile(self):
        self.assertFalse(gp.is_gaming_profile(None))
        self.assertFalse(gp.is_gaming_profile({}))
        self.assertFalse(gp.is_gaming_profile("rocket_league"))

    def test_policy_for_always_returns_the_full_shape(self):
        by_id = {p["id"]: p for p in builtin_profiles()}
        for pid in ("default", "rocket_league"):
            policy = gp.policy_for(by_id[pid])
            self.assertEqual(set(policy), set(gp.GAMING_POLICY) | {"active"})


class ClampTests(unittest.TestCase):
    def test_it_is_a_ceiling_not_a_floor(self):
        self.assertEqual(gp.clamp_completion_tokens(4096), 50)
        self.assertEqual(gp.clamp_completion_tokens(20), 20)

    def test_inactive_leaves_the_request_alone(self):
        self.assertEqual(gp.clamp_completion_tokens(4096, active=False), 4096)

    def test_junk_falls_back_to_the_cap_when_active(self):
        self.assertEqual(gp.clamp_completion_tokens(None), 50)
        self.assertEqual(gp.clamp_completion_tokens("lots"), 50)
        self.assertEqual(gp.clamp_completion_tokens(0), 50)


class SpokenTextTests(unittest.TestCase):
    def test_at_most_two_sentences_survive(self):
        text = gp.trim_spoken_text("One. Two. Three. Four.")
        self.assertEqual(text, "One. Two.")

    def test_a_long_sentence_is_cut_at_a_word_boundary(self):
        long = "word " * 60
        text = gp.trim_spoken_text(long)
        self.assertLessEqual(len(text), gp.MAX_TTS_SENTENCE_CHARS)
        self.assertFalse(text.endswith("wor"), "must not cut mid-word")

    def test_inactive_leaves_the_text_alone(self):
        original = "One. Two. Three."
        self.assertEqual(gp.trim_spoken_text(original, active=False), original)

    def test_empty_stays_empty(self):
        self.assertEqual(gp.trim_spoken_text(""), "")
        self.assertEqual(gp.trim_spoken_text(None), "")


class SendActionTests(unittest.TestCase):
    def test_typing_becomes_the_clipboard_fallback(self):
        for action in ("type_text", "type", "paste", "auto_send"):
            self.assertEqual(gp.resolve_send_action(action), "copy_only", action)

    def test_non_typing_actions_are_left_alone(self):
        self.assertEqual(gp.resolve_send_action("copy_only"), "copy_only")
        self.assertEqual(gp.resolve_send_action("review"), "review")

    def test_inactive_leaves_the_action_alone(self):
        self.assertEqual(gp.resolve_send_action("type_text", active=False), "type_text")

    def test_nothing_defaults_to_the_clipboard(self):
        self.assertEqual(gp.resolve_send_action(""), "copy_only")
        self.assertEqual(gp.resolve_send_action(None), "copy_only")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
