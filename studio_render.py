"""
Scene image rendering + queue (gpt §3).

Scenes already carry a strong `image_prompt`; the cinematic player prefers a real rendered
image and falls back to a gradient otherwise. This module turns prompts into project-local
image assets through a small queue with explicit states, and writes `image_path`/`image_status`
back onto each scene so the player can show it.

It is **backend-agnostic and honest**: there is no image generator bundled in this repo, so the
default renderer reports `unavailable` and the player keeps its gradient — nothing is faked. A
real generator (in-process Diffusers / ComfyUI / a hosted API) drops in as a single callable via
``set_renderer`` or the ``renderer=`` argument. It receives a **PromptPacket dict** (from the
Visual Prompt Compiler — positive/negative prompt + model/steps/cfg/seed/sampler/scheduler):

    renderer(packet: dict, out_path: str) -> bool   # True if it wrote out_path

Queue states: queued → rendering → done | failed | unavailable. The per-scene queue is persisted
to project memory (``render_queue``) so the UI can poll progress.
"""

import logging
from pathlib import Path

import studio_memory as memory

logger = logging.getLogger("studio_render")

QUEUED, RENDERING, DONE, FAILED, UNAVAILABLE = "queued", "rendering", "done", "failed", "unavailable"
_QUEUE_KEY = "render_queue"
_IMAGES_REL = "assets/images"

# A process-wide renderer can be installed once (e.g. at app start) when a generator is configured.
_RENDERER = None


def set_renderer(fn):
    """Install the process-wide image renderer (or None to disable)."""
    global _RENDERER
    _RENDERER = fn


def has_renderer(renderer=None):
    return callable(renderer or _RENDERER)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #

def render_scenes(project_name, project_id, scenes, renderer=None, progress=None, force=False):
    """Render an image for every scene that has a prompt. Mutates ``scenes`` in place with
    ``image_path`` + ``image_status`` and returns (scenes, queue). Idempotent: a scene already
    ``done`` is skipped unless ``force``."""
    renderer = renderer or _RENDERER
    queue = _load_queue(project_name, project_id)
    images_dir = _images_dir(project_name)

    for i, scene in enumerate(scenes or []):
        sid = scene.get("id") or f"s{i + 1}"
        prompt = (scene.get("image_prompt") or "").strip()
        if not prompt:
            scene["image_status"] = queue[sid] = UNAVAILABLE
            continue
        if not force and queue.get(sid) == DONE and scene.get("image_path"):
            scene["image_status"] = DONE
            continue
        if not has_renderer(renderer):
            scene["image_status"] = queue[sid] = UNAVAILABLE
            continue

        queue[sid] = RENDERING
        _save_queue(project_name, project_id, queue)
        if progress:
            try:
                progress(f"Rendering image for scene {i + 1} of {len(scenes)}...")
            except Exception:
                pass

        out_name = f"scene-{sid}.png"
        out_path = images_dir / out_name
        # The backend receives a full PromptPacket (positive/negative + model/steps/cfg/seed…) from
        # the Visual Prompt Compiler when present, else a minimal packet from the flat fields.
        packet = scene.get("prompt_packet") or {
            "positive_prompt": prompt,
            "negative_prompt": scene.get("negative_prompt", ""),
        }
        try:
            ok = bool(renderer(packet, str(out_path)))
        except Exception as e:
            logger.warning(f"Scene {sid} render failed: {e}")
            ok = False

        if ok and out_path.is_file():
            rel = f"{_IMAGES_REL}/{out_name}"
            scene["image_path"] = rel
            scene["image_status"] = queue[sid] = DONE
            try:
                memory.add_asset(project_name, project_id, "image", rel,
                                 metadata={"scene_id": sid, "source": "scene_render"})
            except Exception:
                pass
        else:
            scene["image_status"] = queue[sid] = FAILED

    _save_queue(project_name, project_id, queue)
    return scenes, queue


def render_status(project_name, project_id):
    """Return the per-scene render queue plus a rollup the UI can show."""
    queue = _load_queue(project_name, project_id)
    counts = {}
    for st in queue.values():
        counts[st] = counts.get(st, 0) + 1
    return {"queue": queue, "counts": counts,
            "renderer_available": has_renderer(),
            "total": len(queue)}


# --------------------------------------------------------------------------- #
# Optional HTTP renderer factory (off by default; wire when a generator exists)
# --------------------------------------------------------------------------- #

def http_renderer(url, payload_builder=None, timeout=120):
    """Build a renderer that POSTs to a local txt2img-style HTTP API and saves the PNG.

    Intentionally generic and NOT enabled by default — provide ``payload_builder`` and a
    response decoder that matches your generator (A1111, ComfyUI, etc.). Kept here so wiring a
    real backend later is a one-liner: ``studio_render.set_renderer(http_renderer(MY_URL, ...))``.
    """
    import base64
    import json
    import urllib.request

    def _render(packet, out_path):
        body = (payload_builder or _default_payload)(packet)
        req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
        images = data.get("images") or []
        if not images:
            return False
        raw = images[0].split(",", 1)[-1]  # strip a data: prefix if present
        Path(out_path).write_bytes(base64.b64decode(raw))
        return True

    return _render


def _default_payload(packet):
    return {
        "prompt": packet.get("positive_prompt", ""),
        "negative_prompt": packet.get("negative_prompt", ""),
        "steps": packet.get("steps", 24),
        "cfg_scale": packet.get("cfg", 6.5),
        "seed": packet.get("seed", -1),
        "sampler_name": packet.get("sampler", "dpmpp_2m"),
        "width": packet.get("width", 768),
        "height": packet.get("height", 768),
    }


# --------------------------------------------------------------------------- #
# Storage helpers
# --------------------------------------------------------------------------- #

def _images_dir(project_name):
    d = Path(memory.get_project_dir(project_name)) / _IMAGES_REL
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
    except Exception as e:
        logger.warning(f"Could not persist render queue: {e}")
