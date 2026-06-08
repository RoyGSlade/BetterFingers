"""Tests for the scene image render queue (gpt §3)."""

import os
import tempfile
from pathlib import Path

os.environ.setdefault("STUDIO_DATA_DIR", tempfile.mkdtemp())

import studio_memory as memory
import studio_render as R


def _project():
    name = f"render_{os.urandom(4).hex()}"
    pid = memory.init_project_db(name)
    return name, pid


def _scenes():
    return [{"id": "s1", "image_prompt": "a cold harbor at night", "negative_prompt": "blurry"},
            {"id": "s2", "image_prompt": "a jazz club in smoke"},
            {"id": "s3", "image_prompt": ""}]  # no prompt -> unavailable


def _fake_renderer(packet, out_path):
    assert "positive_prompt" in packet  # backend now receives a PromptPacket dict
    Path(out_path).write_bytes(b"\x89PNG\r\n\x1a\n fake")  # minimal bytes
    return True


# --------------------------------------------------------------------------- #
# No backend configured -> honest 'unavailable', gradient stays
# --------------------------------------------------------------------------- #

def test_no_renderer_marks_unavailable_not_faked():
    name, pid = _project()
    scenes, queue = R.render_scenes(name, pid, _scenes())
    assert all(s.get("image_status") == R.UNAVAILABLE for s in scenes)
    assert not any(s.get("image_path") for s in scenes)
    assert R.render_status(name, pid)["renderer_available"] is False


# --------------------------------------------------------------------------- #
# With a renderer injected -> real asset + done state
# --------------------------------------------------------------------------- #

def test_injected_renderer_writes_assets_and_sets_paths():
    name, pid = _project()
    scenes, queue = R.render_scenes(name, pid, _scenes(), renderer=_fake_renderer)
    assert scenes[0]["image_status"] == R.DONE
    assert scenes[0]["image_path"] == "assets/images/scene-s1.png"
    # The file actually exists under the project dir.
    full = Path(memory.get_project_dir(name)) / scenes[0]["image_path"]
    assert full.is_file()
    # The promptless scene is unavailable, not failed.
    assert scenes[2]["image_status"] == R.UNAVAILABLE
    counts = R.render_status(name, pid)["counts"]
    assert counts.get("done") == 2 and counts.get("unavailable") == 1


def test_render_is_idempotent_unless_forced():
    name, pid = _project()
    calls = {"n": 0}

    def counting(packet, out_path):
        calls["n"] += 1
        return _fake_renderer(packet, out_path)

    scenes = _scenes()
    R.render_scenes(name, pid, scenes, renderer=counting)
    first = calls["n"]
    R.render_scenes(name, pid, scenes, renderer=counting)   # already done -> skipped
    assert calls["n"] == first
    R.render_scenes(name, pid, scenes, renderer=counting, force=True)  # forced -> re-renders
    assert calls["n"] > first


def test_renderer_failure_marks_failed():
    name, pid = _project()

    def boom(packet, out_path):
        raise RuntimeError("backend down")

    scenes, queue = R.render_scenes(name, pid, _scenes(), renderer=boom)
    assert scenes[0]["image_status"] == R.FAILED
    assert not scenes[0].get("image_path")
