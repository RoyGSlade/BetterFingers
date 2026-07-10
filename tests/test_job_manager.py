"""Central job registry (§6.3): stable ids, an observable state machine,
progress, cooperative cancellation, and bounded retention."""

import unittest

from job_manager import JobManager, JobState, TERMINAL_STATES


class _Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t

    def tick(self, delta=1.0):
        self.t += delta
        return self.t


class JobManagerTests(unittest.TestCase):
    def setUp(self):
        self.clock = _Clock()
        self.jm = JobManager(max_finished=3, clock=self.clock)

    def test_create_defaults(self):
        job = self.jm.create("dictation", label="Dictation", resource_estimate={"ram_mb": 500})
        self.assertEqual(job.state, JobState.QUEUED)
        self.assertEqual(job.kind, "dictation")
        self.assertEqual(job.label, "Dictation")
        self.assertEqual(job.resource_estimate, {"ram_mb": 500})
        self.assertIsNone(job.progress)
        self.assertFalse(job.cancel_requested)
        self.assertEqual(len(job.id), 12)

    def test_label_defaults_to_kind(self):
        job = self.jm.create("tts")
        self.assertEqual(job.label, "tts")

    def test_transition_forward_then_terminal_guard(self):
        job = self.jm.create("dictation")
        self.jm.transition(job.id, JobState.TRANSCRIBING, progress=0.2)
        self.assertEqual(self.jm.get(job.id).state, JobState.TRANSCRIBING)
        self.assertEqual(self.jm.get(job.id).progress, 0.2)

        self.jm.complete(job.id, result_ref="draft:7")
        got = self.jm.get(job.id)
        self.assertEqual(got.state, JobState.COMPLETED)
        self.assertEqual(got.result_ref, "draft:7")
        self.assertTrue(got.is_terminal)

        # No transition (or fail/cancel) escapes a terminal state.
        self.assertIsNone(self.jm.transition(job.id, JobState.REFINING))
        self.assertIsNone(self.jm.fail(job.id, "late"))
        self.assertIsNone(self.jm.cancel(job.id))
        self.assertEqual(self.jm.get(job.id).state, JobState.COMPLETED)

    def test_unknown_state_ignored(self):
        job = self.jm.create("dictation")
        self.assertIsNone(self.jm.transition(job.id, "bogus"))
        self.assertEqual(self.jm.get(job.id).state, JobState.QUEUED)

    def test_unknown_job_id_is_safe(self):
        self.assertIsNone(self.jm.transition("nope", JobState.REFINING))
        self.assertIsNone(self.jm.complete("nope"))
        self.assertFalse(self.jm.request_cancel("nope"))
        self.assertIsNone(self.jm.get("nope"))

    def test_progress_clamped_and_bad_values_ignored(self):
        job = self.jm.create("dictation")
        self.jm.update_progress(job.id, 1.5)
        self.assertEqual(self.jm.get(job.id).progress, 1.0)
        self.jm.update_progress(job.id, -0.3)
        self.assertEqual(self.jm.get(job.id).progress, 0.0)
        self.jm.update_progress(job.id, "nope")  # ignored, not nulled
        self.assertEqual(self.jm.get(job.id).progress, 0.0)

    def test_fail_records_error(self):
        job = self.jm.create("dictation")
        self.jm.fail(job.id, "boom")
        got = self.jm.get(job.id)
        self.assertEqual(got.state, JobState.FAILED)
        self.assertEqual(got.error, "boom")

    def test_cooperative_cancel(self):
        job = self.jm.create("dictation")
        self.jm.transition(job.id, JobState.REFINING)
        self.assertTrue(self.jm.request_cancel(job.id))
        # Signalled but not yet terminal — the worker is still unwinding.
        self.assertTrue(self.jm.is_cancel_requested(job.id))
        self.assertFalse(self.jm.get(job.id).is_terminal)
        self.jm.mark_cancelled(job.id)
        self.assertEqual(self.jm.get(job.id).state, JobState.CANCELLED)

    def test_immediate_cancel(self):
        job = self.jm.create("dictation")
        result = self.jm.cancel(job.id)
        self.assertIsNotNone(result)
        self.assertEqual(self.jm.get(job.id).state, JobState.CANCELLED)
        self.assertTrue(self.jm.get(job.id).cancel_requested)

    def test_list_and_active_only(self):
        a = self.jm.create("dictation")
        b = self.jm.create("tts")
        self.jm.complete(a.id)
        all_jobs = self.jm.list()
        active = self.jm.list(active_only=True)
        self.assertEqual([j["id"] for j in all_jobs], [a.id, b.id])  # insertion order
        self.assertEqual([j["id"] for j in active], [b.id])

    def test_updated_at_advances(self):
        job = self.jm.create("dictation")
        created = self.jm.get(job.id).updated_at
        self.clock.tick(5)
        self.jm.transition(job.id, JobState.REFINING)
        self.assertEqual(self.jm.get(job.id).updated_at, created + 5)

    def test_prune_keeps_active_and_caps_terminal(self):
        active = self.jm.create("dictation")  # never terminal -> never pruned
        finished = []
        for _ in range(6):  # max_finished=3
            j = self.jm.create("tts")
            self.jm.complete(j.id)
            finished.append(j.id)
        ids = [j["id"] for j in self.jm.list()]
        self.assertIn(active.id, ids)
        # Only the newest 3 terminal jobs survive.
        terminal_ids = [j["id"] for j in self.jm.list() if j["state"] in TERMINAL_STATES]
        self.assertEqual(terminal_ids, finished[-3:])

    def test_subscribe_receives_snapshots_and_survives_listener_errors(self):
        events = []
        self.jm.subscribe(lambda snap: events.append((snap["state"], snap["id"])))
        self.jm.subscribe(lambda snap: (_ for _ in ()).throw(RuntimeError("bad listener")))
        job = self.jm.create("dictation")
        self.jm.transition(job.id, JobState.REFINING)
        self.jm.complete(job.id)
        states = [state for state, _ in events]
        self.assertEqual(states, [JobState.QUEUED, JobState.REFINING, JobState.COMPLETED])

    def test_to_public_is_json_safe_shape(self):
        job = self.jm.create("dictation", label="Dictation")
        snap = self.jm.get(job.id).to_public()
        self.assertEqual(
            set(snap.keys()),
            {
                "id", "kind", "label", "state", "progress", "error",
                "result_ref", "resource_estimate", "created_at", "updated_at",
                "cancel_requested",
            },
        )
        # No threading.Event or other non-serialisable objects leak out.
        self.assertNotIn("_cancel", snap)


if __name__ == "__main__":
    unittest.main()
