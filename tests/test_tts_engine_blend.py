"""Coverage for the ONNX hot-upgrade-on-blend path added to ReviewTTSEngine.

Context: _resolve_voice_spec only ever honors a blend dict on the ONNX
runtime (kokoro_onnx); the native Kokoro pipeline and SAPI can't accept a
raw blended tensor. Previously a blend requested while running native was
dropped with a single logging.info line and zero feedback to the caller.
speak() now (1) tries once to hot-swap onto ONNX when a blend is requested
on native, and (2) always tells the caller, via a "warnings" key in the
returned status dict, when a blend could not be honored. get_capabilities()
exposes the same blend_capable gate for callers (e.g. /runtime/tts-status)
that want to know ahead of time.

These tests stub every load path (no real kokoro/kokoro-onnx/onnxruntime
imports, no network, no audio device) and patch out the worker thread so
speak() is exercised synchronously and its return value can be asserted
directly, following the pattern already used in test_tts_engine.py's
TTSEngineTests (e.g. test_repeated_speak_replaces_pending_queue_item).
"""

import unittest
from unittest.mock import Mock, patch

from tts_engine import ReviewTTSEngine


class GetCapabilitiesTests(unittest.TestCase):
    def test_unloaded_engine_reports_not_blend_capable(self):
        engine = ReviewTTSEngine()
        caps = engine.get_capabilities()
        self.assertEqual(caps["backend"], "none")
        self.assertIsNone(caps["runtime"])
        self.assertFalse(caps["blend_capable"])

    def test_native_runtime_is_not_blend_capable(self):
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "kokoro"
        engine._kokoro_runtime = "native"
        engine._kokoro_pipeline = Mock()
        caps = engine.get_capabilities()
        self.assertEqual(caps["backend"], "kokoro")
        self.assertEqual(caps["runtime"], "native")
        self.assertFalse(caps["blend_capable"])

    def test_onnx_runtime_with_engine_is_blend_capable(self):
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "kokoro_onnx"
        engine._kokoro_runtime = "onnx"
        engine._kokoro_onnx = Mock()
        caps = engine.get_capabilities()
        self.assertEqual(caps["backend"], "kokoro_onnx")
        self.assertEqual(caps["runtime"], "onnx")
        self.assertTrue(caps["blend_capable"])

    def test_onnx_runtime_missing_engine_handle_is_not_blend_capable(self):
        # Defensive: if _kokoro_runtime says "onnx" but the engine handle
        # itself is gone (e.g. mid-teardown), blend_capable must not lie.
        engine = ReviewTTSEngine()
        engine._backend = "kokoro_onnx"
        engine._kokoro_runtime = "onnx"
        engine._kokoro_onnx = None
        caps = engine.get_capabilities()
        self.assertFalse(caps["blend_capable"])

    def test_sapi_runtime_is_not_blend_capable(self):
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "sapi"
        engine._kokoro_runtime = None
        caps = engine.get_capabilities()
        self.assertEqual(caps["backend"], "sapi")
        self.assertFalse(caps["blend_capable"])


class SpeakBlendHotUpgradeTests(unittest.TestCase):
    """speak() with a non-empty blend while loaded on the native runtime."""

    def _native_engine(self):
        engine = ReviewTTSEngine()
        # Simulate "already loaded on native Kokoro" without touching any
        # real backend: ensure_loaded()'s fast path just returns this state
        # verbatim when self._loaded is already True.
        engine._loaded = True
        engine._backend = "kokoro"
        engine._fallback = False
        engine._status_message = "Kokoro backend loaded."
        engine._kokoro_runtime = "native"
        engine._kokoro_pipeline = Mock()
        return engine

    def _fake_onnx_upgrade_success(self, engine):
        def fake_load(voice_hint="english", prefer_gpu=True, quantization="fp32"):
            # Mirrors _load_kokoro_onnx_backend's real success side effects
            # (pipeline cleared, onnx engine + runtime set) closely enough
            # for _capabilities_locked()/backend() to see a real upgrade.
            engine._kokoro_pipeline = None
            engine._kokoro_onnx = Mock()
            engine._kokoro_runtime = "onnx"
            return (True, "kokoro-onnx backend loaded.")
        return fake_load

    def test_blend_on_native_triggers_exactly_one_upgrade_attempt_and_succeeds(self):
        engine = self._native_engine()
        with patch.object(
            engine, "_load_kokoro_onnx_backend",
            side_effect=self._fake_onnx_upgrade_success(engine),
        ) as onnx_mock, patch.object(engine, "_start_worker_if_needed"), patch.object(
            engine, "stop_current"
        ):
            result = engine.speak("hello", blend={"am_adam": 0.4})

        onnx_mock.assert_called_once()
        self.assertEqual(engine._kokoro_runtime, "onnx")
        self.assertEqual(result["backend"], "kokoro_onnx")
        self.assertTrue(result["ok"])
        # Blend will actually be honored now -> no warning, key omitted entirely.
        self.assertNotIn("warnings", result)
        self.assertFalse(engine._onnx_upgrade_failed)

    def test_blend_on_native_upgrade_failure_sets_guard_and_warns_without_raising(self):
        engine = self._native_engine()
        with patch.object(
            engine, "_load_kokoro_onnx_backend",
            return_value=(False, "kokoro-onnx unavailable (module not installed)."),
        ) as onnx_mock, patch.object(engine, "_start_worker_if_needed"), patch.object(
            engine, "stop_current"
        ):
            result = engine.speak("hello", blend={"am_adam": 0.4})

        onnx_mock.assert_called_once()
        self.assertTrue(engine._onnx_upgrade_failed)
        # Speech must still play (on the base voice) -- never raises, ok stays True.
        self.assertTrue(result["ok"])
        # Still native: blend dropped, and the backend field reflects that honestly.
        self.assertEqual(engine._kokoro_runtime, "native")
        self.assertEqual(result["backend"], "kokoro")
        self.assertIn("warnings", result)
        self.assertIn("ONNX", result["warnings"][0])

    def test_second_blended_speak_after_failed_upgrade_does_not_retry_the_load(self):
        engine = self._native_engine()
        with patch.object(
            engine, "_load_kokoro_onnx_backend",
            return_value=(False, "kokoro-onnx unavailable."),
        ) as onnx_mock, patch.object(engine, "_start_worker_if_needed"), patch.object(
            engine, "stop_current"
        ):
            first = engine.speak("hello", blend={"am_adam": 0.4})
            second = engine.speak("world", blend={"am_adam": 0.4})

        # The guard flag must prevent a second load attempt entirely.
        onnx_mock.assert_called_once()
        self.assertIn("warnings", first)
        self.assertIn("warnings", second)
        self.assertTrue(engine._onnx_upgrade_failed)

    def test_speak_without_blend_never_attempts_upgrade(self):
        engine = self._native_engine()
        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock, patch.object(
            engine, "_start_worker_if_needed"
        ), patch.object(engine, "stop_current"):
            result = engine.speak("hello")  # no blend kwarg at all

        onnx_mock.assert_not_called()
        self.assertNotIn("warnings", result)
        self.assertEqual(engine._kokoro_runtime, "native")

    def test_speak_with_empty_blend_dict_never_attempts_upgrade(self):
        # {} is falsy -- must be treated the same as None, not "blend requested".
        engine = self._native_engine()
        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock, patch.object(
            engine, "_start_worker_if_needed"
        ), patch.object(engine, "stop_current"):
            result = engine.speak("hello", blend={})

        onnx_mock.assert_not_called()
        self.assertNotIn("warnings", result)

    def test_blend_already_on_onnx_never_attempts_upgrade_and_has_no_warning(self):
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "kokoro_onnx"
        engine._kokoro_runtime = "onnx"
        engine._kokoro_onnx = Mock()
        engine._fallback = False
        engine._status_message = "kokoro-onnx backend loaded."

        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock, patch.object(
            engine, "_start_worker_if_needed"
        ), patch.object(engine, "stop_current"):
            result = engine.speak("hello", blend={"am_adam": 0.4})

        onnx_mock.assert_not_called()  # already the capable backend -- nothing to upgrade
        self.assertNotIn("warnings", result)
        self.assertEqual(result["backend"], "kokoro_onnx")

    def test_blend_on_sapi_backend_warns_but_does_not_attempt_upgrade(self):
        # No native pipeline to upgrade FROM (Kokoro entirely unavailable);
        # the hot-upgrade helper only fires when runtime == "native".
        engine = ReviewTTSEngine()
        engine._loaded = True
        engine._backend = "sapi"
        engine._fallback = True
        engine._status_message = "Using Windows SAPI fallback."
        engine._kokoro_runtime = None

        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock, patch.object(
            engine, "_start_worker_if_needed"
        ), patch.object(engine, "stop_current"), patch.object(
            engine, "_speak_sapi", return_value=None
        ):
            result = engine.speak("hello", blend={"am_adam": 0.4})

        onnx_mock.assert_not_called()
        self.assertIn("warnings", result)
        self.assertTrue(result["ok"])  # speech still plays on SAPI


class MaybeUpgradeHelperTests(unittest.TestCase):
    """Direct unit coverage of the guarded upgrade helper itself."""

    def test_guard_flag_prevents_reattempt(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "native"
        engine._onnx_upgrade_failed = True
        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock:
            engine._maybe_upgrade_to_onnx_for_blend(voice_hint="english")
        onnx_mock.assert_not_called()

    def test_already_onnx_is_a_noop(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = "onnx"
        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock:
            engine._maybe_upgrade_to_onnx_for_blend(voice_hint="english")
        onnx_mock.assert_not_called()

    def test_none_runtime_is_a_noop(self):
        engine = ReviewTTSEngine()
        engine._kokoro_runtime = None
        with patch.object(engine, "_load_kokoro_onnx_backend") as onnx_mock:
            engine._maybe_upgrade_to_onnx_for_blend(voice_hint="english")
        onnx_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
