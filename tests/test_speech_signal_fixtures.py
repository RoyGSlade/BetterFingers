"""Validation tests for the synthetic speech-signal fixture corpus (F2.4).

Exercises tests/fixtures/speech_signals/ against compute_speech_signals
(F2.1) to verify: fixture schema, deterministic repeated results, bounded
axes/confidence, no personal data or content-bearing evidence, and exact
compatibility with the frozen contracts. See docs/TEST_DATA_POLICY.md for
provenance, privacy limits, and the checksum/regeneration protocol enforced
here.
"""

import hashlib
import json
import re
from pathlib import Path

import pytest

from backend.domain.contracts import SpeechSignals, TimedSegment, to_dict
from backend.services.speech_signals import compute_speech_signals

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "speech_signals"
MANIFEST_PATH = FIXTURES_DIR / "manifest.json"

_EXPECTED_IDS = {
    "quiet", "fast", "slow", "paused", "empty",
    "noisy", "filler_heavy", "self_correcting",
}

_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b")
_SSN_RE = re.compile(r"\b\d{3}-\d{2}-\d{4}\b")


def _fixture_paths():
    return sorted(p for p in FIXTURES_DIR.glob("*.json") if p.name != "manifest.json")


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


def _to_signals_kwargs(fixture: dict):
    segments = [
        TimedSegment(seg["start_s"], seg["end_s"], seg["text"])
        for seg in fixture["segments"]
    ]
    return segments, fixture.get("audio_duration_s"), fixture.get("energy_windows")


def test_corpus_covers_every_required_scenario():
    ids = {_load(p)["id"] for p in _fixture_paths()}
    assert ids == _EXPECTED_IDS


def test_fixture_filenames_match_their_id():
    for path in _fixture_paths():
        assert _load(path)["id"] == path.stem


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_fixture_schema_is_well_formed(path):
    fixture = _load(path)
    assert set(fixture.keys()) == {"id", "description", "segments", "audio_duration_s", "energy_windows"}
    assert isinstance(fixture["description"], str) and fixture["description"]
    assert isinstance(fixture["segments"], list)
    for seg in fixture["segments"]:
        assert set(seg.keys()) == {"start_s", "end_s", "text"}
        assert seg["end_s"] >= seg["start_s"]
        assert isinstance(seg["text"], str) and seg["text"]
    if fixture["energy_windows"] is not None:
        assert all(isinstance(v, (int, float)) and v >= 0 for v in fixture["energy_windows"])


def test_manifest_checksums_match():
    manifest = _load(MANIFEST_PATH)
    recorded = manifest["files"]
    on_disk = {p.name for p in _fixture_paths()}
    assert set(recorded.keys()) == on_disk, "manifest.json is out of sync with fixture files on disk"
    for name, expected_sha256 in recorded.items():
        actual = hashlib.sha256((FIXTURES_DIR / name).read_bytes()).hexdigest()
        assert actual == expected_sha256, (
            f"{name} content changed without regenerating manifest.json "
            "(see docs/TEST_DATA_POLICY.md)"
        )


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_fixtures_contain_no_pii_markers(path):
    fixture = _load(path)
    text = " ".join(seg["text"] for seg in fixture["segments"])
    assert not _EMAIL_RE.search(text), f"{path.name} contains an email-shaped string"
    assert not _PHONE_RE.search(text), f"{path.name} contains a phone-number-shaped string"
    assert not _SSN_RE.search(text), f"{path.name} contains an SSN-shaped string"


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_fixture_runs_and_produces_bounded_frozen_contract(path):
    fixture = _load(path)
    segments, audio_duration_s, energy_windows = _to_signals_kwargs(fixture)

    signals = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)

    assert isinstance(signals, SpeechSignals)
    assert 0.0 <= signals.confidence <= 1.0
    assert {"arousal", "urgency", "hesitation"} <= signals.delivery_axes.keys()
    for axis, value in signals.delivery_axes.items():
        assert 0.0 <= value <= 1.0, f"{path.name}: {axis} out of bounds: {value}"
    assert signals.pause_count >= 0
    assert signals.filler_count >= 0
    assert signals.self_correction_count >= 0

    # Exact contract compatibility: to_dict round-trips to plain JSON with the
    # frozen SpeechSignals field-name set (same set F2.1's own tests assert).
    payload = to_dict(signals)
    assert json.loads(json.dumps(payload)) == payload
    assert set(payload.keys()) == {
        "words_per_minute", "speaking_ratio", "pause_count", "pause_ratio",
        "mean_pause_s", "longest_pause_s", "filler_count", "self_correction_count",
        "energy_mean", "energy_variation", "delivery_axes", "evidence", "confidence",
    }


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_fixture_is_deterministic_across_repeated_calls(path):
    fixture = _load(path)
    segments, audio_duration_s, energy_windows = _to_signals_kwargs(fixture)

    first = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)
    second = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)

    assert first == second


@pytest.mark.parametrize("path", _fixture_paths(), ids=lambda p: p.stem)
def test_signals_never_echo_fixture_text(path):
    fixture = _load(path)
    segments, audio_duration_s, energy_windows = _to_signals_kwargs(fixture)
    signals = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)

    evidence_joined = " ".join(signals.evidence)
    for seg in fixture["segments"]:
        # Guard against evidence leaking the verbatim dictated sentence; short
        # common words are expected to recur incidentally (e.g. "the").
        words = [w for w in seg["text"].split() if len(w) > 3]
        for phrase_len in (3, 4):
            for i in range(len(words) - phrase_len + 1):
                phrase = " ".join(words[i:i + phrase_len]).lower()
                assert phrase not in evidence_joined.lower(), (
                    f"{path.name}: evidence leaked fixture phrase {phrase!r}"
                )


def test_filler_heavy_fixture_yields_filler_evidence():
    fixture = _load(FIXTURES_DIR / "filler_heavy.json")
    segments, audio_duration_s, energy_windows = _to_signals_kwargs(fixture)
    signals = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)

    assert signals.filler_count > 0
    assert any("filler" in line for line in signals.evidence)


def test_self_correcting_fixture_yields_self_correction_evidence():
    fixture = _load(FIXTURES_DIR / "self_correcting.json")
    segments, audio_duration_s, energy_windows = _to_signals_kwargs(fixture)
    signals = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)

    assert signals.self_correction_count > 0
    assert any("self-correction" in line for line in signals.evidence)


def test_empty_fixture_is_all_zero_and_safe():
    fixture = _load(FIXTURES_DIR / "empty.json")
    segments, audio_duration_s, energy_windows = _to_signals_kwargs(fixture)
    signals = compute_speech_signals(segments, audio_duration_s=audio_duration_s, energy_windows=energy_windows)

    assert signals.words_per_minute == 0.0
    assert signals.confidence == 0.0
    assert signals.delivery_axes == {"arousal": 0.0, "urgency": 0.0, "hesitation": 0.0}
    assert signals.evidence == ["no speech segments provided"]


def test_fast_fixture_has_higher_urgency_than_slow_fixture():
    fast = _load(FIXTURES_DIR / "fast.json")
    slow = _load(FIXTURES_DIR / "slow.json")

    fast_signals = compute_speech_signals(*_to_signals_kwargs(fast))
    slow_signals = compute_speech_signals(*_to_signals_kwargs(slow))

    assert fast_signals.words_per_minute > slow_signals.words_per_minute
    assert fast_signals.delivery_axes["urgency"] > slow_signals.delivery_axes["urgency"]


def test_paused_fixture_has_higher_hesitation_than_fast_fixture():
    paused = _load(FIXTURES_DIR / "paused.json")
    fast = _load(FIXTURES_DIR / "fast.json")

    paused_signals = compute_speech_signals(*_to_signals_kwargs(paused))
    fast_signals = compute_speech_signals(*_to_signals_kwargs(fast))

    assert paused_signals.pause_count > 0
    assert paused_signals.delivery_axes["hesitation"] > fast_signals.delivery_axes["hesitation"]


def test_noisy_fixture_has_higher_energy_variation_than_quiet_fixture():
    noisy = _load(FIXTURES_DIR / "noisy.json")
    quiet = _load(FIXTURES_DIR / "quiet.json")

    noisy_signals = compute_speech_signals(*_to_signals_kwargs(noisy))
    quiet_signals = compute_speech_signals(*_to_signals_kwargs(quiet))

    assert noisy_signals.energy_variation > quiet_signals.energy_variation
