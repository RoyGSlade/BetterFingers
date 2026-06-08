"""
Scene narration audio (gpt §4) — render each beat to a local audio file so the reel is PERFORMED.

The cinematic player can read narration with the browser's `SpeechSynthesis`, but that is a
zero-dependency *fallback*, not the product. This module renders each narration beat to a
project-local audio file (via the local Kokoro TTS path when available) and stamps `audio_path`
+ timing onto the beat, so the player plays a real voice and the reel feels acted, not skimmed.

Same honest, pluggable contract as ``studio_render``: with no TTS engine configured every beat is
marked ``unavailable`` and the player falls back to browser speech — nothing is faked. A real
engine drops in as one callable:

    synth(text: str, out_path: str, voice: str) -> bool   # True if it wrote out_path
"""

import logging
from pathlib import Path

import studio_memory as memory
import studio_media_models

logger = logging.getLogger("studio_audio")

QUEUED, RENDERING, DONE, FAILED, UNAVAILABLE = "queued", "rendering", "done", "failed", "unavailable"
_AUDIO_REL = "assets/audio"
_SYNTH = None

VOICE_MODELS = {k: v for k, v in studio_media_models.MEDIA_MODELS.items() if v.get("kind") == "voice"}
DEFAULT_VOICE_MODEL = "chatterbox"

def voice_model_installed(model_key=DEFAULT_VOICE_MODEL):
    return studio_media_models.model_installed(model_key)

def start_download(model_key=DEFAULT_VOICE_MODEL):
    return studio_media_models.start_download(model_key)

def download_state(model_key=DEFAULT_VOICE_MODEL):
    return studio_media_models.download_state(model_key)

def list_voice_models():
    return studio_media_models.list_models(kind="voice")

# Map a beat's emotion to Chatterbox expressivity. `exaggeration` (0-1) is emotional intensity;
# `cfg_weight` (0-1) governs pacing — lower = slower, more deliberate delivery. This is how we
# "prompt" Chatterbox on HOW a line should be spoken, from the scriptwriter's per-beat emotion.
_EMOTION_STYLE = {
    "angry": (0.85, 0.5), "furious": (0.9, 0.55), "intense": (0.8, 0.5),
    "afraid": (0.75, 0.55), "panicked": (0.85, 0.6), "urgent": (0.8, 0.6),
    "excited": (0.8, 0.55), "joyful": (0.75, 0.5), "happy": (0.65, 0.5),
    "sad": (0.45, 0.35), "grief": (0.5, 0.3), "melancholy": (0.4, 0.35),
    "calm": (0.35, 0.4), "tender": (0.4, 0.4), "solemn": (0.4, 0.35),
    "neutral": (0.5, 0.5), "narration": (0.45, 0.45),
}


def style_for_beat(beat):
    """Return Chatterbox kwargs {exaggeration, cfg_weight} for a narration beat, from its emotion
    (and a slower cadence when the delivery says so)."""
    emotion = str((beat or {}).get("emotion") or "neutral").strip().lower()
    exaggeration, cfg = _EMOTION_STYLE.get(emotion, (0.5, 0.5))
    delivery = str((beat or {}).get("delivery") or "").lower()
    if any(w in delivery for w in ("slow", "measured", "whisper", "soft", "quiet", "deliberate")):
        cfg = max(0.3, cfg - 0.1)
    return {"exaggeration": exaggeration, "cfg_weight": cfg}


def release_cuda():
    """Best-effort release of cached CUDA memory after an in-process model (Chatterbox) runs, so the
    next heavy model (ACE-Step music / image diffusers) has the VRAM. No-op without torch/CUDA."""
    try:
        import gc
        import torch
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass


def apply_gain_fade(path, gain=1.0, fade_in_ms=0, fade_out_ms=0):
    """Scale volume and apply linear fade in/out to a WAV file IN PLACE. Returns True on success,
    False (no-op) if numpy/scipy are unavailable or the file isn't a readable WAV — so callers
    degrade gracefully. Keeps things from blaring: music is rendered loud, this tames it."""
    if gain == 1.0 and not fade_in_ms and not fade_out_ms:
        return False
    try:
        import numpy as np
        from scipy.io import wavfile
    except Exception:
        return False
    try:
        sr, data = wavfile.read(str(path))
    except Exception:
        return False
    dtype = data.dtype
    x = data.astype(np.float32)
    is_int = np.issubdtype(dtype, np.integer)
    maxv = float(np.iinfo(dtype).max) if is_int else 1.0
    if is_int:
        x = x / maxv
    x = x * float(gain)
    n = x.shape[0]

    def _ramp(ms, fade_in):
        k = min(int(sr * ms / 1000), n)
        if k <= 0:
            return
        env = np.linspace(0.0, 1.0, k) if fade_in else np.linspace(1.0, 0.0, k)
        if x.ndim == 2:
            env = env[:, None]
        if fade_in:
            x[:k] *= env
        else:
            x[n - k:] *= env

    _ramp(fade_in_ms, True)
    _ramp(fade_out_ms, False)
    np.clip(x, -1.0, 1.0, out=x)
    out = (x * maxv).astype(dtype) if is_int else x.astype(dtype)
    try:
        wavfile.write(str(path), sr, out)
        return True
    except Exception:
        return False


def _torch_device():
    """Pick the best available torch device (cuda > mps > cpu), without importing torch
    unless it's installed."""
    try:
        import torch
        if torch.cuda.is_available():
            return "cuda"
        if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def chatterbox_synth(project_name):
    """Build a synth backed by the locally-downloaded Chatterbox model.

    Returns a ``synth(text, out_path, voice) -> bool`` callable, or ``None`` when the model isn't
    installed or the ``chatterbox`` package/torch aren't importable — so callers degrade to the
    Kokoro path and ultimately to browser speech. The model is loaded lazily on the first beat
    (and cached) so importing this module stays cheap and a download-but-never-used model costs
    nothing.

    ``voice`` may be a path to a reference clip for zero-shot voice cloning; the Kokoro-style
    named voice ids (``af_heart`` …) don't apply to Chatterbox, so anything that isn't an existing
    file falls back to Chatterbox's built-in voice.
    """
    if not voice_model_installed("chatterbox"):
        return None
    try:
        import torch  # noqa: F401  (presence check; used inside _synth)
        from chatterbox.tts import ChatterboxTTS  # type: ignore
        import torchaudio  # type: ignore
    except Exception:
        logger.info("Chatterbox installed but package/torch unavailable — using fallback TTS.")
        return None

    ckpt_dir = studio_media_models.model_path("chatterbox")
    holder = {"tts": None}  # lazy-loaded singleton; loading the model is the expensive part

    def _synth(text, out_path, voice=None, exaggeration=None, cfg_weight=None):
        text = (text or "").strip()
        if not text:
            return False
        try:
            if holder["tts"] is None:
                holder["tts"] = ChatterboxTTS.from_local(ckpt_dir, device=_torch_device())
            tts = holder["tts"]
            assert tts is not None
            ref = voice if (voice and Path(str(voice)).is_file()) else None
            kwargs = {}
            if ref:
                kwargs["audio_prompt_path"] = ref
            if exaggeration is not None:
                kwargs["exaggeration"] = float(exaggeration)
            if cfg_weight is not None:
                kwargs["cfg_weight"] = float(cfg_weight)
            wav = tts.generate(text, **kwargs)
            torchaudio.save(str(out_path), wav, tts.sr)
            return Path(out_path).is_file() and Path(out_path).stat().st_size > 44
        except Exception as e:
            logger.warning(f"Chatterbox synth failed: {e}")
            return False

    _synth.backend_name = "chatterbox"
    _synth.model_path = ckpt_dir
    return _synth


def best_synth(project_name):
    """Pick the best available local TTS for this project: the premium Chatterbox model when it's
    installed and importable, else the always-present Kokoro path, else ``None`` (browser-speech
    fallback). This is what the workflow should call so a downloaded Chatterbox actually voices."""
    return chatterbox_synth(project_name) or kokoro_synth(project_name)


def set_synth(fn):
    """Install the process-wide TTS synth callable (or None to disable)."""
    global _SYNTH
    _SYNTH = fn


def has_synth(synth=None):
    return callable(synth or _SYNTH)


def synthesize_scenes(project_name, project_id, scenes, synth=None, voice_for=None,
                      progress=None, force=False, gain=1.0, style=True):
    """Render audio for every narration beat. Mutates beats in place with ``audio_path`` +
    ``audio_status`` and returns (scenes, status). Idempotent unless ``force``.

    ``voice_for(speaker) -> voice_id`` lets each speaker get a distinct voice; defaults to one
    narrator voice for everyone.
    """
    synth = synth or _SYNTH
    audio_dir = _audio_dir(project_name)
    available = has_synth(synth)
    synth_backend = getattr(synth, "backend_name", None) if synth is not None else None
    synth_model_path = getattr(synth, "model_path", None) if synth is not None else None
    failures = []
    done = total = 0

    for si, scene in enumerate(scenes or []):
        sid = scene.get("id") or f"s{si + 1}"
        if progress:
            try:
                progress(f"Voicing scene {si + 1} of {len(scenes)}...")
            except Exception:
                pass
        for bi, beat in enumerate(scene.get("narration_script") or []):
            total += 1
            line = (beat.get("line") or "").strip()
            if not line:
                beat["audio_status"] = UNAVAILABLE
                continue
            if not force and beat.get("audio_status") == DONE and beat.get("audio_path"):
                done += 1
                continue
            if not available:
                beat["audio_status"] = UNAVAILABLE
                continue
            out_name = f"{sid}-{bi + 1}.wav"
            out_path = audio_dir / out_name
            if voice_for is not None:
                voice = voice_for(beat.get("speaker")) or "af_heart"
            else:
                voice = "af_heart"
            
            assert synth is not None
            # "Prompt" the voice on HOW to speak this beat (emotion -> expressivity). Engines that
            # don't support these kwargs (e.g. Kokoro) accept and ignore them via **kwargs.
            style_kwargs = style_for_beat(beat) if style else {}
            try:
                try:
                    ok = bool(synth(line, str(out_path), voice, **style_kwargs))
                except TypeError:
                    # Engine signature doesn't take the style kwargs — call it plainly.
                    ok = bool(synth(line, str(out_path), voice))
            except Exception as e:
                logger.warning(f"TTS failed for {sid} beat {bi + 1}: {e}")
                failures.append(f"{sid}-{bi + 1}: {e}")
                ok = False
            if ok and out_path.is_file():
                # Tame the level + a tiny fade to kill clicks between beats.
                apply_gain_fade(out_path, gain=gain, fade_in_ms=10, fade_out_ms=20)
                beat["audio_path"] = f"{_AUDIO_REL}/{out_name}"
                beat["audio_status"] = DONE
                done += 1
            else:
                beat["audio_status"] = FAILED

    status = {
        "done": done,
        "total": total,
        "synth_available": available,
        "synth_backend": synth_backend or ("custom" if available else "none"),
        "synth_model_path": synth_model_path or "",
    }
    if failures:
        status["failures"] = failures[:5]
    try:
        memory.set_user_preference(project_name, project_id, "audio_status", status)
    except Exception:
        pass
    return scenes, status


def kokoro_synth(project_name):
    """Build a synth backed by the existing local Kokoro/TTS path. Returns None if the engine
    isn't importable/available, so callers degrade to browser speech."""
    try:
        from kokoro_sound_engineer import KokoroSoundEngineer
        import server  # ensure_tts_initialized lives here
    except Exception:
        return None
    engineer = KokoroSoundEngineer(project_name=project_name)

    def _synth(text, out_path, voice="af_heart", **_kwargs):
        # Kokoro has no expressivity knobs — it accepts and ignores the Chatterbox style kwargs.
        engine = server.ensure_tts_initialized()
        if not engine:
            return False
        chunks = engineer.prepare_text(text, fallback_voice=voice)
        files = engine.render_prepared_chunks(chunks, str(Path(out_path).parent))
        if not files:
            return False
        # Use the first rendered chunk as the beat's audio (beats are short, usually one chunk).
        Path(files[0]).replace(out_path)
        return True

    _synth.backend_name = "kokoro"
    return _synth


def _audio_dir(project_name):
    d = Path(memory.get_project_dir(project_name)) / _AUDIO_REL
    d.mkdir(parents=True, exist_ok=True)
    return d
