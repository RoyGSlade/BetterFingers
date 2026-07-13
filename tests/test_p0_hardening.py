"""P0 hardening: privacy-wipe lifecycle, SQLite recreation, recording rollback,
dictation-coordinator leases, and FastAPI-lifespan auth.

Covers the second-round review checklist items that harden work already on
main. Grouped by subsystem.
"""

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import dictation_coordinator as dc
import history_store
import recordings
import server


# --------------------------------------------------------------------------- #
# SQLite wipe + recreation
# --------------------------------------------------------------------------- #
class SqliteRecreationTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = patch("history_store.get_user_data_path", return_value=self._tmp.name)
        p.start()
        self.addCleanup(p.stop)
        # Reset module cache so each test rebuilds against the temp dir.
        history_store._initialized_path = None
        history_store._write_count = 0

    def test_wipe_resets_cache_and_recreates_verified_schema(self):
        history_store.init()
        history_store.upsert_draft({"id": 1, "status": "x", "raw_text": "hi", "final_text": "hi"})
        self.assertEqual(history_store.count(), 1)
        result = history_store.wipe_database()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["recreated"])
        self.assertIn("history.db", result["removed"])
        # Critical: after wipe the schema is really back (the old bug left a
        # schemaless file because _initialized_path was stale).
        self.assertEqual(history_store.count(), 0)
        history_store.upsert_draft({"id": 2, "status": "x", "raw_text": "yo", "final_text": "yo"})
        self.assertEqual(history_store.count(), 1)

    def test_verify_schema_detects_missing_tables(self):
        history_store.init()
        base = history_store.get_db_path()
        # Corrupt the DB into a schemaless state.
        with history_store._lock:
            import sqlite3
            conn = sqlite3.connect(base)
            conn.execute("DROP TABLE drafts")
            conn.commit()
            conn.close()
        schema = history_store.verify_schema()
        self.assertFalse(schema["ok"])
        self.assertFalse(schema["drafts_table"])

    def test_verify_schema_roundtrips_on_healthy_empty_db(self):
        history_store.init()
        schema = history_store.verify_schema()
        self.assertTrue(schema["ok"])
        self.assertTrue(schema["roundtrip"])
        self.assertEqual(history_store.count(), 0)  # empty != broken


# --------------------------------------------------------------------------- #
# Recording persistence: UUID ids + atomic pair with rollback
# --------------------------------------------------------------------------- #
class _Rec:
    import numpy as _np
    audio_data = _np.ones(320, dtype=_np.float32)
    sample_rate = 16000
    duration_seconds = 0.02
    stop_reason = "manual"


class RecordingRollbackTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        p = patch("recordings.get_user_data_path", return_value=self._tmp.name)
        p.start()
        self.addCleanup(p.stop)

    def test_new_rec_id_is_valid_and_unique(self):
        ids = {recordings.new_rec_id() for _ in range(1000)}
        self.assertEqual(len(ids), 1000)
        for rid in list(ids)[:20]:
            self.assertTrue(recordings.is_valid_rec_id(rid))

    def test_rollback_when_second_promote_fails_leaves_no_orphan(self):
        real_replace = os.replace
        calls = {"n": 0}

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] == 2:  # metadata promotion fails
                raise OSError("disk full")
            return real_replace(src, dst)

        with patch("recordings.os.replace", side_effect=flaky_replace):
            result = recordings.save_recording(_Rec(), rec_id=recordings.new_rec_id())
        self.assertIsNone(result)
        # No orphan WAV, no orphan meta, no leftover temp.
        self.assertEqual(recordings.list_leftover_files(), [])

    def test_duplicate_id_is_refused(self):
        rid = recordings.new_rec_id()
        first = recordings.save_recording(_Rec(), rec_id=rid)
        self.assertIsNotNone(first)
        second = recordings.save_recording(_Rec(), rec_id=rid)
        self.assertIsNone(second)  # would clobber the existing pair

    def test_concurrent_saves_all_succeed_with_unique_ids(self):
        results = []
        lock = threading.Lock()

        def worker():
            r = recordings.save_recording(_Rec(), rec_id=recordings.new_rec_id())
            with lock:
                results.append(r)

        threads = [threading.Thread(target=worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(sum(1 for r in results if r), 8)
        # 8 recordings -> 16 files, no temps.
        self.assertEqual(len(recordings.list_leftover_files()), 16)


# --------------------------------------------------------------------------- #
# Dictation coordinator: leases, idempotent finish, guaranteed release
# --------------------------------------------------------------------------- #
class DictationLeaseTests(unittest.TestCase):
    def test_session_admits_one_and_releases_on_exit(self):
        coord = dc.DictationCoordinator()
        with coord.session() as lease:
            self.assertTrue(lease.admitted)
            with coord.session() as inner:
                self.assertFalse(inner.admitted)  # single-flight
        # Released — a fresh session is admitted again.
        with coord.session() as lease:
            self.assertTrue(lease.admitted)

    def test_session_releases_even_when_body_raises(self):
        coord = dc.DictationCoordinator()
        with self.assertRaises(ValueError):
            with coord.session() as lease:
                self.assertTrue(lease.admitted)
                raise ValueError("boom during job setup")
        self.assertFalse(coord.is_busy())
        self.assertTrue(coord.try_begin())
        coord.finish()

    def test_double_finish_is_ignored(self):
        coord = dc.DictationCoordinator()
        self.assertTrue(coord.try_begin())
        coord.finish()
        # Second finish must not blow up or release a gate we no longer hold.
        coord.finish()
        self.assertTrue(coord.try_begin())
        coord.finish()

    def test_stale_token_finish_does_not_release_new_holder(self):
        coord = dc.DictationCoordinator()
        with coord.session() as first:
            stale = first.token
        # A new holder acquires; the old lease's finish(token) must be a no-op.
        self.assertTrue(coord.try_begin())
        coord.finish(token=stale)  # stale -> ignored
        self.assertTrue(coord.is_busy())  # still held by the new owner
        coord.finish()


class ProcessGateLeakTests(unittest.TestCase):
    def setUp(self):
        server.draft_queue.clear()
        self.addCleanup(server.draft_queue.clear)
        server.dictation_coordinator.cancellation_event.clear()

    def test_job_creation_failure_releases_gate(self):
        class Rec:
            import numpy as _np
            audio_data = _np.ones(320, dtype=_np.float32)
            sample_rate = 16000
            duration_seconds = 0.02
            stop_reason = "manual"

        with patch.object(server.JOBS, "create", side_effect=RuntimeError("registry down")), \
             patch.object(server.recordings, "save_recording"), \
             patch.object(server, "broadcast_status_threadsafe"):
            out = server.process_recording_result(Rec())
        self.assertIsNone(out)
        # The gate must be free for the next dictation despite the failure.
        self.assertFalse(server.dictation_coordinator.is_busy())
        self.assertFalse(server.is_processing_draft)


# --------------------------------------------------------------------------- #
# Privacy wipe lifecycle
# --------------------------------------------------------------------------- #
class WipeLifecycleTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        for target in ("recordings.get_user_data_path", "history_store.get_user_data_path",
                       "server.get_user_data_path"):
            p = patch(target, return_value=self._tmp.name)
            p.start()
            self.addCleanup(p.stop)
        history_store._initialized_path = None
        server.draft_queue.clear()
        self.addCleanup(server.draft_queue.clear)
        self.addCleanup(server.privacy_wipe_in_progress.clear)

    def test_recording_dropped_while_wipe_in_progress(self):
        server.privacy_wipe_in_progress.set()
        try:
            with patch.object(server, "broadcast_status_threadsafe"), \
                 patch.object(server.recordings, "save_recording") as save:
                out = server.process_recording_result(_Rec())
            self.assertIsNone(out)
            save.assert_not_called()  # no recovery save during a wipe
        finally:
            server.privacy_wipe_in_progress.clear()

    def test_wipe_aborts_and_deletes_nothing_when_pipeline_wont_quiesce(self):
        history_store.init()
        with server.draft_lock:
            server.draft_queue.append({"id": 1, "final_text": "secret", "status": "pending"})
        # Occupy the gate so the wipe cannot acquire it, and fast-forward time
        # so the 10s quiesce window elapses immediately.
        self.assertTrue(server.dictation_coordinator.try_begin())
        try:
            with patch.object(server, "save_draft_history"), \
                 patch.object(server, "broadcast_status_threadsafe"), \
                 patch.object(server.time, "sleep"), \
                 patch.object(server.time, "monotonic", side_effect=[0, 5, 11, 12, 13, 14]):
                report = server._perform_privacy_wipe(wipe_voices=False)
        finally:
            server.dictation_coordinator.finish()
        self.assertFalse(report["ok"])
        self.assertEqual(report["error"], "pipeline_did_not_quiesce")
        # Nothing was deleted — the draft is still queued.
        self.assertEqual(len(server.draft_queue), 1)
        # And the flag was cleared so the app keeps working.
        self.assertFalse(server.privacy_wipe_in_progress.is_set())

    def test_successful_wipe_reports_full_criteria(self):
        history_store.init()
        with server.draft_lock:
            server.draft_queue.append({"id": 1, "final_text": "secret", "status": "pending"})
        with patch.object(server, "save_draft_history"), \
             patch.object(server, "broadcast_status_threadsafe"):
            report = server._perform_privacy_wipe(wipe_voices=False)
        self.assertTrue(report["ok"], report)
        post = report["postconditions"]
        for key in ("recorder_stopped", "recording_callback_drained", "pipeline_quiesced",
                    "output_injector_idle", "draft_queue_empty", "history_file_absent",
                    "history_db_recreated", "recordings_dir_empty"):
            self.assertTrue(post[key], f"{key} should hold")
        self.assertFalse(server.privacy_wipe_in_progress.is_set())


# --------------------------------------------------------------------------- #
# Sidecar auth: lifespan enforcement + rate limit
# --------------------------------------------------------------------------- #
class LifespanAuthTests(unittest.TestCase):
    def test_production_without_token_raises_outside_tests(self):
        # Simulate a real (non-test) production launch.
        with patch.object(server, "_is_test_env", return_value=False), \
             patch.dict(os.environ, {"BETTERFINGERS_ENV": "production"}, clear=False):
            os.environ.pop("BETTERFINGERS_AUTH_TOKEN", None)
            with self.assertRaises(RuntimeError):
                server.enforce_startup_security()

    def test_dev_without_token_generates_and_publishes(self):
        with patch.object(server, "_is_test_env", return_value=False), \
             patch.dict(os.environ, {"BETTERFINGERS_ENV": "development"}, clear=False):
            os.environ.pop("BETTERFINGERS_AUTH_TOKEN", None)
            try:
                result = server.enforce_startup_security()
                self.assertTrue(result["generated"])
                self.assertEqual(os.environ["BETTERFINGERS_AUTH_TOKEN"], result["token"])
                self.assertEqual(server.app.state.auth_token, result["token"])
            finally:
                os.environ.pop("BETTERFINGERS_AUTH_TOKEN", None)

    def test_auth_failures_get_rate_limited(self):
        server._auth_failures.clear()
        client = TestClient(server.app)
        with patch.dict(os.environ, {"BETTERFINGERS_AUTH_TOKEN": "the-secret"}):
            statuses = [
                client.get("/health", headers={"Authorization": "Bearer nope"}).status_code
                for _ in range(server._AUTH_FAIL_LIMIT + 5)
            ]
        self.assertIn(401, statuses)
        self.assertIn(429, statuses)  # throttled once the window fills
        server._auth_failures.clear()


if __name__ == "__main__":
    unittest.main()
