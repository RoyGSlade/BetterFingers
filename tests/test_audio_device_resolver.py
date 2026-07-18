"""Fingerprints identify a microphone across PortAudio index churn."""

import unittest
from unittest.mock import patch

import audio_device_resolver
from audio_device_resolver import build_input_device_fingerprint, resolve_input_device


def _dev(index, name, host_api="ALSA", inputs=2, samplerate=48000.0):
    return {
        "index": index,
        "name": name,
        "host_api": host_api,
        "max_input_channels": inputs,
        "default_samplerate": samplerate,
    }


USB_MIC_FP = {
    "name": "Blue Yeti",
    "host_api": "ALSA",
    "max_input_channels": 2,
    "default_samplerate": 48000.0,
    "last_known_index": 3,
}


class BuildFingerprintTests(unittest.TestCase):
    def _build(self, devices, index):
        with patch.object(audio_device_resolver, "_query_devices", return_value=devices):
            return build_input_device_fingerprint(index)

    def test_captures_identity_of_input_device(self):
        devices = [_dev(0, "HDA Intel", inputs=0), _dev(1, "Blue Yeti")]
        fp = self._build(devices, 1)
        self.assertEqual(fp, {
            "name": "Blue Yeti",
            "host_api": "ALSA",
            "max_input_channels": 2,
            "default_samplerate": 48000.0,
            "last_known_index": 1,
        })

    def test_output_only_device_yields_none(self):
        self.assertIsNone(self._build([_dev(0, "Speakers", inputs=0)], 0))

    def test_out_of_range_index_yields_none(self):
        self.assertIsNone(self._build([_dev(0, "Mic")], 5))

    def test_negative_and_non_int_indices_yield_none(self):
        self.assertIsNone(self._build([_dev(0, "Mic")], -1))
        self.assertIsNone(self._build([_dev(0, "Mic")], "0"))
        self.assertIsNone(self._build([_dev(0, "Mic")], True))

    def test_portaudio_failure_yields_none(self):
        with patch.object(audio_device_resolver, "_query_devices", side_effect=RuntimeError("no PA")):
            self.assertIsNone(build_input_device_fingerprint(0))


class ResolveInputDeviceTests(unittest.TestCase):
    def _resolve(self, devices, fingerprint):
        with patch.object(audio_device_resolver, "_query_devices", return_value=devices):
            return resolve_input_device(fingerprint)

    def test_hint_still_valid_is_trusted(self):
        devices = [_dev(0, "HDA Intel"), _dev(1, "Webcam Mic"), _dev(2, "Other"), _dev(3, "Blue Yeti")]
        self.assertEqual(self._resolve(devices, USB_MIC_FP), 3)

    def test_device_moved_is_found_by_identity(self):
        # After a reboot the mic shifted from index 3 to index 1.
        devices = [_dev(0, "HDA Intel"), _dev(1, "Blue Yeti"), _dev(2, "Webcam Mic")]
        self.assertEqual(self._resolve(devices, USB_MIC_FP), 1)

    def test_hint_now_points_at_different_device(self):
        # Another device took over index 3; the mic itself sits at 0.
        devices = [_dev(0, "Blue Yeti"), _dev(1, "A"), _dev(2, "B"), _dev(3, "Webcam Mic")]
        self.assertEqual(self._resolve(devices, USB_MIC_FP), 0)

    def test_channel_count_change_still_matches_name_and_host_api(self):
        # A driver update changed the reported channel count.
        devices = [_dev(0, "Blue Yeti", inputs=1)]
        self.assertEqual(self._resolve(devices, USB_MIC_FP), 0)

    def test_host_api_change_still_matches_by_name(self):
        devices = [_dev(0, "Blue Yeti", host_api="JACK")]
        self.assertEqual(self._resolve(devices, USB_MIC_FP), 0)

    def test_exact_match_preferred_over_relaxed_match(self):
        # Same name on two host APIs: the fingerprinted host API wins even
        # though the other one appears first in the table.
        devices = [_dev(0, "Blue Yeti", host_api="JACK"), _dev(1, "Blue Yeti", host_api="ALSA")]
        self.assertEqual(self._resolve(devices, USB_MIC_FP), 1)

    def test_output_only_namesake_is_ignored(self):
        devices = [_dev(0, "Blue Yeti", inputs=0)]
        self.assertIsNone(self._resolve(devices, USB_MIC_FP))

    def test_unplugged_device_yields_none(self):
        devices = [_dev(0, "HDA Intel"), _dev(1, "Webcam Mic")]
        self.assertIsNone(self._resolve(devices, USB_MIC_FP))

    def test_empty_or_invalid_fingerprint_yields_none(self):
        devices = [_dev(0, "Blue Yeti")]
        self.assertIsNone(self._resolve(devices, {}))
        self.assertIsNone(self._resolve(devices, None))
        self.assertIsNone(self._resolve(devices, {"host_api": "ALSA"}))
        self.assertIsNone(self._resolve(devices, "Blue Yeti"))

    def test_portaudio_failure_yields_none(self):
        with patch.object(audio_device_resolver, "_query_devices", side_effect=RuntimeError("no PA")):
            self.assertIsNone(resolve_input_device(USB_MIC_FP))

    def test_boolean_hint_is_not_treated_as_index(self):
        fp = dict(USB_MIC_FP, last_known_index=True)
        devices = [_dev(0, "HDA Intel"), _dev(1, "Blue Yeti")]
        self.assertEqual(self._resolve(devices, fp), 1)


class QueryDevicesHostApiTests(unittest.TestCase):
    def test_host_api_names_are_joined_from_query_hostapis(self):
        fake_sd_devices = [
            {"name": "Mic A", "hostapi": 0, "max_input_channels": 1, "default_samplerate": 44100.0},
            {"name": "Mic B", "hostapi": 1, "max_input_channels": 2, "default_samplerate": 48000.0},
            {"name": "Weird", "hostapi": 9, "max_input_channels": 1, "default_samplerate": 48000.0},
        ]
        fake_hostapis = [{"name": "ALSA"}, {"name": "JACK"}]

        class FakeSD:
            @staticmethod
            def query_devices():
                return fake_sd_devices

            @staticmethod
            def query_hostapis():
                return fake_hostapis

        with patch.dict("sys.modules", {"sounddevice": FakeSD}):
            devices = audio_device_resolver._query_devices()

        self.assertEqual([d["host_api"] for d in devices], ["ALSA", "JACK", ""])
        self.assertEqual([d["index"] for d in devices], [0, 1, 2])


if __name__ == "__main__":
    unittest.main()
