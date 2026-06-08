"""Scene ambience/SFX rendering for the cinematic Studio.

Downloads live in ``studio_media_models``. This module is the runtime worker
adapter: it calls Stable Audio Open Small through an isolated tool environment
and stamps ``ambience_path``/``ambience_status`` onto scenes. If the tools or
model are missing, scenes are marked ``unavailable`` so the player can stay
honest instead of pretending a silent loop exists.
"""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import studio_media_models
import studio_memory as memory

logger = logging.getLogger("studio_ambience")

QUEUED, RENDERING, DONE, FAILED, UNAVAILABLE = "queued", "rendering", "done", "failed", "unavailable"
DEFAULT_AMBIENCE_MODEL = "stable-audio-open-small"
_AMBIENCE_REL = "assets/audio/ambience"
_QUEUE_KEY = "ambience_queue"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def stable_audio_tool_root() -> Path:
    return _repo_root() / ".betterfingers" / "tools" / "stable-audio-tools"


def stable_audio_python() -> Path:
    return stable_audio_tool_root() / ".venv" / "bin" / "python"


def stable_audio_script() -> Path:
    return _repo_root() / "tools" / "stable_audio_generate.py"


def stable_audio_tools_installed() -> bool:
    py = stable_audio_python()
    if not py.is_file():
        return False
    try:
        result = subprocess.run(
            [str(py), "-c", "import stable_audio_tools, torchaudio, einops"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def build_ambience_prompt(scene: dict, world: dict | None = None) -> str:
    world = world or {}
    parts = [
        "seamless cinematic background ambience loop",
        "no vocals, no narration, no foreground dialogue",
    ]
    location = (scene.get("location") or scene.get("location_ref") or "").strip()
    if location:
        parts.append(f"location: {location}")
    mood = (scene.get("emotional_shift") or scene.get("mood") or "").strip()
    if mood:
        parts.append(f"mood: {mood}")
    title = (scene.get("title") or "").strip()
    if title:
        parts.append(f"scene: {title}")
    tone = (world.get("tone") or world.get("style") or "").strip() if isinstance(world, dict) else ""
    if tone:
        parts.append(f"tone: {tone}")
    return ", ".join(parts)


class StableAudioBackend:
    def __init__(
        self,
        model_dir: str | None = None,
        python_path: str | None = None,
        script_path: str | None = None,
        device: str = "auto",
        timeout: int = 900,
    ):
        self.model_dir = model_dir or studio_media_models.model_path(DEFAULT_AMBIENCE_MODEL)
        self.python_path = python_path or str(stable_audio_python())
        self.script_path = script_path or str(stable_audio_script())
        self.device = device
        self.timeout = timeout

    def healthcheck(self) -> bool:
        model_dir = Path(self.model_dir)
        return (
            Path(self.python_path).is_file()
            and Path(self.script_path).is_file()
            and (model_dir / ".betterfingers_download_complete").is_file()
            and (model_dir / "model_config.json").is_file()
            and ((model_dir / "model.safetensors").is_file() or (model_dir / "model.ckpt").is_file())
        )

    def render(self, packet: dict, out_path: str) -> bool:
        prompt = (packet or {}).get("prompt") or ""
        if not prompt.strip():
            return False
        cmd = [
            self.python_path,
            self.script_path,
            "--model-dir",
            self.model_dir,
            "--prompt",
            prompt,
            "--out",
            out_path,
            "--seconds",
            str(float((packet or {}).get("seconds", 11.0))),
            "--steps",
            str(int((packet or {}).get("steps", 8))),
            "--cfg-scale",
            str(float((packet or {}).get("cfg_scale", 1.0))),
            "--sampler",
            str((packet or {}).get("sampler", "pingpong")),
            "--seed",
            str(int((packet or {}).get("seed", -1))),
            "--device",
            self.device,
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode != 0:
            logger.warning("Stable Audio generation failed: %s", (result.stderr or result.stdout).strip())
            return False
        return Path(out_path).is_file() and Path(out_path).stat().st_size > 44


def make_ambience_backend(settings: dict | None = None):
    settings = settings or {}
    engine = str(settings.get("ambience_engine") or settings.get("studio_ambience_engine") or "stable-audio-open").lower()
    if engine in ("", "off", "none"):
        return None
    backend = StableAudioBackend(
        model_dir=settings.get("ambience_model_path") or studio_media_models.model_path(DEFAULT_AMBIENCE_MODEL),
        device=settings.get("ambience_device", "auto"),
        timeout=int(settings.get("ambience_timeout", 900)),
    )
    if not backend.healthcheck():
        logger.info("Stable Audio ambience backend not ready — ambience fallback unavailable.")
        return None
    return backend.render


def render_scene_ambience(project_name, project_id, scenes, world=None, renderer=None, progress=None, force=False):
    renderer = renderer or make_ambience_backend()
    queue = _load_queue(project_name, project_id)
    out_dir = _ambience_dir(project_name)
    done = total = 0

    for i, scene in enumerate(scenes or []):
        sid = scene.get("id") or f"s{i + 1}"
        total += 1
        if not force and scene.get("ambience_status") == DONE and scene.get("ambience_path"):
            queue[sid] = DONE
            done += 1
            continue
        prompt = scene.get("ambience_prompt") or build_ambience_prompt(scene, world)
        scene["ambience_prompt"] = prompt
        if not callable(renderer):
            scene["ambience_status"] = queue[sid] = UNAVAILABLE
            continue
        queue[sid] = RENDERING
        _save_queue(project_name, project_id, queue)
        if progress:
            try:
                progress(f"Rendering ambience for scene {i + 1} of {len(scenes)}...")
            except Exception:
                pass
        out_name = f"scene-{sid}-ambience.wav"
        out_path = out_dir / out_name
        packet = {
            "prompt": prompt,
            "seconds": min(11.0, max(1.0, float(scene.get("duration_seconds") or 11.0))),
            "seed": _stable_seed(project_name, sid),
        }
        try:
            ok = bool(renderer(packet, str(out_path)))
        except Exception as exc:
            logger.warning("Ambience render failed for %s: %s", sid, exc)
            ok = False
        if ok and out_path.is_file():
            rel = f"{_AMBIENCE_REL}/{out_name}"
            scene["ambience_path"] = rel
            scene["ambience_status"] = queue[sid] = DONE
            done += 1
            try:
                memory.add_asset(project_name, project_id, "audio", rel, metadata={"scene_id": sid, "source": "stable_audio_ambience"})
            except Exception:
                pass
        else:
            scene["ambience_status"] = queue[sid] = FAILED

    _save_queue(project_name, project_id, queue)
    status = {"done": done, "total": total, "queue": queue, "renderer_available": callable(renderer)}
    try:
        memory.set_user_preference(project_name, project_id, "ambience_status", status)
    except Exception:
        pass
    return scenes, status


def ambience_status(project_name, project_id):
    queue = _load_queue(project_name, project_id)
    counts = {}
    for state in queue.values():
        counts[state] = counts.get(state, 0) + 1
    return {"queue": queue, "counts": counts, "renderer_available": make_ambience_backend() is not None, "total": len(queue)}


def _stable_seed(project_name: str, scene_id: str) -> int:
    text = f"{project_name}:{scene_id}:ambience"
    value = 2166136261
    for ch in text.encode("utf-8"):
        value ^= ch
        value = (value * 16777619) & 0xFFFFFFFF
    return value


def _ambience_dir(project_name):
    d = Path(memory.get_project_dir(project_name)) / _AMBIENCE_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def _load_queue(project_name, project_id):
    try:
        q = memory.get_user_preferences(project_name, project_id).get(_QUEUE_KEY)
        return dict(q) if isinstance(q, dict) else {}
    except Exception:
        return {}


def _save_queue(project_name, project_id, queue):
    try:
        memory.set_user_preference(project_name, project_id, _QUEUE_KEY, queue)
    except Exception as exc:
        logger.warning("Could not persist ambience queue: %s", exc)
