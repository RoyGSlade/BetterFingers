"""Wave 8A package H: the failure vocabulary is closed, honest, and stable."""

import unittest

import audio_status as status


def cfg(mode="off", binding="f10", announce=True):
    return {
        "voice_privacy": {
            "mode": mode, "mute_binding": binding,
            "keep_unmuted_apps": [], "announce_failures": announce,
        }
    }


class VocabularyTests(unittest.TestCase):
    def test_capability_words_are_exactly_the_d0009_set(self):
        self.assertEqual(
            set(status.CAPABILITY_STATUSES),
            {"supported", "supported_with_requirements", "clipboard_only",
             "experimental", "unavailable", "unknown"},
        )

    def test_privacy_statuses_include_the_three_the_objective_names(self):
        self.assertIn("active", status.VOICE_PRIVACY_STATUSES)
        self.assertIn("unavailable", status.VOICE_PRIVACY_STATUSES)
        self.assertIn("partially_restored", status.VOICE_PRIVACY_STATUSES)

    def test_wake_statuses_include_unavailable_and_classifier_missing(self):
        self.assertIn("unavailable", status.WAKE_STATUSES)
        self.assertIn("classifier_missing", status.WAKE_STATUSES)


class VoicePrivacyStatusTests(unittest.TestCase):
    def test_every_result_uses_a_known_status_and_carries_a_reason(self):
        cases = [
            cfg("off"), cfg("push_to_mute"), cfg("push_to_mute", binding=""),
            cfg("isolate_capture_streams"), cfg("isolate_capture_streams", binding=""),
        ]
        for config in cases:
            for engaged in (False, True):
                for restored in (False, True):
                    result = status.voice_privacy_status(
                        config, engaged=engaged, restore_complete=restored
                    )
                    self.assertIn(result["status"], status.VOICE_PRIVACY_STATUSES)
                    self.assertTrue(result["reason"])
                    self.assertTrue(result["detail"])

    def test_privacy_off_is_inactive(self):
        result = status.voice_privacy_status(cfg("off"))
        self.assertEqual(result["status"], "inactive")
        self.assertEqual(result["reason"], status.REASON_PRIVACY_OFF)

    def test_push_to_mute_ready_is_inactive_until_engaged(self):
        result = status.voice_privacy_status(cfg("push_to_mute"))
        self.assertEqual(result["status"], "inactive")
        self.assertEqual(result["effective_mode"], "push_to_mute")

    def test_push_to_mute_engaged_is_active(self):
        result = status.voice_privacy_status(cfg("push_to_mute"), engaged=True)
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["reason"], status.REASON_PRIVACY_ACTIVE)

    def test_push_to_mute_without_a_binding_is_unavailable(self):
        result = status.voice_privacy_status(cfg("push_to_mute", binding=""))
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], status.REASON_NO_MUTE_BINDING)

    def test_no_way_to_hold_the_key_is_unavailable(self):
        result = status.voice_privacy_status(cfg("push_to_mute"), push_to_mute_available=False)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], status.REASON_PUSH_TO_MUTE_UNAVAILABLE)

    def test_an_incomplete_restore_outranks_everything(self):
        result = status.voice_privacy_status(cfg("push_to_mute"), engaged=True, restore_complete=False)
        self.assertEqual(result["status"], "partially_restored")
        self.assertEqual(result["reason"], status.REASON_RESTORE_INCOMPLETE)

    def test_an_incomplete_restore_is_reported_even_when_privacy_is_off(self):
        # A lease left the system changed; "off" would hide that.
        result = status.voice_privacy_status(cfg("off"), restore_complete=False)
        self.assertEqual(result["status"], "partially_restored")

    def test_requested_isolation_degrades_visibly_to_push_to_mute(self):
        result = status.voice_privacy_status(cfg("isolate_capture_streams"), isolation_available=False)
        self.assertEqual(result["reason"], status.REASON_ISOLATION_DEGRADED)
        self.assertEqual(result["requested_mode"], "isolate_capture_streams")
        self.assertEqual(result["effective_mode"], "push_to_mute")
        self.assertFalse(result["isolation_available"])

    def test_requested_isolation_with_no_fallback_is_unavailable(self):
        result = status.voice_privacy_status(
            cfg("isolate_capture_streams", binding=""), isolation_available=False
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], status.REASON_ISOLATION_UNAVAILABLE)

    def test_requested_isolation_when_push_to_mute_also_cannot_run(self):
        result = status.voice_privacy_status(
            cfg("isolate_capture_streams"), isolation_available=False, push_to_mute_available=False
        )
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], status.REASON_ISOLATION_UNAVAILABLE)

    def test_isolation_reports_normally_once_an_adapter_exists(self):
        result = status.voice_privacy_status(
            cfg("isolate_capture_streams", binding=""), isolation_available=True, engaged=True
        )
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["effective_mode"], "isolate_capture_streams")

    def test_announce_failures_is_carried_through(self):
        self.assertTrue(status.voice_privacy_status(cfg("push_to_mute"))["announce"])
        self.assertFalse(status.voice_privacy_status(cfg("push_to_mute", announce=False))["announce"])

    def test_an_unmigrated_legacy_profile_still_reports(self):
        legacy = {"audio_ducking": True, "voice_mute_key": "f10"}
        result = status.voice_privacy_status(legacy, engaged=True)
        self.assertEqual(result["status"], "active")
        self.assertEqual(result["effective_mode"], "push_to_mute")

    def test_detail_override_is_used(self):
        result = status.voice_privacy_status(cfg("off"), detail="custom text")
        self.assertEqual(result["detail"], "custom text")


class VoicePrivacyCapabilityTests(unittest.TestCase):
    def test_every_answer_is_a_d0009_word(self):
        for isolation in (False, True):
            for ptm in (False, True):
                word = status.voice_privacy_capability(
                    isolation_available=isolation, push_to_mute_available=ptm
                )
                self.assertIn(word, status.CAPABILITY_STATUSES)

    def test_push_to_mute_only_needs_a_key_so_it_is_conditional(self):
        self.assertEqual(status.voice_privacy_capability(push_to_mute_available=True), "supported_with_requirements")

    def test_nothing_available_is_unavailable(self):
        self.assertEqual(status.voice_privacy_capability(push_to_mute_available=False), "unavailable")

    def test_isolation_adapter_raises_it_to_supported(self):
        self.assertEqual(status.voice_privacy_capability(isolation_available=True), "supported")


class WakeStatusTests(unittest.TestCase):
    def test_every_result_uses_a_known_status(self):
        for engine in (False, True):
            for classifier in (False, True):
                for enabled in (False, True):
                    for listening in (False, True):
                        for mic in (False, True):
                            result = status.wake_status(
                                enabled=enabled, listening=listening,
                                engine_available=engine, classifier_selected=classifier,
                                microphone_available=mic,
                            )
                            self.assertIn(result["status"], status.WAKE_STATUSES)
                            self.assertTrue(result["reason"])

    def test_missing_engine_is_unavailable(self):
        result = status.wake_status(enabled=True, engine_available=False)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], status.REASON_WAKE_ENGINE_UNAVAILABLE)

    def test_missing_classifier_is_its_own_status(self):
        # The fresh-install steady state: the catalog ships zero classifiers.
        result = status.wake_status(enabled=True, classifier_selected=False)
        self.assertEqual(result["status"], "classifier_missing")
        self.assertEqual(result["reason"], status.REASON_WAKE_CLASSIFIER_MISSING)

    def test_a_missing_engine_outranks_a_missing_classifier(self):
        result = status.wake_status(engine_available=False, classifier_selected=False)
        self.assertEqual(result["status"], "unavailable")

    def test_disabled_with_everything_present(self):
        self.assertEqual(status.wake_status(enabled=False)["status"], "disabled")

    def test_enabled_but_no_microphone_is_unavailable(self):
        result = status.wake_status(enabled=True, microphone_available=False)
        self.assertEqual(result["status"], "unavailable")
        self.assertEqual(result["reason"], status.REASON_WAKE_MICROPHONE_UNAVAILABLE)

    def test_enabled_and_listening(self):
        self.assertEqual(status.wake_status(enabled=True, listening=True)["status"], "listening")

    def test_enabled_but_not_yet_listening_is_ready(self):
        self.assertEqual(status.wake_status(enabled=True, listening=False)["status"], "ready")


class WakeCapabilityTests(unittest.TestCase):
    def test_every_answer_is_a_d0009_word(self):
        for engine in (False, True):
            for classifier in (False, True):
                for qualified in (False, True):
                    self.assertIn(
                        status.wake_capability(engine, classifier, qualified),
                        status.CAPABILITY_STATUSES,
                    )

    def test_no_engine_is_unavailable(self):
        self.assertEqual(status.wake_capability(engine_available=False), "unavailable")

    def test_no_classifier_needs_a_setup_step(self):
        self.assertEqual(
            status.wake_capability(engine_available=True, classifier_available=False),
            "supported_with_requirements",
        )

    def test_unqualified_wake_stays_experimental(self):
        self.assertEqual(
            status.wake_capability(engine_available=True, classifier_available=True, qualified=False),
            "experimental",
        )

    def test_only_measured_qualification_reaches_supported(self):
        self.assertEqual(
            status.wake_capability(engine_available=True, classifier_available=True, qualified=True),
            "supported",
        )


class SnapshotTests(unittest.TestCase):
    def test_snapshot_carries_both_features(self):
        snapshot = status.audio_status_snapshot(cfg("push_to_mute"))
        self.assertIn("voice_privacy", snapshot)
        self.assertIn("wake", snapshot)
        self.assertNotIn("audio_input", snapshot)

    def test_snapshot_routes_arguments_to_the_right_builder(self):
        snapshot = status.audio_status_snapshot(
            cfg("push_to_mute"), engaged=True, enabled=True, listening=True
        )
        self.assertEqual(snapshot["voice_privacy"]["status"], "active")
        self.assertEqual(snapshot["wake"]["status"], "listening")

    def test_snapshot_reports_who_holds_the_microphone(self):
        broker = {
            "open": True, "device": 2, "subscribers": ["wake", "recorder"], "last_error": "",
        }
        snapshot = status.audio_status_snapshot(cfg("off"), broker_status=broker)
        self.assertEqual(snapshot["audio_input"]["holders"], ["wake", "recorder"])
        self.assertEqual(snapshot["audio_input"]["device"], 2)
        self.assertTrue(snapshot["audio_input"]["open"])

    def test_snapshot_tolerates_a_sparse_broker_status(self):
        snapshot = status.audio_status_snapshot(cfg("off"), broker_status={})
        self.assertFalse(snapshot["audio_input"]["open"])
        self.assertEqual(snapshot["audio_input"]["holders"], [])

    def test_unknown_kwargs_are_ignored_rather_than_crashing_a_status_route(self):
        snapshot = status.audio_status_snapshot(cfg("off"), something_new=True)
        self.assertIn("voice_privacy", snapshot)


if __name__ == "__main__":
    unittest.main()
