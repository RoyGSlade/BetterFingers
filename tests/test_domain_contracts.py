import json

from backend.domain.contracts import (
    ContextEnvelope,
    MessageRescueResult,
    SpeechSignals,
    TimedSegment,
    TranscriptionResult,
    to_dict,
)


def test_transcription_contract_preserves_timing_and_confidence():
    result = TranscriptionResult(
        text="Please send the revised draft tomorrow.",
        segments=[TimedSegment(0.0, 2.5, "Please send the revised draft tomorrow.", -0.12, 0.01)],
        confidence=0.94,
        audio_duration_s=2.8,
    )

    payload = to_dict(result)
    assert json.loads(json.dumps(payload)) == payload
    assert payload["segments"][0]["end_s"] == 2.5
    assert payload["confidence"] == 0.94


def test_all_contracts_are_json_round_trip_safe():
    values = [
        SpeechSignals(delivery_axes={"arousal": 0.2}, evidence=["one pause"]),
        ContextEnvelope("ctx-1", "A selected reply", "selection", 1.0, 2.0),
        MessageRescueResult(variants={"faithful": "A reply"}),
    ]
    for value in values:
        payload = to_dict(value)
        assert json.loads(json.dumps(payload)) == payload


def test_context_source_is_explicit():
    context = ContextEnvelope("ctx-1", "text", "manual", 1.0, 2.0)
    assert to_dict(context)["source"] == "manual"
