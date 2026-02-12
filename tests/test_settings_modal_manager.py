import unittest
from types import SimpleNamespace

from settings_modal_manager import SettingsModalManager


class _DummyDialog:
    def __init__(self, name="dialog"):
        self.name = name
        self.open = False
        self.on_dismiss = None
        self.updated = 0

    def update(self):
        self.updated += 1


class _ShowPopPage:
    def __init__(self):
        self.stack = []
        self.pop_calls = 0
        self.update_calls = 0
        self.overlay = []

    def show_dialog(self, dialog):
        dialog.open = True
        self.stack.append(dialog)

    def pop_dialog(self):
        if not self.stack:
            return None
        self.pop_calls += 1
        dialog = self.stack.pop()
        dialog.open = False
        if callable(dialog.on_dismiss):
            dialog.on_dismiss(SimpleNamespace(data=None))
        return dialog

    def update(self):
        self.update_calls += 1


class _OpenClosePage:
    def __init__(self):
        self.open_calls = 0
        self.close_calls = 0
        self.update_calls = 0
        self.overlay = []

    def open(self, dialog):
        self.open_calls += 1
        dialog.open = True

    def close(self, dialog):
        self.close_calls += 1
        dialog.open = False
        if callable(dialog.on_dismiss):
            dialog.on_dismiss(SimpleNamespace(data=None))

    def update(self):
        self.update_calls += 1


class _OverlayOnlyPage:
    def __init__(self):
        self.overlay = []
        self.update_calls = 0

    def update(self):
        self.update_calls += 1


class SettingsModalManagerTests(unittest.TestCase):
    def test_show_and_close_with_show_dialog_backend(self):
        page = _ShowPopPage()
        manager = SettingsModalManager(lambda: page)
        dialog = _DummyDialog("help")

        manager.show("help", dialog)
        self.assertTrue(dialog.open)
        self.assertTrue(manager.is_open("help"))

        closed = manager.close("help")
        self.assertTrue(closed)
        self.assertFalse(manager.is_open("help"))
        self.assertEqual(page.pop_calls, 1)

    def test_single_active_replace_closes_previous(self):
        page = _ShowPopPage()
        manager = SettingsModalManager(lambda: page)
        first = _DummyDialog("first")
        second = _DummyDialog("second")

        manager.show("help", first)
        manager.show("support", second, replace_active=True)

        self.assertFalse(manager.is_open("help"))
        self.assertTrue(manager.is_open("support"))
        self.assertEqual(page.pop_calls, 1)

    def test_on_dismiss_untracks_and_calls_original_handler(self):
        page = _ShowPopPage()
        manager = SettingsModalManager(lambda: page)
        dialog = _DummyDialog("help")
        hits = {"count": 0}

        def _original(_event):
            hits["count"] += 1

        dialog.on_dismiss = _original
        manager.show("help", dialog)

        self.assertTrue(manager.is_open("help"))
        dialog.open = False
        dialog.on_dismiss(SimpleNamespace(data=None))

        self.assertFalse(manager.is_open("help"))
        self.assertEqual(hits["count"], 1)

    def test_close_unknown_key_is_safe(self):
        page = _ShowPopPage()
        manager = SettingsModalManager(lambda: page)

        self.assertFalse(manager.close("missing"))

    def test_open_close_backend_supported(self):
        page = _OpenClosePage()
        manager = SettingsModalManager(lambda: page)
        dialog = _DummyDialog("support")

        manager.show("support", dialog)
        self.assertEqual(page.open_calls, 1)
        self.assertTrue(manager.is_open("support"))

        manager.close("support")
        self.assertEqual(page.close_calls, 1)
        self.assertFalse(manager.is_open("support"))

    def test_overlay_fallback_supported(self):
        page = _OverlayOnlyPage()
        manager = SettingsModalManager(lambda: page)
        dialog = _DummyDialog("fallback")

        manager.show("fallback", dialog)
        self.assertTrue(dialog.open)
        self.assertIn(dialog, page.overlay)

        manager.close("fallback")
        self.assertFalse(dialog.open)
        self.assertNotIn(dialog, page.overlay)


if __name__ == "__main__":
    unittest.main()
