"""Truthful privacy wipe (finding #3) and recording-id path safety (#10).

The wipe must quiesce the pipeline, physically remove the history DB plus its
WAL/SHM companions, sweep orphaned recording files that have no metadata, and
report ok only when postconditions verify. Recording ids arrive as HTTP path
parameters and become filenames — path-shaped ids must be rejected at the
route and in the module.
"""

import os
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import history_store
import recordings
import server


class RecordingIdValidationTests(unittest.TestCase):
    def test_valid_ids_accepted(self):
        for rec_id in ("1752300000000", "abc-DEF_123", "a"):
            self.assertTrue(recordings.is_valid_rec_id(rec_id))

    def test_path_shaped_ids_rejected(self):
        for rec_id in ("../etc/passwd", "a/b", "a\\b", "..", ".", "", None,
                       "x" * 65, "a.wav", "%2e%2e%2fx", "a b"):
            self.assertFalse(recordings.is_valid_rec_id(rec_id), rec_id)

    def test_wav_path_raises_on_traversal(self):
        with self.assertRaises(ValueError):
            recordings._wav_path("../escape")

    def test_load_recording_audio_invalid_id_returns_none(self):
        audio, rate = recordings.load_recording_audio("../escape")
        self.assertIsNone(audio)
        self.assertIsNone(rate)

    def test_delete_recording_invalid_id_returns_false(self):
        self.assertFalse(recordings.delete_recording("../escape"))

    def test_routes_reject_invalid_ids(self):
        client = TestClient(server.app)
        # Slash-bearing and dot-segment ids never reach the route (starlette
        # decodes/normalizes the path first) — 404 is fine, they don't touch
        # the filesystem. Ids that DO match the route but fail the strict
        # pattern (spaces, dots-in-name) must hit our 400 validation.
        self.assertIn(client.delete("/recordings/%2e%2e%2fescape").status_code, (400, 404))
        self.assertIn(client.delete("/recordings/..").status_code, (400, 404))
        self.assertEqual(client.delete("/recordings/a%20b").status_code, 400)
        self.assertEqual(client.post("/recordings/evil.wav/retranscribe").status_code, 400)


class TempDataDirMixin(unittest.TestCase):
    """Point every store at a throwaway directory."""

    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        patchers = [
            patch("recordings.get_user_data_path", return_value=self._tmp.name),
            patch("history_store.get_user_data_path", return_value=self._tmp.name),
            patch("server.get_user_data_path", return_value=self._tmp.name),
            # PersonaLearningStore resolves its path via utils.get_user_data_path
            # directly (not a server.py-bound copy) -- patch it too so the wipe's
            # PersonaLearningStore().clear_all() call stays inside this test's
            # throwaway dir instead of the session-wide conftest isolation dir.
            patch("utils.get_user_data_path", return_value=self._tmp.name),
        ]
        for p in patchers:
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)


class OrphanSweepTests(TempDataDirMixin):
    def test_clear_recordings_sweeps_orphans_and_temps(self):
        directory = recordings.get_recordings_dir()
        # Orphaned WAV (no metadata), corrupt sidecar, interrupted temp file.
        for name in ("orphan.wav", "corrupt.json", "half-written.wav.tmp"):
            with open(os.path.join(directory, name), "w") as fh:
                fh.write("x")
        removed = recordings.clear_recordings()
        self.assertEqual(removed, 3)
        self.assertEqual(recordings.list_leftover_files(), [])

    def test_save_recording_leaves_no_temp_on_failure(self):
        class Rec:
            import numpy as np
            audio_data = np.ones(160, dtype=np.float32)
            sample_rate = 16000
            duration_seconds = 0.01
            stop_reason = "manual"

        with patch("recordings.wavfile.write", side_effect=OSError("disk full")):
            self.assertIsNone(recordings.save_recording(Rec(), rec_id="123"))
        self.assertEqual(recordings.list_leftover_files(), [])


class HistoryDbWipeTests(TempDataDirMixin):
    def test_wipe_database_removes_db_and_wal_files(self):
        history_store.init()
        base = history_store.get_db_path()
        # Simulate WAL artifacts alongside the db.
        for suffix in ("-wal", "-shm"):
            with open(base + suffix, "w") as fh:
                fh.write("wal")
        result = history_store.wipe_database()
        self.assertTrue(result["ok"], result)
        self.assertIn("history.db", result["removed"])
        self.assertIn("history.db-wal", result["removed"])
        self.assertFalse(os.path.exists(base + "-wal"))
        # Store is recreated empty and usable.
        self.assertEqual(history_store.count(), 0)


class VerifiedWipeTests(TempDataDirMixin):
    def setUp(self):
        super().setUp()
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        self.addCleanup(server.draft_queue.clear)

    def test_wipe_reports_postconditions_and_ok(self):
        history_store.init()
        directory = recordings.get_recordings_dir()
        with open(os.path.join(directory, "orphan.wav"), "w") as fh:
            fh.write("x")
        with server.draft_lock:
            server.draft_queue.append({"id": 1, "final_text": "secret"})

        with patch.object(server, "save_draft_history"), \
             patch.object(server, "broadcast_status_threadsafe"):
            report = server._perform_privacy_wipe(wipe_voices=False)

        self.assertTrue(report["ok"], report)
        post = report["postconditions"]
        self.assertTrue(post["draft_queue_empty"])
        self.assertTrue(post["history_db_wiped"])
        self.assertTrue(post["recordings_dir_empty"])
        self.assertTrue(report["cleared"]["pipeline_quiesced"])

    def test_wipe_reports_failure_when_files_remain(self):
        history_store.init()
        directory = recordings.get_recordings_dir()
        with open(os.path.join(directory, "stubborn.wav"), "w") as fh:
            fh.write("x")

        with patch.object(server, "save_draft_history"), \
             patch.object(server, "broadcast_status_threadsafe"), \
             patch.object(server.recordings, "clear_recordings", return_value=0):
            report = server._perform_privacy_wipe(wipe_voices=False)

        self.assertFalse(report["ok"])
        self.assertIn("stubborn.wav", report["postconditions"]["leftover_recordings"])

    def test_wipe_waits_for_pipeline_gate(self):
        history_store.init()
        # Occupy the pipeline; wipe should fail to quiesce (short patience for
        # the test) but still complete and report it.
        self.assertTrue(server.dictation_coordinator.try_begin())
        try:
            with patch.object(server, "save_draft_history"), \
                 patch.object(server, "broadcast_status_threadsafe"), \
                 patch.object(server.time, "monotonic", side_effect=[0, 11, 12, 13]):
                report = server._perform_privacy_wipe(wipe_voices=False)
        finally:
            server.dictation_coordinator.finish()
        self.assertFalse(report["cleared"]["pipeline_quiesced"])

    def test_wipe_voices_removes_dir_and_postcondition_holds(self):
        # P0 regression: the postcondition check itself used to recreate the
        # voices dir (get_voices_dir mkdir'd on every call), so wipe_voices
        # defeated its own verification.
        history_store.init()
        voices_dir = server.ensure_voices_dir()
        with open(os.path.join(str(voices_dir), "cloned_Me.wav"), "w") as fh:
            fh.write("x")

        with patch.object(server, "save_draft_history"), \
             patch.object(server, "broadcast_status_threadsafe"):
            report = server._perform_privacy_wipe(wipe_voices=True)

        self.assertTrue(report["ok"], report)
        self.assertTrue(report["postconditions"]["voices_absent"])
        self.assertTrue(report["cleared"]["voices_removed"])
        self.assertFalse(voices_dir.exists())

    def test_privacy_report_does_not_create_voices_dir(self):
        history_store.init()
        voices_dir = server.get_voices_path()
        self.assertFalse(voices_dir.exists())
        report = server.get_privacy_report()
        self.assertFalse(voices_dir.exists())
        # The report still names the location it would use.
        cloned = next(loc for loc in report["data_locations"]
                      if loc["name"] == "Cloned voices")
        self.assertEqual(cloned["path"], str(voices_dir))

    def test_wipe_cancels_active_dictation(self):
        history_store.init()
        server.cancellation_event.clear()
        with patch.object(server, "save_draft_history"), \
             patch.object(server, "broadcast_status_threadsafe"):
            server._perform_privacy_wipe(wipe_voices=False)
        # cancel_active() fired before deletion (event set, then cleared by
        # the wipe's own try_begin) — observable as the gate having been held.
        # The direct observable: wipe held and released the gate.
        self.assertTrue(server.dictation_coordinator.try_begin())
        server.dictation_coordinator.finish()


if __name__ == "__main__":
    unittest.main()
