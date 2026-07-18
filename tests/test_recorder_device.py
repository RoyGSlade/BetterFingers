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


class RecorderFingerprintResolutionTests(unittest.TestCase):
    FP = {
        "name": "Blue Yeti",
        "host_api": "ALSA",
        "max_input_channels": 2,
        "default_samplerate": 48000.0,
        "last_known_index": 5,
    }

    def _record_once(self, config, resolved):
        captured = {}

        def fake(**kwargs):
            captured.update(kwargs)
            return _FakeStream()

        rec = AudioRecorder()
        with patch.object(recorder, "load_profile", return_value=config), \
             patch.object(recorder, "resolve_input_device", return_value=resolved) as resolve, \
             patch.object(recorder.sd, "InputStream", side_effect=fake), \
             patch.object(rec, "_start_chunk_worker"):
            rec.start_recording("Default")
        rec.recording = False
        return captured, resolve

    def test_fingerprint_resolution_overrides_stale_index(self):
        # Saved at index 5, but the mic now sits at index 2.
        config = {"input_device_index": 5, "input_device_fingerprint": self.FP}
        captured, _ = self._record_once(config, resolved=2)
        self.assertEqual(captured.get("device"), 2)

    def test_unresolvable_fingerprint_keeps_index_as_hint(self):
        config = {"input_device_index": 5, "input_device_fingerprint": self.FP}
        captured, _ = self._record_once(config, resolved=None)
        self.assertEqual(captured.get("device"), 5)

    def test_no_fingerprint_skips_resolution(self):
        config = {"input_device_index": 5, "input_device_fingerprint": {}}
        captured, resolve = self._record_once(config, resolved=2)
        self.assertEqual(captured.get("device"), 5)
        resolve.assert_not_called()

    def test_system_default_selection_skips_resolution(self):
        config = {"input_device_index": -1, "input_device_fingerprint": self.FP}
        captured, resolve = self._record_once(config, resolved=2)
        self.assertIsNone(captured.get("device"))
        resolve.assert_not_called()


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


class InputDeviceFingerprintConfigTests(unittest.TestCase):
    FP = {
        "name": "Blue Yeti",
        "host_api": "ALSA",
        "max_input_channels": 2,
        "default_samplerate": 48000.0,
        "last_known_index": 5,
    }

    def _sanitize(self, value):
        defaults = utils._profile_defaults()
        cfg = {"input_device_fingerprint": value}
        return utils._sanitize_profile_values(cfg, defaults)["input_device_fingerprint"]

    def test_default_profile_has_empty_fingerprint(self):
        self.assertEqual(utils._profile_defaults()["input_device_fingerprint"], {})

    def test_well_formed_fingerprint_round_trips(self):
        self.assertEqual(self._sanitize(dict(self.FP)), self.FP)

    def test_non_dict_collapses_to_empty(self):
        self.assertEqual(self._sanitize("Blue Yeti"), {})
        self.assertEqual(self._sanitize(None), {})

    def test_nameless_fingerprint_collapses_to_empty(self):
        self.assertEqual(self._sanitize({"host_api": "ALSA", "last_known_index": 5}), {})

    def test_field_types_are_coerced(self):
        fp = self._sanitize({
            "name": " Blue Yeti ",
            "host_api": None,
            "max_input_channels": "2",
            "default_samplerate": "48000",
            "last_known_index": "5",
            "unknown_extra": "dropped",
        })
        self.assertEqual(fp, {
            "name": "Blue Yeti",
            "host_api": "",
            "max_input_channels": 2,
            "default_samplerate": 48000.0,
            "last_known_index": 5,
        })


class RefreshFingerprintOnSaveTests(unittest.TestCase):
    FP = InputDeviceFingerprintConfigTests.FP

    def test_system_default_clears_fingerprint(self):
        payload = {"input_device_index": -1, "input_device_fingerprint": dict(self.FP)}
        utils._refresh_input_device_fingerprint(payload)
        self.assertEqual(payload["input_device_fingerprint"], {})

    def test_unchanged_selection_keeps_existing_fingerprint(self):
        payload = {"input_device_index": 5, "input_device_fingerprint": dict(self.FP)}
        with patch("audio_device_resolver.build_input_device_fingerprint") as build:
            utils._refresh_input_device_fingerprint(payload)
            build.assert_not_called()
        self.assertEqual(payload["input_device_fingerprint"], self.FP)

    def test_changed_selection_recaptures_fingerprint(self):
        new_fp = dict(self.FP, name="Webcam Mic", last_known_index=2)
        payload = {"input_device_index": 2, "input_device_fingerprint": dict(self.FP)}
        with patch("audio_device_resolver.build_input_device_fingerprint", return_value=new_fp):
            utils._refresh_input_device_fingerprint(payload)
        self.assertEqual(payload["input_device_fingerprint"], new_fp)

    def test_capture_failure_on_changed_selection_clears_stale_fingerprint(self):
        payload = {"input_device_index": 2, "input_device_fingerprint": dict(self.FP)}
        with patch("audio_device_resolver.build_input_device_fingerprint", return_value=None):
            utils._refresh_input_device_fingerprint(payload)
        self.assertEqual(payload["input_device_fingerprint"], {})


if __name__ == "__main__":
    unittest.main()
