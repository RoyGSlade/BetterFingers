import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import platform_paths


class PlatformPathsTests(unittest.TestCase):
    def test_linux_uses_xdg_dirs(self):
        with tempfile.TemporaryDirectory() as data_dir, tempfile.TemporaryDirectory() as config_dir:
            with patch("sys.platform", "linux"), patch.dict(
                os.environ,
                {
                    "XDG_DATA_HOME": data_dir,
                    "XDG_CONFIG_HOME": config_dir,
                },
                clear=False,
            ):
                self.assertEqual(platform_paths.get_app_data_dir(), Path(data_dir) / "BetterFingers")
                self.assertEqual(platform_paths.get_config_dir(), Path(config_dir) / "BetterFingers")

                dirs = platform_paths.ensure_app_dirs()
                self.assertTrue(Path(dirs["app_data_dir"]).is_dir())
                self.assertTrue(Path(dirs["config_dir"]).is_dir())

    def test_windows_uses_appdata(self):
        with tempfile.TemporaryDirectory() as appdata:
            with patch("sys.platform", "win32"), patch.dict(
                os.environ,
                {"APPDATA": appdata},
                clear=False,
            ):
                expected = Path(appdata) / "BetterFingers"
                self.assertEqual(platform_paths.get_app_data_dir(), expected)
                self.assertEqual(platform_paths.get_config_dir(), expected)

    def test_macos_uses_application_support(self):
        with tempfile.TemporaryDirectory() as home_dir:
            with patch("sys.platform", "darwin"), patch.object(Path, "home", return_value=Path(home_dir)):
                expected = Path(home_dir) / "Library" / "Application Support" / "BetterFingers"
                self.assertEqual(platform_paths.get_app_data_dir(), expected)
                self.assertEqual(platform_paths.get_config_dir(), expected)


if __name__ == "__main__":
    unittest.main()
