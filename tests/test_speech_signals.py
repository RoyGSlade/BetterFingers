import json

from backend.domain.contracts import SpeechSignals, TimedSegment, to_dict
from backend.services.speech_signals import compute_speech_signals

_EMOTION_WORDS = (
    "happy", "sad", "angry", "nervous", "excited", "anxious", "afraid",
    "furious", "calm", "upset", "annoyed", "frustrated",
)


def _segments(*spans, text="word " * 1):
    return [TimedSegment(start, end, text.strip() or "word") for start, end in spans]


def _assert_bounded(signals: SpeechSignals):
    assert 0.0 <= signals.confidence <= 1.0
    for axis, value in signals.delivery_axes.items():
        assert 0.0 <= value <= 1.0, f"{axis} out of bounds: {value}"
    assert {"arousal", "urgency", "hesitation"} <= signals.delivery_axes.keys()


def _assert_no_emotion_language(signals: SpeechSignals):
    joined = " ".join(signals.evidence).lower()
    for word in _EMOTION_WORDS:
        assert word not in joined, f"evidence diagnosed an emotion: {word!r}"


def test_quiet_case_low_energy_bounded_and_evidence_backed():
    segments = [
        TimedSegment(0.0, 2.0, "The report is ready for review today"),
        TimedSegment(2.3, 4.0, "Please take a look when you have time"),
    ]
    signals = compute_speech_signals(
        segments, audio_duration_s=4.0, energy_windows=[0.01, 0.015, 0.012, 0.01]
    )

    _assert_bounded(signals)
    _assert_no_emotion_language(signals)
    assert signals.energy_mean < 0.05
    assert signals.confidence > 0.0
    assert any("wpm" in line for line in signals.evidence)


def test_fast_case_has_higher_urgency_than_slow_case():
    fast_segments = [
        TimedSegment(0.0, 3.0, "we need to ship this right now and get it out the door immediately no delay")
    ]
    slow_segments = [TimedSegment(0.0, 6.0, "we should probably think about this")]

    fast = compute_speech_signals(fast_segments, audio_duration_s=3.0)
    slow = compute_speech_signals(slow_segments, audio_duration_s=6.0)

    _assert_bounded(fast)
    _assert_bounded(slow)
    assert fast.words_per_minute > slow.words_per_minute
    assert fast.delivery_axes["urgency"] > slow.delivery_axes["urgency"]


def test_slow_case_low_wpm_bounded():
    segments = [TimedSegment(0.0, 8.0, "well I suppose we could maybe try that")]
    signals = compute_speech_signals(segments, audio_duration_s=8.0)

    _assert_bounded(signals)
    assert signals.words_per_minute < 90


def test_paused_case_has_higher_hesitation_than_fluent_case():
    paused_segments = [
        TimedSegment(0.0, 1.0, "so I think"),
        TimedSegment(2.5, 3.5, "we should"),
        TimedSegment(5.5, 6.5, "go with option two"),
    ]
    fluent_segments = [TimedSegment(0.0, 6.5, "so I think we should go with option two")]

    paused = compute_speech_signals(paused_segments, audio_duration_s=6.5)
    fluent = compute_speech_signals(fluent_segments, audio_duration_s=6.5)

    _assert_bounded(paused)
    _assert_bounded(fluent)
    assert paused.pause_count == 2
    assert paused.longest_pause_s == 2.0
    assert paused.mean_pause_s == 1.75
    assert paused.delivery_axes["hesitation"] > fluent.delivery_axes["hesitation"]


def test_empty_case_is_all_zero_and_safe():
    signals = compute_speech_signals([])

    _assert_bounded(signals)
    assert signals.words_per_minute == 0.0
    assert signals.speaking_ratio == 0.0
    assert signals.pause_count == 0
    assert signals.filler_count == 0
    assert signals.self_correction_count == 0
    assert signals.confidence == 0.0
    assert signals.delivery_axes == {"arousal": 0.0, "urgency": 0.0, "hesitation": 0.0}
    assert signals.evidence == ["no speech segments provided"]


def test_noisy_case_has_higher_energy_variation_than_quiet_case():
    segments = [TimedSegment(0.0, 4.0, "testing the microphone levels in this room")]
    noisy = compute_speech_signals(
        segments, audio_duration_s=4.0, energy_windows=[0.01, 0.9, 0.02, 0.85, 0.01]
    )
    quiet = compute_speech_signals(
        segments, audio_duration_s=4.0, energy_windows=[0.05, 0.05, 0.05, 0.05]
    )

    _assert_bounded(noisy)
    _assert_bounded(quiet)
    assert noisy.energy_variation > quiet.energy_variation
    assert noisy.delivery_axes["arousal"] > quiet.delivery_axes["arousal"]


def test_filler_and_self_correction_markers_are_counted():
    segments = [
        TimedSegment(0.0, 3.0, "um so I think, uh, you know we should the the go with it"),
        TimedSegment(3.5, 5.0, "I mean, sorry I meant the other option"),
    ]
    signals = compute_speech_signals(segments, audio_duration_s=5.0)

    assert signals.filler_count >= 3  # um, uh, you know
    assert signals.self_correction_count >= 2  # stutter + "I mean"/"sorry I meant"
    assert any("filler" in line for line in signals.evidence)
    assert any("self-correction" in line for line in signals.evidence)


def test_evidence_never_contains_raw_transcript_text():
    secret = "the launch codes are alpha bravo seven"
    segments = [TimedSegment(0.0, 3.0, secret)]
    signals = compute_speech_signals(segments, audio_duration_s=3.0)

    joined = " ".join(signals.evidence)
    assert secret not in joined
    assert "alpha bravo seven" not in joined


def test_deterministic_across_repeated_calls():
    segments = [
        TimedSegment(0.0, 2.0, "first pass at the message"),
        TimedSegment(2.6, 4.0, "second segment of the message"),
    ]
    first = compute_speech_signals(segments, audio_duration_s=4.0, energy_windows=[0.2, 0.3, 0.25])
    second = compute_speech_signals(segments, audio_duration_s=4.0, energy_windows=[0.2, 0.3, 0.25])

    assert first == second


def test_serialization_round_trips_with_frozen_field_names():
    segments = [TimedSegment(0.0, 2.0, "quick json check")]
    signals = compute_speech_signals(segments, audio_duration_s=2.0, energy_windows=[0.1, 0.2])

    payload = to_dict(signals)
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload.keys()) == {
        "words_per_minute", "speaking_ratio", "pause_count", "pause_ratio",
        "mean_pause_s", "longest_pause_s", "filler_count", "self_correction_count",
        "energy_mean", "energy_variation", "delivery_axes", "evidence", "confidence",
    }
