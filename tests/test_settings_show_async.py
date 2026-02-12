import threading
import time
import unittest
import signal
from unittest.mock import patch

import pytest

from settings import SettingsWindow

pytestmark = pytest.mark.smoke


class SettingsShowAsyncTests(unittest.TestCase):
    def test_show_runs_flet_in_background_thread(self):
        gate = threading.Event()
        callbacks = {"show": 0, "hide": 0}

        def _fake_ft_app(*args, **kwargs):
            del args, kwargs
            gate.wait(timeout=1.0)

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
            on_show_callback=lambda: callbacks.__setitem__("show", callbacks["show"] + 1),
            on_hide_callback=lambda: callbacks.__setitem__("hide", callbacks["hide"] + 1),
        )

        with patch("settings.ft.app", side_effect=_fake_ft_app):
            started = time.time()
            window.show()
            elapsed = time.time() - started
            self.assertLess(elapsed, 0.2, "show() should return immediately, not block on ft.app")
            self.assertTrue(window._is_open)
            self.assertIsNotNone(window._window_thread)
            self.assertTrue(window._window_thread.is_alive())
            self.assertEqual(callbacks["show"], 1)

            # Re-entrancy while open should not spawn another worker thread.
            first_thread = window._window_thread
            window.show()
            self.assertIs(window._window_thread, first_thread)

            gate.set()
            first_thread.join(timeout=1.2)

        self.assertFalse(window._is_open)
        self.assertIsNone(window._window_thread)
        self.assertEqual(callbacks["hide"], 1)

    def test_show_patches_signal_registration_in_worker_thread(self):
        callbacks = {"hide": 0}
        original_signal = signal.signal
        gate = threading.Event()

        def _fake_ft_app(*args, **kwargs):
            del args, kwargs
            # In a non-main thread, this normally raises ValueError.
            signal.signal(signal.SIGINT, lambda *_: None)
            gate.wait(timeout=1.0)

        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
            on_hide_callback=lambda: callbacks.__setitem__("hide", callbacks["hide"] + 1),
        )

        with patch("settings.ft.app", side_effect=_fake_ft_app):
            window.show()
            worker = window._window_thread
            self.assertIsNotNone(worker)
            gate.set()
            worker.join(timeout=1.2)

        self.assertFalse(window._is_open)
        self.assertEqual(callbacks["hide"], 1)
        self.assertIs(signal.signal, original_signal)

    def test_ft_app_failure_is_non_fatal(self):
        window = SettingsWindow(
            root=None,
            hotkey_manager=None,
            on_save_callback=lambda: None,
        )
        with patch("settings.ft.app", side_effect=RuntimeError("boom")):
            window.show()
            worker = window._window_thread
            if worker is not None:
                worker.join(timeout=1.2)
            else:
                time.sleep(0.05)
        self.assertFalse(window._is_open)


if __name__ == "__main__":
    unittest.main()
