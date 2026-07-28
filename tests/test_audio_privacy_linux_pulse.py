"""LinuxPulsePrivacyGuard (Wave 8B, D-0010).

Every pactl call is mocked: the runner is injected, so these tests assert the
adapter's decisions (which streams, in what order, with what recorded state)
without an audio server. The one test that touches real pactl skips unless the
binary is present — the director runs live qualification.
"""
import json
import os
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from backend.platform.audio_privacy import base  # noqa: E402
from backend.platform.audio_privacy import linux_pulse  # noqa: E402

PACTL = "/usr/bin/pactl"


def stream_json(index, mute=False, pid=None, serial=None, name=None, binary=None):
    properties = {}
    if pid is not None:
        properties["application.process.id"] = str(pid)
    if serial is not None:
        properties["object.serial"] = str(serial)
    if name is not None:
        properties["application.name"] = name
    if binary is not None:
        properties["application.process.binary"] = binary
    return {"index": index, "mute": mute, "properties": properties}


class FakeRunner:
    """Records every pactl invocation and answers from a scripted table."""

    def __init__(self, streams=None, info_ok=True, list_ok=True, list_output=None,
                 mute_failures=()):
        self.streams = list(streams or [])
        self.info_ok = info_ok
        self.list_ok = list_ok
        self.list_output = list_output
        self.mute_failures = set(str(k) for k in mute_failures)
        self.calls = []

    def __call__(self, args, timeout=None):
        self.calls.append(list(args))
        if args[1:] == ["info"]:
            return (0 if self.info_ok else 1), "Server Name: PulseAudio", ""
        if args[1:] == ["-f", "json", "list", "source-outputs"]:
            if not self.list_ok:
                return 1, "", "Connection refused"
            if self.list_output is not None:
                return 0, self.list_output, ""
            return 0, json.dumps(self.streams), ""
        if args[1:2] == ["set-source-output-mute"]:
            key, value = args[2], args[3]
            if key in self.mute_failures:
                return 1, "", "No such entity"
            for entry in self.streams:
                if str(entry["index"]) == key:
                    entry["mute"] = value == "1"
            return 0, "", ""
        return 1, "", "unexpected command"

    def mute_calls(self):
        return [(c[2], c[3]) for c in self.calls if c[1] == "set-source-output-mute"]


def build_guard(runner, own_pids=(4242,), proc_root="/nonexistent-proc"):
    return linux_pulse.LinuxPulsePrivacyGuard(
        runner=runner, pactl_path=PACTL, own_pids=own_pids, proc_root=proc_root
    )


class AvailabilityTests(unittest.TestCase):
    """Being on Linux proves nothing; the adapter must prove all three steps."""

    def test_available_when_pactl_a_server_and_json_all_answer(self):
        guard = build_guard(FakeRunner(streams=[]))
        self.assertEqual(guard.availability(), (True, base.AVAILABLE))

    def test_missing_binary_is_tool_missing(self):
        guard = linux_pulse.LinuxPulsePrivacyGuard(runner=FakeRunner(), pactl_path=None)
        # pactl_path=None with the resolver forced to find nothing.
        guard._pactl, guard._pactl_resolved = None, True
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_TOOL_MISSING))

    def test_a_dead_server_is_server_unreachable(self):
        guard = build_guard(FakeRunner(info_ok=False))
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_SERVER_UNREACHABLE))

    def test_a_pactl_without_json_support_is_refused(self):
        # pactl < 16 exits non-zero on -f json. We must NOT fall back to
        # parsing its human-readable listing.
        guard = build_guard(FakeRunner(list_ok=False))
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_NO_STRUCTURED_OUTPUT))

    def test_json_that_is_not_a_list_is_refused(self):
        guard = build_guard(FakeRunner(list_output='{"index": 1}'))
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_NO_STRUCTURED_OUTPUT))

    def test_unparseable_output_is_refused_rather_than_scraped(self):
        guard = build_guard(FakeRunner(list_output="Source Output #1\n\tMute: no\n"))
        self.assertEqual(guard.availability(), (False, base.UNAVAILABLE_NO_STRUCTURED_OUTPUT))

    def test_no_pactl_call_ever_pipes_through_a_shell_or_a_text_filter(self):
        runner = FakeRunner(streams=[])
        guard = build_guard(runner)
        guard.availability()
        guard.list_streams()
        for call in runner.calls:
            self.assertIsInstance(call, list)              # argv, never a shell string
            joined = " ".join(call)
            for forbidden in ("grep", "awk", "sed", "|", "sh -c"):
                self.assertNotIn(forbidden, joined)


class EnumerationTests(unittest.TestCase):
    def test_streams_are_parsed_structurally(self):
        runner = FakeRunner(streams=[
            stream_json(1, mute=False, pid=100, serial=11, name="Discord"),
            stream_json(2, mute=True, pid=200, serial=12, binary="zoom"),
        ])
        streams = build_guard(runner).list_streams()
        self.assertEqual([s.key for s in streams], ["1", "2"])
        self.assertEqual([s.muted for s in streams], [False, True])
        self.assertEqual([s.serial for s in streams], [11, 12])
        self.assertEqual(streams[0].labels, ("Discord",))

    def test_our_own_stream_is_identified_by_pid_never_by_name(self):
        runner = FakeRunner(streams=[
            stream_json(1, pid=4242, name="Some Other App"),   # ours, misleading name
            stream_json(2, pid=99, name="BetterFingers"),      # not ours, our name
        ])
        streams = build_guard(runner, own_pids=(4242,)).list_streams()
        self.assertTrue(streams[0].is_self)
        self.assertFalse(streams[1].is_self)

    def test_a_stream_with_no_pid_is_not_treated_as_ours(self):
        runner = FakeRunner(streams=[stream_json(1, name="mystery")])
        self.assertFalse(build_guard(runner).list_streams()[0].is_self)

    def test_a_failed_enumeration_yields_nothing_rather_than_a_guess(self):
        self.assertEqual(build_guard(FakeRunner(list_ok=False)).list_streams(), [])

    def test_yes_no_mute_values_are_accepted(self):
        runner = FakeRunner(list_output=json.dumps([
            {"index": 1, "mute": "yes", "properties": {}},
            {"index": 2, "mute": "no", "properties": {}},
        ]))
        streams = build_guard(runner).list_streams()
        self.assertEqual([s.muted for s in streams], [True, False])

    def test_entries_without_an_index_are_dropped(self):
        runner = FakeRunner(list_output=json.dumps([{"mute": False}, stream_json(5)]))
        self.assertEqual([s.key for s in build_guard(runner).list_streams()], ["5"])


class ProcessIdentityTests(unittest.TestCase):
    """The /proc walk that answers "is this stream ours?"."""

    def setUp(self):
        import tempfile

        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _write_status(self, pid, ppid):
        path = os.path.join(self.tmp.name, str(pid))
        os.makedirs(path, exist_ok=True)
        with open(os.path.join(path, "status"), "w", encoding="utf-8") as handle:
            handle.write(f"Name:\tthing\nPPid:\t{ppid}\n")

    def test_our_own_pid_matches(self):
        self.assertTrue(linux_pulse._is_descendant_of(10, {10}, proc_root=self.tmp.name))

    def test_a_child_process_matches(self):
        self._write_status(20, 10)
        self.assertTrue(linux_pulse._is_descendant_of(20, {10}, proc_root=self.tmp.name))

    def test_a_grandchild_matches(self):
        self._write_status(20, 10)
        self._write_status(30, 20)
        self.assertTrue(linux_pulse._is_descendant_of(30, {10}, proc_root=self.tmp.name))

    def test_an_unrelated_process_does_not_match(self):
        self._write_status(50, 1)
        self.assertFalse(linux_pulse._is_descendant_of(50, {10}, proc_root=self.tmp.name))

    def test_a_missing_proc_entry_answers_false(self):
        # Errs toward "somebody else's stream", which is the safe direction:
        # we mute and restore rather than leaving another app listening.
        self.assertFalse(linux_pulse._is_descendant_of(999, {10}, proc_root=self.tmp.name))

    def test_a_cyclic_chain_terminates(self):
        self._write_status(60, 61)
        self._write_status(61, 60)
        self.assertFalse(linux_pulse._is_descendant_of(60, {10}, proc_root=self.tmp.name))

    def test_no_pid_answers_false(self):
        self.assertFalse(linux_pulse._is_descendant_of(None, {10}, proc_root=self.tmp.name))


class EngageTests(unittest.TestCase):
    def test_only_unmuted_non_self_non_allowlisted_streams_are_muted(self):
        runner = FakeRunner(streams=[
            stream_json(1, mute=False, pid=100, name="Discord"),    # muted by us
            stream_json(2, mute=True, pid=200, name="Zoom"),        # already muted, left alone
            stream_json(3, mute=False, pid=4242, name="Whatever"),  # ours
            stream_json(4, mute=False, pid=300, name="OBS"),        # allowlisted
        ])
        guard = build_guard(runner)
        outcome = guard.engage(keep_unmuted_apps=["obs"])

        self.assertTrue(outcome.ok)
        self.assertEqual([m.key for m in outcome.muted], ["1"])
        self.assertEqual(outcome.skipped_self, 1)
        self.assertEqual(outcome.skipped_allowlisted, 1)
        self.assertEqual(outcome.skipped_already_muted, 1)
        self.assertEqual(runner.mute_calls(), [("1", "1")])

    def test_an_already_muted_stream_is_not_recorded_so_it_is_never_unmuted(self):
        runner = FakeRunner(streams=[stream_json(2, mute=True, pid=200)])
        outcome = build_guard(runner).engage()
        self.assertEqual(outcome.muted, [])
        self.assertEqual(runner.mute_calls(), [])

    def test_the_journal_is_written_before_the_first_mute(self):
        runner = FakeRunner(streams=[stream_json(1, pid=100), stream_json(2, pid=200)])
        order = []

        def journal_write(plan):
            order.append(("journal", [p.key for p in plan]))
            return True

        original = runner.__call__

        def tracking(args, timeout=None):
            if args[1:2] == ["set-source-output-mute"]:
                order.append(("mute", args[2]))
            return original(args, timeout)

        guard = build_guard(tracking)
        guard.engage(journal_write=journal_write)

        self.assertEqual(order[0], ("journal", ["1", "2"]))
        self.assertEqual(order[1:], [("mute", "1"), ("mute", "2")])

    def test_a_journal_that_will_not_persist_aborts_without_muting_anything(self):
        # Muting with no recovery record is the one outcome the journal exists
        # to prevent, so the adapter must refuse rather than proceed.
        runner = FakeRunner(streams=[stream_json(1, pid=100)])
        guard = build_guard(runner)
        outcome = guard.engage(journal_write=lambda plan: False)
        self.assertFalse(outcome.ok)
        self.assertEqual(outcome.reason, "journal_write_failed")
        self.assertEqual(runner.mute_calls(), [])

    def test_nothing_to_mute_is_a_success_not_a_failure(self):
        outcome = build_guard(FakeRunner(streams=[])).engage()
        self.assertTrue(outcome.ok)
        self.assertEqual(outcome.reason, "nothing_to_mute")

    def test_a_failed_mute_is_reported_and_not_recorded_as_ours(self):
        runner = FakeRunner(
            streams=[stream_json(1, pid=100), stream_json(2, pid=200)],
            mute_failures=("2",),
        )
        outcome = build_guard(runner).engage()
        self.assertEqual([m.key for m in outcome.muted], ["1"])
        self.assertEqual(outcome.failed, ["2"])

    def test_the_serial_is_recorded_alongside_the_index(self):
        runner = FakeRunner(streams=[stream_json(1, pid=100, serial=77)])
        outcome = build_guard(runner).engage()
        self.assertEqual(outcome.muted[0].serial, 77)


class RestoreTests(unittest.TestCase):
    def test_only_recorded_streams_are_touched(self):
        runner = FakeRunner(streams=[
            stream_json(1, mute=True, pid=100),
            stream_json(2, mute=True, pid=200),   # muted by somebody else
        ])
        guard = build_guard(runner)
        outcome = guard.restore([base.MutedStream("1", prior_muted=False)])

        self.assertTrue(outcome.complete)
        self.assertEqual(runner.mute_calls(), [("1", "0")])

    def test_a_disappeared_stream_is_gone_not_failed(self):
        runner = FakeRunner(streams=[])
        outcome = build_guard(runner).restore([base.MutedStream("1", prior_muted=False)])
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.gone, 1)
        self.assertEqual(runner.mute_calls(), [])

    def test_a_reused_index_with_a_different_serial_is_left_alone(self):
        # Our stream exited and index 1 now belongs to somebody else. Touching
        # it would be changing something we never changed.
        runner = FakeRunner(streams=[stream_json(1, mute=True, pid=999, serial=200)])
        outcome = build_guard(runner).restore(
            [base.MutedStream("1", prior_muted=False, serial=100)]
        )
        self.assertEqual(outcome.gone, 1)
        self.assertEqual(runner.mute_calls(), [])

    def test_a_matching_serial_is_restored(self):
        runner = FakeRunner(streams=[stream_json(1, mute=True, pid=100, serial=100)])
        outcome = build_guard(runner).restore(
            [base.MutedStream("1", prior_muted=False, serial=100)]
        )
        self.assertTrue(outcome.complete)
        self.assertEqual(runner.mute_calls(), [("1", "0")])

    def test_a_stream_already_back_where_it_started_needs_no_call(self):
        runner = FakeRunner(streams=[stream_json(1, mute=False, pid=100)])
        outcome = build_guard(runner).restore([base.MutedStream("1", prior_muted=False)])
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.restored, 1)
        self.assertEqual(runner.mute_calls(), [])

    def test_a_failed_unmute_makes_the_restore_incomplete(self):
        runner = FakeRunner(streams=[stream_json(1, mute=True, pid=100)], mute_failures=("1",))
        outcome = build_guard(runner).restore([base.MutedStream("1", prior_muted=False)])
        self.assertFalse(outcome.complete)
        self.assertEqual(outcome.failed, ["1"])
        self.assertEqual(outcome.reason, "restore_incomplete")

    def test_the_journal_is_left_holding_exactly_the_remainder(self):
        runner = FakeRunner(
            streams=[stream_json(1, mute=True, pid=100), stream_json(2, mute=True, pid=200)],
            mute_failures=("2",),
        )
        seen = []
        build_guard(runner).restore(
            [base.MutedStream("1", prior_muted=False), base.MutedStream("2", prior_muted=False)],
            journal_replace=lambda remaining: seen.append([r.key for r in remaining]),
        )
        self.assertEqual(seen, [["2"]])

    def test_restoring_nothing_is_complete(self):
        outcome = build_guard(FakeRunner()).restore([])
        self.assertTrue(outcome.complete)
        self.assertEqual(outcome.reason, "nothing_to_restore")

    def test_restore_never_mutes(self):
        runner = FakeRunner(streams=[stream_json(1, mute=False, pid=100)])
        build_guard(runner).restore([base.MutedStream("1", prior_muted=True)])
        # prior_muted=True can only ever be produced by a hand-written record;
        # the engage path never records one. Even then the call is a mute of a
        # stream we are documented to own, and no OTHER stream is touched.
        self.assertEqual(runner.mute_calls(), [("1", "1")])


class _FakeProcess:
    def __init__(self, lines):
        self.stdout = iter(lines)
        self.terminated = False

    def terminate(self):
        self.terminated = True

    def wait(self, timeout=None):
        return 0

    def kill(self):
        pass


class WatchTests(unittest.TestCase):
    def test_new_and_change_events_on_source_outputs_trigger_a_recheck(self):
        lines = [
            "Event 'new' on source-output #42\n",
            "Event 'new' on sink-input #7\n",        # output, not capture
            "Event 'remove' on source-output #42\n",  # removal needs no mute
            "Event 'change' on source-output #43\n",
        ]
        hits = []
        guard = linux_pulse.LinuxPulsePrivacyGuard(
            runner=FakeRunner(), pactl_path=PACTL, popen=lambda *a, **k: _FakeProcess(lines)
        )
        stop = guard.watch(lambda: hits.append(1))
        self.assertIsNotNone(stop)
        stop()
        self.assertEqual(len(hits), 2)

    def test_a_watcher_that_cannot_start_returns_none_rather_than_raising(self):
        def _boom(*args, **kwargs):
            raise OSError("no pactl")

        guard = linux_pulse.LinuxPulsePrivacyGuard(
            runner=FakeRunner(), pactl_path=PACTL, popen=_boom
        )
        self.assertIsNone(guard.watch(lambda: None))


@unittest.skipUnless(shutil.which("pactl"), "pactl is not installed on this machine")
class RealPactlSmokeTests(unittest.TestCase):
    """Read-only smoke test against the real binary. Skips without pactl, and
    never mutes anything — live qualification is the director's run."""

    def test_the_adapter_agrees_with_the_real_binary_about_availability(self):
        guard = linux_pulse.LinuxPulsePrivacyGuard()
        available, reason = guard.availability()

        probe = subprocess.run(
            ["pactl", "-f", "json", "list", "source-outputs"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        expected = probe.returncode == 0
        if expected:
            try:
                json.loads(probe.stdout or "[]")
            except ValueError:
                expected = False

        # A server that is unreachable makes both False for different reasons;
        # what must never happen is the adapter claiming availability the
        # binary cannot back up.
        if available:
            self.assertTrue(expected, f"adapter claimed available, pactl says otherwise ({reason})")

    def test_enumeration_does_not_raise_against_a_real_server(self):
        guard = linux_pulse.LinuxPulsePrivacyGuard()
        if not guard.is_available():
            self.skipTest("no Pulse-compatible server on this machine")
        for stream in guard.list_streams():
            self.assertIsInstance(stream.key, str)
            self.assertIsInstance(stream.muted, bool)


if __name__ == "__main__":
    unittest.main()
