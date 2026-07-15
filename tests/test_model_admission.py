"""Resource ledger + admission control on ModelRuntimeCoordinator (DESIGN.md M6).

Admission must never OOM-crash the app: a load that doesn't fit evicts
idle/non-pinned components (LRU) through their registered evictor, and only
refuses — with a payload naming resident models — once nothing evictable is
left. All fake components; zero real model loads.
"""

import threading
import time
import unittest

import model_runtime_coordinator as mrc


class _FakeAvailable:
    """Injectable available_mb_fn: a queue of values, or a single fixed value
    once the queue is drained — lets tests simulate real-world drift between
    an eviction's *estimated* freed_mb and what psutil actually reports."""

    def __init__(self, *values):
        self._values = list(values)
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if len(self._values) > 1:
            return self._values.pop(0)
        return self._values[0]


def _coordinator(available_mb, ram_floor_mb=1500):
    fn = available_mb if callable(available_mb) else _FakeAvailable(available_mb)
    return mrc.ModelRuntimeCoordinator(available_mb_fn=fn, ram_floor_mb=ram_floor_mb), fn


class LedgerTests(unittest.TestCase):
    def test_note_loaded_populates_ledger(self):
        c, _ = _coordinator(10000)
        c.note_loaded("llm", "gemma-4-e2b-q4", 3500)
        snap = c.resources_snapshot()
        self.assertEqual(snap["ledger"]["llm"]["model_id"], "gemma-4-e2b-q4")
        self.assertEqual(snap["ledger"]["llm"]["estimated_mb"], 3500)
        self.assertFalse(snap["ledger"]["llm"]["pinned"])
        self.assertIsNone(snap["ledger"]["stt"])

    def test_note_unloaded_clears_entry(self):
        c, _ = _coordinator(10000)
        c.note_loaded("stt", "base.en", 500)
        c.note_unloaded("stt")
        self.assertIsNone(c.resources_snapshot()["ledger"]["stt"])

    def test_set_pinned_reflected_in_snapshot_and_existing_entry(self):
        c, _ = _coordinator(10000)
        c.note_loaded("llm", "m", 100)
        c.set_pinned("llm", True)
        snap = c.resources_snapshot()
        self.assertTrue(snap["pinned"]["llm"])
        self.assertTrue(snap["ledger"]["llm"]["pinned"])

    def test_read_lease_touches_last_used(self):
        c, _ = _coordinator(10000)
        c.note_loaded("tts", "kokoro", 400)
        stale_ts = c._ledger["tts"].last_used - 1000
        c._ledger["tts"].last_used = stale_ts
        with c.read_lease("tts"):
            pass
        self.assertGreater(c._ledger["tts"].last_used, stale_ts)

    def test_unknown_component_raises(self):
        c, _ = _coordinator(10000)
        with self.assertRaises(KeyError):
            c.note_loaded("gpu", "x", 1)


class AdmissionAcceptTests(unittest.TestCase):
    def test_allows_when_headroom_sufficient(self):
        c, _ = _coordinator(8000)
        result = c.request_admission("llm", 2000)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["evicted"], [])
        self.assertIsNone(result["refusal"])

    def test_never_blocks_when_ram_telemetry_unavailable(self):
        c, _ = _coordinator(None)
        result = c.request_admission("llm", 999999)
        self.assertTrue(result["allowed"])
        self.assertIsNone(result["refusal"])

    def test_self_credit_on_replacement(self):
        # 4000 MB free, floor 1500 -> only 2500 MB is actually loadable
        # headroom. Replacing the SAME component's own 3000 MB model with a
        # 3000 MB model must not refuse: its own residency is reclaimable.
        c, _ = _coordinator(4000)
        c.note_loaded("llm", "old-model", 3000)
        result = c.request_admission("llm", 3000, model_id="new-model")
        self.assertTrue(result["allowed"])
        self.assertEqual(result["evicted"], [])  # no eviction needed once self-credited


class AdmissionEvictionTests(unittest.TestCase):
    def test_evicts_lru_first(self):
        # 2100 MB free (deficit vs. the 1000 MB load), 2600 MB free once stt's
        # 500 MB is actually freed (resampled, not just arithmetic) -> enough.
        c, _ = _coordinator(_FakeAvailable(2100, 2600))
        evicted_order = []
        c.register_evictor("stt", lambda: evicted_order.append("stt"))
        c.register_evictor("tts", lambda: evicted_order.append("tts"))
        c.note_loaded("stt", "base.en", 500)
        time.sleep(0.01)
        c.note_loaded("tts", "kokoro", 400)  # more recently used than stt
        c.stop_idle_sweep()

        result = c.request_admission("llm", 1000)
        self.assertTrue(result["allowed"])
        self.assertEqual(evicted_order, ["stt"])  # LRU (stt) evicted, not tts
        self.assertEqual(len(result["evicted"]), 1)
        self.assertEqual(result["evicted"][0]["component"], "stt")
        self.assertIsNone(c.resources_snapshot()["ledger"]["stt"])
        self.assertIsNotNone(c.resources_snapshot()["ledger"]["tts"])  # untouched

    def test_pinned_component_never_evicted(self):
        c, _ = _coordinator(1600)
        evicted = []
        c.register_evictor("stt", lambda: evicted.append("stt"))
        c.note_loaded("stt", "base.en", 500)
        c.set_pinned("stt", True)
        c.stop_idle_sweep()

        result = c.request_admission("llm", 1000)
        self.assertFalse(result["allowed"])
        self.assertEqual(evicted, [])
        self.assertIsNotNone(result["refusal"])
        self.assertIsNotNone(c.resources_snapshot()["ledger"]["stt"])

    def test_busy_component_skipped_not_evicted(self):
        c, _ = _coordinator(1600)
        evicted = []
        c.register_evictor("stt", lambda: evicted.append("stt"))
        c.note_loaded("stt", "base.en", 500)
        c.stop_idle_sweep()

        with c.read_lease("stt"):  # active inference: must not be evicted
            result = c.request_admission("llm", 1000)

        self.assertFalse(result["allowed"])
        self.assertEqual(evicted, [])

    def test_resamples_real_available_mb_after_eviction(self):
        # Estimated freed_mb (500) undershoots what the eviction actually
        # freed in reality (900) -> a naive arithmetic-only subtraction would
        # keep refusing; resampling must pick up the real number and allow.
        available = _FakeAvailable(1600, 2500)  # before eviction, after eviction
        c, _ = _coordinator(available)
        c.register_evictor("stt", lambda: None)
        c.note_loaded("stt", "base.en", 500)
        c.stop_idle_sweep()

        result = c.request_admission("llm", 1000)
        self.assertTrue(result["allowed"])
        self.assertEqual(result["available_mb_after"], 2500)
        self.assertGreaterEqual(available.calls, 2)

    def test_refusal_payload_names_resident_models(self):
        c, _ = _coordinator(1600)
        c.note_loaded("stt", "base.en", 500)
        c.set_pinned("stt", True)  # nothing evictable
        result = c.request_admission("llm", 5000, model_id="gemma-4-e4b-q4")
        self.assertFalse(result["allowed"])
        refusal = result["refusal"]
        self.assertIn("base.en", refusal["message"])
        self.assertEqual(refusal["resident"], [
            {"component": "stt", "model_id": "base.en", "estimated_mb": 500, "pinned": True},
        ])

    def test_suggested_model_id_only_for_llm_refusals(self):
        c, _ = _coordinator(1600)
        result = c.request_admission("stt", 5000, model_id="whatever")
        self.assertFalse(result["allowed"])
        self.assertIsNone(result["refusal"]["suggested_model_id"])


class EvictorLockDisciplineTests(unittest.TestCase):
    """_evict_component is the sole path admission AND idle eviction use to
    actually free a component — it must invoke the evictor strictly INSIDE
    the runtime's exclusive write lease (acquire -> evictor() -> release),
    the same contract _unload_model_component_locked's "_locked" name implies
    for its manual-unload caller. A reader mid-eviction would otherwise be
    able to observe (or race) a component disappearing out from under it."""

    def test_evictor_runs_with_write_lease_held(self):
        c, _ = _coordinator(10000)
        observed = {}

        def evictor():
            rt = c._runtime("stt")
            observed["writer_held"] = rt._writer
            observed["state"] = rt.state
            observed["readers"] = rt._readers

        c.register_evictor("stt", evictor)
        c.stop_idle_sweep()
        c.note_loaded("stt", "base.en", 500)

        self.assertTrue(c._evict_component("stt", evictor))
        self.assertTrue(observed["writer_held"])
        self.assertEqual(observed["state"], mrc.UNLOADING)
        self.assertEqual(observed["readers"], 0)
        # Lease released afterward -> not busy, back to UNLOADED.
        self.assertFalse(c.is_busy("stt"))
        self.assertEqual(c._runtime("stt").state, mrc.UNLOADED)

    def test_admission_eviction_goes_through_evict_component(self):
        # Same guarantee via the request_admission entry point, not just the
        # internal helper directly.
        c, _ = _coordinator(1600)
        observed = {}

        def evictor():
            observed["writer_held"] = c._runtime("stt")._writer

        c.register_evictor("stt", evictor)
        c.stop_idle_sweep()
        c.note_loaded("stt", "base.en", 500)

        c.request_admission("llm", 1000)
        self.assertTrue(observed.get("writer_held"))


class IdleEvictionTests(unittest.TestCase):
    def tearDown(self):
        pass  # coordinators are local; nothing global to clean up

    def test_idle_eviction_respects_timeout(self):
        c, _ = _coordinator(10000)
        evicted = []
        c.register_evictor("llm", lambda: evicted.append("llm"))
        c.stop_idle_sweep()  # deterministic: drive it directly, no background thread
        c.note_loaded("llm", "m", 1000)

        self.assertFalse(c.check_idle_eviction("llm"))  # fresh, not idle yet
        self.assertEqual(evicted, [])

        c._ledger["llm"].last_used = time.monotonic() - 10_000
        self.assertTrue(c.check_idle_eviction("llm"))
        self.assertEqual(evicted, ["llm"])

    def test_idle_eviction_skips_pinned(self):
        c, _ = _coordinator(10000)
        evicted = []
        c.register_evictor("llm", lambda: evicted.append("llm"))
        c.stop_idle_sweep()
        c.note_loaded("llm", "m", 1000)
        c.set_pinned("llm", True)
        c._ledger["llm"].last_used = time.monotonic() - 10_000

        self.assertFalse(c.check_idle_eviction("llm"))
        self.assertEqual(evicted, [])

    def test_idle_eviction_skips_busy_component(self):
        c, _ = _coordinator(10000)
        evicted = []
        c.register_evictor("stt", lambda: evicted.append("stt"))
        c.stop_idle_sweep()
        c.note_loaded("stt", "base.en", 500)
        c._ledger["stt"].last_used = time.monotonic() - 10_000

        with c.read_lease("stt"):
            self.assertFalse(c.check_idle_eviction("stt"))
        self.assertEqual(evicted, [])

    def test_idle_sweep_excludes_tts_by_default(self):
        # TTS self-manages its own idle-unload sentinel; the coordinator's
        # sweep must never touch it, so registering ONLY a tts evictor must
        # not spin up the background sweep thread at all.
        c, _ = _coordinator(10000)
        c.register_evictor("tts", lambda: None)
        self.assertIsNone(c._idle_thread)

    def test_idle_eviction_is_idempotent_double_free_safe(self):
        # An evictor that's already a no-op when nothing is loaded (the real
        # server.py evictors are guarded this way) must be safe to call twice
        # in a row without error — the second check_idle_eviction sees an
        # empty ledger entry and short-circuits before ever calling it again.
        c, _ = _coordinator(10000)
        calls = []
        c.register_evictor("llm", lambda: calls.append(1))
        c.stop_idle_sweep()
        c.note_loaded("llm", "m", 1000)
        c._ledger["llm"].last_used = time.monotonic() - 10_000

        self.assertTrue(c.check_idle_eviction("llm"))
        self.assertEqual(len(calls), 1)
        # Second call: ledger entry is already None (note_unloaded ran as
        # part of the first eviction) -> short-circuits, evictor NOT called.
        self.assertFalse(c.check_idle_eviction("llm"))
        self.assertEqual(len(calls), 1)

    def test_register_evictor_starts_sweep_thread_for_llm_stt(self):
        c, _ = _coordinator(10000)
        c.register_evictor("llm", lambda: None)
        self.assertIsNotNone(c._idle_thread)
        self.assertTrue(c._idle_thread.is_alive())
        c.stop_idle_sweep()
        self.assertIsNone(c._idle_thread)


if __name__ == "__main__":
    unittest.main()
