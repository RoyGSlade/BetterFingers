import os
import tempfile
from pathlib import Path

os.environ.setdefault("STUDIO_DATA_DIR", tempfile.mkdtemp())

import studio_memory as memory
import studio_music as M


def _project():
    name = f"music_{os.urandom(4).hex()}"
    pid = memory.init_project_db(name)
    bible = memory.get_bible(name, pid)
    bible["scenes"] = [{"id": "s1", "title": "Night Drive"}]
    memory.save_bible(name, pid, bible)
    return name, pid


def test_no_music_renderer_marks_unavailable(monkeypatch):
    name, pid = _project()
    monkeypatch.setattr(M, "make_music_backend", lambda *a, **k: None)
    result = M.render_project_music(name, pid, [{"id": "s1", "title": "Night Drive"}], renderer=None)
    assert result["music_status"] == M.UNAVAILABLE
    assert result["renderer_available"] is False
    assert "Night Drive" in result["music_prompt"]


def test_injected_music_renderer_writes_asset():
    name, pid = _project()

    def renderer(packet, out_dir):
        assert "instrumental" in packet["prompt"]
        Path(out_dir, "music.wav").write_bytes(b"RIFFfake music")
        return True

    result = M.render_project_music(name, pid, [{"id": "s1", "title": "Night Drive"}], renderer=renderer)
    assert result["music_status"] == M.DONE
    assert result["music_path"] == "assets/audio/music/music.wav"
    assert (Path(memory.get_project_dir(name)) / result["music_path"]).is_file()


def test_music_render_is_idempotent_unless_forced():
    name, pid = _project()
    calls = {"n": 0}

    def renderer(packet, out_dir):
        calls["n"] += 1
        Path(out_dir, "music.wav").write_bytes(b"RIFFfake music")
        return True

    scenes = [{"id": "s1", "title": "Night Drive"}]
    M.render_project_music(name, pid, scenes, renderer=renderer)
    M.render_project_music(name, pid, scenes, renderer=renderer)
    assert calls["n"] == 1
    M.render_project_music(name, pid, scenes, renderer=renderer, force=True)
    assert calls["n"] == 2
