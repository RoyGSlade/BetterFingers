import os
import tempfile
from pathlib import Path

os.environ.setdefault("STUDIO_DATA_DIR", tempfile.mkdtemp())

import studio_ambience as A
import studio_memory as memory


def _project():
    name = f"ambience_{os.urandom(4).hex()}"
    pid = memory.init_project_db(name)
    return name, pid


def _scenes():
    return [
        {"id": "s1", "title": "The Harbor", "location": "cold harbor", "duration_seconds": 7},
        {"id": "s2", "title": "The Room", "location": "smoky room", "duration_seconds": 12},
    ]


def _fake_renderer(packet, out_path):
    assert "prompt" in packet
    assert packet["seconds"] <= 11.0
    Path(out_path).write_bytes(b"RIFFfake ambience")
    return True


def test_no_ambience_renderer_marks_unavailable(monkeypatch):
    name, pid = _project()
    monkeypatch.setattr(A, "make_ambience_backend", lambda *a, **k: None)
    scenes, status = A.render_scene_ambience(name, pid, _scenes(), renderer=None)
    assert status["renderer_available"] is False
    assert all(s["ambience_status"] == A.UNAVAILABLE for s in scenes)
    assert not any(s.get("ambience_path") for s in scenes)


def test_injected_ambience_renderer_writes_assets():
    name, pid = _project()
    scenes, status = A.render_scene_ambience(name, pid, _scenes(), renderer=_fake_renderer)
    assert status["done"] == 2
    assert scenes[0]["ambience_path"] == "assets/audio/ambience/scene-s1-ambience.wav"
    assert (Path(memory.get_project_dir(name)) / scenes[0]["ambience_path"]).is_file()
    assert "cold harbor" in scenes[0]["ambience_prompt"]


def test_ambience_render_is_idempotent_unless_forced():
    name, pid = _project()
    calls = {"n": 0}

    def renderer(packet, out_path):
        calls["n"] += 1
        return _fake_renderer(packet, out_path)

    scenes = _scenes()
    A.render_scene_ambience(name, pid, scenes, renderer=renderer)
    first = calls["n"]
    A.render_scene_ambience(name, pid, scenes, renderer=renderer)
    assert calls["n"] == first
    A.render_scene_ambience(name, pid, scenes, renderer=renderer, force=True)
    assert calls["n"] > first
