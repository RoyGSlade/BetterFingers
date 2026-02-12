"""Tests for user_profile_manager.py — sanitisation and APPDATA fallback."""
import os
import unittest
from unittest.mock import patch

from user_profile_manager import _sanitize_filename, UserProfileManager


class SanitizeFilenameTests(unittest.TestCase):
    def test_strips_special_characters(self):
        self.assertEqual(_sanitize_filename("My:Profile/Name?"), "MyProfileName")

    def test_keeps_hyphens_and_underscores(self):
        self.assertEqual(_sanitize_filename("my-profile_1"), "my-profile_1")

    def test_empty_input_returns_default(self):
        self.assertEqual(_sanitize_filename(""), "Default")

    def test_none_input_returns_default(self):
        self.assertEqual(_sanitize_filename(None), "Default")

    def test_only_special_chars_returns_default(self):
        self.assertEqual(_sanitize_filename("@#$%^&*"), "Default")

    def test_preserves_spaces(self):
        self.assertEqual(_sanitize_filename("My Profile"), "My Profile")


class AppdataFallbackTests(unittest.TestCase):
    @patch.dict(os.environ, {}, clear=True)
    def test_falls_back_to_home_when_appdata_missing(self):
        # Remove APPDATA from env entirely
        os.environ.pop("APPDATA", None)
        mgr = UserProfileManager()
        home = os.path.expanduser("~")
        self.assertTrue(
            mgr.profile_path.startswith(home),
            f"Expected path to start with {home!r}, got {mgr.profile_path!r}",
        )


if __name__ == "__main__":
    unittest.main()
