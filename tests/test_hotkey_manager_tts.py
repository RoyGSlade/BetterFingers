import unittest
from unittest.mock import patch

from hotkey_manager import HotkeyManager


class _DummyRecorder:
    def __init__(self):
        self.recording = False

    def start_recording(self, profile_name="Default"):
        del profile_name
        self.recording = True

    def stop_recording(self, stop_reason="manual"):
        del stop_reason
        self.recording = False
        return None


class HotkeyManagerTTSTests(unittest.TestCase):
    @staticmethod
    def _config(review_key="ctrl+shift+space", manual_key=""):
        return {
            "hotkey": "f8",
            "force_stop_key": "",
            "manual_send_hotkey": manual_key,
            "review_tts_hotkey": review_key,
            "recording_mode": "toggle",
            "controller_enabled": False,
            "controller_binding": {
                "style": "single",
                "events": ["button:4"],
                "sequence_window_ms": 400,
                "axis_threshold": 0.6,
                "device_scope": "any_device",
            },
        }

    @patch("hotkey_manager.load_profile")
    def test_registers_and_dispatches_review_tts_hotkey(self, load_profile):
        load_profile.return_value = self._config()
        tts_hits = {"count": 0}

        manager = HotkeyManager(
            recorder=_DummyRecorder(),
            on_recording_complete_callback=lambda _result: None,
            on_recording_start_callback=lambda: None,
            on_review_tts_callback=lambda: tts_hits.__setitem__("count", tts_hits["count"] + 1),
        )

        manager.start()
        self.assertTrue(manager._running)
        self.assertEqual(manager.review_tts_hotkey, "ctrl+shift+space")

        manager._review_tts_trigger()
        self.assertEqual(tts_hits["count"], 1)

        manager.stop()
        self.assertFalse(manager._running)

    @patch("hotkey_manager.load_profile")
    def test_dedupes_review_tts_when_same_as_manual_send(self, load_profile):
        load_profile.return_value = self._config(review_key="f9", manual_key="f9")

        manager = HotkeyManager(
            recorder=_DummyRecorder(),
            on_recording_complete_callback=lambda _result: None,
            on_recording_start_callback=lambda: None,
        )

        manager.start()
        self.assertEqual(manager.review_tts_hotkey, "f9")
        self.assertEqual(manager.manual_send_hotkey, "f9")

        manager.stop()
        self.assertFalse(manager._running)

    @patch("hotkey_manager.load_profile")
    def test_normalizes_uppercase_hotkey_letters_before_hooking(self, load_profile):
        config = self._config(review_key="ctrl+shift+A", manual_key="ctrl+shift+X")
        config["hotkey"] = "ctrl+shift+Z"
        load_profile.return_value = config

        manager = HotkeyManager(
            recorder=_DummyRecorder(),
            on_recording_complete_callback=lambda _result: None,
            on_recording_start_callback=lambda: None,
        )

        self.assertEqual(manager.hotkey, "ctrl+shift+z")
        self.assertEqual(manager.manual_send_hotkey, "ctrl+shift+x")
        self.assertEqual(manager.review_tts_hotkey, "ctrl+shift+a")

    @patch("hotkey_manager.load_profile")
    def test_update_config_restarts_for_review_tts_hotkey_change(self, load_profile):
        load_profile.side_effect = [
            self._config(review_key="ctrl+shift+space"),
            self._config(review_key="ctrl+alt+r"),
        ]

        manager = HotkeyManager(
            recorder=_DummyRecorder(),
            on_recording_complete_callback=lambda _result: None,
            on_recording_start_callback=lambda: None,
        )
        manager._running = True

        with patch.object(manager, "stop") as stop_mock, patch.object(manager, "start") as start_mock:
            manager.update_config("Default")
            stop_mock.assert_called_once()
            start_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
