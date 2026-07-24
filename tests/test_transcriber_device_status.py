"""Tests for honest device-selection status on Transcriber (no real model or
GPU dependency -- WhisperModel is mocked).

_load_model() tries CUDA first when prefer_gpu is True and silently falls
back to CPU on any exception (e.g. missing cuDNN on Windows). These tests
verify that fallback is now RECORDED, not just logged: self.active_device,
self.active_compute_type and self.device_fallback_reason must reflect what
actually loaded, so the /doctor status surface can be honest about it."""
import unittest
from unittest.mock import patch

from transcriber import Transcriber


class _DummySegment:
    def __init__(self, text, start=0.0, end=0.0):
        self.start = start
        self.end = end
        self.text = text


class _DummyWhisperModel:
    def transcribe(self, _audio, beam_size=5, hotwords=None):
        del beam_size, hotwords
        return [_DummySegment("hello world", start=0.0, end=0.5)], None


def _cuda_fails_cpu_succeeds(*_args, **kwargs):
    """Stand-in for WhisperModel(...): raises for device='cuda' (simulating a
    missing/broken CUDA runtime, e.g. no cuDNN on Windows), succeeds for
    device='cpu' -- regardless of local_files_only retry branch taken."""
    if kwargs.get("device") == "cuda":
        raise RuntimeError("Unable to load libcudnn / CUDA driver init failed")
    return _DummyWhisperModel()


class TranscriberDeviceStatusDefaultsTests(unittest.TestCase):
    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_unloaded_transcriber_has_none_device_state(self, _whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        self.assertIsNone(transcriber.active_device)
        self.assertIsNone(transcriber.active_compute_type)
        self.assertIsNone(transcriber.device_fallback_reason)


class TranscriberCudaFallbackTests(unittest.TestCase):
    """prefer_gpu True, CUDA init fails on every attempt -> lands on CPU. The
    fallback must be queryable, matching the Windows-no-cuDNN scenario this
    fix targets."""

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": True})
    @patch("transcriber.WhisperModel", side_effect=_cuda_fails_cpu_succeeds)
    def test_cuda_failure_records_cpu_device_and_reason(self, whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        self.assertTrue(transcriber.prefer_gpu)

        ok = transcriber.ensure_loaded()

        self.assertTrue(ok)
        self.assertIsNotNone(transcriber.model)
        self.assertEqual(transcriber.active_device, "cpu")
        self.assertEqual(transcriber.active_compute_type, "int8")
        self.assertEqual(transcriber.device_fallback_reason, "CUDA initialization failed")
        # Every constructor call attempted CUDA before the successful CPU one.
        whisper_model.assert_called()

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": True})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_cuda_success_records_cuda_device_with_no_fallback(self, _whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)

        ok = transcriber.ensure_loaded()

        self.assertTrue(ok)
        self.assertEqual(transcriber.active_device, "cuda")
        self.assertEqual(transcriber.active_compute_type, "float16")
        self.assertIsNone(transcriber.device_fallback_reason)

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": True})
    @patch("transcriber.WhisperModel", side_effect=_cuda_fails_cpu_succeeds)
    def test_unload_clears_device_state_after_fallback(self, _whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        transcriber.ensure_loaded()
        self.assertEqual(transcriber.active_device, "cpu")
        self.assertIsNotNone(transcriber.device_fallback_reason)

        transcriber.unload()

        self.assertIsNone(transcriber.model)
        self.assertIsNone(transcriber.active_device)
        self.assertIsNone(transcriber.active_compute_type)
        self.assertIsNone(transcriber.device_fallback_reason)


class TranscriberCpuPreferredTests(unittest.TestCase):
    """prefer_gpu False -> CPU is a deliberate choice, not a fallback; no
    fallback reason should ever be set."""

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": False})
    @patch("transcriber.WhisperModel", return_value=_DummyWhisperModel())
    def test_cpu_preferred_no_fallback_reason(self, whisper_model, _load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        self.assertFalse(transcriber.prefer_gpu)

        ok = transcriber.ensure_loaded()

        self.assertTrue(ok)
        self.assertEqual(transcriber.active_device, "cpu")
        self.assertEqual(transcriber.active_compute_type, "int8")
        self.assertIsNone(transcriber.device_fallback_reason)
        # CUDA must never even be attempted when prefer_gpu is False.
        whisper_model.assert_called_once()
        _args, call_kwargs = whisper_model.call_args
        self.assertEqual(call_kwargs.get("device"), "cpu")
        self.assertEqual(call_kwargs.get("compute_type"), "int8")


class TranscriberReloadProfileTests(unittest.TestCase):
    """Switching profiles (model size or gpu preference) invalidates the
    loaded model; the device status must not keep reporting stale info for a
    model that is no longer loaded."""

    @patch("transcriber.load_profile", return_value={"model_size": "base.en", "use_gpu": True})
    @patch("transcriber.WhisperModel", side_effect=_cuda_fails_cpu_succeeds)
    def test_reload_profile_with_changed_gpu_pref_clears_stale_device(self, _whisper_model, load_profile):
        transcriber = Transcriber(profile_name="Default", preload=False)
        transcriber.ensure_loaded()
        self.assertEqual(transcriber.active_device, "cpu")

        load_profile.return_value = {"model_size": "small.en", "use_gpu": True}
        transcriber.reload_profile(profile_name="Default", preload=False)

        self.assertIsNone(transcriber.model)
        self.assertIsNone(transcriber.active_device)
        self.assertIsNone(transcriber.active_compute_type)
        self.assertIsNone(transcriber.device_fallback_reason)


if __name__ == "__main__":
    unittest.main()
