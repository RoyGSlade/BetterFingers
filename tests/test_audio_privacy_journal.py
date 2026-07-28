"""The crash-recovery journal (Wave 8B, D-0010).

The invariant under test is the one the module exists for: **the journal is
written before the state changes, it is content-free, and it is recovered and
cleared at the next startup.**
"""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.platform.audio_privacy import base, journal as journal_mod  # noqa: E402


class _TempJournalCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "audio_privacy_journal.json")
        self.journal = journal_mod.PrivacyJournal(path=self.path, clock=lambda: 1000.0)


class WriteAndReadTests(_TempJournalCase):
    def test_a_record_round_trips(self):
        streams = [base.MutedStream("3", False, serial=9), base.MutedStream("4", False)]
        written = self.journal.record("linux_pulse", streams, lease_id="abc")
        self.assertTrue(written)
        self.assertEqual(self.journal.pending_streams(), streams)

    def test_the_file_is_on_disk_before_record_returns(self):
        # "Written before the state changes" is only true if record() is
        # synchronous through to the filesystem.
        self.journal.record("linux_pulse", [base.MutedStream("1", False)])
        self.assertTrue(os.path.exists(self.path))
        with open(self.path, "r", encoding="utf-8") as handle:
            self.assertEqual(json.load(handle)["adapter"], "linux_pulse")

    def test_the_written_record_contains_no_names_and_no_extra_keys(self):
        self.journal.record("linux_pulse", [base.MutedStream("1", False, serial=2)])
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        self.assertEqual(set(payload), {"version", "lease_id", "adapter", "started_at", "streams"})
        self.assertEqual(set(payload["streams"][0]), {"key", "prior_muted", "serial"})

    def test_extra_fields_are_stripped_rather_than_persisted(self):
        # Even if a future adapter hands over a dict with a label in it, the
        # sanitizer is the chokepoint and it drops everything unrecognized.
        record = self.journal.record(
            "linux_pulse",
            [{"key": "1", "prior_muted": False, "application_name": "Discord", "audio": [0.1]}],
        )
        self.assertEqual(set(record["streams"][0]), {"key", "prior_muted"})
        with open(self.path, "r", encoding="utf-8") as handle:
            self.assertNotIn("Discord", handle.read())

    def test_reading_a_missing_journal_is_empty_not_an_error(self):
        self.assertEqual(self.journal.read(), {})
        self.assertEqual(self.journal.pending_streams(), [])

    def test_a_corrupt_journal_reads_empty_and_is_left_for_the_caller(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("{not json")
        self.assertEqual(self.journal.read(), {})
        self.assertTrue(os.path.exists(self.path))

    def test_a_record_with_no_adapter_is_refused(self):
        self.assertEqual(self.journal.record("", [base.MutedStream("1", False)]), {})
        self.assertFalse(os.path.exists(self.path))

    def test_clear_is_idempotent(self):
        self.journal.record("linux_pulse", [base.MutedStream("1", False)])
        self.assertTrue(self.journal.clear())
        self.assertTrue(self.journal.clear())
        self.assertFalse(os.path.exists(self.path))

    def test_an_unwritable_location_reports_failure_instead_of_raising(self):
        bad = journal_mod.PrivacyJournal(path=os.path.join(self.tmp.name, "f.txt", "j.json"))
        with open(os.path.join(self.tmp.name, "f.txt"), "w", encoding="utf-8") as handle:
            handle.write("not a directory")
        self.assertEqual(bad.record("linux_pulse", [base.MutedStream("1", False)]), {})


class _RecordingGuard(base.PrivacyGuard):
    """A guard that records what it was asked to restore."""

    def __init__(self, name="linux_pulse", available=True, complete=True, raises=False):
        self.name = name
        self._available = available
        self._complete = complete
        self._raises = raises
        self.restored = None

    def availability(self):
        return self._available, base.AVAILABLE if self._available else base.UNAVAILABLE_TOOL_MISSING

    def restore(self, muted_streams, journal_replace=None):
        if self._raises:
            raise RuntimeError("audio server went away")
        self.restored = list(muted_streams)
        return base.RestoreOutcome(
            complete=self._complete,
            restored=len(self.restored) if self._complete else 0,
            failed=[] if self._complete else [s.key for s in self.restored],
        )


class RecoverPendingTests(_TempJournalCase):
    def test_no_journal_means_nothing_to_do(self):
        result = journal_mod.recover_pending(guard=_RecordingGuard(), journal=self.journal)
        self.assertFalse(result["recovered"])
        self.assertEqual(result["reason"], "no_journal")

    def test_a_pending_journal_is_restored_and_cleared(self):
        self.journal.record("linux_pulse", [base.MutedStream("3", False, serial=9)])
        guard = _RecordingGuard()
        result = journal_mod.recover_pending(guard=guard, journal=self.journal)

        self.assertTrue(result["recovered"])
        self.assertEqual([s.key for s in guard.restored], ["3"])
        self.assertEqual(guard.restored[0].serial, 9)
        self.assertFalse(os.path.exists(self.path))

    def test_a_failed_restore_is_reported_and_the_journal_is_still_cleared(self):
        # Retrying forever across restarts would let one unrestorable stream
        # block the feature permanently; the failure is reported instead.
        self.journal.record("linux_pulse", [base.MutedStream("3", False)])
        result = journal_mod.recover_pending(guard=_RecordingGuard(complete=False), journal=self.journal)
        self.assertFalse(result["recovered"])
        self.assertEqual(result["reason"], "restore_incomplete")
        self.assertFalse(os.path.exists(self.path))

    def test_a_guard_that_raises_does_not_propagate(self):
        self.journal.record("linux_pulse", [base.MutedStream("3", False)])
        result = journal_mod.recover_pending(guard=_RecordingGuard(raises=True), journal=self.journal)
        self.assertEqual(result["reason"], "restore_failed")
        self.assertFalse(os.path.exists(self.path))

    def test_a_journal_from_a_different_adapter_is_not_acted_on(self):
        self.journal.record("windows_core_audio", [base.MutedStream("3", False)])
        guard = _RecordingGuard(name="linux_pulse")
        result = journal_mod.recover_pending(guard=guard, journal=self.journal)
        self.assertEqual(result["reason"], "adapter_unavailable")
        self.assertIsNone(guard.restored)
        self.assertFalse(os.path.exists(self.path))

    def test_an_unavailable_adapter_cannot_restore(self):
        self.journal.record("linux_pulse", [base.MutedStream("3", False)])
        guard = _RecordingGuard(available=False)
        result = journal_mod.recover_pending(guard=guard, journal=self.journal)
        self.assertEqual(result["reason"], "adapter_unavailable")
        self.assertIsNone(guard.restored)

    def test_an_unreadable_journal_is_discarded(self):
        with open(self.path, "w", encoding="utf-8") as handle:
            handle.write("}{")
        result = journal_mod.recover_pending(guard=_RecordingGuard(), journal=self.journal)
        self.assertEqual(result["reason"], "unreadable_journal")
        self.assertFalse(os.path.exists(self.path))

    def test_an_empty_stream_list_clears_without_calling_the_adapter(self):
        self.journal.record("linux_pulse", [])
        guard = _RecordingGuard()
        result = journal_mod.recover_pending(guard=guard, journal=self.journal)
        self.assertEqual(result["reason"], "nothing_to_restore")
        self.assertIsNone(guard.restored)


class LeaseIdTests(unittest.TestCase):
    def test_lease_ids_are_random_and_content_free(self):
        first, second = journal_mod.new_lease_id(), journal_mod.new_lease_id()
        self.assertNotEqual(first, second)
        self.assertEqual(len(first), 32)
        self.assertTrue(all(c in "0123456789abcdef" for c in first))


if __name__ == "__main__":
    unittest.main()
