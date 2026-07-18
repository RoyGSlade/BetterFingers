import os
import tempfile
import time
import types
import unittest
from unittest.mock import MagicMock, patch

import numpy as np
from fastapi.testclient import TestClient

import history_store
import recordings
import routes_wake
import server
import voice_clone_engine


class DummyTranscriber:
    def __init__(self, profile_name="Default", preload=True):
        self.profile_name = profile_name
        self.preload = preload
        self.model = None


class PrivacyWipeTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        server.transcriber = None
        history_store._initialized_path = None
        # Keep the startup warmup thread from loading (and on a fresh data
        # dir, DOWNLOADING) real models: an in-flight .gguf.part download
        # holds an open handle that breaks TemporaryDirectory cleanup on
        # Windows (WinError 32) and wastes CI bandwidth.
        residency_patcher = patch.object(
            server,
            "get_model_residency_settings",
            return_value={"llm": False, "stt": False, "tts": False},
        )
        residency_patcher.start()
        self.addCleanup(residency_patcher.stop)

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        server.transcriber = None
        history_store._initialized_path = None

    def _client(self):
        return TestClient(server.app)

    def _seed_history(self):
        history_store.upsert_draft(
            {
                "id": 1,
                "created_at": "2026-01-01T00:00:00",
                "status": "sent",
                "profile": "Default",
                "raw_text": "hello world",
                "final_text": "Hello world.",
            }
        )

    def _seed_recording(self):
        audio = np.zeros(1600, dtype=np.float32)
        recording_result = types.SimpleNamespace(
            audio_data=audio,
            sample_rate=16000,
            duration_seconds=0.1,
            stop_reason="manual",
        )
        recordings.save_recording(recording_result, rec_id=str(int(time.time() * 1000)))

    def test_wipe_clears_history_db_and_recordings(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            self._seed_history()
            self._seed_recording()

            self.assertTrue(history_store.search("hello"))
            self.assertTrue(recordings.list_recordings())

            with self._client() as client:
                resp = client.post("/privacy/wipe", json={})

            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            cleared = payload["cleared"]
            self.assertTrue(cleared["history_db_wiped"]["ok"])
            self.assertGreaterEqual(cleared["recordings_files_removed"], 1)
            self.assertTrue(payload["postconditions"]["recordings_dir_empty"])

            self.assertEqual(history_store.search("hello"), [])
            self.assertEqual(recordings.list_recordings(), [])

    def test_wipe_with_nothing_to_clear_still_ok(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.post("/privacy/wipe", json={})

            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            cleared = payload["cleared"]
            self.assertTrue(cleared["history_db_wiped"]["ok"])
            self.assertEqual(cleared["recordings_files_removed"], 0)

    def test_privacy_report_lists_history_db_and_recordings(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                resp = client.get("/privacy")

            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()
            names = {loc["name"] for loc in data["data_locations"]}
            self.assertIn("Searchable history (database)", names)
            self.assertIn("Raw audio recordings", names)
            self.assertTrue(data["retention"]["recordings_persisted_to_disk"])

    def test_privacy_report_wake_listener_is_live_truthful(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            with self._client() as client:
                # Disabled by default -- the report must say so, not claim a
                # listener exists.
                resp = client.get("/privacy")
                self.assertFalse(resp.json()["wake_listener"]["active"])
                self.assertFalse(resp.json()["wake_listener"]["persists_audio"])

                with patch.object(routes_wake, "is_wake_listening", return_value=True):
                    resp2 = client.get("/privacy")
                self.assertTrue(resp2.json()["wake_listener"]["active"])

    def test_wipe_stops_wake_listener_before_draining_recorder(self):
        """The wake mic stream is a second, independent audio consumer --
        it must be stopped before (not after/instead of) the recorder drain,
        and the wipe must succeed even though wake word was never enabled
        (idempotent/no-op-safe, not a new failure mode)."""
        call_order = []
        real_stop = routes_wake.stop_wake_listener
        real_drain = server._drain_recorder

        def _tracked_stop():
            call_order.append("wake_listener_stopped")
            return real_stop()

        def _tracked_drain(*args, **kwargs):
            call_order.append("recorder_drained")
            return real_drain(*args, **kwargs)

        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(routes_wake, "stop_wake_listener", side_effect=_tracked_stop), patch.object(
            server, "_drain_recorder", side_effect=_tracked_drain
        ):
            with self._client() as client:
                resp = client.post("/privacy/wipe", json={})

            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            self.assertTrue(payload["cleared"]["wake_listener_stopped"])
            # Only the first two calls are from the wipe itself -- shutdown_event
            # (fired when the TestClient context below exits) also calls
            # stop_wake_listener() as its own safety net and would otherwise
            # append a third entry here.
            self.assertEqual(call_order[:2], ["wake_listener_stopped", "recorder_drained"])


class _FakeTTSEngine:
    """Stand-in for ReviewTTSEngine that only implements the drain surface
    the wipe relies on."""

    def __init__(self, drain_result=None, stop_ok=True):
        self.drain_result = drain_result or {"worker_idle": True, "queue_empty": True}
        self.stop_ok = stop_ok
        self.cache_cleared = True
        self.drain_calls = []
        self.cache_clear_calls = 0
        self.speak = MagicMock(return_value={"ok": True, "queued": True})

    def stop_current(self):
        if not self.stop_ok:
            raise RuntimeError("stop failed")

    def drain(self, timeout=10.0):
        self.drain_calls.append(timeout)
        return dict(self.drain_result)

    def clear_audio_cache(self):
        self.cache_clear_calls += 1
        return self.cache_cleared


class TTSWipeDrainTests(PrivacyWipeTests):
    """The wipe must drain TTS playback and voice-clone conversion, not just
    recordings/history/output — see the P0 finding this closes."""

    def test_wipe_drains_tts_and_reports_postconditions(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            fake = _FakeTTSEngine()
            with patch.object(server, "tts_engine", fake), \
                 patch.object(voice_clone_engine, "wait_for_conversion_idle", return_value=True) as wait_idle, \
                 patch.object(voice_clone_engine, "unload") as unload:
                with self._client() as client:
                    resp = client.post("/privacy/wipe", json={})

            self.assertEqual(resp.status_code, 200, resp.text)
            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            post = payload["postconditions"]
            for key in ("tts_worker_idle", "tts_queue_empty", "tts_playback_stopped",
                        "voice_clone_conversion_idle", "voice_cache_cleared"):
                self.assertTrue(post[key], key)
            self.assertEqual(fake.cache_clear_calls, 1)
            unload.assert_called_once()
            wait_idle.assert_called()

    def test_wipe_aborts_without_deleting_when_tts_wont_quiesce(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            self._seed_history()
            fake = _FakeTTSEngine(drain_result={"worker_idle": False, "queue_empty": True})
            with patch.object(server, "tts_engine", fake):
                with self._client() as client:
                    resp = client.post("/privacy/wipe", json={})

            payload = resp.json()
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"], "tts_did_not_quiesce")
            self.assertTrue(history_store.search("hello"))  # nothing deleted
            self.assertEqual(fake.cache_clear_calls, 0)      # no cache clear before quiesce

    def test_wipe_aborts_when_clone_conversion_wont_finish(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ):
            self._seed_history()
            fake = _FakeTTSEngine()
            with patch.object(server, "tts_engine", fake), \
                 patch.object(voice_clone_engine, "wait_for_conversion_idle", return_value=False):
                with self._client() as client:
                    resp = client.post("/privacy/wipe", json={})

            payload = resp.json()
            self.assertFalse(payload["ok"])
            self.assertEqual(payload["error"], "tts_did_not_quiesce")
            self.assertTrue(history_store.search("hello"))

    def test_wipe_with_no_tts_engine_still_ok(self):
        with patch.dict(os.environ, {"BETTERFINGERS_LAZY_STARTUP": "1"}, clear=False), patch.object(
            server, "Transcriber", DummyTranscriber
        ), patch.object(server, "tts_engine", None), \
             patch.object(voice_clone_engine, "wait_for_conversion_idle", return_value=True):
            with self._client() as client:
                resp = client.post("/privacy/wipe", json={})

            payload = resp.json()
            self.assertTrue(payload["ok"], payload)
            self.assertTrue(payload["postconditions"]["tts_worker_idle"])


class KeyboardReviewTTSGatingTests(unittest.TestCase):
    """The keyboard review-TTS shortcut (speak_text_aloud) must respect the
    same wipe flag and runtime lease as the HTTP TTS routes."""

    def test_speak_text_aloud_refuses_during_wipe(self):
        fake = _FakeTTSEngine()
        server.privacy_wipe_in_progress.set()
        try:
            with patch.object(server, "ensure_tts_initialized", return_value=fake):
                server.speak_text_aloud("secret draft text")
        finally:
            server.privacy_wipe_in_progress.clear()
        fake.speak.assert_not_called()

    def test_speak_text_aloud_holds_tts_read_lease(self):
        fake = _FakeTTSEngine()
        seen = {}

        def record_busy(*args, **kwargs):
            seen["busy_during_speak"] = server.model_runtime.is_busy("tts")
            return {"ok": True}

        fake.speak.side_effect = record_busy
        with patch.object(server, "ensure_tts_initialized", return_value=fake), \
             patch.object(server, "load_profile", return_value={"review_tts_enabled": True}):
            server.speak_text_aloud("hello")
        fake.speak.assert_called_once()
        self.assertTrue(seen.get("busy_during_speak"))

    def test_speak_text_aloud_skips_when_tts_reconfiguring(self):
        # Simulate a concurrent destructive reconfiguration (write lease held)
        # without actually blocking this thread on the real read lease, which
        # would deadlock synchronously against the write lease we're holding.
        fake = _FakeTTSEngine()
        from model_runtime_coordinator import RuntimeBusyError

        with patch.object(server, "ensure_tts_initialized", return_value=fake), \
             patch.object(server, "load_profile", return_value={"review_tts_enabled": True}), \
             patch.object(server.model_runtime, "read_lease", side_effect=RuntimeBusyError("tts busy")):
            server.speak_text_aloud("hello")  # must not raise
        fake.speak.assert_not_called()


if __name__ == "__main__":
    unittest.main()
