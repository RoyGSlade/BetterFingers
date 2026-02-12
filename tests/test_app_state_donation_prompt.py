import os
import tempfile
import unittest

import utils


class AppStateDonationPromptTests(unittest.TestCase):
    def test_register_launch_prompts_once_at_threshold(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                for _ in range(4):
                    self.assertFalse(utils.register_launch_and_should_show_donation(threshold=5))

                self.assertTrue(utils.register_launch_and_should_show_donation(threshold=5))
                state = utils.load_app_state()
                self.assertEqual(state.get("launch_count"), 5)
                self.assertTrue(bool(state.get("donation_prompt_shown")))

                self.assertFalse(utils.register_launch_and_should_show_donation(threshold=5))
                state = utils.load_app_state()
                self.assertEqual(state.get("launch_count"), 6)
                self.assertTrue(bool(state.get("donation_prompt_shown")))
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
