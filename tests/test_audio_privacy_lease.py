"""The privacy lease (Wave 8B, D-0010).

What matters here is not that the lease can engage — it is that **every stop
path releases**, that a partial restore is reported rather than swallowed, and
that a stored ``isolate_capture_streams`` becomes real isolation where an
adapter exists and degrades visibly to push-to-mute where one does not.
"""
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import audio_schema  # noqa: E402
import audio_status  # noqa: E402
from backend.platform.audio_privacy import base, journal as journal_mod  # noqa: E402
from backend.platform.audio_privacy import lease as lease_mod  # noqa: E402


class FakeGuard(base.PrivacyGuard):
    """An in-memory audio server: streams, mutes, and a watch hook."""

    name = "linux_pulse"

    def __init__(self, streams=None, available=True, restore_complete=True,
                 engage_failure=False, watchable=True):
        self.name = "linux_pulse"
        self._available = available
        self._streams = list(streams or [])
        self._restore_complete = restore_complete
        self._engage_failure = engage_failure
        self._watchable = watchable
        self.engage_calls = 0
        self.restored = []
        self.watch_stopped = False
        self.on_new_stream = None

    def availability(self):
        return self._available, base.AVAILABLE if self._available else base.UNAVAILABLE_TOOL_MISSING

    def add_stream(self, key, muted=False, is_self=False, labels=()):
        self._streams.append(base.CaptureStream(key=key, muted=muted, is_self=is_self, labels=labels))

    def engage(self, keep_unmuted_apps=(), journal_write=None):
        self.engage_calls += 1
        if self._engage_failure:
            return base.EngageOutcome(ok=False, reason="mute_failed", failed=["1"])
        plan = [
            base.MutedStream(key=s.key, prior_muted=False)
            for s in self._streams
            if not s.is_self and not s.muted and not s.matches_allowlist(keep_unmuted_apps)
        ]
        if not plan:
            return base.EngageOutcome(ok=True, reason="nothing_to_mute")
        if journal_write is not None and not journal_write(plan):
            return base.EngageOutcome(ok=False, reason="journal_write_failed")
        self._streams = [
            base.CaptureStream(key=s.key, muted=True, is_self=s.is_self, labels=s.labels)
            if any(p.key == s.key for p in plan) else s
            for s in self._streams
        ]
        return base.EngageOutcome(ok=True, muted=plan, reason="engaged")

    def restore(self, muted_streams, journal_replace=None):
        entries = list(muted_streams)
        self.restored.extend(entries)
        if self._restore_complete:
            if journal_replace is not None:
                journal_replace([])
            return base.RestoreOutcome(complete=True, restored=len(entries))
        if journal_replace is not None:
            journal_replace(entries)
        return base.RestoreOutcome(complete=False, failed=[e.key for e in entries],
                                   reason="restore_incomplete")

    def watch(self, on_new_stream):
        if not self._watchable:
            return None
        self.on_new_stream = on_new_stream

        def _stop():
            self.watch_stopped = True

        return _stop


class FakeInjector:
    def __init__(self, hold_raises=False, release_raises=False):
        self.held = False
        self.holds = 0
        self.releases = 0
        self._hold_raises = hold_raises
        self._release_raises = release_raises

    def hold_mute_key(self):
        self.holds += 1
        if self._hold_raises:
            raise RuntimeError("no injection tool")
        self.held = True

    def release_mute_key(self):
        self.releases += 1
        if self._release_raises:
            raise RuntimeError("tool went away")
        self.held = False


def isolate_config(keep=None):
    return {
        "voice_privacy": {
            "mode": audio_schema.PRIVACY_MODE_ISOLATE,
            "mute_binding": "f13",
            "keep_unmuted_apps": list(keep or []),
            "announce_failures": True,
        }
    }


def push_config():
    return {
        "voice_privacy": {
            "mode": audio_schema.PRIVACY_MODE_PUSH_TO_MUTE,
            "mute_binding": "f13",
            "keep_unmuted_apps": [],
            "announce_failures": True,
        }
    }


def off_config():
    return {"voice_privacy": {"mode": audio_schema.PRIVACY_MODE_OFF, "mute_binding": ""}}


class _LeaseCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.journal_path = os.path.join(self.tmp.name, "journal.json")
        self.journal = journal_mod.PrivacyJournal(path=self.journal_path, clock=lambda: 1.0)
        self.injector = FakeInjector()

    def build(self, guard, injector=None):
        return lease_mod.AudioPrivacyLease(
            guard=guard,
            journal=self.journal,
            push_to_mute_provider=lambda: injector if injector is not None else self.injector,
        )


class ModeSelectionTests(_LeaseCase):
    def test_privacy_off_engages_nothing(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        status = lease.acquire(off_config())

        self.assertFalse(status["held"])
        self.assertEqual(guard.engage_calls, 0)
        self.assertEqual(self.injector.holds, 0)

    def test_isolation_runs_when_an_adapter_is_available(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        status = lease.acquire(isolate_config())

        self.assertTrue(status["held"])
        self.assertEqual(status["mode"], audio_schema.PRIVACY_MODE_ISOLATE)
        self.assertEqual(status["muted_streams"], 1)
        self.assertEqual(self.injector.holds, 0)

    def test_isolation_degrades_to_push_to_mute_when_no_adapter_exists(self):
        # Exactly what audio_schema.effective_privacy_mode already promised;
        # the lease must honor it rather than silently doing nothing.
        lease = self.build(base.NullPrivacyGuard())
        status = lease.acquire(isolate_config())

        self.assertTrue(status["held"])
        self.assertEqual(status["mode"], audio_schema.PRIVACY_MODE_PUSH_TO_MUTE)
        self.assertTrue(self.injector.held)

    def test_push_to_mute_holds_the_key(self):
        lease = self.build(base.NullPrivacyGuard())
        lease.acquire(push_config())
        self.assertTrue(self.injector.held)

    def test_push_to_mute_with_no_injector_is_reported_not_pretended(self):
        lease = lease_mod.AudioPrivacyLease(
            guard=base.NullPrivacyGuard(), journal=self.journal,
            push_to_mute_provider=lambda: None,
        )
        status = lease.acquire(push_config())
        self.assertEqual(status["reason"], "push_to_mute_unavailable")

    def test_the_keep_unmuted_allowlist_is_honored(self):
        guard = FakeGuard()
        guard.add_stream("1", labels=("Discord",))
        guard.add_stream("2", labels=("OBS",))
        lease = self.build(guard)
        status = lease.acquire(isolate_config(keep=["obs"]))
        self.assertEqual(status["muted_streams"], 1)


class AcquireReleaseTests(_LeaseCase):
    def test_acquire_is_idempotent(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        lease.acquire(isolate_config())
        self.assertEqual(guard.engage_calls, 1)

    def test_release_puts_back_exactly_what_was_muted(self):
        guard = FakeGuard()
        guard.add_stream("1")
        guard.add_stream("2", muted=True)      # somebody else's mute
        lease = self.build(guard)
        lease.acquire(isolate_config())
        status = lease.release()

        self.assertFalse(status["held"])
        self.assertEqual([r.key for r in guard.restored], ["1"])
        self.assertTrue(lease.restore_complete())

    def test_release_is_idempotent_across_every_racing_stop_path(self):
        # Emergency stop, wipe and shutdown can all fire for one recording.
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        for reason in ("stop", "emergency_stop", "privacy_wipe", "shutdown"):
            lease.release(reason=reason)
        self.assertEqual(len(guard.restored), 1)
        self.assertEqual(self.injector.releases, 0)

    def test_releasing_a_lease_that_was_never_acquired_is_safe(self):
        lease = self.build(FakeGuard())
        status = lease.release()
        self.assertFalse(status["held"])
        self.assertTrue(lease.restore_complete())

    def test_push_to_mute_release_drops_the_key(self):
        lease = self.build(base.NullPrivacyGuard())
        lease.acquire(push_config())
        lease.release()
        self.assertFalse(self.injector.held)
        self.assertEqual(self.injector.releases, 1)

    def test_the_watcher_is_torn_down_on_release(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        self.assertTrue(lease.status()["watching"])
        lease.release()
        self.assertTrue(guard.watch_stopped)
        self.assertFalse(lease.status()["watching"])

    def test_a_guard_that_cannot_watch_still_isolates(self):
        guard = FakeGuard(watchable=False)
        guard.add_stream("1")
        lease = self.build(guard)
        status = lease.acquire(isolate_config())
        self.assertTrue(status["held"])
        self.assertFalse(status["watching"])

    def test_an_engage_failure_never_blocks_the_recording(self):
        lease = self.build(FakeGuard(engage_failure=True))
        status = lease.acquire(isolate_config())
        self.assertTrue(status["held"])       # the lease still exists to be released
        self.assertEqual(status["muted_streams"], 0)

    def test_a_hold_that_raises_is_caught(self):
        lease = self.build(base.NullPrivacyGuard(), injector=FakeInjector(hold_raises=True))
        status = lease.acquire(push_config())
        self.assertEqual(status["reason"], "push_to_mute_failed")


class RestoreHonestyTests(_LeaseCase):
    """``restore_complete`` is measured now, not a constant."""

    def test_a_complete_restore_reports_complete(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        lease.release()
        self.assertTrue(lease.restore_complete())

    def test_a_partial_restore_reports_partially_restored(self):
        guard = FakeGuard(restore_complete=False)
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        lease.release()

        self.assertFalse(lease.restore_complete())
        status = audio_status.voice_privacy_status(
            isolate_config(), isolation_available=True,
            restore_complete=lease.restore_complete(),
        )
        self.assertEqual(status["status"], audio_status.VOICE_PRIVACY_PARTIALLY_RESTORED)
        self.assertEqual(status["reason"], audio_status.REASON_RESTORE_INCOMPLETE)

    def test_a_partial_restore_is_sticky_until_acknowledged(self):
        # A later clean recording must not paper over a microphone we left
        # muted in somebody else's application.
        guard = FakeGuard(restore_complete=False)
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        lease.release()

        guard._restore_complete = True
        guard.add_stream("2")
        lease.acquire(isolate_config())
        lease.release()
        self.assertFalse(lease.restore_complete())

        lease.acknowledge_partial_restore()
        self.assertTrue(lease.restore_complete())

    def test_a_release_key_failure_makes_the_restore_incomplete(self):
        lease = self.build(base.NullPrivacyGuard(), injector=FakeInjector(release_raises=True))
        lease.acquire(push_config())
        lease.release()
        self.assertFalse(lease.restore_complete())

    def test_an_injector_that_vanished_before_release_is_incomplete(self):
        injector = FakeInjector()
        holder = {"injector": injector}
        lease = lease_mod.AudioPrivacyLease(
            guard=base.NullPrivacyGuard(), journal=self.journal,
            push_to_mute_provider=lambda: holder["injector"],
        )
        lease.acquire(push_config())
        holder["injector"] = None
        lease.release()
        self.assertFalse(lease.restore_complete())


class JournalIntegrationTests(_LeaseCase):
    def test_the_journal_exists_while_held_and_is_gone_after_a_clean_release(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)

        lease.acquire(isolate_config())
        self.assertTrue(os.path.exists(self.journal_path))
        self.assertEqual([s.key for s in self.journal.pending_streams()], ["1"])

        lease.release()
        self.assertFalse(os.path.exists(self.journal_path))

    def test_a_partial_restore_leaves_the_remainder_journaled_for_next_startup(self):
        guard = FakeGuard(restore_complete=False)
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        lease.release()

        self.assertEqual([s.key for s in self.journal.pending_streams()], ["1"])

    def test_a_journal_that_will_not_write_prevents_muting(self):
        bad = journal_mod.PrivacyJournal(path=os.path.join(self.tmp.name, "nope", "x", "j.json"))
        # Make the parent path a file so makedirs fails.
        with open(os.path.join(self.tmp.name, "nope"), "w", encoding="utf-8") as handle:
            handle.write("x")
        guard = FakeGuard()
        guard.add_stream("1")
        lease = lease_mod.AudioPrivacyLease(
            guard=guard, journal=bad, push_to_mute_provider=lambda: self.injector
        )
        status = lease.acquire(isolate_config())
        self.assertEqual(status["muted_streams"], 0)

    def test_a_mid_recording_stream_is_muted_and_joins_the_journal(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())

        guard.add_stream("2")          # a capture client starts mid-recording
        guard.on_new_stream()

        self.assertEqual(lease.status()["muted_streams"], 2)
        self.assertEqual([s.key for s in self.journal.pending_streams()], ["1", "2"])

        lease.release()
        self.assertEqual(sorted(r.key for r in guard.restored), ["1", "2"])

    def test_a_new_stream_event_after_release_does_nothing(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())
        callback = guard.on_new_stream
        lease.release()

        guard.add_stream("2")
        callback()
        self.assertEqual(lease.status()["muted_streams"], 0)


class CrashRecoveryTests(_LeaseCase):
    def test_a_crashed_lease_is_recovered_on_the_next_startup(self):
        guard = FakeGuard()
        guard.add_stream("1")
        lease = self.build(guard)
        lease.acquire(isolate_config())

        # Simulate the crash: the process dies with the journal on disk and no
        # release ever running.
        del lease
        self.assertTrue(os.path.exists(self.journal_path))

        fresh_guard = FakeGuard()
        result = lease_mod.recover_on_startup(guard=fresh_guard, journal=self.journal)

        self.assertTrue(result["recovered"])
        self.assertEqual([r.key for r in fresh_guard.restored], ["1"])
        self.assertFalse(os.path.exists(self.journal_path))


class SingletonTests(unittest.TestCase):
    def tearDown(self):
        lease_mod.reset_lease_for_tests(None)

    def test_get_lease_returns_the_same_object(self):
        lease_mod.reset_lease_for_tests(None)
        self.assertIs(lease_mod.get_lease(), lease_mod.get_lease())

    def test_resetting_releases_a_held_lease_rather_than_leaking_a_mute(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        guard = FakeGuard()
        guard.add_stream("1")
        lease = lease_mod.AudioPrivacyLease(
            guard=guard,
            journal=journal_mod.PrivacyJournal(path=os.path.join(tmp.name, "j.json")),
            push_to_mute_provider=lambda: None,
        )
        lease.acquire(isolate_config())
        lease_mod.reset_lease_for_tests(lease)
        lease_mod.reset_lease_for_tests(None)
        self.assertEqual([r.key for r in guard.restored], ["1"])


if __name__ == "__main__":
    unittest.main()
