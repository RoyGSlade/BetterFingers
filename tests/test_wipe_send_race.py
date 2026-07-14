"""Privacy wipe vs in-flight draft send (the drain handshake).

The wipe must never delete user data while a send is mid-injection, and a send
must never re-persist draft history after the wipe has erased it. The
OutputCoordinator closes both directions: the wipe drains (cancel + wait for
the active-send count to hit zero + exclusive lease) before deleting, aborts
without deleting if sends will not finish, and a send rechecks cancellation
before its final persistence.
"""

import contextlib
import threading
import time
import unittest
from unittest.mock import patch

import server


class WipeSendRaceMixin(unittest.TestCase):
    def setUp(self):
        super().setUp()
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1
        server.privacy_wipe_in_progress.clear()
        server.output_coordinator.release()
        self.addCleanup(server.draft_queue.clear)
        self.addCleanup(server.draft_recordings.clear)
        self.addCleanup(server.pending_manual_send_ids.clear)
        self.addCleanup(server.privacy_wipe_in_progress.clear)
        self.addCleanup(server.output_coordinator.release)

    def _queue_draft(self, draft_id=1, status="pending", **extra):
        draft = {
            "id": draft_id, "status": status, "final_text": "hello world",
            "raw_text": "hello world", "pending_send": False, "send_result": None,
        }
        draft.update(extra)
        with server.draft_lock:
            server.draft_queue.append(draft)
            server.next_draft_id = max(server.next_draft_id, draft_id + 1)
        return draft

    def _wipe_patches(self):
        """Patch the wipe's non-output steps so tests exercise only the
        send/output drain. Returns a list of patcher context managers."""
        class Gate:
            def cancel_active(self):
                pass

            def try_begin(self):
                return True

            def finish(self):
                pass

        return [
            patch.object(server, "_drain_recorder", return_value=True),
            patch.object(server, "dictation_coordinator", Gate()),
            patch.object(server.history_store, "wipe_database",
                         return_value={"ok": True, "recreated": True}),
            patch.object(server.recordings, "clear_recordings", return_value=0),
            patch.object(server.recordings, "list_leftover_files", return_value=[]),
            patch.object(server, "broadcast_status_threadsafe"),
            patch.object(server.os.path, "exists", return_value=False),
            patch.object(server.os, "remove"),
        ]


class WipeWaitsForActiveSendTests(WipeSendRaceMixin):
    def test_wipe_blocks_until_send_finishes_and_send_skips_final_persist(self):
        """The reported P0 sequence: wipe starts mid-send. The wipe must wait
        for the send to finish, and the send must not persist history after
        cancellation was requested."""
        self._queue_draft(1)
        injection_started = threading.Event()
        injection_may_finish = threading.Event()
        saves = []

        def fake_inject(text, action, open_chat=False):
            injection_started.set()
            assert injection_may_finish.wait(timeout=10.0)
            return {"ok": True, "action": "copy_only", "message": "ok"}

        wipe_result = {}

        def run_wipe():
            wipe_result["payload"] = server._perform_privacy_wipe(False)

        patches = self._wipe_patches() + [
            patch.object(server, "save_draft_history",
                         side_effect=lambda changed_draft_id=None: saves.append(changed_draft_id)),
            patch.object(server, "perform_output_action", side_effect=fake_inject),
            patch.object(server, "get_profile_output_settings",
                         return_value={"send_mode": "review_first"}),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            sender = threading.Thread(
                target=server.send_draft_by_id, args=(1,),
                kwargs={"action": "copy_only"})
            sender.start()
            self.assertTrue(injection_started.wait(timeout=10.0))

            wiper = threading.Thread(target=run_wipe)
            wiper.start()
            # The wipe must NOT complete while the send is mid-injection.
            time.sleep(0.3)
            self.assertNotIn("payload", wipe_result)
            self.assertEqual(len(server.draft_queue), 1,
                             "wipe deleted drafts under a live send")

            injection_may_finish.set()
            sender.join(timeout=10.0)
            wiper.join(timeout=10.0)

        self.assertTrue(wipe_result["payload"]["ok"], wipe_result["payload"])
        self.assertEqual(len(server.draft_queue), 0)
        # The send persists exactly once (the pre-injection "sending" marker,
        # changed_draft_id=1); its final persist must have been skipped because
        # cancellation was requested. The wipe's own full-queue save passes
        # changed_draft_id=None and doesn't count here.
        self.assertEqual(saves.count(1), 1,
                         "send re-persisted history during/after the wipe")
        # The drain rollback must not leave sends permanently rejected.
        self.assertFalse(server.output_coordinator.cancel_requested())


class WipeAbortsOnStuckSendTests(WipeSendRaceMixin):
    def test_wipe_aborts_without_deleting_when_send_will_not_finish(self):
        self._queue_draft(1)
        injection_started = threading.Event()
        injection_may_finish = threading.Event()

        def fake_inject(text, action, open_chat=False):
            injection_started.set()
            assert injection_may_finish.wait(timeout=10.0)
            return {"ok": True, "action": "copy_only", "message": "ok"}

        patches = self._wipe_patches() + [
            patch.object(server, "save_draft_history"),
            patch.object(server, "perform_output_action", side_effect=fake_inject),
            patch.object(server, "get_profile_output_settings",
                         return_value={"send_mode": "review_first"}),
            patch.object(server, "OUTPUT_DRAIN_TIMEOUT_SECONDS", 0.2),
        ]
        with contextlib.ExitStack() as stack:
            for p in patches:
                stack.enter_context(p)
            sender = threading.Thread(
                target=server.send_draft_by_id, args=(1,),
                kwargs={"action": "copy_only"})
            sender.start()
            self.assertTrue(injection_started.wait(timeout=10.0))

            payload = server._perform_privacy_wipe(False)

            injection_may_finish.set()
            sender.join(timeout=10.0)

        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"], "output_did_not_quiesce")
        self.assertTrue(payload["stuck_sends"], payload)
        self.assertEqual(len(server.draft_queue), 1,
                         "aborted wipe must not delete drafts")
        # System recovers: flag cleared, sends allowed again.
        self.assertFalse(server.privacy_wipe_in_progress.is_set())
        self.assertFalse(server.output_coordinator.cancel_requested())


class SendRejectedDuringWipeTests(WipeSendRaceMixin):
    def test_send_rejected_while_coordinator_drained(self):
        """Even if the wipe flag were momentarily unobserved, the coordinator
        lease must independently refuse new sends."""
        self._queue_draft(1)
        ok, stuck = server.output_coordinator.drain(timeout=0.5)
        self.assertTrue(ok, stuck)
        try:
            with patch.object(server, "save_draft_history"), \
                    patch.object(server, "perform_output_action") as inject, \
                    patch.object(server, "broadcast_status_threadsafe"):
                response = server.send_draft_by_id(1, action="copy_only")
        finally:
            server.output_coordinator.release()
        self.assertFalse(response.get("ok", True))
        self.assertEqual(response.get("error"), "privacy_wipe_in_progress")
        inject.assert_not_called()
        with server.draft_lock:
            self.assertEqual(server.draft_queue[0]["status"], "pending",
                             "rejected send must not leave the draft 'sending'")


if __name__ == "__main__":
    unittest.main()
