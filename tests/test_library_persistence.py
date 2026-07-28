"""Wave 3 (Gate 3, Task W3-B) persistence tests: pinned columns, per-item
archive deletion, and backend-driven filtered query in history_store.py, plus
the matching DraftStore additions in backend/stores/drafts.py.

Written against docs/release/WAVE3_LIBRARY_CONTRACT.md §3. Runs regardless of
whether the sibling backend/domain/library.py module exists yet -- history_store
imports it lazily and falls back to an inline default-filling helper, and
these tests assert on the resulting behavior (defaults filled), not on which
code path filled them.
"""

import os
import sqlite3
import tempfile
import unittest

import history_store
from backend.stores.drafts import DraftStore


class _TempAppdataMixin:
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self._orig = os.environ.get("APPDATA")
        os.environ["APPDATA"] = self._tmp.name
        history_store._initialized_path = None
        history_store._write_count = 0

    def tearDown(self):
        if self._orig is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = self._orig
        history_store._initialized_path = None
        history_store._write_count = 0


def _draft(draft_id, **overrides):
    base = {
        "id": draft_id,
        "created_at": f"2026-01-0{draft_id}T00:00:00" if draft_id < 10 else f"2026-01-{draft_id}T00:00:00",
        "status": "pending",
        "profile": "Default",
        "raw_text": f"raw {draft_id}",
        "final_text": f"final {draft_id}",
    }
    base.update(overrides)
    return base


class MigrationTests(_TempAppdataMixin, unittest.TestCase):
    """Old data must load unchanged: a pre-Wave-3 database (no pinned/
    pinned_at columns) must keep working, and pin state on legacy rows must
    default to False/None rather than erroring."""

    def _create_legacy_db(self):
        db_path = history_store.get_db_path()
        conn = sqlite3.connect(db_path)
        try:
            # The exact pre-Wave-3 DDL (history_store.py before pinned/pinned_at
            # were added), by hand -- no `pinned`/`pinned_at` columns at all.
            conn.executescript(
                """
                CREATE TABLE drafts (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT,
                    status TEXT,
                    profile TEXT,
                    raw_text TEXT,
                    final_text TEXT,
                    data TEXT
                );
                CREATE VIRTUAL TABLE drafts_fts USING fts5(
                    raw_text, final_text, content='drafts', content_rowid='id'
                );
                CREATE TRIGGER drafts_ai AFTER INSERT ON drafts BEGIN
                    INSERT INTO drafts_fts(rowid, raw_text, final_text)
                    VALUES (new.id, new.raw_text, new.final_text);
                END;
                CREATE TRIGGER drafts_ad AFTER DELETE ON drafts BEGIN
                    INSERT INTO drafts_fts(drafts_fts, rowid, raw_text, final_text)
                    VALUES ('delete', old.id, old.raw_text, old.final_text);
                END;
                CREATE TRIGGER drafts_au AFTER UPDATE ON drafts BEGIN
                    INSERT INTO drafts_fts(drafts_fts, rowid, raw_text, final_text)
                    VALUES ('delete', old.id, old.raw_text, old.final_text);
                    INSERT INTO drafts_fts(rowid, raw_text, final_text)
                    VALUES (new.id, new.raw_text, new.final_text);
                END;
                """
            )
            conn.execute(
                "INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text) "
                "VALUES (1, '2026-01-01T00:00:00', 'sent', 'Default', 'legacy raw', 'legacy final')"
            )
            conn.commit()
        finally:
            conn.close()

    def test_old_database_gains_pinned_columns_non_destructively(self):
        self._create_legacy_db()
        # No pinned/pinned_at columns exist yet.
        conn = sqlite3.connect(history_store.get_db_path())
        try:
            columns_before = {row[1] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()}
        finally:
            conn.close()
        self.assertNotIn("pinned", columns_before)
        self.assertNotIn("pinned_at", columns_before)

        # init() (triggered by any read) runs the additive migration.
        loaded = history_store.load_recent_full(100)

        conn = sqlite3.connect(history_store.get_db_path())
        try:
            columns_after = {row[1] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()}
        finally:
            conn.close()
        self.assertIn("pinned", columns_after)
        self.assertIn("pinned_at", columns_after)

        # The legacy row still loads, with pin state defaulted, and its
        # original fields intact.
        self.assertEqual(len(loaded), 1)
        row = loaded[0]
        self.assertEqual(row["id"], 1)
        self.assertEqual(row["raw_text"], "legacy raw")
        self.assertEqual(row["final_text"], "legacy final")
        self.assertEqual(row["status"], "sent")
        self.assertFalse(row["pinned"])
        self.assertIsNone(row["pinned_at"])

    def test_legacy_row_survives_a_write_after_migration(self):
        self._create_legacy_db()
        history_store.init()
        # A write for an unrelated reason should not disturb the legacy row.
        history_store.upsert_draft(_draft(2))
        loaded = history_store.load_recent_full(100)
        ids = {r["id"] for r in loaded}
        self.assertEqual(ids, {1, 2})


class GetTests(_TempAppdataMixin, unittest.TestCase):
    """Amendment A2: history_store.get(draft_id) -- a single indexed lookup
    delete_item(kind="history_entry") needs to resolve a target that may
    exist only in the archive, not the bounded in-memory draft_queue."""

    def _create_legacy_db(self):
        db_path = history_store.get_db_path()
        conn = sqlite3.connect(db_path)
        try:
            conn.executescript(
                """
                CREATE TABLE drafts (
                    id INTEGER PRIMARY KEY,
                    created_at TEXT,
                    status TEXT,
                    profile TEXT,
                    raw_text TEXT,
                    final_text TEXT,
                    data TEXT
                );
                CREATE VIRTUAL TABLE drafts_fts USING fts5(
                    raw_text, final_text, content='drafts', content_rowid='id'
                );
                CREATE TRIGGER drafts_ai AFTER INSERT ON drafts BEGIN
                    INSERT INTO drafts_fts(rowid, raw_text, final_text)
                    VALUES (new.id, new.raw_text, new.final_text);
                END;
                CREATE TRIGGER drafts_ad AFTER DELETE ON drafts BEGIN
                    INSERT INTO drafts_fts(drafts_fts, rowid, raw_text, final_text)
                    VALUES ('delete', old.id, old.raw_text, old.final_text);
                END;
                CREATE TRIGGER drafts_au AFTER UPDATE ON drafts BEGIN
                    INSERT INTO drafts_fts(drafts_fts, rowid, raw_text, final_text)
                    VALUES ('delete', old.id, old.raw_text, old.final_text);
                    INSERT INTO drafts_fts(rowid, raw_text, final_text)
                    VALUES (new.id, new.raw_text, new.final_text);
                END;
                """
            )
            conn.execute(
                "INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text) "
                "VALUES (1, '2026-01-01T00:00:00', 'sent', 'Default', 'legacy raw', 'legacy final')"
            )
            conn.commit()
        finally:
            conn.close()

    def test_get_returns_full_record_including_a_json_only_field(self):
        history_store.upsert_draft(_draft(1, preset="Alice", gate_reasons=["clip_too_short"]))
        record = history_store.get(1)
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], 1)
        # gate_reasons only lives in the `data` JSON, not a typed column --
        # proves this went through _full_from_row, not the column subset.
        self.assertEqual(record["gate_reasons"], ["clip_too_short"])

    def test_get_on_legacy_row_returns_defaulted_pin_state_and_recovered_preset(self):
        self._create_legacy_db()
        record = history_store.get(1)
        self.assertIsNotNone(record)
        self.assertEqual(record["raw_text"], "legacy raw")
        self.assertFalse(record["pinned"])
        self.assertIsNone(record["pinned_at"])

    def test_get_returns_none_for_absent_id(self):
        self.assertIsNone(history_store.get(999))

    def test_get_returns_none_after_delete(self):
        history_store.upsert_draft(_draft(1))
        history_store.delete_draft(1)
        self.assertIsNone(history_store.get(1))


class WipePathUnaffectedByNewColumnsTests(_TempAppdataMixin, unittest.TestCase):
    """The privacy-wipe path can't be exercised from this session (its tests
    need fastapi/numpy, unavailable to this sandbox's pytest invocation --
    see handoff). Directly check the two things that could plausibly break
    from widening the table by three columns: verify_schema()'s bare-column-
    list sentinel INSERT (pinned/pinned_at/preset are all either NOT NULL
    DEFAULT or nullable, so it must still succeed), and a full wipe/recreate
    cycle."""

    def test_verify_schema_sentinel_insert_still_succeeds(self):
        history_store.init()
        result = history_store.verify_schema()
        self.assertTrue(result["ok"], result)
        self.assertTrue(result["roundtrip"])

    def test_wipe_database_recreates_a_usable_widened_schema(self):
        history_store.upsert_draft(_draft(1))
        history_store.set_pinned(1, True, "2026-01-01T00:00:00")
        result = history_store.wipe_database()
        self.assertTrue(result["ok"], result)
        self.assertEqual(history_store.count(), 0)
        # The recreated schema still has the widened columns and behaves.
        history_store.upsert_draft(_draft(2))
        history_store.set_pinned(2, True, "2026-01-02T00:00:00")
        loaded = history_store.load_recent_full(10)
        self.assertEqual(len(loaded), 1)
        self.assertTrue(loaded[0]["pinned"])


class SetPinnedTests(_TempAppdataMixin, unittest.TestCase):
    def test_returns_false_for_absent_row(self):
        self.assertFalse(history_store.set_pinned(12345, True, "2026-01-01T00:00:00"))

    def test_round_trips_through_columns_and_data_json(self):
        history_store.upsert_draft(_draft(1))
        ok = history_store.set_pinned(1, True, "2026-01-01T12:00:00")
        self.assertTrue(ok)

        loaded = history_store.load_recent_full(10)
        self.assertEqual(len(loaded), 1)
        self.assertTrue(loaded[0]["pinned"])
        self.assertEqual(loaded[0]["pinned_at"], "2026-01-01T12:00:00")

        # The columns themselves (not just the data JSON) reflect the pin,
        # since pinned filtering/ordering is pushed into SQL.
        conn = sqlite3.connect(history_store.get_db_path())
        try:
            row = conn.execute("SELECT pinned, pinned_at FROM drafts WHERE id = 1").fetchone()
        finally:
            conn.close()
        self.assertEqual(row[0], 1)
        self.assertEqual(row[1], "2026-01-01T12:00:00")

    def test_unpin_clears_pinned_at(self):
        history_store.upsert_draft(_draft(1))
        history_store.set_pinned(1, True, "2026-01-01T12:00:00")
        history_store.set_pinned(1, False, None)
        loaded = history_store.load_recent_full(10)
        self.assertFalse(loaded[0]["pinned"])
        self.assertIsNone(loaded[0]["pinned_at"])

    def test_pin_state_survives_a_full_store_reload(self):
        history_store.upsert_draft(_draft(1))
        history_store.set_pinned(1, True, "2026-01-01T12:00:00")

        # Simulate a process restart: drop the cached schema-init state so the
        # next call re-opens the database fresh, same as a new process would.
        history_store._initialized_path = None
        loaded = history_store.load_recent_full(10)
        self.assertTrue(loaded[0]["pinned"])
        self.assertEqual(loaded[0]["pinned_at"], "2026-01-01T12:00:00")


class DeleteDraftTests(_TempAppdataMixin, unittest.TestCase):
    def test_deletes_row(self):
        history_store.upsert_draft(_draft(1, raw_text="findme", final_text="findme too"))
        self.assertTrue(history_store.delete_draft(1))
        self.assertEqual(history_store.load_recent_full(10), [])

    def test_idempotent_on_absent_row(self):
        history_store.upsert_draft(_draft(1))
        self.assertTrue(history_store.delete_draft(1))
        self.assertFalse(history_store.delete_draft(1))
        self.assertFalse(history_store.delete_draft(999))

    def test_fts_trigger_stays_in_sync_after_delete(self):
        history_store.upsert_draft(_draft(1, raw_text="findme", final_text="findme too"))
        self.assertTrue(any(r["id"] == 1 for r in history_store.search("findme")))
        history_store.delete_draft(1)
        self.assertEqual(history_store.search("findme"), [])


class QueryTests(_TempAppdataMixin, unittest.TestCase):
    # persona is draft["preset"] (e.g. "True Janitor"), NOT the `profile`
    # column (draft["metadata"]["profile"], an unrelated application/settings
    # profile) -- Amendment A1. profile is set to something else entirely
    # here specifically so a test that accidentally filtered on `profile`
    # instead of `preset` would fail loudly.
    def setUp(self):
        super().setUp()
        history_store.upsert_draft(
            _draft(1, created_at="2026-01-01T00:00:00", status="pending", preset="Alice",
                   profile="unrelated-app-profile", raw_text="alpha report", final_text="alpha report final")
        )
        history_store.upsert_draft(
            _draft(2, created_at="2026-01-05T00:00:00", status="sent", preset="Bob",
                   profile="unrelated-app-profile", raw_text="beta memo", final_text="beta memo final")
        )
        history_store.upsert_draft(
            _draft(3, created_at="2026-01-10T00:00:00", status="sent", preset="Alice",
                   profile="unrelated-app-profile", raw_text="gamma note", final_text="gamma note final")
        )
        history_store.set_pinned(2, True, "2026-01-06T00:00:00")

    def test_filter_by_persona(self):
        res = history_store.query({"persona": "Alice"})
        self.assertEqual({r["id"] for r in res["results"]}, {1, 3})
        self.assertEqual(res["total"], 2)

    def test_persona_filter_ignores_the_unrelated_profile_column(self):
        # All three rows share the same `profile` value; a persona filter of
        # "Bob" must still isolate exactly the one row whose preset is "Bob".
        res = history_store.query({"persona": "Bob"})
        self.assertEqual([r["id"] for r in res["results"]], [2])

    def test_persona_filter_finds_pre_preset_column_rows_via_json_fallback(self):
        # Migration evidence for Amendment A1: a row written before the
        # `preset` column existed only carries persona inside the JSON body.
        # The COALESCE(preset, json_extract(data, '$.preset')) fallback must
        # still find it.
        conn = sqlite3.connect(history_store.get_db_path())
        try:
            conn.execute("UPDATE drafts SET preset = NULL WHERE id = 3")
            conn.commit()
        finally:
            conn.close()
        res = history_store.query({"persona": "Alice"})
        self.assertEqual({r["id"] for r in res["results"]}, {1, 3})

    def test_filter_by_status(self):
        res = history_store.query({"status": "sent"})
        self.assertEqual({r["id"] for r in res["results"]}, {2, 3})

    def test_filter_by_status_collection(self):
        res = history_store.query({"status": ["pending", "sent"]})
        self.assertEqual({r["id"] for r in res["results"]}, {1, 2, 3})

    def test_filter_by_status_wider_vocabulary(self):
        # server.py also writes send_error/error/blocked/scratch statuses
        # (not just the pending/sent/sending trio) -- a plain column match
        # needs no special-casing, but exercise one to prove it.
        history_store.upsert_draft(
            _draft(4, created_at="2026-01-11T00:00:00", status="blocked", preset="Alice",
                   raw_text="delta draft", final_text="delta draft final")
        )
        res = history_store.query({"status": "blocked"})
        self.assertEqual([r["id"] for r in res["results"]], [4])

    def test_filter_by_pinned(self):
        res = history_store.query({"pinned": True})
        self.assertEqual([r["id"] for r in res["results"]], [2])
        res_false = history_store.query({"pinned": False})
        self.assertEqual({r["id"] for r in res_false["results"]}, {1, 3})

    def test_filter_by_date_range(self):
        res = history_store.query({"date_from": "2026-01-02", "date_to": "2026-01-09"})
        self.assertEqual([r["id"] for r in res["results"]], [2])

    def test_date_to_is_inclusive_of_the_full_day(self):
        # Bounds arrive already canonicalized (e.g. domain.library.
        # parse_filters expands a date-only date_to to end-of-day) -- query()
        # must use them as opaque >=/<= bounds without re-parsing. A same-day
        # date_to that has already been expanded to end-of-day must still
        # include a row timestamped later that same day.
        res = history_store.query({"date_from": "2026-01-10T00:00:00", "date_to": "2026-01-10T23:59:59.999999"})
        self.assertEqual([r["id"] for r in res["results"]], [3])

    def test_filter_by_query_text(self):
        res = history_store.query({"query": "gamma"})
        self.assertEqual([r["id"] for r in res["results"]], [3])

    def test_combined_filters(self):
        res = history_store.query({"persona": "Alice", "status": "sent"})
        self.assertEqual([r["id"] for r in res["results"]], [3])

    def test_pinned_first_ordering(self):
        res = history_store.query({})
        # id 2 is pinned -> sorts first despite being neither newest nor oldest.
        self.assertEqual(res["results"][0]["id"], 2)
        # Remaining ids newest-first.
        self.assertEqual([r["id"] for r in res["results"][1:]], [3, 1])

    def test_limit_offset_paging_reports_correct_total(self):
        page1 = history_store.query({}, limit=2, offset=0)
        page2 = history_store.query({}, limit=2, offset=2)
        self.assertEqual(page1["total"], 3)
        self.assertEqual(page2["total"], 3)
        self.assertEqual(len(page1["results"]), 2)
        self.assertEqual(len(page2["results"]), 1)
        seen_ids = [r["id"] for r in page1["results"]] + [r["id"] for r in page2["results"]]
        self.assertEqual(seen_ids, [2, 3, 1])

    def test_results_are_normalized_records(self):
        res = history_store.query({"persona": "Alice"})
        for record in res["results"]:
            self.assertIn("pinned", record)
            self.assertIn("pinned_at", record)
            self.assertIn("duplicated_from_id", record)

    def test_hostile_query_string_does_not_raise_or_corrupt(self):
        hostile = "\" ; DROP TABLE drafts; --"
        res = history_store.query({"query": hostile})
        self.assertEqual(res["results"], [])
        # The table is untouched -- prior rows are all still readable.
        self.assertEqual(history_store.count(), 3)

        hostile2 = "malicious\"* OR 1=1; DROP TABLE drafts_fts; --"
        res2 = history_store.query({"query": hostile2})
        self.assertIsInstance(res2["results"], list)
        self.assertEqual(history_store.count(), 3)

    def test_no_filters_returns_everything(self):
        res = history_store.query({})
        self.assertEqual(res["total"], 3)
        self.assertEqual(len(res["results"]), 3)


class FakeHistoryStore:
    """In-memory stand-in for history_store.py, matching the fake used in
    tests/test_draft_store.py, extended with the Wave 3 persistence surface
    DraftStore now delegates to."""

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

    def set_pinned(self, draft_id, pinned, pinned_at):
        if draft_id not in self.records:
            return False
        self.records[draft_id]["pinned"] = bool(pinned)
        self.records[draft_id]["pinned_at"] = pinned_at if pinned else None
        return True

    def delete_draft(self, draft_id):
        return self.records.pop(draft_id, None) is not None


def _noop_review_fields(draft):
    draft["token_count"] = 0
    draft["token_limit"] = 1200
    draft["long_text"] = False
    draft["auto_send_ok"] = True
    draft["force_review"] = False
    draft["force_review_reason"] = ""
    return draft


class DraftStoreLibraryTests(unittest.TestCase):
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

    # -- set_pinned ----------------------------------------------------
    def test_set_pinned_updates_queue_and_returns_draft(self):
        draft = self._create()
        result = self.store.set_pinned(draft["id"], True, save_fn=self.store.save_history)
        self.assertIsNotNone(result)
        self.assertTrue(result["pinned"])
        stored = self.store.get_draft_by_id(draft["id"])
        self.assertTrue(stored["pinned"])

    def test_set_pinned_absent_draft_returns_none(self):
        result = self.store.set_pinned(999, True, save_fn=self.store.save_history)
        self.assertIsNone(result)

    # -- delete_draft ----------------------------------------------------
    def test_delete_draft_removes_from_queue_and_recordings(self):
        draft = self._create(recording_result={"path": "/tmp/x.wav"})
        self.assertIn(draft["id"], self.store.draft_recordings)
        ok = self.store.delete_draft(draft["id"], save_fn=self.store.save_history)
        self.assertTrue(ok)
        self.assertIsNone(self.store.get_draft_by_id(draft["id"]))
        self.assertNotIn(draft["id"], self.store.draft_recordings)

    def test_delete_draft_idempotent(self):
        draft = self._create()
        self.assertTrue(self.store.delete_draft(draft["id"], save_fn=self.store.save_history))
        self.assertFalse(self.store.delete_draft(draft["id"], save_fn=self.store.save_history))

    # -- duplicate_draft ---------------------------------------------------
    def test_duplicate_draft_is_pending_with_send_state_reset(self):
        draft = self._create(status="sent")
        stored = self.store.get_draft_by_id(draft["id"])
        stored["status"] = "sent"
        stored["send_result"] = {"ok": True}
        stored["pending_send"] = False

        dup = self.store.duplicate_draft(draft["id"], save_fn=self.store.save_history)
        self.assertIsNotNone(dup)
        self.assertEqual(dup["status"], "pending")
        self.assertIsNone(dup["send_result"])
        self.assertFalse(dup["pending_send"])
        self.assertNotEqual(dup["id"], draft["id"])
        self.assertEqual(dup["raw_text"], "hello world")

    def test_duplicate_draft_absent_returns_none(self):
        self.assertIsNone(self.store.duplicate_draft(999, save_fn=self.store.save_history))

    # -- create_from_record -------------------------------------------------
    def test_create_from_record_assigns_id_and_appends(self):
        record = {
            "raw_text": "built elsewhere", "final_text": "Built elsewhere.",
            "status": "pending", "preset": "True Janitor", "metadata": {}, "error": "",
            "gate_reasons": [], "confidence": {"score": None, "avg_logprob": None, "no_speech_prob": None},
            "pending_send": False, "send_result": None, "created_at": "2026-01-01T00:00:00Z",
        }
        before_next_id = self.store.next_draft_id
        result = self.store.create_from_record(dict(record), save_fn=self.store.save_history)
        self.assertEqual(result["id"], before_next_id)
        self.assertEqual(self.store.next_draft_id, before_next_id + 1)
        self.assertEqual(self.store.get_draft_by_id(result["id"])["raw_text"], "built elsewhere")

    def test_create_from_record_honours_max_history_trim(self):
        self.store.max_history = 2
        first = self.store.create_from_record(
            {"raw_text": "a", "final_text": "a", "status": "pending", "created_at": "t1"},
            save_fn=self.store.save_history,
        )
        self.store.draft_recordings[first["id"]] = {"path": "/tmp/a.wav"}
        self.store.create_from_record(
            {"raw_text": "b", "final_text": "b", "status": "pending", "created_at": "t2"},
            save_fn=self.store.save_history,
        )
        self.store.create_from_record(
            {"raw_text": "c", "final_text": "c", "status": "pending", "created_at": "t3"},
            save_fn=self.store.save_history,
        )
        self.assertEqual(len(self.store.draft_queue), 2)
        self.assertIsNone(self.store.get_draft_by_id(first["id"]))
        self.assertNotIn(first["id"], self.store.draft_recordings)

    # -- list_drafts ---------------------------------------------------
    def test_list_drafts_returns_all_without_filters(self):
        self._create()
        self._create()
        result = self.store.list_drafts()
        self.assertEqual(len(result), 2)

    def test_list_drafts_filters_by_status(self):
        a = self._create(status="pending")
        b = self._create(status="pending")
        stored_b = self.store.get_draft_by_id(b["id"])
        stored_b["status"] = "sent"
        result = self.store.list_drafts(filters={"status": "sent"})
        self.assertEqual([d["id"] for d in result], [b["id"]])


if __name__ == "__main__":
    unittest.main()
