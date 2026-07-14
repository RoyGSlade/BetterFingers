"""Cloned-voice synthesis wiring (DESIGN §10 M5 U6).

CI-safe: the heavy optional deps (kanade-tokenizer/torch models) are never
loaded here — these tests cover the id namespace, reference resolution,
availability gating, the honest-failure paths in speak(), the conversion hook
in _generate_kokoro_audio, and the DELETE /tts/voices route.
"""

import builtins
import os
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
from fastapi.testclient import TestClient

import server
import tts_engine
import voice_clone_engine


class ClonedIdTests(unittest.TestCase):
    def test_namespace_detection(self):
        self.assertTrue(voice_clone_engine.is_cloned_voice_id("cloned_My_Voice"))
        self.assertTrue(voice_clone_engine.is_cloned_voice_id("  Cloned_X "))
        self.assertFalse(voice_clone_engine.is_cloned_voice_id("af_heart"))
        self.assertFalse(voice_clone_engine.is_cloned_voice_id(""))
        self.assertFalse(voice_clone_engine.is_cloned_voice_id(None))

    def test_reference_resolution_and_traversal_safety(self):
        with tempfile.TemporaryDirectory() as d:
            sample = os.path.join(d, "cloned_Me.wav")
            open(sample, "w").close()
            with patch.object(voice_clone_engine, "get_voices_dir", return_value=d):
                self.assertEqual(voice_clone_engine.find_reference_sample("cloned_Me"), sample)
                self.assertIsNone(voice_clone_engine.find_reference_sample("cloned_Missing"))
                self.assertIsNone(voice_clone_engine.find_reference_sample("af_heart"))
                # A path-traversal id must never escape the voices dir.
                self.assertIsNone(voice_clone_engine.find_reference_sample("cloned_../../etc/passwd"))


class AvailabilityTests(unittest.TestCase):
    def test_reports_missing_dependency_with_setup_hint(self):
        real_import = builtins.__import__

        def no_kanade(name, *args, **kwargs):
            if name.startswith("kanade_tokenizer"):
                raise ImportError(name=name)
            return real_import(name, *args, **kwargs)

        with patch.object(builtins, "__import__", side_effect=no_kanade):
            status = voice_clone_engine.availability()
        self.assertFalse(status["available"])
        self.assertIn("setup_voice_cloning", status["setup_hint"])


class SpeakGateTests(unittest.TestCase):
    def _engine(self):
        return tts_engine.ReviewTTSEngine()

    def test_missing_sample_fails_honestly(self):
        engine = self._engine()
        with patch.object(voice_clone_engine, "find_reference_sample", return_value=None):
            result = engine.speak("hello", voice_hint="cloned_Ghost")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "cloned_sample_missing")

    def test_unavailable_engine_fails_honestly_not_wrong_voice(self):
        engine = self._engine()
        with patch.object(voice_clone_engine, "find_reference_sample", return_value="/tmp/x.wav"), \
             patch.object(voice_clone_engine, "availability",
                          return_value={"available": False, "reason": "deps missing",
                                        "setup_hint": voice_clone_engine.SETUP_HINT}):
            result = engine.speak("hello", voice_hint="cloned_Me")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "cloning_unavailable")
        self.assertIn("setup_voice_cloning", result["message"])

    def test_builtin_voices_never_touch_the_gate(self):
        engine = self._engine()
        with patch.object(voice_clone_engine, "availability") as availability:
            with patch.object(engine, "ensure_loaded", return_value={"ok": False, "message": "no backend"}):
                engine.speak("hello", voice_hint="af_heart")
        availability.assert_not_called()


class GenerateHookTests(unittest.TestCase):
    class _FakeOnnx:
        voices = {"af_heart": object()}

        def create(self, text, voice, speed, lang):
            return np.ones(2400, dtype=np.float32), 24000

    def _engine(self):
        engine = tts_engine.ReviewTTSEngine()
        engine._kokoro_runtime = "onnx"
        engine._kokoro_onnx = self._FakeOnnx()
        return engine

    def test_cloned_hint_synthesizes_base_then_converts(self):
        engine = self._engine()
        converted = (np.zeros(4800, dtype=np.float32), 24000)
        with patch.object(voice_clone_engine, "find_reference_sample", return_value="/tmp/ref.wav"), \
             patch.object(voice_clone_engine, "convert", return_value=converted) as convert:
            audio, sr = engine._generate_kokoro_audio("hi", 1.0, "cloned_Me")
        convert.assert_called_once()
        args = convert.call_args.args
        self.assertEqual(len(args[0]), 2400)          # the base-voice synthesis went in
        self.assertEqual(args[2], "/tmp/ref.wav")     # against the stored reference
        self.assertEqual(len(audio), 4800)            # the converted audio came out
        self.assertEqual(sr, 24000)

    def test_cloned_hint_with_missing_sample_raises_not_wrong_voice(self):
        engine = self._engine()
        with patch.object(voice_clone_engine, "find_reference_sample", return_value=None):
            with self.assertRaises(RuntimeError):
                engine._generate_kokoro_audio("hi", 1.0, "cloned_Ghost")

    def test_builtin_voice_is_untouched(self):
        engine = self._engine()
        with patch.object(voice_clone_engine, "convert") as convert:
            audio, sr = engine._generate_kokoro_audio("hi", 1.0, "af_heart")
        convert.assert_not_called()
        self.assertEqual(len(audio), 2400)


class DeleteClonedVoiceRouteTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        if self._orig is None:
            self.addCleanup(lambda: os.environ.pop("APPDATA", None))
        else:
            self.addCleanup(lambda: os.environ.__setitem__("APPDATA", self._orig))

    def _seed_voice(self, name="cloned_Me"):
        voices_dir = str(server.get_voices_dir())
        for suffix in (".wav", ".meta.json"):
            open(os.path.join(voices_dir, f"{name}{suffix}"), "w").close()
        return voices_dir

    def test_delete_removes_sample_and_metadata(self):
        voices_dir = self._seed_voice()
        with TestClient(server.app) as client:
            response = client.delete("/tts/voices/cloned_Me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(sorted(response.json()["removed"]),
                         ["cloned_Me.meta.json", "cloned_Me.wav"])
        self.assertEqual([f for f in os.listdir(voices_dir) if f.startswith("cloned_Me")], [])

    def test_delete_rejects_non_cloned_ids(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.delete("/tts/voices/af_heart").status_code, 400)

    def test_delete_rejects_traversal(self):
        with TestClient(server.app) as client:
            response = client.delete("/tts/voices/cloned_..%2F..%2Fetc")
        self.assertIn(response.status_code, (400, 404))

    def test_delete_unknown_is_404(self):
        with TestClient(server.app) as client:
            self.assertEqual(client.delete("/tts/voices/cloned_Nobody").status_code, 404)

    def test_voices_listing_reports_cloning_availability(self):
        with TestClient(server.app) as client:
            payload = client.get("/tts/voices").json()
        self.assertIn("cloning", payload)
        self.assertIn("available", payload["cloning"])


if __name__ == "__main__":
    unittest.main()
