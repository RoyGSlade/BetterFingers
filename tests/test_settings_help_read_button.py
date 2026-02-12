import unittest
from unittest.mock import Mock

from settings import SettingsWindow


class _ModalRecorder:
    def __init__(self):
        self.show_calls = []

    def show(self, key, dialog, replace_active=True):
        self.show_calls.append((key, dialog, replace_active))

    def close(self, key=None):
        del key
        return True

    def close_all(self):
        return None

    def is_open(self, key):
        del key
        return False

    def get_key_for_dialog(self, dialog):
        del dialog
        return None


class SettingsHelpReadButtonTests(unittest.TestCase):
    def test_help_dialog_does_not_autoplay_and_read_aloud_button_invokes_tts(self):
        tts_preview = Mock(return_value={"ok": True})
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
            on_tts_preview_callback=tts_preview,
        )
        window._page = object()
        window._modal_manager = _ModalRecorder()

        window._show_help_dialog("master_hotkey")

        self.assertEqual(len(window._modal_manager.show_calls), 1)
        tts_preview.assert_not_called()

        dialog = window._modal_manager.show_calls[0][1]
        read_button = dialog.actions[0]
        read_button.on_click(None)

        tts_preview.assert_called_once()


if __name__ == "__main__":
    unittest.main()
