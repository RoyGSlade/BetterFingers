import threading
import time
import unittest

import pytest

from main import App

pytestmark = pytest.mark.smoke


class _BlockingManager:
    def __init__(self, delay_sec=0.8):
        self.delay_sec = float(delay_sec)
        self.stop_calls = 0

    def stop(self):
        self.stop_calls += 1
        time.sleep(self.delay_sec)


class _SettingsStub:
    def __init__(self):
        self._is_open = True
        self.force_close_calls = 0
        self.wait_for_shutdown_calls = 0
        self.wait_for_shutdown_timeouts = []

    def force_close_for_shutdown(self):
        self.force_close_calls += 1

    def wait_for_shutdown(self, timeout_sec=0):
        self.wait_for_shutdown_calls += 1
        self.wait_for_shutdown_timeouts.append(timeout_sec)
        return True


class _SettingsOrderStub(_SettingsStub):
    def __init__(self, calls):
        super().__init__()
        self.calls = calls

    def force_close_for_shutdown(self):
        self.calls.append("settings.force_close")
        super().force_close_for_shutdown()

    def wait_for_shutdown(self, timeout_sec=0):
        self.calls.append("settings.wait_for_shutdown")
        return super().wait_for_shutdown(timeout_sec=timeout_sec)


class _RootImmediate:
    def __init__(self):
        self.quit_calls = 0

    def after(self, _delay_ms, callback):
        callback()

    def quit(self):
        self.quit_calls += 1


class _OverlayStub:
    def __init__(self, calls):
        self.calls = calls

    def destroy(self):
        self.calls.append("overlay.destroy")


class _BrokenOverlayRoot:
    def winfo_exists(self):
        raise RuntimeError("window already gone")


class _OverlayHideStub:
    def __init__(self):
        self.root = _BrokenOverlayRoot()
        self.stop_calls = 0
        self.setup_calls = 0

    def stop_transparency_refresh(self):
        self.stop_calls += 1

    def _setup_windows_transparency(self):
        self.setup_calls += 1


class MainExitShutdownTests(unittest.TestCase):
    def test_on_exit_starts_watchdog_before_blocking_manager_stop(self):
        app = App()
        app.manager = _BlockingManager(delay_sec=0.8)
        app.injector = None
        app.tts_engine = None
        app.overlay = None
        app.preview_overlay = None
        app.icon = None
        app.root = None
        app.settings_window = None

        watchdog_started = threading.Event()

        def _fake_force_exit_after_timeout(timeout_sec=0):
            del timeout_sec
            watchdog_started.set()

        app._force_exit_after_timeout = _fake_force_exit_after_timeout

        worker = threading.Thread(target=app.on_exit, args=(None, None), daemon=True)
        worker.start()

        self.assertTrue(
            watchdog_started.wait(timeout=0.25),
            "Expected watchdog thread to start before blocking cleanup completes.",
        )
        worker.join(timeout=2.0)
        self.assertEqual(app.manager.stop_calls, 1)

    def test_on_exit_calls_settings_force_close_when_available(self):
        app = App()
        app.manager = _BlockingManager(delay_sec=0.0)
        app.injector = None
        app.tts_engine = None
        app.overlay = None
        app.preview_overlay = None
        app.icon = None
        app.root = None
        app.settings_window = _SettingsStub()

        app._force_exit_after_timeout = lambda timeout_sec=0: None
        app.on_exit()

        self.assertEqual(app.settings_window.force_close_calls, 1)
        self.assertEqual(app.settings_window.wait_for_shutdown_calls, 1)

    def test_on_exit_uses_longer_watchdog_timeout_when_settings_open(self):
        app = App()
        app.manager = _BlockingManager(delay_sec=0.0)
        app.injector = None
        app.tts_engine = None
        app.overlay = None
        app.preview_overlay = None
        app.icon = None
        app.root = None
        app.settings_window = _SettingsStub()

        watchdog_started = threading.Event()
        captured = {}

        def _fake_force_exit_after_timeout(timeout_sec=0):
            captured["timeout_sec"] = timeout_sec
            watchdog_started.set()

        app._force_exit_after_timeout = _fake_force_exit_after_timeout
        app.on_exit()

        self.assertTrue(watchdog_started.wait(timeout=0.3))
        self.assertGreaterEqual(captured.get("timeout_sec", 0), 3.0)

    def test_on_exit_closes_settings_before_overlay_destroy(self):
        app = App()
        app.manager = _BlockingManager(delay_sec=0.0)
        app.injector = None
        app.tts_engine = None
        app.preview_overlay = None
        app.icon = None
        app.root = _RootImmediate()

        calls = []
        app.settings_window = _SettingsOrderStub(calls)
        app.overlay = _OverlayStub(calls)

        app._force_exit_after_timeout = lambda timeout_sec=0: None
        app.on_exit()

        self.assertIn("settings.force_close", calls)
        self.assertIn("overlay.destroy", calls)
        self.assertLess(calls.index("settings.force_close"), calls.index("overlay.destroy"))

    def test_on_settings_hide_skips_overlay_work_when_overlay_window_is_gone(self):
        app = App()
        app.overlay = _OverlayHideStub()
        app._overlay_hidden_for_settings = True
        app.pipeline_state = "idle"

        app._on_settings_hide()

        self.assertEqual(app.overlay.stop_calls, 0)
        self.assertEqual(app.overlay.setup_calls, 0)
        self.assertFalse(app._overlay_hidden_for_settings)


if __name__ == "__main__":
    unittest.main()
