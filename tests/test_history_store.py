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


if __name__ == "__main__":
    unittest.main()
