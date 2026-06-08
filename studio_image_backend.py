"""
In-process image backend (MEDIA_DISPATCHER §4.4) — Studio IS the app, no external generator.

Runs Stable Diffusion XL (or Flux) **inside the FastAPI backend** via `diffusers` + torch/CUDA, the
same way the llama.cpp sidecar and Kokoro TTS already run in-process. It consumes the Visual Prompt
Compiler's `PromptPacket` (positive/negative + model/steps/cfg/seed/sampler/scheduler) and writes a
PNG, then installs itself into the render queue via ``studio_render.set_renderer``.

Honest + graceful by construction:
- `diffusers` is imported **lazily** inside `ensure_loaded`, so this module imports fine even when
  diffusers/accelerate aren't installed yet.
- `healthcheck()` returns False unless diffusers is importable AND a CUDA device is present AND the
  model file/id is resolvable. When it returns False, nothing is registered and the player keeps its
  atmospheric gradient — nothing is faked.
- `unload()` frees VRAM (`del pipe; torch.cuda.empty_cache()`) so the ModelHost GPU lane can hand the
  card back to the 12B writer (the serialized-lane rule on a 16 GB card).

The packet→pipeline mapping and scheduler resolution are pure functions so they're unit-tested
without ever loading a model.
"""

import logging
import os
import threading
from pathlib import Path

logger = logging.getLogger("studio_image_backend")

# Image-model catalog (kept separate from model_manager's GGUF/llama-server catalog). Single-file
# SDXL checkpoints, downloaded via huggingface_hub (native resume) into the app's models dir.
IMAGE_MODELS = {
    "animagine-xl-4": {
        "name": "Animagine XL 4.0",
        "repo": "cagliostrolab/animagine-xl-4.0",
        # Loaded from the repo's diffusers-format layout (unet/, vae/, text_encoder*/) via
        # from_pretrained — this avoids diffusers' single-file CLIP conversion, which is broken
        # against transformers 5.x (pinned by Kokoro TTS). Downloaded into a per-model subdir.
        "format": "diffusers",
        "subdir": "animagine-xl-4.0",
        # Pull the diffusers components; skip the redundant root single-file checkpoints.
        "ignore_patterns": ["animagine-xl-4.0*.safetensors", "*.ckpt", "*.pt"],
        "pipeline": "sdxl",
        "size_mb": 6800,
        "group": "studio",
        "roles": ["image"],
        "lane": "gpu-transient",
        "recommended_for": "Default Studio anime/comic image model.",
    },
}
DEFAULT_IMAGE_MODEL = "animagine-xl-4"


def _models_dir():
    try:
        import model_manager
        return Path(model_manager.get_models_dir())
    except Exception:
        from utils import get_user_data_path
        d = Path(get_user_data_path()) / "models"
        d.mkdir(parents=True, exist_ok=True)
        return d


def image_model_path(model_key=DEFAULT_IMAGE_MODEL):
    """Local path: a directory for diffusers-format models, a file for single-file checkpoints."""
    entry = IMAGE_MODELS.get(model_key)
    if not entry:
        return ""
    if entry.get("format") == "diffusers":
        return str(_models_dir() / entry.get("subdir", model_key))
    return str(_models_dir() / entry["filename"])


def image_model_installed(model_key=DEFAULT_IMAGE_MODEL):
    entry = IMAGE_MODELS.get(model_key) or {}
    p = image_model_path(model_key)
    if not p:
        return False
    if entry.get("format") == "diffusers":
        return os.path.isfile(os.path.join(p, "model_index.json"))
    return os.path.exists(p) and os.path.getsize(p) > 1_000_000


# Background download state (image checkpoints are large; the UI polls this).
_DL_STATE = {}
_DL_LOCK = threading.Lock()
_DL_THREADS = {}


def start_download(model_key=DEFAULT_IMAGE_MODEL):
    """Kick a background download (idempotent — reuses an in-flight job). Returns the state dict."""
    with _DL_LOCK:
        thread = _DL_THREADS.get(model_key)
        st = _DL_STATE.get(model_key)
        if thread and thread.is_alive():
            body = dict(st or {})
            body["active"] = True
            return body
        if image_model_installed(model_key):
            _DL_STATE[model_key] = {"status": "done", "installed": True, "active": False, "error": ""}
            return dict(_DL_STATE[model_key])
        _DL_STATE[model_key] = {"status": "downloading", "installed": False, "active": True, "error": ""}

    def _run():
        try:
            ensure_image_model(model_key)
            with _DL_LOCK:
                _DL_STATE[model_key] = {"status": "done", "installed": True, "active": False, "error": ""}
        except Exception as e:
            logger.warning(f"Image model download failed: {e}")
            with _DL_LOCK:
                _DL_STATE[model_key] = {"status": "failed", "installed": False, "active": False, "error": str(e)}
        finally:
            with _DL_LOCK:
                current = _DL_THREADS.get(model_key)
                if current is threading.current_thread():
                    _DL_THREADS.pop(model_key, None)

    thread = threading.Thread(target=_run, name=f"studio-image-download-{model_key}", daemon=True)
    with _DL_LOCK:
        _DL_THREADS[model_key] = thread
    thread.start()
    return dict(_DL_STATE[model_key])


def download_state(model_key=DEFAULT_IMAGE_MODEL):
    with _DL_LOCK:
        thread = _DL_THREADS.get(model_key)
        st = dict(_DL_STATE.get(model_key) or {"status": "idle"})
        st["active"] = bool(thread and thread.is_alive())
    st["installed"] = image_model_installed(model_key)
    if st["installed"] and st.get("status") not in ("done", "downloading"):
        st["status"] = "done"
    return st


def list_image_models():
    return [
        {"key": k, "name": v["name"], "size_mb": v["size_mb"],
         "pipeline": v["pipeline"], "installed": image_model_installed(k),
         "recommended_for": v.get("recommended_for", "")}
        for k, v in IMAGE_MODELS.items()
    ]


def ensure_image_model(model_key=DEFAULT_IMAGE_MODEL, progress=None):
    """Download the image checkpoint into the models dir (resumable, via huggingface_hub). Returns
    the local path, or '' if the key is unknown. Safe to call when already present (no-op)."""
    entry = IMAGE_MODELS.get(model_key)
    if not entry:
        return ""
    dest = image_model_path(model_key)
    if image_model_installed(model_key):
        return dest
    if progress:
        try:
            progress(f"Downloading {entry['name']} (~{entry['size_mb']} MB)...")
        except Exception:
            pass
    if entry.get("format") == "diffusers":
        # Pull the diffusers-format layout (unet/, vae/, text_encoder*/) into a per-model dir,
        # skipping the redundant root single-file checkpoints.
        from huggingface_hub import snapshot_download
        snapshot_download(repo_id=entry["repo"], local_dir=dest,
                          ignore_patterns=entry.get("ignore_patterns") or [])
        return dest
    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo_id=entry["repo"], filename=entry["filename"],
                           local_dir=str(_models_dir()))

# Map (sampler, scheduler) hints from the compiler onto diffusers scheduler classes. Kept as names so
# the mapping is testable without importing diffusers; resolved to classes lazily at load time.
_SCHEDULER_MAP = {
    ("dpmpp_2m", "karras"): ("DPMSolverMultistepScheduler", {"use_karras_sigmas": True}),
    ("dpmpp_2m", ""):        ("DPMSolverMultistepScheduler", {}),
    ("euler_a", ""):         ("EulerAncestralDiscreteScheduler", {}),
    ("euler", ""):           ("EulerDiscreteScheduler", {}),
    ("ddim", ""):            ("DDIMScheduler", {}),
}


def packet_to_kwargs(packet):
    """Pure: turn a PromptPacket dict into diffusers pipeline call kwargs (minus the generator,
    which needs a torch device). Unit-testable with no torch/diffusers."""
    packet = packet or {}
    return {
        "prompt": packet.get("positive_prompt", ""),
        "negative_prompt": packet.get("negative_prompt", ""),
        "num_inference_steps": int(packet.get("steps", 24)),
        "guidance_scale": float(packet.get("cfg", 6.5)),
        "width": int(packet.get("width", 768)),
        "height": int(packet.get("height", 768)),
    }


def resolve_scheduler_name(sampler, scheduler):
    """Pure: pick the diffusers scheduler class name + kwargs for a (sampler, scheduler) hint."""
    key = (str(sampler or "").lower(), str(scheduler or "").lower())
    if key in _SCHEDULER_MAP:
        return _SCHEDULER_MAP[key]
    # Fall back on sampler alone, then a safe default.
    alt = (key[0], "")
    return _SCHEDULER_MAP.get(alt, ("DPMSolverMultistepScheduler", {}))


def apply_scheduler(pipe, sampler, scheduler):
    """Apply the requested scheduler to an already-loaded diffusers pipeline."""
    import diffusers as _diff
    cls_name, sched_kwargs = resolve_scheduler_name(sampler, scheduler)
    sched_cls = getattr(_diff, cls_name, None)
    if sched_cls is not None:
        pipe.scheduler = sched_cls.from_config(pipe.scheduler.config, **sched_kwargs)
    return pipe


def _looks_like_repo_id(s):
    """A HF repo id like 'org/model' (not an absolute path, not a bare filename)."""
    s = str(s or "")
    return (not os.path.isabs(s)) and s.count("/") == 1 and not s.endswith(".safetensors") and "\\" not in s


def diffusers_available():
    """True if the heavy deps are importable (does not load a model)."""
    try:
        import importlib.util as u
        if u.find_spec("diffusers") is None:
            return False
        import torch
        return bool(torch.cuda.is_available())
    except Exception:
        return False


class DiffusersBackend:
    """An ImageBackend that renders SDXL/Flux in-process. Default Studio image generator."""

    def __init__(self, model_path, pipeline="sdxl", dtype="float16", device="cuda"):
        self.model_path = model_path          # local .safetensors path or HF repo id
        self.pipeline_kind = pipeline         # "sdxl" | "flux"
        self.dtype = dtype
        self.device = device
        self._pipe = None

    # --- lifecycle ----------------------------------------------------------
    def healthcheck(self):
        if not diffusers_available():
            return False
        p = self.model_path
        if not p:
            return False
        return os.path.exists(p) or _looks_like_repo_id(p)  # local checkpoint OR HF repo id

    def ensure_loaded(self):
        if self._pipe is not None:
            return self._pipe
        import torch
        from diffusers import StableDiffusionXLPipeline, AutoPipelineForText2Image

        dtype = torch.float16 if self.dtype == "float16" else torch.float32
        if os.path.isdir(self.model_path):
            # Diffusers-format directory (default path) — avoids single-file CLIP conversion, which
            # is broken against transformers 5.x.
            pipe = AutoPipelineForText2Image.from_pretrained(self.model_path, torch_dtype=dtype)
        elif os.path.isfile(self.model_path):
            pipe = StableDiffusionXLPipeline.from_single_file(self.model_path, torch_dtype=dtype)
        else:
            pipe = AutoPipelineForText2Image.from_pretrained(self.model_path, torch_dtype=dtype)

        # Start with the compiler default; render() can swap per packet.
        apply_scheduler(pipe, "dpmpp_2m", "karras")

        pipe = pipe.to(self.device)
        try:
            pipe.enable_attention_slicing()      # gentler VRAM on 16 GB
        except Exception:
            pass
        self._pipe = pipe
        return pipe

    def render(self, packet, out_path):
        """Render one PromptPacket to ``out_path``. Returns True on success."""
        import torch
        pipe = self.ensure_loaded()
        apply_scheduler(pipe, (packet or {}).get("sampler", "dpmpp_2m"),
                        (packet or {}).get("scheduler", "karras"))
        kwargs = packet_to_kwargs(packet)
        # Per-packet scheduler (lets the compiler vary sampler later without a reload of the pipe).
        seed = int((packet or {}).get("seed", -1))
        if seed >= 0:
            kwargs["generator"] = torch.Generator(device=self.device).manual_seed(seed)
        image = pipe(**kwargs).images[0]
        image.save(out_path)
        return os.path.exists(out_path)

    def unload(self):
        if self._pipe is None:
            return
        try:
            import torch
            del self._pipe
            self._pipe = None
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
        except Exception as e:
            logger.warning(f"Diffusers unload failed: {e}")


def make_image_backend(settings):
    """Factory: build the configured image backend's render callable, or None if unavailable.

    ``settings`` is the resolved Studio media settings dict, e.g.
        {"image_backend": "diffusers"|"comfyui"|"off", "image_model_path": "...",
         "image_pipeline": "sdxl"|"flux"}
    Returns a ``render(packet, out_path) -> bool`` callable for ``studio_render.set_renderer``,
    or None (→ render queue reports 'unavailable', gradient fallback stands)."""
    settings = settings or {}
    backend = str(settings.get("image_backend", "diffusers")).lower()
    if backend in ("off", "none", ""):
        return None
    if backend == "diffusers":
        # Explicit path wins; otherwise use the configured/default catalog model's local path.
        path = settings.get("image_model_path") or image_model_path(
            settings.get("image_model", DEFAULT_IMAGE_MODEL))
        be = DiffusersBackend(path, pipeline=settings.get("image_pipeline", "sdxl"))
        if not be.healthcheck():
            logger.info("Diffusers image backend not ready (deps/model/CUDA missing) — gradient fallback.")
            return None
        unload_after_render = str(settings.get("resource_profile") or settings.get("studio_resource_profile") or "saver").lower() != "speedy"

        def _render(packet, out_path):
            try:
                return be.render(packet, out_path)
            finally:
                if unload_after_render:
                    be.unload()

        return _render
    # comfyui handled by studio_render.http_renderer when configured (optional, later).
    return None
