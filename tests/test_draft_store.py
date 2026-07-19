"""Focused tests for DraftStore's I3.1 additive fields: transcription_result and
speech_signals. Pure unit tests against backend.stores.drafts.DraftStore with a
fake in-memory history_store (no FastAPI/model/real SQLite needed for most
cases), plus one full round-trip test against the real history_store module to
prove JSON+SQLite persistence/reload survives a process restart unchanged.
"""

import json
import os
import tempfile
import unittest

from backend.stores.drafts import DraftStore


class FakeHistoryStore:
    """In-memory stand-in for history_store.py's SQLite archive."""

    def __init__(self):
        self.records = {}

    def init(self):
        pass

    def verify_schema(self):
        return {"ok": True}

    def load_recent_full(self, limit=100):
        ordered = sorted(self.records.values(), key=lambda d: d["id"])
        return ordered[-limit:]

    def upsert_many(self, drafts):
        for d in drafts:
            self.records[d["id"]] = dict(d)

    def migrate_from_json(self, path):
        pass


def _noop_review_fields(draft):
    draft["token_count"] = 0
    draft["token_limit"] = 1200
    draft["long_text"] = False
    draft["auto_send_ok"] = True
    draft["force_review"] = False
    draft["force_review_reason"] = ""
    return draft


class DraftStoreSignalsTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.history = FakeHistoryStore()
        self.store = DraftStore(
            data_dir_fn=lambda: self._tmp.name,
            history_store=self.history,
            send_process_token="test-token",
        )

    def _create(self, **overrides):
        kwargs = dict(
            raw_text="hello world",
            final_text="Hello world.",
            review_fields_fn=_noop_review_fields,
            save_fn=self.store.save_history,
        )
        kwargs.update(overrides)
        return self.store.create_draft(**kwargs)

    def test_stores_transcription_result_and_speech_signals_when_provided(self):
        structured = {"text": "hello world", "segments": [], "confidence": 0.9, "audio_duration_s": 1.2}
        signals = {"words_per_minute": 120.0, "delivery_axes": {"arousal": 0.1}, "evidence": ["1 pause(s)"]}
        draft = self._create(transcription_result=structured, speech_signals=signals)

        self.assertEqual(draft["transcription_result"], structured)
        self.assertEqual(draft["speech_signals"], signals)
        stored = self.store.get_draft_by_id(draft["id"])
        self.assertEqual(stored["transcription_result"], structured)
        self.assertEqual(stored["speech_signals"], signals)

    def test_defaults_to_none_when_not_provided(self):
        draft = self._create()
        self.assertIsNone(draft["transcription_result"])
        self.assertIsNone(draft["speech_signals"])

    def test_existing_fields_and_send_policy_inputs_unaffected_by_new_kwargs(self):
        """Adding transcription_result/speech_signals must not perturb any
        existing field's value or the confidence dict shape the send policy reads."""
        confidence = {"score": 0.91, "avg_logprob": -0.2, "no_speech_prob": 0.01}
        draft = self._create(
            confidence=confidence,
            transcription_result={"text": "x"},
            speech_signals={"confidence": 0.5},
        )
        self.assertEqual(draft["raw_text"], "hello world")
        self.assertEqual(draft["final_text"], "Hello world.")
        self.assertEqual(draft["confidence"], confidence)
        self.assertEqual(draft["status"], "pending")

    def test_old_draft_json_without_new_keys_loads_unchanged(self):
        """A draft written before I3.1 (no transcription_result/speech_signals
        keys at all) must load without KeyError and keep every original field."""
        history_file = os.path.join(self._tmp.name, "draft_history.json")
        old_draft = {
            "id": 1, "raw_text": "legacy raw", "final_text": "legacy final",
            "preset": "True Janitor", "status": "pending", "metadata": {}, "error": "",
            "gate_reasons": [], "confidence": {"score": 0.8, "avg_logprob": None, "no_speech_prob": None},
            "pending_send": False, "send_result": None, "created_at": "2026-06-01T00:00:00Z",
        }
        with open(history_file, "w", encoding="utf-8") as f:
            json.dump([old_draft], f)

        # No SQLite records yet, so load_history falls back to the JSON file.
        self.store.load_history(max_history=100)

        self.assertEqual(len(self.store.draft_queue), 1)
        loaded = self.store.draft_queue[0]
        self.assertEqual(loaded["raw_text"], "legacy raw")
        self.assertEqual(loaded["final_text"], "legacy final")
        self.assertNotIn("transcription_result", loaded)
        self.assertNotIn("speech_signals", loaded)
        self.assertIsNone(loaded.get("transcription_result"))
        self.assertIsNone(loaded.get("speech_signals"))

    def test_save_and_reload_round_trip_retains_new_fields(self):
        """Simulates a restart: save via this store, then load_history on a
        *fresh* DraftStore instance sharing the same backing history_store must
        see the additive fields intact."""
        structured = {"text": "restart me", "segments": [{"start_s": 0.0, "end_s": 0.5, "text": "restart me"}]}
        signals = {"words_per_minute": 90.0, "evidence": ["2 words"]}
        draft = self._create(transcription_result=structured, speech_signals=signals)

        restarted = DraftStore(
            data_dir_fn=lambda: self._tmp.name,
            history_store=self.history,
            send_process_token="new-process-token",
        )
        restarted.load_history(max_history=100)

        reloaded = restarted.get_draft_by_id(draft["id"])
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded["transcription_result"], structured)
        self.assertEqual(reloaded["speech_signals"], signals)
        self.assertEqual(reloaded["raw_text"], "hello world")

    def test_recover_interrupted_sends_preserves_new_fields(self):
        """A crash-recovered mid-send draft keeps its structured/signal data —
        only send-state fields are reclassified."""
        structured = {"text": "in flight"}
        draft = self._create(transcription_result=structured, status="sending")
        draft_ref = self.store.get_draft_by_id(draft["id"])
        draft_ref["status"] = "sending"
        draft_ref["send_process_token"] = "a-different-process"

        recovered = self.store.recover_interrupted_sends(save_fn=self.store.save_history)

        self.assertEqual(recovered, [draft["id"]])
        after = self.store.get_draft_by_id(draft["id"])
        self.assertEqual(after["status"], "send_interrupted")
        self.assertEqual(after["transcription_result"], structured)

    def test_absent_segments_transcription_result_persists_as_given(self):
        """No-audio / empty-segment structured payloads persist exactly as
        produced by compute_speech_signals's own empty-input contract (I3.1
        does not reinterpret or drop them)."""
        structured = {"text": "", "segments": [], "confidence": None, "audio_duration_s": 0.0}
        signals = {"words_per_minute": 0.0, "evidence": ["no speech segments provided"]}
        draft = self._create(
            raw_text="", final_text="", status="blocked",
            transcription_result=structured, speech_signals=signals,
        )
        self.assertEqual(draft["transcription_result"]["segments"], [])
        self.assertEqual(draft["speech_signals"]["evidence"], ["no speech segments provided"])


class DraftStoreRealHistoryStoreRoundTripTests(unittest.TestCase):
    """One end-to-end check against the real SQLite-backed history_store module
    (not the in-memory fake) to prove the additive fields survive the actual
    JSON+SQLite persistence path, not just the fake's dict copy semantics."""

    def setUp(self):
        import history_store as real_history_store
        from unittest.mock import patch

        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        patcher = patch.object(real_history_store, "get_user_data_path", return_value=self._tmp.name)
        patcher.start()
        self.addCleanup(patcher.stop)
        real_history_store._initialized_path = None
        self.real_history_store = real_history_store

    def test_sqlite_round_trip_retains_additive_fields(self):
        store = DraftStore(
            data_dir_fn=lambda: self._tmp.name,
            history_store=self.real_history_store,
            send_process_token="token-a",
        )
        structured = {"text": "sqlite round trip", "segments": [], "confidence": 0.77, "audio_duration_s": 2.0}
        signals = {"words_per_minute": 133.0, "delivery_axes": {"urgency": 0.4}, "evidence": []}
        draft = store.create_draft(
            raw_text="sqlite round trip", final_text="Sqlite round trip.",
            review_fields_fn=_noop_review_fields, save_fn=store.save_history,
            transcription_result=structured, speech_signals=signals,
        )

        fresh_store = DraftStore(
            data_dir_fn=lambda: self._tmp.name,
            history_store=self.real_history_store,
            send_process_token="token-b",
        )
        fresh_store.load_history(max_history=100)

        reloaded = fresh_store.get_draft_by_id(draft["id"])
        self.assertIsNotNone(reloaded)
        self.assertEqual(reloaded["transcription_result"], structured)
        self.assertEqual(reloaded["speech_signals"], signals)


if __name__ == "__main__":
    unittest.main()
