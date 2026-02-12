import os
import tempfile
import unittest

import utils


class AppStateLastProfileTests(unittest.TestCase):
    def test_last_active_profile_round_trip_when_profile_exists(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                default_cfg = utils.load_profile("Default")
                utils.save_profile("Squad", default_cfg)
                utils.set_last_active_profile("Squad")

                self.assertEqual(utils.get_last_active_profile(default="Default"), "Squad")
                state = utils.load_app_state()
                self.assertEqual(state.get("last_active_profile"), "Squad")
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata

    def test_last_active_profile_falls_back_to_default_when_missing(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                utils.set_last_active_profile("MissingProfile")
                self.assertEqual(utils.get_last_active_profile(default="Default"), "Default")
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
