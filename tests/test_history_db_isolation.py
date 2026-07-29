"""Wave 6 — a guard against the cross-test pollution that hid a weak assertion.

NOTE FOR THE INTEGRATOR: this file needs renaming to
``tests/test_history_db_isolation.py``. It began as a throwaway diagnostic and
the session's tooling refused every delete/move of it, so its contents were
replaced with the real test rather than leaving a stray probe in the suite. The
name is the only thing wrong with it.

What it guards
--------------
``tests/test_wipe_send_race.py`` stubs ``history_store.wipe_database`` — it is
scoped to the send/output drain and does not want to touch the database. That
was invisible for as long as the wipe's ``history_db_wiped`` postcondition was
copied from the stub's own return value.

Wave 6 made the wipe verify by re-reading the disk, which is the point of the
whole design: "we called wipe_database" is not evidence. The moment the check
became real, the stub stopped satisfying it — and the row that made it fail had
been left in the shared session database by ``tests/test_server_drafts.py``
running earlier in the same suite. The race test passed alone and failed in the
full run.

So the lesson is not about that one test. It is that a suite-shared SQLite file
lets one test's leftovers decide another test's outcome, and the only reason it
surfaced here is that a verification got stricter. This asserts the invariant
directly.
"""

import unittest

import history_store


class HistoryDatabaseIsolationTests(unittest.TestCase):
    def test_a_test_can_always_start_from_an_empty_history_database(self):
        """The recovery any polluted test needs: wiping really empties it.

        If this ever fails, no amount of per-test cleanup will make the suite
        deterministic, because the shared database cannot be reset.
        """
        history_store.init()
        history_store.upsert_draft({
            "id": 987654, "created_at": "2026-07-28T00:00:00Z", "status": "pending",
            "raw_text": "isolation probe", "final_text": "isolation probe",
            "metadata": {"profile": "Default"},
        })
        self.assertGreater(history_store.count(), 0)

        result = history_store.wipe_database()
        self.assertTrue(result.get("ok"), result)
        self.assertTrue(result.get("recreated"), result)
        self.assertEqual(history_store.count(), 0,
                         "wiping the history database left rows behind, so no test "
                         "can rely on a clean starting state")

    def test_count_reads_the_file_rather_than_a_cached_handle(self):
        """A verification that re-reads must see the current file.

        ``count()`` opens a fresh connection per call. If it were ever changed
        to reuse a cached one, a wipe would delete the file while the old
        handle kept serving rows from the unlinked inode — and every
        "verified" the privacy wipe reports would become meaningless.
        """
        history_store.init()
        history_store.wipe_database()
        self.assertEqual(history_store.count(), 0)
        history_store.upsert_draft({
            "id": 987655, "created_at": "2026-07-28T00:00:00Z", "status": "pending",
            "raw_text": "second probe", "final_text": "second probe",
            "metadata": {"profile": "Default"},
        })
        self.assertEqual(history_store.count(), 1)
        history_store.wipe_database()
        self.assertEqual(history_store.count(), 0)


if __name__ == "__main__":
    unittest.main()
