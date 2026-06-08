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

logger = logging.getLogger("studio_audio")

QUEUED, RENDERING, DONE, FAILED, UNAVAILABLE = "queued", "rendering", "done", "failed", "unavailable"
_AUDIO_REL = "assets/audio"
_SYNTH = None


def set_synth(fn):
    """Install the process-wide TTS synth callable (or None to disable)."""
    global _SYNTH
    _SYNTH = fn


def has_synth(synth=None):
    return callable(synth or _SYNTH)


def synthesize_scenes(project_name, project_id, scenes, synth=None, voice_for=None,
                      progress=None, force=False):
    """Render audio for every narration beat. Mutates beats in place with ``audio_path`` +
    ``audio_status`` and returns (scenes, status). Idempotent unless ``force``.

    ``voice_for(speaker) -> voice_id`` lets each speaker get a distinct voice; defaults to one
    narrator voice for everyone.
    """
    synth = synth or _SYNTH
    audio_dir = _audio_dir(project_name)
    available = has_synth(synth)
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
            voice = (voice_for(beat.get("speaker")) if callable(voice_for) else None) or "af_heart"
            try:
                ok = bool(synth(line, str(out_path), voice))
            except Exception as e:
                logger.warning(f"TTS failed for {sid} beat {bi + 1}: {e}")
                ok = False
            if ok and out_path.is_file():
                beat["audio_path"] = f"{_AUDIO_REL}/{out_name}"
                beat["audio_status"] = DONE
                done += 1
            else:
                beat["audio_status"] = FAILED

    status = {"done": done, "total": total, "synth_available": available}
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

    def _synth(text, out_path, voice="af_heart"):
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

    return _synth


def _audio_dir(project_name):
    d = Path(memory.get_project_dir(project_name)) / _AUDIO_REL
    d.mkdir(parents=True, exist_ok=True)
    return d
