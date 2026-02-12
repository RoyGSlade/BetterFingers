import unittest

from settings import SettingsWindow


class _FakeWindow:
    def __init__(self):
        self.visible = False
        self.focused = False
        self.minimized = True

    async def to_front(self):
        return None


class _FakePage:
    def __init__(self):
        self.window = _FakeWindow()
        self.update_calls = 0
        self.run_task_calls = []

    def update(self):
        self.update_calls += 1

    def run_task(self, handler, *args):
        self.run_task_calls.append((handler, args))


class SettingsWindowFocusFrontTests(unittest.TestCase):
    def test_show_brings_existing_window_to_front_via_run_task(self):
        page = _FakePage()
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        window._is_open = True
        window._page = page
        window._window_thread = None

        window.show()

        self.assertGreaterEqual(page.update_calls, 1)
        self.assertTrue(page.window.visible)
        self.assertTrue(page.window.focused)
        self.assertFalse(page.window.minimized)
        self.assertEqual(len(page.run_task_calls), 1)
        self.assertEqual(page.run_task_calls[0][0], page.window.to_front)


if __name__ == "__main__":
    unittest.main()
