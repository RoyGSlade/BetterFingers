"""Held-recording queue: recordings are never rejected, they wait their turn.

Covers the uninterrupted-dictation batch changes:
- DictationCoordinator.begin() blocks until the running pipeline finishes
  (the dispatcher's admission mode) with the same clear-cancel semantics.
- The dispatcher processes held recordings FIFO and passes each recording's
  streamed transcript into the pipeline.
- Queue overflow falls back to the recovery bin instead of growing RAM.
- A privacy wipe drops held recordings and aborts their streaming sessions;
  a pipeline admitted mid-wipe re-checks the flag and bows out.
"""

import queue
import threading
import time
import unittest
from unittest.mock import patch

import numpy as np

import server
from dictation_coordinator import DictationCoordinator


class FakeRecording:
    def __init__(self, tag):
        self.tag = tag
        self.audio_data = np.ones(1600, dtype=np.float32)
        self.sample_rate = 16000
        self.duration_seconds = 0.1
        self.frame_count = 1
        self.sample_count = 1600
        self.max_amplitude = 1.0
        self.rms_amplitude = 1.0
        self.stop_reason = "manual"


class FakeSession:
    def __init__(self, text):
        self.text = text
        self.aborted = False
        self.finalized = False

    def finalize(self, timeout=120.0):
        self.finalized = True
        return {
            "ok": True,
            "text": self.text,
            "confidence": {"score": 0.9, "avg_logprob": -0.1, "no_speech_prob": 0.02},
            "batches": 2,
            "transcribe_ms_total": 5.0,
        }

    def abort(self):
        self.aborted = True


class BlockingBeginTests(unittest.TestCase):
    def test_begin_waits_for_finish_instead_of_rejecting(self):
        coord = DictationCoordinator()
        self.assertTrue(coord.try_begin())
        acquired = threading.Event()

        def waiter():
            if coord.begin(timeout=5.0):
                acquired.set()
                coord.finish()

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.15)
        self.assertFalse(acquired.is_set())  # still held -> still waiting
        coord.finish()
        self.assertTrue(acquired.wait(timeout=5.0))
        t.join(timeout=5.0)

    def test_begin_times_out_when_gate_stays_held(self):
        coord = DictationCoordinator()
        self.assertTrue(coord.try_begin())
        self.assertFalse(coord.begin(timeout=0.1))
        coord.finish()

    def test_begin_clears_stale_cancel_like_try_begin(self):
        coord = DictationCoordinator()
        coord.cancellation_event.set()
        self.assertTrue(coord.begin(timeout=1.0))
        self.assertFalse(coord.cancellation_event.is_set())
        coord.finish()


class HoldQueueDispatcherTests(unittest.TestCase):
    def test_recordings_process_fifo_with_streamed_text(self):
        processed = []
        done = threading.Event()

        def fake_process(recording_result, streamed_text=None, streamed_confidence=None,
                         streamed_stt_ms=None, wait_for_gate=False):
            processed.append((recording_result.tag, streamed_text, wait_for_gate))
            if len(processed) == 2:
                done.set()

        fresh_queue = queue.Queue()
        with patch.object(server, "_pending_recordings", fresh_queue), \
             patch.object(server, "_recording_dispatcher_thread", None), \
             patch.object(server, "process_recording_result", side_effect=fake_process):
            server._enqueue_recording(FakeRecording("first"), FakeSession("hello there"))
            server._enqueue_recording(FakeRecording("second"), FakeSession("second thought"))
            self.assertTrue(done.wait(timeout=10.0))

        self.assertEqual(
            processed,
            [("first", "hello there", True), ("second", "second thought", True)],
        )

    def test_failed_stream_session_falls_back_to_full_pass(self):
        processed = []
        done = threading.Event()

        def fake_process(recording_result, streamed_text=None, streamed_confidence=None,
                         streamed_stt_ms=None, wait_for_gate=False):
            processed.append(streamed_text)
            done.set()

        class FailedSession(FakeSession):
            def finalize(self, timeout=120.0):
                return {"ok": False, "text": "", "confidence": {}, "batches": 0}

        fresh_queue = queue.Queue()
        with patch.object(server, "_pending_recordings", fresh_queue), \
             patch.object(server, "_recording_dispatcher_thread", None), \
             patch.object(server, "process_recording_result", side_effect=fake_process):
            server._enqueue_recording(FakeRecording("solo"), FailedSession(""))
            self.assertTrue(done.wait(timeout=10.0))

        self.assertEqual(processed, [None])  # dispatcher passed no streamed text

    def test_queue_overflow_saves_to_recovery_and_aborts_session(self):
        session = FakeSession("overflow")
        saved = []
        with patch.object(server, "MAX_PENDING_RECORDINGS", 0), \
             patch.object(server, "_ensure_recording_dispatcher"), \
             patch.object(server.recordings, "save_recording",
                          side_effect=lambda rr, rec_id=None, metadata=None: saved.append(metadata)):
            server._enqueue_recording(FakeRecording("overflow"), session)

        self.assertTrue(session.aborted)
        self.assertEqual(len(saved), 1)
        self.assertEqual(saved[0].get("rejected_reason"), "queue_full")

    def test_privacy_wipe_drops_held_recordings(self):
        sessions = [FakeSession("a"), FakeSession("b")]
        fresh_queue = queue.Queue()
        with patch.object(server, "_pending_recordings", fresh_queue), \
             patch.object(server, "_ensure_recording_dispatcher"):
            server._enqueue_recording(FakeRecording("a"), sessions[0])
            server._enqueue_recording(FakeRecording("b"), sessions[1])
            dropped = server._drop_pending_recordings()
            self.assertEqual(dropped, 2)
            self.assertTrue(fresh_queue.empty())
        self.assertTrue(all(s.aborted for s in sessions))


class WipeRecheckAfterAdmissionTests(unittest.TestCase):
    def tearDown(self):
        server.privacy_wipe_in_progress.clear()
        server.cancellation_event.clear()

    def test_pipeline_admitted_mid_wipe_drops_and_releases_gate(self):
        # Occupy the gate, start a waiting pipeline, then begin a "wipe"
        # before releasing: the waiter must drop the recording and release.
        self.assertTrue(server.dictation_coordinator.try_begin())
        result = {}
        finished = threading.Event()

        def waiter():
            result["draft"] = server.process_recording_result(
                FakeRecording("stale"), wait_for_gate=True
            )
            finished.set()

        t = threading.Thread(target=waiter, daemon=True)
        t.start()
        time.sleep(0.2)  # let the waiter block inside begin()
        server.privacy_wipe_in_progress.set()
        server.dictation_coordinator.finish()

        self.assertTrue(finished.wait(timeout=10.0))
        t.join(timeout=5.0)
        self.assertIsNone(result["draft"])
        # The gate must have been released by the drop path.
        self.assertTrue(server.dictation_coordinator.try_begin())
        server.dictation_coordinator.finish()


if __name__ == "__main__":
    unittest.main()
