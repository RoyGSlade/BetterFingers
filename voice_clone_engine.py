"""Real cloned-voice synthesis via Kanade voice conversion (DESIGN §10 M5, U6).

Pipeline (the kokoclone approach, Apache-2.0 — github.com/Ashish-Patnaik/kokoclone):
Kokoro synthesizes the text with a built-in voice as usual; this module then
re-voices that audio to match the user's stored reference sample using the
Kanade speech tokenizer's voice conversion (github.com/frothywater/kanade-tokenizer,
MIT) plus its vocoder.

The dependencies (torch is already a runtime dep; torchaudio + kanade-tokenizer
are NOT) are deliberately optional: kanade-tokenizer is a git-only package that
cannot live in the hashed lock files, so — like llama-server — cloning is an
on-demand provisioned capability. Run ``tools/setup_voice_cloning.py`` to
install it; until then, ``availability()`` explains exactly what's missing and
callers must surface that instead of silently speaking a wrong voice.

Supply chain: both the pip install (see the setup tool) and the Hugging Face
model are pinned — the model to an exact revision, mirroring the SHA-256
pinning used for every other model/runtime download.

Verified live on this machine (2026-07-14): converting af_heart speech against
a bm_george reference moved the output's median F0 from 198Hz to 141Hz (the
reference measures 142Hz) at RTF ~0.16 on an RTX 4060 Ti.
"""

import logging
import os
import threading

import numpy as np

import app_paths

# The cloned-voice id namespace ("cloned_<name>"), as written by POST /tts/clone.
CLONED_PREFIX = "cloned_"

# Pinned supply chain (update both together, deliberately).
KANADE_TOKENIZER_REPO = "https://github.com/frothywater/kanade-tokenizer"
KANADE_TOKENIZER_COMMIT = "961f20bf892c59f391d0b6c5f7b88e70ed919b99"
KANADE_MODEL_REPO = "frothywater/kanade-12.5hz"
KANADE_MODEL_REVISION = "bfc4a8a753ea71394cf98e752ca68c7fbc847f0d"

SETUP_HINT = "Run tools/setup_voice_cloning.py to install the voice-cloning engine."

# Kanade's mel decoder has ~1024 precomputed positions (~10.9s); kokoclone caps
# chunks at ~9s with 0.5s context so long drafts convert without artifacts.
MAX_CHUNK_SECONDS = 9.0
OVERLAP_SECONDS = 0.5
# Cap how much reference audio is encoded per conversion (VRAM + latency bound;
# a few seconds of clean speech is plenty to capture a voice).
MAX_REFERENCE_SECONDS = 30.0

_lock = threading.Lock()
_model = None
_vocoder = None
_device = None


def is_cloned_voice_id(voice_id) -> bool:
    return isinstance(voice_id, str) and voice_id.strip().lower().startswith(CLONED_PREFIX)


def get_voices_dir():
    return app_paths.get_app_paths().voices


def find_reference_sample(voice_id):
    """Absolute path of the stored reference sample for a cloned voice id, or
    None. Only ever resolves inside the voices dir (ids are sanitized at clone
    time, but never trust a path segment)."""
    if not is_cloned_voice_id(voice_id):
        return None
    safe = os.path.basename(str(voice_id).strip())
    path = os.path.join(str(get_voices_dir()), f"{safe}.wav")
    return path if os.path.exists(path) else None


def is_available() -> bool:
    return availability()["available"]


def availability() -> dict:
    """Whether cloned-voice synthesis can run, with an actionable reason."""
    try:
        import kanade_tokenizer  # noqa: F401
        import torch  # noqa: F401
    except ImportError as exc:
        return {"available": False,
                "reason": f"voice-cloning dependencies not installed ({exc.name})",
                "setup_hint": SETUP_HINT}
    return {"available": True, "reason": "", "setup_hint": ""}


def _ensure_loaded():
    """Lazy, thread-safe model+vocoder load. Raises RuntimeError with an
    actionable message when the optional dependencies are missing."""
    global _model, _vocoder, _device
    status = availability()
    if not status["available"]:
        raise RuntimeError(f"{status['reason']}. {status['setup_hint']}")
    with _lock:
        if _model is not None:
            return _model, _vocoder, _device
        import torch
        from kanade_tokenizer import KanadeModel, load_vocoder

        logging.info("voice_clone: loading %s@%s ...", KANADE_MODEL_REPO, KANADE_MODEL_REVISION[:12])
        model = KanadeModel.from_pretrained(KANADE_MODEL_REPO, revision=KANADE_MODEL_REVISION).eval()
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model = model.to(device)
        vocoder_name = getattr(model.config, "vocoder_name", "vocos")
        vocoder = load_vocoder(vocoder_name).to(device)
        _model, _vocoder, _device = model, vocoder, device
        logging.info("voice_clone: ready on %s (vocoder=%s)", device, vocoder_name)
        return _model, _vocoder, _device


def unload():
    """Release the models (privacy wipe / VRAM pressure). Next use reloads."""
    global _model, _vocoder, _device
    with _lock:
        _model = None
        _vocoder = None
        _device = None
    try:
        import torch
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except ImportError:
        pass


def _resample(torch, torchaudio, wav, from_sr, to_sr):
    if from_sr == to_sr:
        return wav
    return torchaudio.functional.resample(wav, from_sr, to_sr)


def convert(audio: np.ndarray, sample_rate: int, reference_wav_path: str):
    """Re-voice `audio` (float32 mono) to match the reference sample.

    Chunks sources longer than MAX_CHUNK_SECONDS (with OVERLAP_SECONDS of
    context trimmed from the mel on each side, kokoclone-style) and vocodes the
    concatenated mel in one pass. Returns (float32 numpy audio, sample_rate).
    """
    model, vocoder, device = _ensure_loaded()
    import torch
    import torchaudio

    from kanade_tokenizer import load_audio, vocode

    k_sr = int(getattr(model.config, "sample_rate", 24000))
    src = torch.from_numpy(np.asarray(audio, dtype=np.float32).flatten())
    src = _resample(torch, torchaudio, src, int(sample_rate), k_sr).to(device)
    ref = load_audio(reference_wav_path, sample_rate=k_sr)
    ref = ref[: int(MAX_REFERENCE_SECONDS * k_sr)].to(device)

    chunk_samples = int(MAX_CHUNK_SECONDS * k_sr)
    overlap_samples = int(OVERLAP_SECONDS * k_sr)
    n = src.shape[-1]

    mel_parts = []
    with torch.inference_mode():
        if n <= chunk_samples + 2 * overlap_samples:
            mel_parts.append(model.voice_conversion(source_waveform=src, reference_waveform=ref))
        else:
            pos = 0
            while pos < n:
                core_end = min(pos + chunk_samples, n)
                win_start = max(0, pos - overlap_samples)
                win_end = min(n, core_end + overlap_samples)
                window = src[win_start:win_end]
                mel = model.voice_conversion(source_waveform=window, reference_waveform=ref)
                frames = mel.shape[-1]
                frames_per_sample = frames / max(1, (win_end - win_start))
                left_trim = round((pos - win_start) * frames_per_sample)
                right_trim = frames - round((win_end - core_end) * frames_per_sample)
                mel_parts.append(mel[..., left_trim:right_trim])
                pos = core_end
        mel_full = torch.cat(mel_parts, dim=-1)
        out = vocode(vocoder, mel_full.unsqueeze(0) if mel_full.dim() == 2 else mel_full)

    return out.squeeze().float().cpu().numpy(), k_sr
