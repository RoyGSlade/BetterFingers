"""The shared output injector is serialized (P1 input injection).

Two concurrent sends must not race the singleton's creation/reload or interleave
their injections; a config reload cannot land mid-injection.
"""

import threading
import time
import unittest
from unittest.mock import patch

import server


class _RecordingInjector:
    """Fake injector that records overlapping use to prove serialization."""
    active = 0
    max_overlap = 0
    reloads_during_injection = 0
    _injecting = False
    _lock = threading.Lock()

    def __init__(self, profile_name=None):
        pass

    def reload_config(self, profile_name=None):
        if _RecordingInjector._injecting:
            _RecordingInjector.reloads_during_injection += 1

    def open_chat(self):
        pass

    def send_output(self, text, auto_submit=False, close_action="none"):
        with _RecordingInjector._lock:
            _RecordingInjector.active += 1
            _RecordingInjector.max_overlap = max(_RecordingInjector.max_overlap, _RecordingInjector.active)
            _RecordingInjector._injecting = True
        time.sleep(0.15)  # hold the "injection" long enough to catch a race
        with _RecordingInjector._lock:
            _RecordingInjector.active -= 1
            _RecordingInjector._injecting = False

    def type_text(self, text):
        self.send_output(text)


class InjectionLockingTests(unittest.TestCase):
    def setUp(self):
        _RecordingInjector.active = 0
        _RecordingInjector.max_overlap = 0
        _RecordingInjector.reloads_during_injection = 0
        self._prior = server.output_injector
        server.output_injector = None
        self.addCleanup(lambda: setattr(server, "output_injector", self._prior))

    def test_concurrent_sends_do_not_overlap(self):
        caps = {"supports_input_injection": True, "platform": "linux", "session_type": "x11"}
        with patch("injector.InputInjector", _RecordingInjector), \
             patch.object(server, "get_capabilities", return_value=caps), \
             patch.object(server, "get_profile_output_settings",
                          return_value={"auto_submit": False, "chat_close_action": "none",
                                        "send_mode": "manual"}), \
             patch.object(server, "get_last_active_profile", return_value="Default"):
            results = []

            def worker():
                results.append(server.perform_output_action("hello world", "paste"))

            threads = [threading.Thread(target=worker) for _ in range(4)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(5)

            self.assertEqual(len(results), 4)
            self.assertTrue(all(r["ok"] for r in results))
            # The lock must have prevented any concurrent injection.
            self.assertEqual(_RecordingInjector.max_overlap, 1)
            # No config reload landed while an injection was running.
            self.assertEqual(_RecordingInjector.reloads_during_injection, 0)


if __name__ == "__main__":
    unittest.main()
