import os
import tempfile
import unittest
from unittest.mock import patch

import history_store


class _TempAppdataMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        history_store._initialized_path = None
        history_store._write_count = 0

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        self._tmp.cleanup()
        history_store._initialized_path = None
        history_store._write_count = 0


def _seed(n, prefix="draft"):
    for i in range(n):
        history_store.upsert_draft(
            {
                "id": i,
                "created_at": f"2026-01-01T00:{i:02d}:00",
                "status": "sent",
                "profile": "Default",
                "raw_text": f"{prefix}{i}",
                "final_text": f"{prefix}{i} final",
            }
        )


class PruneHistoryTests(_TempAppdataMixin, unittest.TestCase):
    def test_under_limit_is_a_no_op(self):
        _seed(3)
        removed = history_store.prune_history(max_keep=5000)
        self.assertEqual(removed, 0)
        self.assertEqual(history_store.count(), 3)

    def test_keeps_newest_removes_oldest(self):
        _seed(12)
        removed = history_store.prune_history(max_keep=5)
        self.assertEqual(removed, 7)
        self.assertEqual(history_store.count(), 5)

        kept = history_store.recent(limit=100)
        kept_texts = {row["raw_text"] for row in kept}
        self.assertEqual(kept_texts, {f"draft{i}" for i in range(7, 12)})

    def test_fts_index_stays_in_sync_after_prune(self):
        _seed(10)
        history_store.prune_history(max_keep=3)

        # Oldest drafts are gone from search (FTS trigger fired on delete).
        self.assertEqual(history_store.search("draft0"), [])
        self.assertEqual(history_store.search("draft6"), [])
        # Newest drafts are still searchable.
        results = history_store.search("draft9")
        self.assertTrue(any(r["raw_text"] == "draft9" for r in results))

    def test_periodic_prune_fires_on_upsert(self):
        history_store._PRUNE_EVERY_N_WRITES = 5
        try:
            _seed(11, prefix="periodic")
            # 11 writes with a max_keep of 5000 (default) never trims anything,
            # but the periodic-prune call itself must not raise or corrupt state.
            self.assertEqual(history_store.count(), 11)
        finally:
            history_store._PRUNE_EVERY_N_WRITES = 100

    def test_init_calls_prune_on_first_run_for_a_data_path(self):
        with patch("history_store.prune_history") as mock_prune:
            history_store.init()
            mock_prune.assert_called_once_with()

    def test_init_does_not_reprune_once_already_initialized(self):
        history_store.init()
        with patch("history_store.prune_history") as mock_prune:
            history_store.init()  # same path — should be a no-op
            mock_prune.assert_not_called()


class FullRecordTests(_TempAppdataMixin, unittest.TestCase):
    def _rich_draft(self, draft_id=1):
        return {
            "id": draft_id,
            "created_at": f"2026-01-01T00:{draft_id:02d}:00",
            "status": "sent",
            "raw_text": f"raw {draft_id}",
            "final_text": f"final {draft_id}",
            "metadata": {"profile": "Default", "sample_rate": 16000},
            "confidence": {"score": 0.91, "avg_logprob": -0.2, "no_speech_prob": 0.01},
            "gate_reasons": ["clip_too_short"],
            "send_outcome": "sent",
            "send_result": {"ok": True, "action": "paste"},
            "token_count": 2,
            "long_text": False,
        }

    def test_upsert_stores_full_record_and_load_roundtrips(self):
        draft = self._rich_draft(1)
        history_store.upsert_draft(draft)
        loaded = history_store.load_recent_full(100)
        self.assertEqual(len(loaded), 1)
        # Every field the queue carried survives the round-trip — not just the
        # searchable subset.
        self.assertEqual(loaded[0], draft)

    def test_load_recent_full_is_oldest_first(self):
        for i in (1, 2, 3):
            history_store.upsert_draft(self._rich_draft(i))
        loaded = history_store.load_recent_full(100)
        self.assertEqual([d["id"] for d in loaded], [1, 2, 3])

    def test_load_recent_full_respects_limit_and_returns_newest(self):
        for i in range(1, 6):
            history_store.upsert_draft(self._rich_draft(i))
        loaded = history_store.load_recent_full(2)
        # Newest two, still oldest-first within the window.
        self.assertEqual([d["id"] for d in loaded], [4, 5])

    def test_backcompat_row_without_data_falls_back_to_columns(self):
        history_store.init()
        # Simulate a row written before the full-record column existed.
        with history_store._lock:
            conn = history_store._connect()
            try:
                conn.execute(
                    "INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text) "
                    "VALUES (7, '2026-01-01T00:07:00', 'pending', 'Default', 'legacy raw', 'legacy final')"
                )
                conn.commit()
            finally:
                conn.close()
        loaded = history_store.load_recent_full(100)
        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0]["id"], 7)
        self.assertEqual(loaded[0]["raw_text"], "legacy raw")
        self.assertEqual(loaded[0]["final_text"], "legacy final")
        self.assertEqual(loaded[0]["status"], "pending")


if __name__ == "__main__":
    unittest.main()
