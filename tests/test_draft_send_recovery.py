"""Crash-safe draft sending (deep draft sending).

A send stamps the draft with an operation id + this process's token and persists
"sending" to disk *before* the non-idempotent injection, so a crash mid-send is
detectable. On restart, recover_interrupted_sends() moves any draft left in
"sending" by a dead process to the honest "send_interrupted" state (outcome
unknown) rather than silently reverting it (risking a double paste) or dropping
it. Every terminal send carries an explicit send_outcome class.
"""

import unittest
from unittest.mock import patch

import server


class DraftStateMixin(unittest.TestCase):
    def setUp(self):
        super().setUp()
        server.draft_queue.clear()
        server.draft_recordings.clear()
        server.pending_manual_send_ids.clear()
        server.next_draft_id = 1
        self.addCleanup(server.draft_queue.clear)
        self.addCleanup(server.draft_recordings.clear)
        self.addCleanup(server.pending_manual_send_ids.clear)

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


class PersistBeforeInjectionTests(DraftStateMixin):
    def test_sending_is_persisted_before_injection_runs(self):
        self._queue_draft(1)
        events = []

        def fake_save(changed_draft_id=None):
            d = server.get_draft_by_id(1)
            events.append(("save", d.get("status") if d else None))

        def fake_inject(text, action, open_chat=False):
            d = server.get_draft_by_id(1)
            events.append(("inject", d.get("status")))
            return {"ok": True, "action": "copy_only", "message": "ok"}

        with patch.object(server, "save_draft_history", side_effect=fake_save), \
             patch.object(server, "perform_output_action", side_effect=fake_inject), \
             patch.object(server, "get_profile_output_settings",
                          return_value={"send_mode": "review_first"}), \
             patch.object(server, "broadcast_status_threadsafe"):
            server.send_draft_by_id(1, action="copy_only")

        # A save recorded the "sending" state, and it happened before injection.
        first_sending_save = next(i for i, e in enumerate(events) if e == ("save", "sending"))
        inject_idx = events.index(("inject", "sending"))
        self.assertLess(first_sending_save, inject_idx)


class OutcomeClassTests(DraftStateMixin):
    def _send(self, inject_result=None, inject_exc=None):
        def fake_inject(text, action, open_chat=False):
            if inject_exc is not None:
                raise inject_exc
            return inject_result

        return patch.multiple(
            server,
            save_draft_history=lambda changed_draft_id=None: None,
            perform_output_action=fake_inject,
            get_profile_output_settings=lambda: {"send_mode": "review_first"},
            broadcast_status_threadsafe=lambda *a, **k: None,
        )

    def test_success_sets_outcome_sent_and_clears_token(self):
        self._queue_draft(1)
        with self._send(inject_result={"ok": True, "message": "sent"}):
            resp = server.send_draft_by_id(1, action="copy_only")
        self.assertEqual(resp["status"], "sent")
        self.assertEqual(resp["send_outcome"], "sent")
        self.assertIn("send_operation_id", resp)
        # No longer in flight → the process token is dropped.
        self.assertNotIn("send_process_token", server.get_draft_by_id(1))

    def test_clean_failure_sets_outcome_failed(self):
        self._queue_draft(1)
        with self._send(inject_result={"ok": False, "message": "boom"}):
            resp = server.send_draft_by_id(1, action="copy_only")
        self.assertEqual(resp["status"], "send_error")
        self.assertEqual(resp["send_outcome"], "failed")
        self.assertNotIn("send_process_token", server.get_draft_by_id(1))

    def test_abnormal_interruption_marks_send_interrupted(self):
        self._queue_draft(1)
        with self._send(inject_exc=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt):
                server.send_draft_by_id(1, action="copy_only")
        draft = server.get_draft_by_id(1)
        self.assertEqual(draft["status"], "send_interrupted")
        self.assertEqual(draft["send_outcome"], "interrupted")
        self.assertNotIn("send_process_token", draft)

    def test_interrupted_draft_is_resendable_without_allow_resend(self):
        # A recovered/interrupted draft was never confirmed sent, so a plain
        # resend must proceed (not be rejected as already_sent).
        self._queue_draft(1, status="send_interrupted", send_outcome="interrupted")
        with self._send(inject_result={"ok": True, "message": "sent"}):
            resp = server.send_draft_by_id(1, action="copy_only")
        self.assertEqual(resp["status"], "sent")
        self.assertEqual(resp["send_outcome"], "sent")

    def test_concurrent_send_is_rejected(self):
        # An in-flight "sending" draft rejects a second request instead of
        # double-injecting.
        self._queue_draft(1, status="sending")
        with self._send(inject_result={"ok": True, "message": "sent"}):
            resp = server.send_draft_by_id(1, action="copy_only")
        self.assertFalse(resp["ok"])
        self.assertEqual(resp["error"], "send_in_progress")


class RecoverInterruptedSendsTests(DraftStateMixin):
    def test_stale_sending_from_dead_process_is_reclassified(self):
        self._queue_draft(1, status="sending", send_process_token="dead-process-token",
                           send_operation_id="op-1", pending_send=True)
        with patch.object(server, "save_draft_history") as save:
            recovered = server.recover_interrupted_sends()
        self.assertEqual(recovered, [1])
        draft = server.get_draft_by_id(1)
        self.assertEqual(draft["status"], "send_interrupted")
        self.assertEqual(draft["send_outcome"], "interrupted")
        self.assertFalse(draft["pending_send"])
        self.assertNotIn("send_process_token", draft)
        save.assert_called_once()  # one full mirror, not per-row

    def test_inflight_sending_from_this_process_is_left_alone(self):
        # Same-process token means a genuine in-flight send, not a crash.
        self._queue_draft(1, status="sending",
                          send_process_token=server.SEND_PROCESS_TOKEN)
        with patch.object(server, "save_draft_history"):
            recovered = server.recover_interrupted_sends()
        self.assertEqual(recovered, [])
        self.assertEqual(server.get_draft_by_id(1)["status"], "sending")

    def test_recovery_is_idempotent(self):
        self._queue_draft(1, status="sending", send_process_token="dead")
        with patch.object(server, "save_draft_history"):
            first = server.recover_interrupted_sends()
            second = server.recover_interrupted_sends()
        self.assertEqual(first, [1])
        self.assertEqual(second, [])

    def test_non_sending_drafts_are_untouched(self):
        self._queue_draft(1, status="sent", send_outcome="sent")
        self._queue_draft(2, status="pending")
        with patch.object(server, "save_draft_history") as save:
            recovered = server.recover_interrupted_sends()
        self.assertEqual(recovered, [])
        save.assert_not_called()
        self.assertEqual(server.get_draft_by_id(1)["status"], "sent")
        self.assertEqual(server.get_draft_by_id(2)["status"], "pending")


if __name__ == "__main__":
    unittest.main()
