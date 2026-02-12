import unittest

from settings import SettingsWindow


class _ValueControl:
    def __init__(self, value=""):
        self.value = value


class _WindowStub:
    def __init__(self):
        self.destroy_calls = 0
        self.close_calls = 0
        self.prevent_close = False
        self.on_event = None

    def destroy(self):
        self.destroy_calls += 1

    def close(self):
        self.close_calls += 1


class _PageStub:
    def __init__(self):
        self.window = _WindowStub()

    def update(self):
        return None


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


class SettingsDirtyCloseTests(unittest.TestCase):
    def _window(self):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._page = _PageStub()
        window._modal_manager = _ModalRecorder()
        window._controls = {"example": _ValueControl("value")}
        return window

    def test_dirty_snapshot_detects_changes(self):
        window = self._window()
        window._mark_settings_clean()
        self.assertFalse(window._has_unsaved_changes())

        window._controls["example"].value = "updated"
        self.assertTrue(window._has_unsaved_changes())

    def test_clean_close_destroys_window_without_modal(self):
        window = self._window()
        window._mark_settings_clean()
        window._on_close_clicked()

        self.assertEqual(window._page.window.close_calls, 1)
        self.assertEqual(window._page.window.destroy_calls, 0)
        self.assertEqual(len(window._modal_manager.show_calls), 0)

    def test_dirty_close_shows_confirmation_modal(self):
        window = self._window()
        window._mark_settings_clean()
        window._controls["example"].value = "dirty"

        window._on_close_clicked()

        self.assertEqual(window._page.window.destroy_calls, 0)
        self.assertEqual(len(window._modal_manager.show_calls), 1)
        self.assertEqual(window._modal_manager.show_calls[0][0], window.MODAL_KEY_UNSAVED_CHANGES)

    def test_window_event_close_name_invokes_close_handler(self):
        class _Event:
            data = ""
            name = "window_close"

        window = self._window()
        window._mark_settings_clean()

        window._on_window_event(_Event())

        self.assertEqual(window._page.window.close_calls, 1)

    def test_window_event_close_request_token_invokes_close_handler(self):
        class _Event:
            data = "close_request"
            name = ""

        window = self._window()
        window._mark_settings_clean()

        window._on_window_event(_Event())

        self.assertEqual(window._page.window.close_calls, 1)

    def test_shutdown_force_close_bypasses_unsaved_dialog(self):
        window = self._window()
        window._mark_settings_clean()
        window._controls["example"].value = "dirty"

        window.force_close_for_shutdown()

        self.assertTrue(window._shutdown_requested)
        self.assertEqual(window._page.window.close_calls, 1)
        self.assertEqual(len(window._modal_manager.show_calls), 0)

    def test_shutdown_flag_skips_unsaved_prompt_on_close_click(self):
        window = self._window()
        window._mark_settings_clean()
        window._controls["example"].value = "dirty"
        window._shutdown_requested = True

        window._on_close_clicked()

        self.assertEqual(window._page.window.close_calls, 1)
        self.assertEqual(len(window._modal_manager.show_calls), 0)


if __name__ == "__main__":
    unittest.main()
