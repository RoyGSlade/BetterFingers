"""Draft persistence does bounded work (review finding #9).

save_draft_history snapshots under the lock and does IO outside it, writes the
JSON atomically (temp + os.replace), and narrows the searchable-archive mirror
to the one changed draft; history_store.upsert_many batches all rows into one
connection and one transaction.
"""

import json
import os
import tempfile
import unittest
from unittest.mock import patch

import history_store
import server


class TempDataDirMixin(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self._tmp = tempfile.TemporaryDirectory()
        for target in ("history_store.get_user_data_path", "server.get_user_data_path"):
            p = patch(target, return_value=self._tmp.name)
            p.start()
            self.addCleanup(p.stop)
        self.addCleanup(self._tmp.cleanup)
        server.draft_queue.clear()
        self.addCleanup(server.draft_queue.clear)


class BatchUpsertTests(TempDataDirMixin):
    def _draft(self, i):
        return {"id": i, "created_at": f"2026-07-12T0{i % 10}:00:00Z", "status": "pending",
                "raw_text": f"raw {i}", "final_text": f"final {i}",
                "metadata": {"profile": "Default"}}

    def test_upsert_many_single_transaction_batches_all(self):
        history_store.init()
        connections = []
        real_connect = history_store._connect

        def counting_connect():
            conn = real_connect()
            connections.append(conn)
            return conn

        with patch.object(history_store, "_connect", side_effect=counting_connect):
            history_store.upsert_many([self._draft(i) for i in range(1, 51)])

        # One connection for 50 drafts — not one per draft.
        self.assertEqual(len(connections), 1)
        self.assertEqual(history_store.count(), 50)

    def test_upsert_many_skips_bad_rows_but_keeps_good(self):
        history_store.init()
        history_store.upsert_many([
            self._draft(1), {"no": "id"}, None, self._draft(2)
        ])
        self.assertEqual(history_store.count(), 2)


class AtomicSaveTests(TempDataDirMixin):
    def test_save_writes_json_atomically_and_narrows_mirror(self):
        history_store.init()
        with server.draft_lock:
            for i in (1, 2, 3):
                server.draft_queue.append(
                    {"id": i, "status": "pending", "raw_text": f"r{i}", "final_text": f"f{i}",
                     "created_at": "2026-07-12T00:00:00Z", "metadata": {}})

        server.save_draft_history(changed_draft_id=2)

        history_file = os.path.join(self._tmp.name, "draft_history.json")
        self.assertTrue(os.path.exists(history_file))
        self.assertFalse(os.path.exists(history_file + ".tmp"))
        data = json.load(open(history_file))
        self.assertEqual([d["id"] for d in data], [1, 2, 3])  # JSON has full queue
        self.assertEqual(history_store.count(), 1)  # mirror got only the change

    def test_save_without_changed_id_mirrors_everything(self):
        history_store.init()
        with server.draft_lock:
            for i in (1, 2):
                server.draft_queue.append(
                    {"id": i, "status": "pending", "raw_text": "r", "final_text": "f",
                     "created_at": "2026-07-12T00:00:00Z", "metadata": {}})
        server.save_draft_history()
        self.assertEqual(history_store.count(), 2)


if __name__ == "__main__":
    unittest.main()
