import os
import tempfile
import unittest

from guided_tour import TAB_KEY_TO_INDEX, build_legacy_tutorial_script, load_guided_tour_steps


class GuidedTourTests(unittest.TestCase):
    def test_structured_steps_load_without_script(self):
        with tempfile.TemporaryDirectory() as tmp:
            missing_script = os.path.join(tmp, "does_not_exist.txt")
            steps = load_guided_tour_steps(script_path=missing_script)
            self.assertGreaterEqual(len(steps), 10)
            titles = [s.title for s in steps]
            self.assertIn("Core Controls", titles)
            self.assertIn("Review TTS", titles)
            self.assertIn("You Are Ready", titles)
            for step in steps:
                self.assertIn(step.tab_key, TAB_KEY_TO_INDEX)

    def test_script_enrichment_and_f9_guidance(self):
        with tempfile.TemporaryDirectory() as tmp:
            script_path = os.path.join(tmp, "Tutorial_Script.txt")
            with open(script_path, "w", encoding="utf-8") as handle:
                handle.write(
                    'Introduction\n'
                    '"Custom welcome for testing."\n\n'
                    'Master Hotkey\n'
                    '"Pick a key you can press quickly."\n\n'
                    'Review TTS Voice\n'
                    '"Use Ctrl + Shift + Space to hear selected text."\n'
                )

            steps = load_guided_tour_steps(script_path=script_path)
            welcome_step = next((s for s in steps if s.title == "Welcome to Better Fingers"), None)
            self.assertIsNotNone(welcome_step)
            self.assertIn("custom welcome", welcome_step.narration.lower())

            review_step = next((s for s in steps if s.title == "Review TTS"), None)
            self.assertIsNotNone(review_step)
            self.assertIn("ctrl + shift + space", review_step.narration.lower())
            self.assertIn("f9", review_step.narration.lower())

    def test_legacy_script_includes_action_hint(self):
        legacy = build_legacy_tutorial_script()
        self.assertGreater(len(legacy), 0)
        self.assertTrue(any("Try this:" in entry.get("msg", "") for entry in legacy))


if __name__ == "__main__":
    unittest.main()
