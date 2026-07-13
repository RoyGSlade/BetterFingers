"""Ordered, coalesced draft-history persistence (deep draft persistence).

The naive "snapshot + os.replace" per mutation had two problems that this covers:
  1. Lost updates: concurrent savers os.replace their own snapshots out of order,
     so the JSON on disk could regress to a stale state (surfacing only after a
     restart). A single-writer lock + snapshot-at-write-time + a monotonic
     written-revision guard means the file always ends at the newest state.
  2. Redundant IO: a burst of saves each did a full disk+SQLite write. A saver
     whose revision is already covered by a newer flush now skips (coalescing),
     and coalesced saves accumulate their narrowed mirror ids so one flush
     mirrors them all.
"""

import json
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import history_store
import server


class PersistTestMixin(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        for target in ("history_store.get_user_data_path", "server.get_user_data_path"):
            p = patch(target, return_value=self._tmp.name)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        # Reset the module-level writer state so revisions/mirror-debt from other
        # tests can't bleed in.
        server._draft_request_rev = 0
        server._draft_written_rev = 0
        server._draft_pending_full_mirror = False
        server._draft_pending_changed_ids.clear()
        server.draft_queue.clear()
        self.addCleanup(server.draft_queue.clear)
        self.addCleanup(server._draft_pending_changed_ids.clear)
        history_store.init()

    @property
    def _history_file(self):
        return os.path.join(self._tmp.name, "draft_history.json")

    def _append(self, draft_id, status="pending"):
        with server.draft_lock:
            server.draft_queue.append({
                "id": draft_id, "status": status, "raw_text": f"r{draft_id}",
                "final_text": f"f{draft_id}", "created_at": "2026-07-12T00:00:00Z",
                "metadata": {}})


class OrderingTests(PersistTestMixin):
    def test_concurrent_saves_never_lose_updates(self):
        # 20 threads each append a draft then save; regardless of interleaving,
        # the file on disk must end up containing all 20.
        def worker(i):
            self._append(i)
            server.save_draft_history(changed_draft_id=i)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(1, 21)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=10)

        data = json.load(open(self._history_file))
        self.assertEqual(sorted(d["id"] for d in data), list(range(1, 21)))
        # The searchable mirror also captured every id (no dropped narrowed save).
        self.assertEqual(history_store.count(), 20)


class CoalescingTests(PersistTestMixin):
    def test_burst_behind_a_held_writer_coalesces(self):
        # Seed one draft per id so the narrowed mirror has rows to upsert.
        for i in range(1, 12):
            self._append(i)

        replaces = []
        first_inside = threading.Event()
        release_first = threading.Event()
        real_replace = os.replace

        def slow_replace(src, dst):
            replaces.append(dst)
            if not first_inside.is_set():
                first_inside.set()
                release_first.wait(timeout=5)  # hold the first writer inside the lock
            real_replace(src, dst)

        with patch("server.os.replace", side_effect=slow_replace):
            t0 = threading.Thread(target=lambda: server.save_draft_history(changed_draft_id=1))
            t0.start()
            self.assertTrue(first_inside.wait(timeout=5))  # first writer holds write_lock

            # These all register a revision, then block on the write lock.
            burst = [threading.Thread(target=server.save_draft_history,
                                      kwargs={"changed_draft_id": i}) for i in range(2, 12)]
            for t in burst:
                t.start()
            time.sleep(0.2)  # let every burst saver pass step 1 (revision + pending)
            release_first.set()
            for t in burst:
                t.join(timeout=5)
            t0.join(timeout=5)

        # 11 save calls collapsed into far fewer physical writes.
        self.assertLess(len(replaces), 11)
        self.assertGreaterEqual(len(replaces), 1)
        # Every distinct changed id still reached the mirror despite coalescing.
        self.assertEqual(history_store.count(), 11)


class MirrorDebtTests(PersistTestMixin):
    def test_mirror_failure_is_reattempted_on_next_save(self):
        self._append(5)
        self._append(6)

        calls = {"n": 0}
        real_upsert = history_store.upsert_many

        def flaky_upsert(rows):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("mirror offline")
            return real_upsert(rows)

        with patch.object(history_store, "upsert_many", side_effect=flaky_upsert):
            server.save_draft_history(changed_draft_id=5)  # JSON ok, mirror fails → id 5 re-armed
            self.assertEqual(history_store.count(), 0)
            server.save_draft_history(changed_draft_id=6)  # mirrors the re-armed 5 AND 6

        self.assertEqual(history_store.count(), 2)  # both 5 and 6 present


class SingleSaveRegressionTests(PersistTestMixin):
    def test_one_save_writes_json_and_narrows_mirror(self):
        for i in (1, 2, 3):
            self._append(i)
        server.save_draft_history(changed_draft_id=2)

        self.assertFalse(os.path.exists(self._history_file + ".tmp"))
        data = json.load(open(self._history_file))
        self.assertEqual([d["id"] for d in data], [1, 2, 3])
        self.assertEqual(history_store.count(), 1)  # only the changed id mirrored


if __name__ == "__main__":
    unittest.main()
