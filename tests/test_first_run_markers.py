import os
import tempfile
import unittest

import utils
from guided_tour import (
    has_completed_guided_tour,
    mark_guided_tour_complete,
    reset_guided_tour_marker,
)


class FirstRunMarkerTests(unittest.TestCase):
    def test_first_run_marker_is_one_time(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                self.assertTrue(utils.check_first_run())
                self.assertFalse(utils.check_first_run())
                marker_path = os.path.join(utils.get_user_data_path(), ".first_run_complete")
                self.assertTrue(os.path.exists(marker_path))
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata

    def test_guided_tour_marker_round_trip(self):
        with tempfile.TemporaryDirectory() as tmp:
            original_appdata = os.environ.get("APPDATA")
            os.environ["APPDATA"] = tmp
            try:
                reset_guided_tour_marker()
                self.assertFalse(has_completed_guided_tour())
                mark_guided_tour_complete()
                self.assertTrue(has_completed_guided_tour())
                reset_guided_tour_marker()
                self.assertFalse(has_completed_guided_tour())
            finally:
                if original_appdata is None:
                    os.environ.pop("APPDATA", None)
                else:
                    os.environ["APPDATA"] = original_appdata


if __name__ == "__main__":
    unittest.main()
