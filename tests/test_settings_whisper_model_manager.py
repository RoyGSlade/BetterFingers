import unittest
from unittest.mock import Mock

from settings import SettingsWindow


class _ModalRecorder:
    def __init__(self):
        self.show_calls = []
        self.close_calls = []

    def show(self, key, dialog, replace_active=True):
        self.show_calls.append((key, dialog, replace_active))

    def close(self, key=None):
        self.close_calls.append(key)
        return True

    def close_all(self):
        self.close_calls.append("__all__")

    def is_open(self, key):
        del key
        return False

    def get_key_for_dialog(self, dialog):
        del dialog
        return None


class SettingsWhisperModelManagerTests(unittest.TestCase):
    def _window(self, status_callback=None, test_callback=None, uninstall_callback=None):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
            get_whisper_download_status_callback=status_callback,
            on_test_whisper_model_callback=test_callback,
            on_uninstall_whisper_model_callback=uninstall_callback,
        )
        window._page = object()
        window._modal_manager = _ModalRecorder()
        window._build_controls()
        return window

    def test_downloaded_model_summary_refreshes_from_callback(self):
        status_callback = Mock(
            return_value={
                "ok": True,
                "models": [
                    {"model_size": "small.en", "installed": True, "size_bytes": 123},
                    {"model_size": "base.en", "installed": False, "size_bytes": 0},
                ],
                "summary": "Installed: small.en",
            }
        )
        window = self._window(status_callback=status_callback)

        window._refresh_whisper_download_status()

        self.assertIn("Installed: small.en", window._controls["whisper_downloaded_summary"].value)
        self.assertEqual(window._controls["whisper_download_model"].value, "small.en")

    def test_test_selected_model_invokes_runtime_callback(self):
        test_callback = Mock(return_value={"ok": True, "message": "Whisper test ok."})
        window = self._window(
            status_callback=lambda: {"ok": True, "models": [], "summary": ""},
            test_callback=test_callback,
        )
        window._controls["whisper_download_model"].value = "medium.en"

        window._on_test_whisper_model(None)

        test_callback.assert_called_once_with("medium.en")
        self.assertEqual(window._controls["whisper_download_status"].value, "Whisper test ok.")

    def test_uninstall_selected_model_routes_through_confirmation_modal(self):
        uninstall_callback = Mock(return_value={"ok": True, "message": "Removed Whisper cache."})
        window = self._window(
            status_callback=lambda: {"ok": True, "models": [], "summary": ""},
            uninstall_callback=uninstall_callback,
        )
        window._controls["whisper_download_model"].value = "small.en"

        window._on_uninstall_whisper_model_clicked(None)

        self.assertEqual(len(window._modal_manager.show_calls), 1)
        key, dialog, _replace = window._modal_manager.show_calls[0]
        self.assertEqual(key, window.MODAL_KEY_WHISPER_UNINSTALL)

        uninstall_button = dialog.actions[-1]
        uninstall_button.on_click(None)

        uninstall_callback.assert_called_once_with("small.en")
        self.assertEqual(window._controls["whisper_download_status"].value, "Removed Whisper cache.")


if __name__ == "__main__":
    unittest.main()
