"""ACE-Step score cue worker for cinematic Studio projects."""

from __future__ import annotations

import logging
import os
import subprocess
from pathlib import Path

import studio_media_models
import studio_memory as memory

logger = logging.getLogger("studio_music")

DONE, FAILED, UNAVAILABLE = "done", "failed", "unavailable"
DEFAULT_MUSIC_MODEL = "ace-step-1-5"
_MUSIC_REL = "assets/audio/music"


def _repo_root() -> Path:
    return Path(__file__).resolve().parent


def ace_tool_root() -> Path:
    return _repo_root() / ".betterfingers" / "tools" / "ACE-Step-1.5"


def ace_python() -> Path:
    return ace_tool_root() / ".venv" / "bin" / "python"


def ace_script() -> Path:
    return _repo_root() / "tools" / "ace_step_generate.py"


def ace_tools_installed() -> bool:
    py = ace_python()
    if not py.is_file():
        return False
    try:
        result = subprocess.run(
            [str(py), "-c", "import acestep"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            check=False,
        )
        return result.returncode == 0
    except Exception:
        return False


def build_music_prompt(scenes: list[dict], blueprint: dict | None = None, world: dict | None = None) -> str:
    blueprint = blueprint or {}
    world = world or {}
    parts = ["instrumental cinematic score cue", "no vocals"]
    summary = (blueprint.get("summary") or "").strip()
    if summary:
        parts.append(summary)
    tone = (world.get("tone") or world.get("style") or "").strip() if isinstance(world, dict) else ""
    if tone:
        parts.append(f"tone: {tone}")
    titles = [str(s.get("title") or "").strip() for s in scenes[:5] if s.get("title")]
    if titles:
        parts.append("scenes: " + ", ".join(titles))
    return ", ".join(parts)


class AceStepBackend:
    def __init__(
        self,
        checkpoint_dir: str | None = None,
        python_path: str | None = None,
        script_path: str | None = None,
        tool_root: str | None = None,
        device: str = "cuda",
        timeout: int = 1800,
    ):
        self.checkpoint_dir = checkpoint_dir or studio_media_models.model_path(DEFAULT_MUSIC_MODEL)
        self.python_path = python_path or str(ace_python())
        self.script_path = script_path or str(ace_script())
        self.tool_root = tool_root or str(ace_tool_root())
        self.device = device
        self.timeout = timeout

    def healthcheck(self) -> bool:
        root = Path(self.checkpoint_dir)
        return (
            Path(self.python_path).is_file()
            and Path(self.script_path).is_file()
            and Path(self.tool_root).is_dir()
            and (root / ".betterfingers_download_complete").is_file()
            and (root / "acestep-v15-turbo" / "model.safetensors").is_file()
            and (root / "acestep-5Hz-lm-1.7B" / "model.safetensors").is_file()
            and (root / "vae" / "diffusion_pytorch_model.safetensors").is_file()
        )

    def render(self, packet: dict, out_dir: str) -> bool:
        prompt = (packet or {}).get("prompt") or ""
        if not prompt.strip():
            return False
        cmd = [
            self.python_path,
            self.script_path,
            "--tool-root",
            self.tool_root,
            "--checkpoint-dir",
            self.checkpoint_dir,
            "--prompt",
            prompt,
            "--out-dir",
            out_dir,
            "--duration",
            str(float((packet or {}).get("duration", 30.0))),
            "--seed",
            str(int((packet or {}).get("seed", -1))),
            "--steps",
            str(int((packet or {}).get("steps", 8))),
            "--guidance-scale",
            str(float((packet or {}).get("guidance_scale", 7.0))),
            "--device",
            self.device,
            "--lm-backend",
            str((packet or {}).get("lm_backend", "pt")),
        ]
        env = os.environ.copy()
        env.setdefault("PYTHONUNBUFFERED", "1")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=self.timeout)
        if result.returncode != 0:
            logger.warning("ACE-Step generation failed: %s", (result.stderr or result.stdout).strip())
            return False
        final = Path(out_dir) / "music.wav"
        return final.is_file() and final.stat().st_size > 44


def make_music_backend(settings: dict | None = None):
    settings = settings or {}
    engine = str(settings.get("music_engine") or settings.get("studio_music_engine") or "ace-step").lower()
    if engine in ("", "off", "none"):
        return None
    backend = AceStepBackend(
        checkpoint_dir=settings.get("music_model_path") or studio_media_models.model_path(DEFAULT_MUSIC_MODEL),
        device=settings.get("music_device", "cuda"),
        timeout=int(settings.get("music_timeout", 1800)),
    )
    if not backend.healthcheck():
        logger.info("ACE-Step music backend not ready — score fallback unavailable.")
        return None
    return backend.render


def render_project_music(project_name, project_id, scenes, blueprint=None, world=None, renderer=None, force=False):
    renderer = renderer or make_music_backend()
    bible = memory.get_bible(project_name, project_id)
    if not force and bible.get("music_path"):
        return {"ok": True, "music_path": bible.get("music_path"), "music_status": DONE, "renderer_available": callable(renderer)}
    prompt = build_music_prompt(scenes or [], blueprint, world)
    if not callable(renderer):
        bible["music_prompt"] = prompt
        bible["music_status"] = UNAVAILABLE
        memory.save_bible(project_name, project_id, bible)
        return {"ok": True, "music_status": UNAVAILABLE, "renderer_available": False, "music_prompt": prompt}

    out_dir = _music_dir(project_name)
    packet = {"prompt": prompt, "duration": 30.0, "seed": _stable_seed(project_name)}
    try:
        ok = bool(renderer(packet, str(out_dir)))
    except Exception as exc:
        logger.warning("Music render failed: %s", exc)
        ok = False
    if ok:
        rel = f"{_MUSIC_REL}/music.wav"
        # Tame the score so it sits UNDER the narration, with a gentle fade in/out so it doesn't
        # punch in/out. Volume is user-adjustable (music_volume pref); default low on purpose.
        try:
            import studio_audio
            prefs = memory.get_user_preferences(project_name, project_id)
            vol = prefs.get("music_volume")
            vol = float(vol) if vol is not None else 0.35
            studio_audio.apply_gain_fade(out_dir / "music.wav", gain=max(0.0, min(2.0, vol)),
                                         fade_in_ms=1500, fade_out_ms=2500)
        except Exception as exc:
            logger.warning("Music post-process (gain/fade) skipped: %s", exc)
        bible["music_path"] = rel
        bible["music_status"] = DONE
        try:
            memory.add_asset(project_name, project_id, "audio", rel, metadata={"source": "ace_step_music"})
        except Exception:
            pass
    else:
        bible["music_status"] = FAILED
    bible["music_prompt"] = prompt
    memory.save_bible(project_name, project_id, bible)
    return {"ok": True, "music_status": bible["music_status"], "music_path": bible.get("music_path"), "renderer_available": callable(renderer), "music_prompt": prompt}


def _music_dir(project_name):
    d = Path(memory.get_project_dir(project_name)) / _MUSIC_REL
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stable_seed(project_name: str) -> int:
    value = 2166136261
    for ch in f"{project_name}:music".encode("utf-8"):
        value ^= ch
        value = (value * 16777619) & 0xFFFFFFFF
    return value
