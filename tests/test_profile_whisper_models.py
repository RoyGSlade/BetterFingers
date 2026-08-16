import os
import tempfile
import unittest
from unittest.mock import patch

import utils


class ProfileWhisperModelTests(unittest.TestCase):
    def test_distil_whisper_selections_survive_profile_sanitization(self):
        defaults = utils._profile_defaults()

        for model_size in ("distil-medium.en", "distil-large-v3"):
            with self.subTest(model_size=model_size):
                sanitized = utils._sanitize_profile_values(
                    {"model_size": model_size}, defaults
                )
                self.assertEqual(sanitized["model_size"], model_size)

    def test_distil_whisper_selection_round_trips_through_profile_store(self):
        with tempfile.TemporaryDirectory(prefix="betterfingers-distil-profile-") as root:
            with patch("utils.get_profiles_dir", return_value=root), patch(
                "utils._app_state_path", return_value=os.path.join(root, "app_state.yaml")
            ):
                utils.save_profile("Default", {"model_size": "distil-medium.en"})
                loaded = utils.load_profile("Default")

        self.assertEqual(loaded["model_size"], "distil-medium.en")


if __name__ == "__main__":
    unittest.main()
