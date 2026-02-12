import unittest

from settings import SettingsWindow


class _ModalRecorder:
    def __init__(self):
        self.show_calls = []
        self.close_calls = []
        self._keys_by_dialog = {}

    def show(self, key, dialog, replace_active=True):
        self.show_calls.append((key, dialog, replace_active))
        self._keys_by_dialog[id(dialog)] = key
        try:
            dialog.open = True
        except Exception:
            pass

    def close(self, key=None):
        self.close_calls.append(key)
        return True

    def close_all(self):
        self.close_calls.append("__all__")

    def is_open(self, key):
        del key
        return False

    def get_key_for_dialog(self, dialog):
        return self._keys_by_dialog.get(id(dialog))


class SettingsModalWiringTests(unittest.TestCase):
    def _window(self):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._page = object()
        window._modal_manager = _ModalRecorder()
        return window

    def test_help_modal_uses_keyed_manager_calls(self):
        window = self._window()
        window._help_dialog = object()

        window._show_help_dialog("master_hotkey")

        self.assertIn(window.MODAL_KEY_HELP, window._modal_manager.close_calls)
        shown_keys = [call[0] for call in window._modal_manager.show_calls]
        self.assertIn(window.MODAL_KEY_HELP, shown_keys)

    def test_support_modal_uses_keyed_manager_calls(self):
        window = self._window()
        window._support_dialog = object()

        window._open_support_panel()

        self.assertIn(window.MODAL_KEY_SUPPORT, window._modal_manager.close_calls)
        shown_keys = [call[0] for call in window._modal_manager.show_calls]
        self.assertIn(window.MODAL_KEY_SUPPORT, shown_keys)

    def test_profile_new_modal_uses_key(self):
        window = self._window()

        window._on_new_profile_clicked(None)

        shown_keys = [call[0] for call in window._modal_manager.show_calls]
        self.assertIn(window.MODAL_KEY_PROFILE_NEW, shown_keys)

    def test_profile_delete_modal_uses_key(self):
        window = self._window()
        window.current_profile = "Custom"

        window._on_delete_profile_clicked(None)

        shown_keys = [call[0] for call in window._modal_manager.show_calls]
        self.assertIn(window.MODAL_KEY_PROFILE_DELETE, shown_keys)

    def test_tour_intro_modal_uses_keyed_close_and_show(self):
        window = self._window()
        window._tour_intro_dialog = object()

        window._show_tour_intro_dialog()

        self.assertIn(window.MODAL_KEY_TOUR_INTRO, window._modal_manager.close_calls)
        shown_keys = [call[0] for call in window._modal_manager.show_calls]
        self.assertIn(window.MODAL_KEY_TOUR_INTRO, shown_keys)

    def test_tour_close_uses_keyed_close(self):
        window = self._window()
        window._tour_intro_dialog = object()

        window._tour_close(None)

        self.assertIn(window.MODAL_KEY_TOUR_INTRO, window._modal_manager.close_calls)


if __name__ == "__main__":
    unittest.main()
