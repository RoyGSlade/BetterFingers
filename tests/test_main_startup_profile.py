import unittest
from unittest.mock import patch

from main import App


class MainStartupProfileTests(unittest.TestCase):
    @patch("main.get_last_active_profile", return_value="Squad")
    @patch("main.list_profiles", return_value=["Default", "Squad"])
    def test_resolve_startup_profile_uses_last_active_when_available(
        self,
        _list_profiles,
        _get_last_active_profile,
    ):
        self.assertEqual(App._resolve_startup_profile(), "Squad")

    @patch("main.get_last_active_profile", return_value="DeletedProfile")
    @patch("main.list_profiles", return_value=["Default", "Alpha"])
    def test_resolve_startup_profile_falls_back_when_missing(
        self,
        _list_profiles,
        _get_last_active_profile,
    ):
        self.assertEqual(App._resolve_startup_profile(), "Default")


if __name__ == "__main__":
    unittest.main()
