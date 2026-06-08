"""Tests for per-beat narration audio (gpt §4)."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("STUDIO_DATA_DIR", tempfile.mkdtemp())

import studio_memory as memory
import studio_audio as A


def _project():
    name = f"audio_{os.urandom(4).hex()}"
    pid = memory.init_project_db(name)
    return name, pid


def _scenes():
    return [
        {"id": "s1", "narration_script": [
            {"speaker": "Narrator", "line": "Cold settled over the car."},
            {"speaker": "Louis", "line": "One last job."}]},
        {"id": "s2", "narration_script": [{"speaker": "Narrator", "line": ""}]},  # empty -> unavailable
    ]


def _fake_synth(text, out_path, voice="af_heart"):
    Path(out_path).write_bytes(b"RIFFfake")
    return True


def test_no_synth_marks_unavailable_not_faked():
    name, pid = _project()
    scenes, status = A.synthesize_scenes(name, pid, _scenes())
    assert status["synth_available"] is False
    assert all(b.get("audio_status") == A.UNAVAILABLE
               for s in scenes for b in s["narration_script"])
    assert not any(b.get("audio_path") for s in scenes for b in s["narration_script"])


def test_injected_synth_writes_beat_audio():
    name, pid = _project()
    scenes, status = A.synthesize_scenes(name, pid, _scenes(), synth=_fake_synth)
    assert status["done"] == 2  # two non-empty beats
    s1 = scenes[0]["narration_script"]
    assert s1[0]["audio_path"] == "assets/audio/s1-1.wav"
    assert (Path(memory.get_project_dir(name)) / s1[0]["audio_path"]).is_file()
    # The empty beat is unavailable, not failed.
    assert scenes[1]["narration_script"][0]["audio_status"] == A.UNAVAILABLE


def test_voice_for_routes_per_speaker():
    name, pid = _project()
    seen = []

    def synth(text, out_path, voice="af_heart"):
        seen.append(voice)
        return _fake_synth(text, out_path, voice)

    A.synthesize_scenes(name, pid, _scenes(), synth=synth,
                        voice_for=lambda sp: "am_adam" if sp == "Louis" else "af_heart")
    assert "am_adam" in seen and "af_heart" in seen


def test_audio_is_idempotent_unless_forced():
    name, pid = _project()
    calls = {"n": 0}

    def synth(text, out_path, voice="af_heart"):
        calls["n"] += 1
        return _fake_synth(text, out_path, voice)

    scenes = _scenes()
    A.synthesize_scenes(name, pid, scenes, synth=synth)
    first = calls["n"]
    A.synthesize_scenes(name, pid, scenes, synth=synth)       # done -> skipped
    assert calls["n"] == first
    A.synthesize_scenes(name, pid, scenes, synth=synth, force=True)
    assert calls["n"] > first
