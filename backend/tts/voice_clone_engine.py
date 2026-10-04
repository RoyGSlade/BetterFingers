"""Real cloned-voice synthesis via Kanade voice conversion (DESIGN §10 M5/M6, U6).

Pipeline (the kokoclone approach, Apache-2.0 — github.com/Ashish-Patnaik/kokoclone):
Kokoro synthesizes the text with a built-in voice as usual; this module then
re-voices that audio to match the user's stored reference sample using the
Kanade speech tokenizer's voice conversion (github.com/frothywater/kanade-tokenizer,
MIT) plus its vocoder.

The dependencies (torch is already a runtime dep; torchaudio + kanade-tokenizer
are NOT) are deliberately optional, and are made available through TWO
independent mechanisms — ``availability()`` reports whichever actually works:

1. **in-process** — kanade-tokenizer/torchaudio pip-installed directly into
   the CURRENT interpreter (the original dev-venv path; still supported
   unchanged, see ``_convert``/``_ensure_loaded`` below).
2. **side-runtime** — a self-contained, sha256-verified clone runtime
   (pinned python-build-standalone 3.12 + torch/torchaudio/kanade-tokenizer
   pre-installed), downloaded/extracted on demand via
   ``provision_clone_runtime()`` and driven as a subprocess
   (``_convert_via_side_runtime``). This is the mechanism that actually works
   in a frozen (PyInstaller) build, where pip-install-into-sys.executable is
   impossible (no writable site-packages) — like llama-server, provisioning
   is download-verify-extract, not pip.

Run ``tools/setup_voice_cloning.py`` to provision mechanism 2; until either
mechanism is available, ``availability()`` explains exactly what's missing
and callers must surface that instead of silently speaking a wrong voice —
it must never claim available in a frozen build just because a dev venv
elsewhere on the machine happens to have torch installed (there is no
"elsewhere" once the process is actually frozen).

Supply chain: the Kanade Hugging Face model is pinned to an exact revision;
the side-runtime archive and the WavLM SSL front end it bundles are likewise
sha256-pinned (see LICENSES-MODELS.md — WavLM's weights are CC BY-SA 3.0, so
they're pinned to the ORIGINAL upstream host rather than re-hosted under our
own release, same as how model_manager.py pins llama-server's binary).

Verified live on this machine (2026-07-14): converting af_heart speech against
a bm_george reference moved the output's median F0 from 198Hz to 141Hz (the
reference measures 142Hz) at RTF ~0.16 on an RTX 4060 Ti.
"""

import importlib.util
import json
import logging
import os
import platform
import re
import subprocess
import tempfile
import threading
import time
import wave

import numpy as np

import app_paths

# The cloned-voice id namespace ("cloned_<name>"), as written by POST /tts/clone.
CLONED_PREFIX = "cloned_"

# Canonical cloned-voice id form, enforced wherever an id names a stored voice
# (lookup here; creation/deletion/selection/export in server.py). Namespace
# detection (is_cloned_voice_id) is deliberately looser so a malformed id still
# routes to the clone path and fails honestly instead of speaking a built-in voice.
CLONED_ID_PATTERN = re.compile(r"^cloned_[A-Za-z0-9_-]{1,64}$")

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

# Tracks in-flight conversions so a privacy wipe can verify none is mid-flight
# before deleting samples and caches: the TTS chunked-playback generation
# thread can outlive the worker join and keep converting user audio.
_conversion_cv = threading.Condition()
_active_conversions = 0


def conversion_active() -> bool:
    with _conversion_cv:
        return _active_conversions > 0


def wait_for_conversion_idle(timeout: float = 10.0) -> bool:
    """Block until no conversion is running; True if idle within timeout."""
    deadline = time.monotonic() + timeout
    with _conversion_cv:
        while _active_conversions > 0:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            _conversion_cv.wait(remaining)
        return True


def is_cloned_voice_id(voice_id) -> bool:
    return isinstance(voice_id, str) and voice_id.strip().lower().startswith(CLONED_PREFIX)


def is_valid_cloned_voice_id(voice_id) -> bool:
    """Whether the id is in the canonical stored-voice form. Every operation
    that touches a stored voice by id must pass this gate."""
    return isinstance(voice_id, str) and bool(CLONED_ID_PATTERN.match(voice_id.strip()))


def get_voices_path():
    # Pure lookup — never creates the directory (see server.ensure_voices_dir
    # for the sole creation point).
    return app_paths.get_app_paths().voices


def find_reference_sample(voice_id):
    """Absolute path of the stored reference sample for a cloned voice id, or
    None. Ids must be in canonical form (which cannot contain a path
    separator); basename() stays as a second line of defense."""
    if not is_valid_cloned_voice_id(voice_id):
        return None
    safe = os.path.basename(str(voice_id).strip())
    path = os.path.join(str(get_voices_path()), f"{safe}.wav")
    return path if os.path.exists(path) else None


def is_available() -> bool:
    return availability()["available"]


def availability() -> dict:
    """Whether cloned-voice synthesis can run, with an actionable reason.

    Checks the in-process mechanism first (unchanged from before side-runtime
    provisioning existed — a dev venv with kanade-tokenizer pip-installed
    keeps working exactly as before), then falls back to checking whether a
    side-runtime has been provisioned. A frozen build's interpreter never has
    torch importable, so it naturally falls through to the side-runtime
    check — this never claims availability "because torch exists somewhere,"
    only because one of the two concrete mechanisms actually works here.
    """
    try:
        import kanade_tokenizer  # noqa: F401
        import torch  # noqa: F401
        return {"available": True, "reason": "", "setup_hint": "", "mechanism": "in-process"}
    except ImportError as exc:
        in_process_reason = f"voice-cloning dependencies not installed ({exc.name})"

    if is_clone_runtime_provisioned():
        return {"available": True, "reason": "", "setup_hint": "", "mechanism": "side-runtime"}

    return {
        "available": False,
        "reason": in_process_reason,
        "setup_hint": SETUP_HINT,
        "mechanism": None,
    }


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

    Dispatches to the side-runtime subprocess ONLY when kanade-tokenizer is
    not importable in-process AND a side-runtime has actually been
    provisioned — i.e. exactly the frozen-build case. Everywhere else
    (including "neither mechanism available") falls through to the original
    in-process `_convert`, unchanged, so its existing honest-failure message
    (via `_ensure_loaded`) is preserved verbatim rather than duplicated here.
    """
    global _active_conversions
    with _conversion_cv:
        _active_conversions += 1
    try:
        if importlib.util.find_spec("kanade_tokenizer") is None and is_clone_runtime_provisioned():
            return _convert_via_side_runtime(audio, sample_rate, reference_wav_path)
        return _convert(audio, sample_rate, reference_wav_path)
    finally:
        with _conversion_cv:
            _active_conversions -= 1
            _conversion_cv.notify_all()


def _convert(audio: np.ndarray, sample_rate: int, reference_wav_path: str):
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


# --- Clone runtime provisioning (frozen-build compatible, DESIGN §10 M5/M6) ---
#
# pip-install-into-sys.executable (the original tools/setup_voice_cloning.py
# approach) cannot work in a frozen (PyInstaller) build — there is no
# writable site-packages to install into, and kanade-tokenizer has no PyPI
# wheel/hashes to pin anyway. Instead, like llama-server, cloning is
# provisioned as a self-contained, sha256-verified runtime: a pinned
# python-build-standalone 3.12 interpreter with torch(cpu)/torchaudio/
# kanade-tokenizer already installed into it, published as one archive per
# platform under our own GitHub release. Pinned to 3.12 independent of the
# app's own Python version on every platform — sidesteps the Windows build's
# py3.13/torch-less lock (see requirements-win.lock) entirely.
#
# NOTE: the actual archives are an integration/publishing dependency (per
# tier3-orchestrator, not this workstream) — these URLs are catalog SHAPE,
# to be verified against once the real artifacts are published. sha256=None
# means "not yet published"; provision_clone_runtime() refuses cleanly rather
# than attempting a download that would fail with a confusing mismatch.
CLONE_RUNTIME_RELEASE_BASE = "https://github.com/RoyGSlade/BetterFingers/releases/download/clone-runtime-v1"

CLONE_RUNTIME_CATALOG = {
    "linux-x86_64": {
        "url": f"{CLONE_RUNTIME_RELEASE_BASE}/clone-runtime-linux-x86_64.tar.gz",
        "archive_name": "clone-runtime-linux-x86_64.tar.gz",
        "sha256": None,
        "python_relpath": os.path.join("bin", "python3"),
    },
    "windows-x86_64": {
        "url": f"{CLONE_RUNTIME_RELEASE_BASE}/clone-runtime-windows-x86_64.tar.gz",
        "archive_name": "clone-runtime-windows-x86_64.tar.gz",
        "sha256": None,
        "python_relpath": "python.exe",
    },
}

# WavLM-base-plus SSL front end (torchaudio's WAVLM_BASE_PLUS bundle, what
# kanade's local/global encoders run on): pinned to the UPSTREAM host, NOT
# re-hosted under our own release — see LICENSES-MODELS.md, its weights are
# CC BY-SA 3.0 (not MIT), so running it is fine but redistributing our own
# copy is not something we want to take on for a binary blob. Pre-placed into
# the side-runtime's TORCH_HOME cache during provisioning so torchaudio's own
# lazy first-use download never fires (§11: no unpinned downloads).
# Verified against upstream (supply-chain gate, §11): torchaudio v2.9.0's
# WAVLM_BASE_PLUS._path = "wavlm_base_plus.pth", resolved by
# utils._get_state_dict against https://download.pytorch.org/torchaudio/models/
# — downloaded and hashed directly from that URL (377,604,347 bytes).
CLONE_WAVLM_PIN = {
    "url": "https://download.pytorch.org/torchaudio/models/wavlm_base_plus.pth",
    "sha256": "136a3e720c04f2c77bf7a4dc6a3868b14d5a2c145a988114b733cb1a8428be98",
    "size_bytes": 377604347,
    "cache_relpath": os.path.join("hub", "checkpoints", "wavlm_base_plus.pth"),
}

CLONE_RUNTIME_STATE_FILE = "clone-runtime.state.json"


def _clone_runtime_platform_key():
    """The catalog key for this machine, or None if unsupported (macOS isn't
    a shipped platform for this app today; see model_manager.py's own
    Windows/Linux-only SERVER_BIN_URL branches for the same scope)."""
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "linux" and machine in ("x86_64", "amd64"):
        return "linux-x86_64"
    if system == "windows" and machine in ("amd64", "x86_64"):
        return "windows-x86_64"
    return None


def clone_runtime_dir():
    from model_manager import get_models_dir
    return os.path.join(get_models_dir(), "clone-runtime")


def _clone_runtime_catalog_entry():
    key = _clone_runtime_platform_key()
    return CLONE_RUNTIME_CATALOG.get(key) if key else None


def clone_runtime_python_path():
    """Absolute path to the provisioned interpreter, or None when this
    platform has no catalog entry. Does not imply the path exists yet — see
    is_clone_runtime_provisioned()."""
    entry = _clone_runtime_catalog_entry()
    if entry is None:
        return None
    return os.path.join(clone_runtime_dir(), entry["python_relpath"])


def is_clone_runtime_provisioned():
    """True only once the interpreter is extracted AND the state file marks
    the whole provision (including the WavLM pin) as complete — a partial
    provision (e.g. interrupted after extraction but before the WavLM
    download) must not be reported as ready."""
    python_path = clone_runtime_python_path()
    if not python_path or not os.path.exists(python_path):
        return False
    state_path = os.path.join(clone_runtime_dir(), CLONE_RUNTIME_STATE_FILE)
    try:
        with open(state_path, "r", encoding="utf-8") as fh:
            state = json.load(fh)
    except (OSError, ValueError):
        return False
    return bool(state.get("ready"))


def _extract_clone_runtime_archive(archive_path, dest_dir, required_members=()):
    """Extract the clone-runtime tarball PRESERVING its directory tree.

    Deliberately NOT model_manager.safe_extract_runtime_archive: that
    function flattens every archive member into one directory — correct for
    the single-binary-plus-siblings llama-server archive, but it would
    destroy a Python interpreter distribution's nested bin/lib/site-packages
    layout. Uses stdlib tarfile's 'data' extraction filter (PEP 706, Python
    3.12+, rejects absolute paths/traversal/device files) instead of
    reimplementing member validation, then promotes atomically (extract to a
    staging dir first, only swap it in for dest_dir after the required
    members are confirmed present) so a failed/interrupted provision never
    leaves a half-extracted runtime in place of a working one.
    """
    import shutil
    import tarfile

    # Staged as a SIBLING of dest_dir, not a child of it (unlike
    # model_manager.safe_extract_runtime_archive's staging-inside-dest_dir):
    # the promote step below may rename dest_dir itself out of the way to
    # back up a previous install, which would otherwise carry a
    # staging-dir-inside-dest_dir along with it and break the subsequent
    # os.replace(staging_dir, dest_dir).
    parent_dir = os.path.dirname(os.path.abspath(dest_dir)) or "."
    os.makedirs(parent_dir, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=".staging-clone-runtime-", dir=parent_dir)
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            archive.extractall(staging_dir, filter="data")

        missing = [m for m in required_members if not os.path.exists(os.path.join(staging_dir, m))]
        if missing:
            raise RuntimeError(
                f"clone runtime archive missing expected member(s): {', '.join(missing)}"
            )

        backup_dir = None
        if os.path.isdir(dest_dir) and os.listdir(dest_dir):
            backup_dir = f"{dest_dir}.bak-{os.getpid()}"
            os.replace(dest_dir, backup_dir)
        try:
            os.replace(staging_dir, dest_dir)
        except Exception:
            if backup_dir is not None:
                os.replace(backup_dir, dest_dir)
            raise
        if backup_dir is not None:
            shutil.rmtree(backup_dir, ignore_errors=True)
        return {"ok": True, "dest_dir": dest_dir}
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)


def _provision_wavlm_pin(dest_dir, progress_callback=None):
    if not CLONE_WAVLM_PIN.get("url") or not CLONE_WAVLM_PIN.get("sha256"):
        return {"ok": False, "message": "The pinned WavLM artifact has not been configured yet."}
    dest = os.path.join(dest_dir, "torch-home", CLONE_WAVLM_PIN["cache_relpath"])
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    from model_manager import download_file

    try:
        download_file(
            CLONE_WAVLM_PIN["url"], dest, desc="WavLM SSL front end",
            progress_callback=progress_callback, expected_sha256=CLONE_WAVLM_PIN["sha256"],
        )
    except Exception as exc:
        return {"ok": False, "message": f"WavLM download failed: {exc}"}
    return {"ok": True}


def provision_clone_runtime(progress_callback=None):
    """Download, verify, and extract the clone runtime (+ pin WavLM's
    weights into its cache) into app data. Idempotent — a no-op when already
    provisioned. Returns {"ok": bool, "message"?: str, "already_provisioned"?: bool}."""
    if is_clone_runtime_provisioned():
        return {"ok": True, "already_provisioned": True}

    entry = _clone_runtime_catalog_entry()
    if entry is None:
        return {
            "ok": False,
            "message": f"Voice cloning provisioning is not supported on this platform "
                       f"({platform.system()} {platform.machine()}).",
        }
    if not entry.get("sha256") or not entry.get("url"):
        return {"ok": False, "message": "The voice-cloning runtime artifact has not been published yet."}

    dest_dir = clone_runtime_dir()
    os.makedirs(dest_dir, exist_ok=True)
    archive_path = os.path.join(dest_dir, entry["archive_name"])

    from model_manager import download_file

    try:
        download_file(
            entry["url"], archive_path, desc="Voice-cloning runtime",
            progress_callback=progress_callback, expected_sha256=entry["sha256"],
        )
    except Exception as exc:
        return {"ok": False, "message": f"Download failed: {exc}"}

    try:
        _extract_clone_runtime_archive(
            archive_path, dest_dir, required_members=(entry["python_relpath"],)
        )
    except Exception as exc:
        return {"ok": False, "message": f"Extraction failed: {exc}"}
    finally:
        try:
            os.remove(archive_path)
        except OSError:
            pass

    wavlm_result = _provision_wavlm_pin(dest_dir, progress_callback=progress_callback)
    if not wavlm_result.get("ok", False):
        return wavlm_result

    _write_clone_worker_script(dest_dir)

    state_path = os.path.join(dest_dir, CLONE_RUNTIME_STATE_FILE)
    with open(state_path, "w", encoding="utf-8") as fh:
        json.dump({"ready": True, "platform": _clone_runtime_platform_key()}, fh)

    return {"ok": True, "already_provisioned": False}


# Standalone worker: mirrors _convert()'s exact chunking algorithm, but runs
# under the side-runtime's OWN interpreter (torch/torchaudio/kanade_tokenizer
# pre-installed there) rather than this process's. Written to disk at
# provision time — not imported by the main app — so re-provisioning can ship
# worker fixes without needing a new interpreter archive.
_CLONE_WORKER_SCRIPT = '''\
"""Standalone voice-conversion worker for the provisioned clone runtime.
Mirrors voice_clone_engine._convert(); written here so it runs under the
side-runtime's own interpreter, which is not on the main app's sys.path.
"""
import argparse
import sys

import torch
import torchaudio
from kanade_tokenizer import KanadeModel, load_audio, load_vocoder, vocode

KANADE_MODEL_REPO = "frothywater/kanade-12.5hz"
KANADE_MODEL_REVISION = "bfc4a8a753ea71394cf98e752ca68c7fbc847f0d"
MAX_CHUNK_SECONDS = 9.0
OVERLAP_SECONDS = 0.5
MAX_REFERENCE_SECONDS = 30.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = KanadeModel.from_pretrained(KANADE_MODEL_REPO, revision=KANADE_MODEL_REVISION).eval().to(device)
    vocoder_name = getattr(model.config, "vocoder_name", "vocos")
    vocoder = load_vocoder(vocoder_name).to(device)
    k_sr = int(getattr(model.config, "sample_rate", 24000))

    src_wav, src_sr = torchaudio.load(args.source)
    src = src_wav.mean(dim=0) if src_wav.dim() > 1 else src_wav.squeeze(0)
    if src_sr != k_sr:
        src = torchaudio.functional.resample(src, src_sr, k_sr)
    src = src.to(device)

    ref = load_audio(args.reference, sample_rate=k_sr)
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

    out = out.squeeze().float().cpu()
    torchaudio.save(args.out, out.unsqueeze(0), k_sr)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"clone_worker error: {exc}", file=sys.stderr)
        sys.exit(1)
'''


def _write_clone_worker_script(dest_dir):
    path = os.path.join(dest_dir, "clone_worker.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(_CLONE_WORKER_SCRIPT)
    return path


def _write_temp_wav(audio, sample_rate):
    fd, path = tempfile.mkstemp(suffix=".wav")
    os.close(fd)
    pcm16 = np.clip(np.asarray(audio, dtype=np.float32).flatten(), -1.0, 1.0)
    pcm16 = (pcm16 * 32767.0).astype(np.int16)
    with wave.open(path, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(int(sample_rate))
        wav_file.writeframes(pcm16.tobytes())
    return path


def _read_wav_float32(path):
    with wave.open(path, "rb") as wav_file:
        sample_rate = wav_file.getframerate()
        raw = wav_file.readframes(wav_file.getnframes())
    pcm16 = np.frombuffer(raw, dtype=np.int16)
    return pcm16.astype(np.float32) / 32767.0, sample_rate


def _convert_via_side_runtime(audio, sample_rate, reference_wav_path, timeout=180.0):
    """Run one conversion as a subprocess in the provisioned side-runtime.
    Same (audio, sample_rate) contract as `_convert`, dispatched to a
    completely separate interpreter/process instead of this one."""
    python_path = clone_runtime_python_path()
    dest_dir = clone_runtime_dir()
    worker_path = os.path.join(dest_dir, "clone_worker.py")
    if not python_path or not os.path.exists(python_path) or not os.path.exists(worker_path):
        raise RuntimeError(f"Voice-cloning runtime is not provisioned. {SETUP_HINT}")

    src_path = _write_temp_wav(audio, sample_rate)
    out_fd, out_path = tempfile.mkstemp(suffix=".wav")
    os.close(out_fd)
    # Isolated caches inside the runtime dir — never the real user/dev
    # HOME/torch cache — so the pinned WavLM placement above is what
    # torchaudio actually finds, and any HF downloads the worker triggers
    # (the Kanade checkpoint itself) stay scoped to app data.
    env = dict(os.environ)
    env["TORCH_HOME"] = os.path.join(dest_dir, "torch-home")
    env["HF_HOME"] = os.path.join(dest_dir, "hf-home")
    try:
        result = subprocess.run(
            [python_path, worker_path, "--source", src_path, "--reference", reference_wav_path, "--out", out_path],
            capture_output=True, text=True, timeout=timeout, env=env,
        )
        if result.returncode != 0:
            raise RuntimeError(f"clone worker failed: {(result.stderr or '').strip()[:800]}")
        return _read_wav_float32(out_path)
    finally:
        for p in (src_path, out_path):
            try:
                os.remove(p)
            except OSError:
                pass
