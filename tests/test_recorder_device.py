"""The recorder honors the profile's selected input microphone."""

import unittest
from unittest.mock import patch

import recorder
import utils
from recorder import AudioRecorder


class _FakeStream:
    def start(self):
        pass

    def stop(self):
        pass

    def close(self):
        pass


class RecorderDeviceSelectionTests(unittest.TestCase):
    def _record_once(self, config, inputstream):
        rec = AudioRecorder()
        with patch.object(recorder, "load_profile", return_value=config), \
             patch.object(recorder.sd, "InputStream", side_effect=inputstream), \
             patch.object(rec, "_start_chunk_worker"):
            rec.start_recording("Default")
        rec.recording = False
        return rec

    def test_uses_configured_device_index(self):
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return _FakeStream()

        self._record_once({"input_device_index": 3}, fake)
        self.assertEqual(captured.get("device"), 3)

    def test_default_of_minus_one_means_system_default(self):
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return _FakeStream()

        self._record_once({"input_device_index": -1}, fake)
        self.assertIsNone(captured.get("device"))

    def test_missing_key_means_system_default(self):
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return _FakeStream()

        self._record_once({}, fake)
        self.assertIsNone(captured.get("device"))

    def test_failed_device_falls_back_to_system_default(self):
        attempts = []

        def fake(**kwargs):
            attempts.append(kwargs.get("device"))
            if kwargs.get("device") == 5:
                raise RuntimeError("device busy")
            return _FakeStream()

        rec = self._record_once({"input_device_index": 5}, fake)
        # Tried the selected device, then retried on the system default.
        self.assertEqual(attempts, [5, None])


class InputDeviceConfigTests(unittest.TestCase):
    def _sanitize(self, value):
        defaults = utils._profile_defaults()
        return utils._sanitize_profile_values({"input_device_index": value}, defaults)["input_device_index"]

    def test_default_profile_has_system_default_input(self):
        self.assertEqual(utils._profile_defaults()["input_device_index"], -1)

    def test_string_from_select_is_coerced_to_int(self):
        self.assertEqual(self._sanitize("4"), 4)  # "<select>".value arrives as a string

    def test_below_range_clamps_to_system_default(self):
        self.assertEqual(self._sanitize(-9), -1)

    def test_garbage_falls_back_to_default(self):
        self.assertEqual(self._sanitize("not-a-number"), -1)


if __name__ == "__main__":
    unittest.main()
