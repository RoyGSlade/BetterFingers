import os
import tempfile
import unittest
from unittest.mock import patch

import server


class DownloadsDirTests(unittest.TestCase):
    def test_prefers_downloads_when_present(self):
        with tempfile.TemporaryDirectory() as home:
            downloads = os.path.join(home, "Downloads")
            os.makedirs(downloads)
            with patch("os.path.expanduser", return_value=home), patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("XDG_DOWNLOAD_DIR", None)
                self.assertEqual(server._get_downloads_dir(), downloads)

    def test_falls_back_to_home_without_downloads(self):
        with tempfile.TemporaryDirectory() as home:
            with patch("os.path.expanduser", return_value=home), patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("XDG_DOWNLOAD_DIR", None)
                self.assertEqual(server._get_downloads_dir(), home)

    def test_honors_xdg_download_dir(self):
        with tempfile.TemporaryDirectory() as home:
            custom = os.path.join(home, "MyDownloads")
            os.makedirs(custom)

            def _expanduser(path):
                return home if path == "~" else path

            with patch("os.path.expanduser", side_effect=_expanduser), patch.dict(
                os.environ, {"XDG_DOWNLOAD_DIR": custom}, clear=False
            ):
                self.assertEqual(server._get_downloads_dir(), custom)

    def test_never_uses_desktop(self):
        with tempfile.TemporaryDirectory() as home:
            os.makedirs(os.path.join(home, "Desktop"))
            with patch("os.path.expanduser", return_value=home), patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("XDG_DOWNLOAD_DIR", None)
                result = server._get_downloads_dir()
                self.assertNotIn("Desktop", result)


if __name__ == "__main__":
    unittest.main()
