"""Single-flight dictation gate, idempotent draft send, whitespace preservation.

Covers the Phase-1 pipeline-safety fixes:
- process_recording_result rejects a competing invocation instead of
  interleaving (and persists the rejected recording to the recovery bin).
- A rejected competitor never clears the running job's cancellation event.
- send_draft_by_id is an atomic ready -> sending -> sent transition; two
  simultaneous sends inject exactly once, and a sent draft is not re-injected
  without allow_resend.
- Output actions preserve the user's whitespace (indentation, trailing
  newlines, deliberate blank lines).
"""

import threading
import time
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

import server
from dictation_coordinator import DictationCoordinator


class DictationCoordinatorTests(unittest.TestCase):
    def test_try_begin_is_exclusive_until_finish(self):
        coord = DictationCoordinator()
        self.assertTrue(coord.try_begin())
        self.assertFalse(coord.try_begin())
        coord.finish()
        self.assertTrue(coord.try_begin())
        coord.finish()

    def test_loser_does_not_clear_pending_cancel(self):
        coord = DictationCoordinator()
        self.assertTrue(coord.try_begin())
        coord.cancel_active()  # user cancels the running job
        self.assertFalse(coord.try_begin())  # competitor rejected...
        self.assertTrue(coord.cancellation_event.is_set())  # ...cancel intact
        coord.finish()

    def test_winner_clears_stale_cancel(self):
        coord = DictationCoordinator()
        coord.cancellation_event.set()
        self.assertTrue(coord.try_begin())
        self.assertFalse(coord.cancellation_event.is_set())
        coord.finish()

    def test_cancel_active_reports_active_job_id(self):
        coord = DictationCoordinator()
        coord.try_begin()
        coord.set_active_job("job-1")
        self.assertEqual(coord.cancel_active(), "job-1")
        coord.finish()
        self.assertIsNone(coord.active_job_id)

    def test_finish_without_begin_does_not_raise(self):
        DictationCoordinator().finish()


class SingleFlightPipelineTests(unittest.TestCase):
    def setUp(self):
        self._save_patcher = patch("server.save_draft_history")
        self._save_patcher.start()
        server.draft_queue.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def tearDown(self):
        self._save_patcher.stop()
        server.draft_queue.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1
        server.cancellation_event.clear()

    def test_busy_pipeline_rejects_and_persists_recording(self):
        saved = []
        statuses = []

        class Rec:
            audio_data = [0.1]
            stop_reason = "manual"

        self.assertTrue(server.dictation_coordinator.try_begin())  # occupy
        try:
            with patch.object(server.recordings, "save_recording",
                              side_effect=lambda rr, rec_id, metadata: saved.append(metadata)), \
                 patch.object(server, "broadcast_status_threadsafe",
                              side_effect=lambda status, payload=None: statuses.append(status)):
                result = server.process_recording_result(Rec())
        finally:
            server.dictation_coordinator.finish()

        self.assertIsNone(result)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].get("rejected_reason"), "pipeline_busy")
        self.assertIn("dictation_busy", statuses)

    def test_rejected_competitor_preserves_cancellation(self):
        class Rec:
            audio_data = [0.1]
            stop_reason = "manual"

        self.assertTrue(server.dictation_coordinator.try_begin())
        try:
            server.cancellation_event.set()  # cancel aimed at the running job
            with patch.object(server.recordings, "save_recording"), \
                 patch.object(server, "broadcast_status_threadsafe"):
                self.assertIsNone(server.process_recording_result(Rec()))
            self.assertTrue(server.cancellation_event.is_set())
        finally:
            server.dictation_coordinator.finish()

    def test_retry_endpoint_returns_409_when_busy(self):
        client = TestClient(server.app)
        with server.draft_lock:
            server.draft_recordings[1] = object.__new__(object)

        self.assertTrue(server.dictation_coordinator.try_begin())
        try:
            with patch.object(server.recordings, "save_recording"), \
                 patch.object(server, "broadcast_status_threadsafe"):
                response = client.post("/drafts/1/retry")
        finally:
            server.dictation_coordinator.finish()
            with server.draft_lock:
                server.draft_recordings.clear()

        self.assertEqual(response.status_code, 409)


class IdempotentSendTests(unittest.TestCase):
    def setUp(self):
        self._save_patcher = patch("server.save_draft_history")
        self._save_patcher.start()
        server.draft_queue.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def tearDown(self):
        self._save_patcher.stop()
        server.draft_queue.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1

    def _make_draft(self, status="pending"):
        with server.draft_lock:
            draft = {"id": 1, "final_text": "hello world", "status": status,
                     "pending_send": False}
            server.draft_queue.append(draft)
        return draft

    def test_concurrent_sends_inject_exactly_once(self):
        self._make_draft()
        injections = []
        first_inject_started = threading.Event()

        def slow_output(text, requested_action, open_chat=False):
            first_inject_started.set()
            time.sleep(0.2)  # hold the "injection" long enough to race
            injections.append(text)
            return {"ok": True, "action": requested_action}

        results = []
        with patch.object(server, "perform_output_action", side_effect=slow_output):
            t1 = threading.Thread(target=lambda: results.append(server.send_draft_by_id(1, action="paste")))
            t1.start()
            first_inject_started.wait(timeout=2)
            results.append(server.send_draft_by_id(1, action="paste"))
            t1.join(timeout=5)

        self.assertEqual(len(injections), 1)
        errors = [r.get("error") for r in results if not r.get("send_result") and r.get("error")]
        self.assertIn("send_in_progress", errors)

    def test_sent_draft_requires_allow_resend(self):
        self._make_draft(status="sent")
        with patch.object(server, "perform_output_action") as out:
            response = server.send_draft_by_id(1, action="paste")
        out.assert_not_called()
        self.assertEqual(response.get("error"), "already_sent")

        with patch.object(server, "perform_output_action",
                          return_value={"ok": True, "action": "paste"}) as out:
            response = server.send_draft_by_id(1, action="paste", allow_resend=True)
        out.assert_called_once()
        self.assertEqual(response.get("status"), "sent")

    def test_send_error_leaves_draft_retryable(self):
        self._make_draft()
        with patch.object(server, "perform_output_action",
                          return_value={"ok": False, "message": "boom"}):
            response = server.send_draft_by_id(1, action="paste")
        self.assertEqual(response.get("status"), "send_error")
        # A retry after failure must not be blocked.
        with patch.object(server, "perform_output_action",
                          return_value={"ok": True, "action": "paste"}):
            response = server.send_draft_by_id(1, action="paste")
        self.assertEqual(response.get("status"), "sent")

    def test_exception_during_send_restores_status(self):
        self._make_draft()
        with patch.object(server, "perform_output_action", side_effect=RuntimeError("boom")):
            with self.assertRaises(RuntimeError):
                server.send_draft_by_id(1, action="paste")
        with server.draft_lock:
            self.assertEqual(server.get_draft_by_id(1).get("status"), "pending")


class WhitespacePreservationTests(unittest.TestCase):
    def test_copy_only_preserves_whitespace(self):
        text = "    indented code\n\nsecond paragraph\n\n"
        copied = []
        with patch.object(server, "copy_text_to_clipboard",
                          side_effect=lambda t: (copied.append(t) or {"ok": True, "action": "copy_only"})):
            payload = server.perform_output_action(text, "copy_only")
        self.assertTrue(payload["ok"])
        self.assertEqual(copied, [text])

    def test_whitespace_only_text_is_still_rejected(self):
        payload = server.perform_output_action("   \n\n  ", "copy_only")
        self.assertFalse(payload["ok"])
        self.assertEqual(payload.get("error"), "empty_text")

    def test_injector_compose_preserves_whitespace(self):
        from injector import InputInjector
        injector = InputInjector.__new__(InputInjector)
        injector.config = {}
        text = "  def f():\n      return 1\n\n"
        self.assertEqual(injector._compose_output_text(text), text)

    def test_injector_compose_appends_sign_off_without_stripping(self):
        from injector import InputInjector
        injector = InputInjector.__new__(InputInjector)
        injector.config = {"sign_off_text": "-- sent by voice"}
        self.assertEqual(
            injector._compose_output_text("hello\n"),
            "hello\n -- sent by voice",
        )

    def test_injector_compose_rejects_whitespace_only(self):
        from injector import InputInjector
        injector = InputInjector.__new__(InputInjector)
        injector.config = {}
        self.assertEqual(injector._compose_output_text("   \n "), "")


if __name__ == "__main__":
    unittest.main()
