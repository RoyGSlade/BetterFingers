import unittest
from unittest.mock import patch

from settings import SettingsWindow


class _ModalRecorder:
    def __init__(self):
        self.show_calls = []
        self.close_calls = []
        self.close_all_calls = 0

    def show(self, key, dialog, replace_active=True):
        self.show_calls.append((key, dialog, replace_active))
        try:
            dialog.open = True
        except Exception:
            pass

    def close(self, key=None):
        self.close_calls.append(key)
        return True

    def close_all(self):
        self.close_all_calls += 1

    def is_open(self, key):
        del key
        return False

    def get_key_for_dialog(self, dialog):
        del dialog
        return None


class _PageStub:
    def __init__(self):
        self.snack_bar = None

    def update(self):
        return None


class SettingsPersonaActionTests(unittest.TestCase):
    def _window(self):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._page = _PageStub()
        window._modal_manager = _ModalRecorder()
        window._build_controls()
        return window

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_true_janitor_disables_edit_and_delete_buttons(self, _mock_names):
        window = self._window()
        window._refresh_persona_options()
        window._controls["persona"].value = "True Janitor"

        window._on_persona_selection_changed(None)

        self.assertTrue(window._controls["persona_edit_button"].disabled)
        self.assertTrue(window._controls["persona_delete_button"].disabled)

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_non_janitor_enables_edit_and_delete_buttons(self, _mock_names):
        window = self._window()
        window._refresh_persona_options()
        window._controls["persona"].value = "Formal"

        window._on_persona_selection_changed(None)

        self.assertFalse(window._controls["persona_edit_button"].disabled)
        self.assertFalse(window._controls["persona_delete_button"].disabled)

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    def test_edit_handler_blocks_true_janitor(self, _mock_names):
        window = self._window()
        window._refresh_persona_options()
        window._controls["persona"].value = "True Janitor"

        toast_messages = []
        window._toast = lambda message: toast_messages.append(str(message))
        opened = {"count": 0}
        window._open_persona_editor = lambda *args, **kwargs: opened.__setitem__("count", opened["count"] + 1)

        window._on_edit_persona_clicked(None)

        self.assertEqual(opened["count"], 0)
        self.assertTrue(any("cannot be edited" in message.lower() for message in toast_messages))

    @patch("settings_controls_mixin.get_fast_lane_preset_names", return_value=["True Janitor", "Formal"])
    @patch("settings_controls_mixin.delete_persona", return_value=(True, "Deleted persona 'Formal'."))
    def test_delete_confirm_closes_modal_and_updates_selection(self, _mock_delete, _mock_names):
        window = self._window()
        window._refresh_persona_options()
        window._controls["persona"].value = "Formal"

        window._on_delete_persona_clicked(None)

        self.assertEqual(len(window._modal_manager.show_calls), 1)
        key, dialog, _replace = window._modal_manager.show_calls[0]
        self.assertEqual(key, "persona_delete")
        delete_button = dialog.actions[-1]
        delete_button.on_click(None)

        _mock_delete.assert_called_once_with("Formal", allow_builtin=True)
        self.assertIn("persona_delete", window._modal_manager.close_calls)

    @patch("settings_controls_mixin.upsert_persona", return_value=(True, "Saved persona 'Custom Persona'."))
    @patch("settings_controls_mixin.get_persona_prompt", return_value="")
    def test_create_save_closes_modal(self, _mock_prompt, _mock_upsert):
        window = self._window()
        window._open_persona_editor(mode="create")

        self.assertEqual(len(window._modal_manager.show_calls), 1)
        key, dialog, _replace = window._modal_manager.show_calls[0]
        self.assertEqual(key, "persona_editor")

        content_column = dialog.content.content
        name_input = content_column.controls[0]
        name_input.value = "Custom Persona"

        save_button = dialog.actions[-1]
        save_button.on_click(None)

        self.assertTrue(_mock_upsert.called)
        self.assertIn("persona_editor", window._modal_manager.close_calls)


if __name__ == "__main__":
    unittest.main()
