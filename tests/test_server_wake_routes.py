"""Route-behavior tests for routes_wake.py. Detector construction and the
mic stream are both mocked -- no real ONNX models, no real audio hardware.
tests/conftest.py already isolates APPDATA/XDG dirs and seeds a
residency-off Default.yaml + lazy startup for the whole suite, so this file
only resets wake-specific module state per test.
"""
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import routes_wake
import server
import wake_word


class _StubInputStream:
    """sounddevice.InputStream-shaped stub; no real audio hardware touched."""

    instances = []

    def __init__(self, samplerate, device, channels, dtype, blocksize, callback):
        self.callback = callback
        self.started = False
        self.closed = False
        _StubInputStream.instances.append(self)

    def start(self):
        self.started = True

    def stop(self):
        self.started = False

    def close(self):
        self.closed = True


class _StubDetector(wake_word.WakeDetector):
    def __init__(self, score=0.0):
        self.score = score

    def predict(self, audio_chunk, sample_rate):
        return {"detected": False, "score": self.score, "label": "stub"}


class WakeRoutesTests(unittest.TestCase):
    def setUp(self):
        routes_wake.stop_wake_listener()
        _StubInputStream.instances = []
        server.transcriber = None
        routes_wake._training_state.update(
            {"status": "idle", "percent": 0, "message": "", "result": None}
        )

    def tearDown(self):
        routes_wake.stop_wake_listener()
        server.transcriber = None

    def _client(self):
        return TestClient(server.app)

    def test_status_disabled_by_default(self):
        with self._client() as client:
            r = client.get("/wake/status")
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["enabled"])
        self.assertFalse(body["listening"])

    def test_enable_reports_unavailable_when_no_classifier(self):
        with patch(
            "wake_word.build_openwakeword_detector",
            return_value=(None, False, "unavailable: no wake-phrase classifier selected"),
        ):
            with self._client() as client:
                r = client.post("/wake/enable", json={})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["available"])
        self.assertIn("unavailable", body["reason"])

    def test_enable_starts_listener_and_status_reflects_it(self):
        detector = _StubDetector()
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _StubInputStream
        ):
            with self._client() as client:
                r = client.post("/wake/enable", json={"classifier_id": "hey_fingers"})
                self.assertEqual(r.status_code, 200)
                body = r.json()
                self.assertTrue(body["ok"])
                self.assertTrue(body["listening"])

                r2 = client.get("/wake/status")
                self.assertTrue(r2.json()["listening"])
                # Check while the app is still "running" -- shutdown_event
                # (which now also stops the wake listener) fires when the
                # TestClient context exits.
                self.assertTrue(_StubInputStream.instances[0].started)

    def test_double_enable_is_idempotent_one_stream(self):
        detector = _StubDetector()
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _StubInputStream
        ):
            with self._client() as client:
                client.post("/wake/enable", json={})
                r = client.post("/wake/enable", json={})
        self.assertTrue(r.json().get("already_enabled"))
        self.assertEqual(len(_StubInputStream.instances), 1)

    def test_disable_closes_stream(self):
        detector = _StubDetector()
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _StubInputStream
        ):
            with self._client() as client:
                client.post("/wake/enable", json={})
                r = client.post("/wake/disable")
        self.assertTrue(r.json()["ok"])
        self.assertFalse(r.json()["listening"])
        self.assertTrue(_StubInputStream.instances[0].closed)

    def test_enable_start_failure_reports_unavailable(self):
        class _BoomStream(_StubInputStream):
            def __init__(self, *a, **kw):
                raise RuntimeError("device busy")

        detector = _StubDetector()
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _BoomStream
        ):
            with self._client() as client:
                r = client.post("/wake/enable", json={})
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertFalse(body["available"])

    def test_stop_wake_listener_is_the_privacy_wipe_quiesce_hook(self):
        """server.py's privacy-wipe path calls routes_wake.stop_wake_listener()
        directly (not via HTTP) -- verify it fully closes the stream."""
        detector = _StubDetector()
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _StubInputStream
        ):
            with self._client() as client:
                client.post("/wake/enable", json={})
                self.assertTrue(routes_wake.is_wake_listening())
                routes_wake.stop_wake_listener()
                self.assertFalse(routes_wake.is_wake_listening())
        self.assertTrue(_StubInputStream.instances[0].closed)

    def test_models_list_reflects_catalog(self):
        with self._client() as client:
            r = client.get("/wake/models")
        ids = {m["id"] for m in r.json()["models"]}
        self.assertIn("melspectrogram", ids)
        self.assertIn("embedding_model", ids)

    def test_models_download_starts_background_job(self):
        with patch("wake_models.download_wake_model") as mock_dl:
            mock_dl.side_effect = lambda model_id: time.sleep(0.05)
            with self._client() as client:
                r = client.post("/wake/models/melspectrogram/download")
                self.assertEqual(r.status_code, 200)
                self.assertTrue(r.json()["background"])
                time.sleep(0.2)
        mock_dl.assert_called_once_with("melspectrogram")

    def test_models_download_unknown_id_400(self):
        with self._client() as client:
            r = client.post("/wake/models/not_a_real_model/download")
        self.assertEqual(r.status_code, 400)

    def test_failed_download_is_preserved_in_state(self):
        # A failing download must leave a queryable record (status=failed +
        # error), not vanish the instant the thread exits.
        routes_wake._download_jobs.pop("melspectrogram", None)
        with patch("wake_models.download_wake_model", side_effect=RuntimeError("network down")):
            with self._client() as client:
                r = client.post("/wake/models/melspectrogram/download")
                self.assertTrue(r.json()["background"])
                # Poll until the thread finishes and writes its terminal state.
                deadline = time.time() + 3.0
                state = None
                while time.time() < deadline:
                    state = client.get("/wake/models/melspectrogram/download-state").json()
                    if not state["active"]:
                        break
                    time.sleep(0.02)
        self.assertFalse(state["active"])
        self.assertFalse(state["downloaded"])
        self.assertEqual(state["error"], "network down")
        with routes_wake._download_jobs_lock:
            job = routes_wake._download_jobs.get("melspectrogram")
        self.assertIsNotNone(job)  # not deleted on failure
        self.assertEqual(job["status"], "failed")

    def test_download_state_reports_truthful_downloaded(self):
        # download-state's "downloaded" reflects loadability, not mere presence.
        with patch(
            "wake_models.backbone_status",
            return_value={"downloaded": True, "verified": False, "loadable": False, "error": "digest_mismatch"},
        ):
            with self._client() as client:
                state = client.get("/wake/models/melspectrogram/download-state").json()
        self.assertFalse(state["downloaded"])
        self.assertTrue(state["present"])
        self.assertFalse(state["verified"])
        self.assertEqual(state["error"], "digest_mismatch")

    def test_import_model_route_round_trip(self):
        with self._client() as client:
            r = client.post(
                "/wake/models/import",
                data={"name": "My Model"},
                files={"file": ("classifier.onnx", b"tiny classifier bytes", "application/octet-stream")},
            )
            self.assertEqual(r.status_code, 200, r.text)
            body = r.json()
            self.assertEqual(body["license"], "user-provided")
            self.assertEqual(body["origin"], "user-imported")

            r2 = client.get("/wake/models")
            ids = {m["id"] for m in r2.json()["models"]}
            self.assertIn(body["id"], ids)

            r3 = client.delete(f"/wake/models/{body['id']}")
            self.assertEqual(r3.status_code, 200)

            r4 = client.get("/wake/models")
            ids_after = {m["id"] for m in r4.json()["models"]}
            self.assertNotIn(body["id"], ids_after)

    def test_import_model_rejects_oversized_file(self):
        import wake_models

        payload = b"x" * (wake_models.MAX_IMPORT_BYTES + 1)
        with self._client() as client:
            r = client.post(
                "/wake/models/import",
                data={"name": "Too Big"},
                files={"file": ("classifier.onnx", payload, "application/octet-stream")},
            )
        self.assertEqual(r.status_code, 400)

    def test_delete_unknown_imported_model_404(self):
        with self._client() as client:
            r = client.delete("/wake/models/does_not_exist")
        self.assertEqual(r.status_code, 404)

    def test_wake_test_route_reports_score_peaks(self):
        detector = _StubDetector(score=0.42)
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _StubInputStream
        ):
            with self._client() as client:
                r = client.post("/wake/test", json={"duration_s": 0.02})
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body["ok"])
        self.assertAlmostEqual(body["duration_s"], 0.02)
        # A temporary listener was spun up for the test window and torn down.
        self.assertTrue(_StubInputStream.instances[0].closed)

    def test_wake_test_reuses_already_enabled_listener(self):
        detector = _StubDetector(score=0.1)
        with patch("wake_word.build_openwakeword_detector", return_value=(detector, True, "ready")), patch(
            "sounddevice.InputStream", _StubInputStream
        ):
            with self._client() as client:
                client.post("/wake/enable", json={})
                r = client.post("/wake/test", json={"duration_s": 0.02})
                self.assertTrue(r.json()["ok"])
                # Reused the already-running listener -- only one stream, still open.
                self.assertEqual(len(_StubInputStream.instances), 1)
                self.assertFalse(_StubInputStream.instances[0].closed)

    def _await_training_done(self, client, timeout=5.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            body = client.get("/wake/train/status").json()
            if body["status"] == "done":
                return body
            time.sleep(0.02)
        self.fail("training did not complete in time")

    def test_train_route_runs_and_registers(self):
        fake = {"ok": True, "verdict": "reliable", "threshold": 0.5,
                "model_id": "trained_123", "n_pos": 40, "n_neg": 80}
        with patch.object(server, "ensure_tts_initialized", return_value=object()), patch(
            "wake_training_service.preflight_training", return_value={"ok": True}
        ), patch(
            "wake_training_service.train_phrase_model", return_value=fake
        ) as train:
            with self._client() as client:
                start = client.post("/wake/train", json={"phrase": "hey fingers"})
                self.assertTrue(start.json()["started"])
                body = self._await_training_done(client)
        self.assertTrue(body["result"]["ok"])
        self.assertEqual(body["result"]["model_id"], "trained_123")
        # The phrase reached the trainer (via the background thread).
        self.assertEqual(train.call_args.args[0], "hey fingers")

    def test_train_preflight_failure_returns_reason_without_starting(self):
        # A failed preflight returns the exact reason immediately and never
        # flips training into the running state.
        with patch.object(server, "ensure_tts_initialized", return_value=object()), patch(
            "wake_training_service.preflight_training",
            return_value={"ok": False, "message": "Wake backbone not ready: melspectrogram is not downloaded."},
        ), patch("wake_training_service.train_phrase_model") as train:
            with self._client() as client:
                r = client.post("/wake/train", json={"phrase": "hey fingers"})
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("backbone", body["message"].lower())
        train.assert_not_called()
        self.assertEqual(routes_wake._training_state["status"], "idle")

    def test_train_threads_user_recordings_to_trainer(self):
        import base64
        import io
        import wave

        import numpy as np

        def _wav_b64(samples):
            buf = io.BytesIO()
            with wave.open(buf, "wb") as handle:
                handle.setnchannels(1)
                handle.setsampwidth(2)
                handle.setframerate(16000)
                handle.writeframes((np.asarray(samples) * 32767).astype("<i2").tobytes())
            return base64.b64encode(buf.getvalue()).decode("ascii")

        positive = _wav_b64(np.ones(1600, dtype=np.float32) * 0.5)
        fake = {"ok": True, "verdict": "reliable", "model_id": "trained_9"}
        with patch.object(server, "ensure_tts_initialized", return_value=object()), patch(
            "wake_training_service.preflight_training", return_value={"ok": True}
        ), patch("wake_training_service.train_phrase_model", return_value=fake) as train:
            with self._client() as client:
                start = client.post(
                    "/wake/train", json={"phrase": "hey fingers", "positive_clips": [positive]}
                )
                self.assertTrue(start.json()["started"])
                self._await_training_done(client)
        clips = train.call_args.kwargs["user_positive_clips"]
        self.assertIsNotNone(clips)
        self.assertEqual(len(clips), 1)
        self.assertEqual(int(clips[0].shape[0]), 1600)

    def test_train_bad_recording_is_400(self):
        with self._client() as client:
            r = client.post(
                "/wake/train", json={"phrase": "hey fingers", "positive_clips": ["not-a-wav!!"]}
            )
        self.assertEqual(r.status_code, 400)

    def test_train_empty_phrase_400(self):
        with self._client() as client:
            r = client.post("/wake/train", json={"phrase": "   "})
        self.assertEqual(r.status_code, 400)

    def test_train_already_running_is_guarded(self):
        routes_wake._training_state.update({"status": "running", "percent": 20})
        with self._client() as client:
            r = client.post("/wake/train", json={"phrase": "hey fingers"})
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertTrue(body["already_running"])

    def test_train_failure_surfaces_in_status(self):
        fail = {"ok": False, "message": "Wake backbone not ready."}
        with patch.object(server, "ensure_tts_initialized", return_value=object()), patch(
            "wake_training_service.preflight_training", return_value={"ok": True}
        ), patch(
            "wake_training_service.train_phrase_model", return_value=fail
        ):
            with self._client() as client:
                client.post("/wake/train", json={"phrase": "hey fingers"})
                body = self._await_training_done(client)
        self.assertFalse(body["result"]["ok"])
        self.assertIn("backbone", body["result"]["message"].lower())

    def test_wake_test_unavailable_when_no_classifier(self):
        with patch(
            "wake_word.build_openwakeword_detector",
            return_value=(None, False, "unavailable: no wake-phrase classifier selected"),
        ):
            with self._client() as client:
                r = client.post("/wake/test", json={"duration_s": 0.02})
        body = r.json()
        self.assertFalse(body["ok"])
        self.assertIn("unavailable", body["reason"])


if __name__ == "__main__":
    unittest.main()
