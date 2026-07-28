"""ApplicationContextService (Wave 7).

The rule this suite exists to hold is the one in ``NoInferenceTests``: the
service may select a profile and nothing else. Every other test here protects a
behaviour whose failure is invisible until it costs someone something -- a
profile that switches mid-recording, a Wayland session that gets a confident
wrong answer, a window title read for a person's name, or an alt-tab that
unloads a model.
"""

import unittest

from backend.domain import gaming_policy
from backend.services import app_context as ac
from backend.stores.app_profiles import AppProfileStore

import os
import tempfile


class _Clock:
    """Injected millisecond clock -- no sleeping in tests."""

    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now

    def advance(self, ms):
        self.now += ms
        return self.now


class _Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.store = AppProfileStore(path=os.path.join(self._tmp.name, "app_profiles.json"))
        self.clock = _Clock()
        self.detected = ""
        self.service = ac.ApplicationContextService(
            store=self.store,
            detector=lambda: self.detected,
            clock=self.clock,
            debounce_ms=600,
        )

    def tearDown(self):
        self._tmp.cleanup()

    def focus(self, raw, settle=True):
        """Observe an application and let the debounce elapse.

        Returns the snapshot from the settling observe, not a later current():
        an announcement is one-shot and is cleared once delivered, so reading
        it back afterwards would always see "".
        """
        snapshot = self.service.observe(raw)
        if settle:
            self.clock.advance(600)
            snapshot = self.service.observe(raw)
        return snapshot

    def imported_modules(self):
        """Every module name ``app_context`` imports, anywhere in the file --
        parsed, so prose in a docstring cannot pass or fail the check."""
        import ast
        import inspect

        names = set()
        for node in ast.walk(ast.parse(inspect.getsource(ac))):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                names.add(node.module.split(".")[0])
                names.add(node.module)
        return names


class ResolutionTests(_Base):
    def test_unknown_resolves_to_default_and_says_so(self):
        snapshot = self.service.current()
        self.assertEqual(snapshot["profile_id"], "default")
        self.assertEqual(snapshot["source"], "unknown")
        self.assertFalse(snapshot["detected"])

    def test_wayland_empty_detection_stays_default_and_unknown(self):
        # No DISPLAY, no xdotool, no portable focused-window query: detection
        # returns "" and that must read as "cannot see", not as an app.
        self.detected = ""
        snapshot = self.service.poll()
        self.assertEqual(snapshot["profile_id"], "default")
        self.assertEqual(snapshot["source"], "unknown")
        self.assertEqual(snapshot["app_key"], "")

    def test_discord_matches_its_builtin(self):
        snapshot = self.focus("discord")
        self.assertEqual(snapshot["profile_id"], "discord")
        self.assertEqual(snapshot["source"], "matched")
        self.assertEqual(snapshot["app_key"], "discord")

    def test_windows_executable_name_matches(self):
        self.assertEqual(self.focus("RocketLeague.exe")["profile_id"], "rocket_league")

    def test_wm_class_with_a_dotted_prefix_matches(self):
        self.assertEqual(self.focus("Navigator.Wow.exe")["profile_id"], "world_of_warcraft")

    def test_libreoffice_alias_matches_the_writing_profile(self):
        # normalize_app maps soffice -> libreoffice; the writing profile lists
        # both, so either spelling has to land in the same place.
        self.assertEqual(self.focus("soffice")["profile_id"], "writing_app")
        self.assertEqual(self.focus("libreoffice-writer")["profile_id"], "writing_app")

    def test_an_unrecognised_application_resolves_to_default_not_a_guess(self):
        snapshot = self.focus("some-obscure-editor")
        self.assertEqual(snapshot["profile_id"], "default")
        self.assertEqual(snapshot["source"], "default")
        self.assertTrue(snapshot["detected"])

    def test_a_window_title_is_never_used_as_a_match_input(self):
        # A title like "Priya - Discord" must NOT select the Discord profile:
        # detection is class-only precisely so a person's name can never be an
        # input to this feature.
        raw = "Priya - Discord"
        self.assertFalse(ac._matches(self.store.get("discord"), self.service.normalize(raw), raw))

    def test_classify_is_pure_and_ignores_the_current_state(self):
        self.focus("discord")
        self.assertEqual(self.service.classify("wow.exe", "wow.exe")[0], "world_of_warcraft")
        self.assertEqual(self.service.current()["profile_id"], "discord")

    def test_gaming_policy_rides_along_with_a_game_profile(self):
        snapshot = self.focus("RocketLeague.exe")
        self.assertTrue(snapshot["gaming_policy"]["active"])
        self.assertEqual(snapshot["gaming_policy"]["max_completion_tokens"],
                         gaming_policy.MAX_COMPLETION_TOKENS)
        self.assertFalse(self.focus("discord")["gaming_policy"]["active"])


class DebounceTests(_Base):
    def test_a_transient_focus_does_not_switch(self):
        self.focus("discord")
        # Alt-tabbing through a window on the way somewhere else.
        self.service.observe("wow.exe")
        self.clock.advance(100)
        self.service.observe("wow.exe")
        self.assertEqual(self.service.current()["profile_id"], "discord")

    def test_a_settled_focus_switches(self):
        self.focus("discord")
        self.service.observe("wow.exe")
        self.clock.advance(600)
        self.service.observe("wow.exe")
        self.assertEqual(self.service.current()["profile_id"], "world_of_warcraft")

    def test_flapping_back_before_the_window_elapses_never_switches(self):
        self.focus("discord")
        for _ in range(5):
            self.service.observe("wow.exe")
            self.clock.advance(100)
            self.service.observe("discord")
            self.clock.advance(100)
        self.assertEqual(self.service.current()["profile_id"], "discord")

    def test_subscribers_see_one_event_per_real_change(self):
        events = []
        self.service.subscribe(events.append)
        self.focus("discord")
        self.focus("discord")
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["profile_id"], "discord")

    def test_unsubscribe_stops_delivery(self):
        events = []
        stop = self.service.subscribe(events.append)
        self.focus("discord")
        stop()
        self.focus("wow.exe")
        self.assertEqual(len(events), 1)

    def test_a_raising_subscriber_does_not_break_the_others(self):
        seen = []

        def boom(_snapshot):
            raise RuntimeError("bad consumer")

        self.service.subscribe(boom)
        self.service.subscribe(seen.append)
        self.focus("discord")
        self.assertEqual(len(seen), 1)


class RecordingTests(_Base):
    def test_a_switch_during_recording_is_held_not_applied(self):
        self.focus("discord")
        self.service.set_recording_active(True)
        snapshot = self.focus("wow.exe")
        self.assertEqual(snapshot["profile_id"], "discord")
        self.assertTrue(snapshot["deferred"])
        self.assertEqual(snapshot["pending_profile_id"], "world_of_warcraft")

    def test_a_held_switch_does_not_rewrite_the_explanation_of_the_live_one(self):
        # The source line explains the profile currently IN EFFECT. Rewriting
        # it for a profile that has not been applied yet would have the panel
        # explain one profile while naming another.
        self.focus("discord")
        self.service.set_recording_active(True)
        snapshot = self.focus("RocketLeague.exe")
        self.assertEqual(snapshot["profile_id"], "discord")
        self.assertEqual(snapshot["source"], "matched")

    def test_a_pin_set_during_a_recording_wins_when_the_held_switch_lands(self):
        # The held change is re-resolved on release, not replayed: replaying a
        # stale (id, source) pair would land the wrong profile and explain it
        # confidently.
        self.focus("discord")
        self.service.set_recording_active(True)
        self.focus("someindiegame")
        self.service.pin_current("game_generic")
        snapshot = self.service.set_recording_active(False)
        self.assertEqual(snapshot["profile_id"], "game_generic")
        self.assertEqual(snapshot["source"], "pinned")

    def test_the_held_switch_applies_when_recording_ends(self):
        self.focus("discord")
        self.service.set_recording_active(True)
        self.focus("wow.exe")
        snapshot = self.service.set_recording_active(False)
        self.assertEqual(snapshot["profile_id"], "world_of_warcraft")
        self.assertFalse(snapshot["deferred"])
        self.assertIsNone(snapshot["pending_profile_id"])

    def test_subscribers_are_notified_only_when_the_held_switch_lands(self):
        events = []
        self.focus("discord")
        self.service.subscribe(events.append)
        self.service.set_recording_active(True)
        self.focus("wow.exe")
        self.assertEqual(events, [])
        self.service.set_recording_active(False)
        self.assertEqual([e["profile_id"] for e in events], ["world_of_warcraft"])

    def test_the_service_never_reaches_into_the_recorder(self):
        imported = self.imported_modules()
        for module in ("recorder", "audio_ducker", "hotkey_manager"):
            self.assertNotIn(module, imported,
                             "the recording state is pushed in, never read out")


class OverrideAndPinTests(_Base):
    def test_override_wins_over_the_matched_profile(self):
        self.focus("discord")
        result = self.service.set_override("writing_app")
        self.assertTrue(result["ok"])
        snapshot = self.service.current()
        self.assertEqual(snapshot["profile_id"], "writing_app")
        self.assertEqual(snapshot["source"], "override")
        self.assertTrue(snapshot["override_active"])

    def test_override_survives_a_focus_change_until_cleared(self):
        self.service.set_override("writing_app")
        self.assertEqual(self.focus("discord")["profile_id"], "writing_app")
        self.service.clear_override()
        self.assertEqual(self.service.current()["profile_id"], "discord")

    def test_override_to_a_missing_profile_is_refused(self):
        result = self.service.set_override("no_such_profile")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "not_found")

    def test_override_is_not_persisted(self):
        self.service.set_override("writing_app")
        fresh = ac.ApplicationContextService(
            store=AppProfileStore(path=self.store.path),
            detector=lambda: "", clock=_Clock(),
        )
        self.assertFalse(fresh.current()["override_active"])

    def test_pin_is_durable_and_beats_the_match_rules(self):
        self.focus("discord")
        result = self.service.pin_current("writing_app")
        self.assertTrue(result["ok"])
        self.assertEqual(self.service.current()["source"], "pinned")

        fresh = ac.ApplicationContextService(
            store=AppProfileStore(path=self.store.path),
            detector=lambda: "discord", clock=_Clock(), debounce_ms=0,
        )
        fresh.poll()
        fresh.poll()
        snapshot = fresh.current()
        self.assertEqual(snapshot["profile_id"], "writing_app")
        self.assertTrue(snapshot["pinned"])

    def test_pin_with_nothing_detected_is_refused(self):
        result = self.service.pin_current("writing_app")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "unknown_application")

    def test_pinning_an_unknown_game_gets_the_generic_game_profile(self):
        self.focus("someindiegame")
        self.service.pin_current("game_generic")
        snapshot = self.service.current()
        self.assertEqual(snapshot["profile_id"], "game_generic")
        self.assertEqual(snapshot["injection_policy"], "review_only")
        self.assertTrue(snapshot["gaming_policy"]["active"])


class AnnouncementTests(_Base):
    def test_announcements_are_off_by_default(self):
        self.assertFalse(self.service.announce_enabled)
        self.assertEqual(self.focus("RocketLeague.exe")["announcement"], "")

    def test_an_enabled_announcement_is_one_short_sentence(self):
        self.service.announce_enabled = True
        snapshot = self.focus("RocketLeague.exe")
        text = snapshot["announcement"]
        self.assertTrue(text)
        self.assertLessEqual(text.count("."), 1)
        self.assertLessEqual(len(text), gaming_policy.MAX_TTS_SENTENCE_CHARS)

    def test_a_profile_that_does_not_announce_stays_silent(self):
        self.service.announce_enabled = True
        self.assertEqual(self.focus("discord")["announcement"], "")

    def test_an_announcement_is_not_repeated_after_it_is_delivered(self):
        self.service.announce_enabled = True
        seen = []
        self.service.subscribe(lambda s: seen.append(s["announcement"]))
        self.focus("RocketLeague.exe")
        self.assertTrue(seen[0])
        self.assertEqual(self.service.current()["announcement"], "")


class NoInferenceTests(_Base):
    """The Wave 7 hard rule, asserted against the output vocabulary itself."""

    def _all_snapshots(self):
        snapshots = [self.service.current()]
        for raw in ("discord", "RocketLeague.exe", "soffice", "thunderbird",
                    "wow.exe", "some-obscure-editor", ""):
            snapshots.append(self.focus(raw))
        self.service.set_recording_active(True)
        snapshots.append(self.focus("discord"))
        self.service.set_recording_active(False)
        self.service.set_override("writing_app")
        snapshots.append(self.service.current())
        self.service.clear_override()
        self.focus("discord")
        self.service.pin_current("game_generic")
        snapshots.append(self.service.current())
        return snapshots

    def _keys(self, value, prefix=""):
        keys = []
        if isinstance(value, dict):
            for key, sub in value.items():
                keys.append(f"{prefix}{key}")
                keys.extend(self._keys(sub, f"{prefix}{key}."))
        elif isinstance(value, (list, tuple)):
            for item in value:
                keys.extend(self._keys(item, prefix))
        return keys

    def test_the_snapshot_vocabulary_is_exactly_the_declared_one(self):
        for snapshot in self._all_snapshots():
            self.assertEqual(set(snapshot), set(ac.SNAPSHOT_FIELDS))

    def test_no_snapshot_field_names_a_recipient_or_a_conversation(self):
        for snapshot in self._all_snapshots():
            for key in self._keys(snapshot):
                lowered = key.lower()
                for term in ac.FORBIDDEN_OUTPUT_TERMS:
                    self.assertNotIn(
                        term, lowered,
                        f"'{key}' names {term!r}: the service may select a profile, "
                        f"never infer who or what you are writing about",
                    )

    def test_the_selectable_slots_are_the_five_declared_ones(self):
        self.assertEqual(
            set(ac.SELECTABLE_SLOTS),
            {"writing_preset", "performance_preset", "injection_policy", "tts", "bindings"},
        )
        for slot in ac.SELECTABLE_SLOTS:
            self.assertIn(slot, ac.SNAPSHOT_FIELDS)

    def test_no_snapshot_value_carries_free_text_the_user_wrote_about_a_person(self):
        # writing_preset is the one string slot; it is a PRESET NAME chosen from
        # the personas that exist, and it is None on every built-in.
        for snapshot in self._all_snapshots():
            self.assertIsNone(snapshot["writing_preset"])

    def test_applying_a_profile_touches_no_model_lifecycle(self):
        imported = self.imported_modules()
        for module in ("model_manager", "model_runtime_coordinator", "llm_engine",
                       "transcriber", "tts_engine", "streaming_transcriber"):
            self.assertNotIn(module, imported,
                             f"a profile switch must not reach {module} -- alt-tabbing "
                             f"must never cost a model reload")


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
