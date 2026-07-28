"""Tests for the delivery-signal preservation probe (plan Stage 9's gate).

Exercised entirely with fakes: the point of delivery_preservation.py being pure
is that its verdict logic can be trusted before it is ever pointed at a real
model. Includes negative controls for each failure mode -- a gate that cannot
fail is not a gate, and this one guards a default that changes the words users
send.
"""

import pytest

from delivery_preservation import (
    AGITATED_SUMMARY,
    CALM_SUMMARY,
    MAX_LENGTH_RATIO,
    PROBES,
    assert_probes_check_facts,
    markers_preserved,
    run_delivery_preservation_suite,
    run_delivery_probe,
    signals_leaked,
)

PROBE = PROBES[0]  # "I am really frustrated ... 5pm demo"


def echo(text, delivery_summary=None):
    """A model that changes nothing -- the ideal outcome for rule 5."""
    return text


class TestMarkerPreservation:
    def test_missing_marker_is_reported(self):
        assert markers_preserved("I am really frustrated", "I am annoyed", ("really", "frustrated")) == [
            "really",
            "frustrated",
        ]

    def test_present_markers_are_not_reported(self):
        assert markers_preserved("I am really frustrated", "I am really frustrated.", ("really", "frustrated")) == []

    def test_matching_is_word_level_not_substring(self):
        # "not" must NOT be satisfied by "nothing" -- that is how a negation
        # check quietly stops checking anything.
        assert markers_preserved("I am not angry", "nothing to report", ("not",)) == ["not"]

    def test_empty_candidate_loses_every_marker(self):
        assert markers_preserved("really frustrated", "   ", ("really",)) == ["really"]


class TestLeakDetection:
    @pytest.mark.parametrize(
        "text",
        [
            "You sounded arousal=0.94 there",
            "Delivery signal summary suggests urgency",
            "hesitation was high",
            "pauses=4 detected",
        ],
    )
    def test_measurements_in_output_are_caught(self, text):
        assert signals_leaked(text) is True

    def test_ordinary_text_is_not_flagged(self):
        assert signals_leaked("I am really frustrated that the build broke.") is False


class TestProbeVerdicts:
    def test_a_faithful_model_passes(self):
        result = run_delivery_probe(echo, probe=PROBE)
        assert result["status"] == "PASS", result

    def test_call_failure_is_distinct_from_preservation_failure(self):
        def boom(text, delivery_summary=None):
            raise RuntimeError("llama-server down")

        result = run_delivery_probe(boom, probe=PROBE)
        assert result["status"] == "CALL_FAILED"
        assert result["exception_type"] == "RuntimeError"

    def test_flattening_intensity_fails(self):
        # The exact rule-5 violation: calm delivery talks the model out of the
        # intensity the speaker actually stated.
        def flatten(text, delivery_summary=None):
            if delivery_summary == CALM_SUMMARY:
                return "The build broke before the 5pm demo."
            return text

        result = run_delivery_probe(flatten, probe=PROBE)
        assert result["status"] == "FAIL"
        assert "calm" in result["lost_intensity_markers"]

    def test_amplifying_intensity_fails(self):
        def amplify(text, delivery_summary=None):
            if delivery_summary == AGITATED_SUMMARY:
                return (
                    "I am really frustrated and furious and absolutely livid that the build "
                    "broke again right before the 5pm demo and this keeps happening every "
                    "single time without fail which is completely unacceptable"
                )
            return text

        result = run_delivery_probe(amplify, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["length_ratio_exceeded"] is True
        assert result["calm_vs_agitated_length_ratio"] > MAX_LENGTH_RATIO

    def test_leaking_the_measurements_fails(self):
        def leaky(text, delivery_summary=None):
            if delivery_summary:
                return f"{text} (arousal={delivery_summary})"
            return text

        result = run_delivery_probe(leaky, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["signal_leak_detected"]

    def test_dropping_a_fact_fails(self):
        def drop_number(text, delivery_summary=None):
            return text.replace("20", "a few")

        result = run_delivery_probe(drop_number, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["fact_preservation_failures"]

    def test_the_fact_check_is_not_vacuous(self):
        # The failure this guards: an earlier probe transcript matched no
        # check_preservation category at all, so "facts preserved" was true of
        # literally any output. A decorative check is worse than none, because
        # it reads as evidence.
        result = run_delivery_probe(echo, probe=PROBE)
        assert result["fact_categories_checked"], "probe checks no facts"


class TestProbeSanity:
    def test_every_probe_can_detect_a_dropped_fact(self):
        # Guards future edits to PROBES: a transcript with no numbers, names,
        # dates or negation cannot fail a fact check no matter what a model
        # does to it.
        assert_probes_check_facts()

    @pytest.mark.parametrize("probe", PROBES, ids=lambda p: p["name"])
    def test_every_probe_states_its_own_intensity(self, probe):
        # Markers must be literally present in the transcript, or the probe is
        # asking the model to preserve something that was never said.
        missing = markers_preserved(probe["transcript"], probe["transcript"], probe["markers"])
        assert missing == [], f"{probe['name']} claims markers absent from its own transcript: {missing}"

    def test_empty_output_fails(self):
        def silent(text, delivery_summary=None):
            return "" if delivery_summary else text

        result = run_delivery_probe(silent, probe=PROBE)
        assert result["status"] == "FAIL"
        assert set(result["empty_outputs"]) == {"calm", "agitated"}

    def test_report_never_contains_model_text(self):
        result = run_delivery_probe(echo, probe=PROBE)
        blob = repr(result)
        assert "frustrated" not in blob, "probe report leaked transcript text"
        assert "demo" not in blob


class TestSuiteVerdict:
    def test_all_pass_is_the_only_green(self):
        report = run_delivery_preservation_suite(echo)
        assert report["overall"] == "PASS"
        assert report["passed"] == report["probe_count"] == len(PROBES)

    def test_one_bad_probe_fails_the_suite(self):
        def flatten_everything(text, delivery_summary=None):
            return "Fine." if delivery_summary else text

        report = run_delivery_preservation_suite(flatten_everything)
        # Only the summarised runs are flattened, so this IS delivery's doing.
        assert report["overall"] == "FAIL_DELIVERY"
        assert report["passed"] < report["probe_count"]

    def test_a_dead_model_is_not_reported_as_failure_or_pass(self):
        def boom(text, delivery_summary=None):
            raise ConnectionError("no sidecar")

        report = run_delivery_preservation_suite(boom)
        assert report["overall"] == "CALL_FAILED"

    def test_gate_note_states_the_rule(self):
        report = run_delivery_preservation_suite(echo)
        assert "default-on" in report["gate_note"]


class TestFailureAttribution:
    """Separating "the model does this anyway" from "the summary made it".

    Without this the first real run reads as evidence against delivery signals
    when the baseline -- no summary at all -- fails identically. That would send
    someone hunting a regression that predates the feature. It is exactly what
    happened on the first live run against Gemma.
    """

    def test_a_baseline_shared_failure_is_not_attributed_to_delivery(self):
        def always_drops_number(text, delivery_summary=None):
            return text.replace("20", "some")  # fails with or without a summary

        result = run_delivery_probe(always_drops_number, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["baseline_also_failed"] is True
        assert result["failure_attributable_to_delivery"] is False

        report = run_delivery_preservation_suite(always_drops_number)
        assert report["overall"] == "FAIL_BASELINE"
        assert report["attributable_failures"] == []

    def test_a_delivery_only_failure_is_attributed(self):
        def degrades_only_with_signals(text, delivery_summary=None):
            return text.replace("20", "some") if delivery_summary else text

        result = run_delivery_probe(degrades_only_with_signals, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["baseline_also_failed"] is False
        assert result["failure_attributable_to_delivery"] is True

        report = run_delivery_preservation_suite(degrades_only_with_signals)
        assert report["overall"] == "FAIL_DELIVERY", "a delivery-caused regression must block default-on"
        assert PROBE["name"] in report["attributable_failures"]

    def test_a_passing_probe_is_never_marked_attributable(self):
        result = run_delivery_probe(echo, probe=PROBE)
        assert result["failure_attributable_to_delivery"] is False

    def test_divergence_between_calm_and_agitated_is_always_attributable(self):
        # Neither run "fails" on its own terms, but they disagree with each
        # other -- which only the delivery summary can explain.
        def verbose_when_agitated(text, delivery_summary=None):
            if delivery_summary == AGITATED_SUMMARY:
                return text + " " + " ".join(["and", "it", "keeps", "happening"] * 6)
            return text

        result = run_delivery_probe(verbose_when_agitated, probe=PROBE)
        assert result["length_ratio_exceeded"] is True
        assert result["failure_attributable_to_delivery"] is True


# --- Audience axis (Stage 11's gate) -----------------------------------------
#
# Same differential, mirrored risk: knowing you are writing to your manager must
# not license formalising what you said, and knowing you are writing to your
# brother must not license casualising it. Plus one failure mode delivery
# signals cannot cause -- inventing a greeting or a sign-off.

from delivery_preservation import (  # noqa: E402
    CLOSE_AUDIENCE,
    FORMAL_AUDIENCE,
    addressing_invented,
    run_audience_preservation_suite,
    run_audience_probe,
)


class TestAddressingInvented:
    def test_an_added_greeting_is_caught(self):
        added = addressing_invented("the build broke again", "Hi Priya, the build broke again")
        assert "hi" in added

    def test_an_added_sign_off_is_caught(self):
        added = addressing_invented("the build broke again", "The build broke again. Best regards")
        assert "best regards" in added

    def test_a_greeting_the_speaker_actually_said_is_kept(self):
        # Only ADDITIONS count. A speaker who said "hey" gets to keep it.
        assert addressing_invented("hey the build broke", "Hey, the build broke.") == []

    def test_matching_is_word_level_not_substring(self):
        # "best" must be matched by "best regards", not by ordinary prose.
        assert addressing_invented("pick the option", "Pick the best option we have") == []

    def test_nothing_added_is_an_empty_list(self):
        assert addressing_invented("the build broke", "The build broke.") == []


def _echo(text, audience_summary=None, **_kwargs):
    return text


class TestAudienceProbe:
    def test_a_model_that_ignores_the_audience_passes(self):
        # The correct outcome: audience context that changes nothing cannot
        # have degraded anything.
        result = run_audience_probe(_echo, probe=PROBE)
        assert result["status"] == "PASS"
        assert result["failure_attributable_to_audience"] is False

    def test_the_audience_prose_leaking_into_output_fails(self):
        def leaky(text, audience_summary=None, **_k):
            return text if audience_summary is None else f"{text} (for my younger brother)"

        result = run_audience_probe(leaky, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["signal_leak_detected"]
        assert result["failure_attributable_to_audience"] is True

    def test_an_invented_greeting_fails_and_is_attributed(self):
        def polite(text, audience_summary=None, **_k):
            return text if audience_summary is None else f"Hi there, {text}. Kind regards"

        result = run_audience_probe(polite, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["invented_addressing"]
        assert result["failure_attributable_to_audience"] is True

    def test_a_dropped_intensity_marker_fails(self):
        def flatten(text, audience_summary=None, **_k):
            if audience_summary is None:
                return text
            return text.replace("really ", "").replace("frustrated", "unhappy")

        result = run_audience_probe(flatten, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["lost_intensity_markers"]

    def test_wildly_different_lengths_between_variants_fail(self):
        def verbose_when_formal(text, audience_summary=None, **_k):
            if audience_summary == FORMAL_AUDIENCE:
                return text + " " + " ".join(["additionally"] * 30)
            return text

        result = run_audience_probe(verbose_when_formal, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["length_ratio_exceeded"] is True

    def test_a_pre_existing_failure_is_not_blamed_on_the_audience(self):
        # The whole point of the baseline arm: a model that always drops a fact
        # was already doing that, and reporting it as an audience regression
        # would send someone hunting a bug that predates the feature.
        def always_drops_number(text, audience_summary=None, **_k):
            return text.replace("20", "").replace("3", "")

        result = run_audience_probe(always_drops_number, probe=PROBE)
        assert result["status"] == "FAIL"
        assert result["baseline_also_failed"] is True
        assert result["failure_attributable_to_audience"] is False

    def test_a_raising_model_is_reported_as_call_failed(self):
        def boom(_text, audience_summary=None, **_k):
            raise RuntimeError("no model")

        assert run_audience_probe(boom, probe=PROBE)["status"] == "CALL_FAILED"

    def test_the_probe_passes_the_audience_as_its_own_kwarg(self):
        seen = []

        def record(text, audience_summary=None, **_k):
            seen.append(audience_summary)
            return text

        run_audience_probe(record, probe=PROBE)
        assert seen == [None, CLOSE_AUDIENCE, FORMAL_AUDIENCE]

    def test_the_audience_blocks_carry_no_name(self):
        # contacts.audience_block() never emits one, so a probe that fed a name
        # would be testing a prompt the app never builds.
        for block in (CLOSE_AUDIENCE, FORMAL_AUDIENCE):
            assert "Priya" not in block
            assert "Sarah" not in block


class TestAudienceSuite:
    def test_all_pass_is_the_only_green(self):
        report = run_audience_preservation_suite(_echo)
        assert report["overall"] == "PASS"
        assert report["passed"] == report["probe_count"]

    def test_an_audience_caused_failure_blocks_the_gate(self):
        def polite(text, audience_summary=None, **_k):
            return text if audience_summary is None else f"Hello, {text}"

        report = run_audience_preservation_suite(polite)
        assert report["overall"] == "FAIL_AUDIENCE"
        assert report["attributable_failures"]

    def test_a_baseline_failure_is_reported_separately(self):
        def always_drops_number(text, audience_summary=None, **_k):
            return text.replace("20", "").replace("3", "")

        report = run_audience_preservation_suite(always_drops_number)
        assert report["overall"] == "FAIL_BASELINE"
        assert report["attributable_failures"] == []

    def test_the_suite_never_returns_model_text(self):
        # A failing run must not leak a user's dictation into a log.
        report = run_audience_preservation_suite(_echo)
        blob = repr(report)
        for probe in PROBES:
            assert probe["transcript"] not in blob
