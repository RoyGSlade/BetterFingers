import time
import unittest
from unittest.mock import Mock

from settings import SettingsWindow


class SettingsModelCatalogTests(unittest.TestCase):
    def _window(self):
        status_callback = Mock(
            return_value={
                "ok": True,
                "models": [
                    {"model_size": "base.en", "installed": True, "size_bytes": 1000},
                    {"model_size": "small.en", "installed": False, "size_bytes": 0},
                ],
                "summary": "Installed: base.en",
            }
        )
        download_callback = Mock(return_value={"ok": True, "message": "downloaded"})
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
            get_whisper_download_status_callback=status_callback,
            on_download_whisper_model_callback=download_callback,
        )
        window._page = object()
        window._build_controls()
        return window, download_callback

    def test_model_catalog_renders_rows(self):
        window, _download = self._window()
        window._refresh_model_catalog()
        rows = window._controls["model_catalog_rows"].controls
        self.assertGreater(len(rows), 0)

    def test_whisper_download_action_invokes_callback(self):
        window, download_callback = self._window()
        window._on_download_whisper_model_action("small.en")

        # Background worker is async; allow a short moment.
        deadline = time.time() + 0.5
        while time.time() < deadline and not download_callback.called:
            time.sleep(0.02)
        self.assertTrue(download_callback.called)


if __name__ == "__main__":
    unittest.main()
