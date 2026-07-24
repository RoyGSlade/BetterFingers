"""Runtime orchestration for the wake/command-phrase builder: wire the real
Apache-2.0 backbone and the real Kokoro TTS into the pure trainer
(``wake_trainer`` + ``wake_training_data``), run the full pipeline, and register
the result as a classifier the wake engine can load.

The heavy/impure adapters (``real_make_scorer``, ``kokoro_synthesize``) are
constructed here but injected into ``train_phrase_model`` with defaults, so the
orchestration is unit-testable with stubs and this module's tests need no
models, no TTS, and no audio device.
"""

import logging
import os

import numpy as np

import wake_models
import wake_trainer
import wake_training_data

TARGET_SAMPLE_RATE = 16000

# A spread of Kokoro voices for synthetic positives/negatives. Kept small so a
# training run is seconds, not minutes; the user's own recordings are the anchor.
DEFAULT_SYNTHETIC_VOICES = ("af_heart", "am_puck", "bf_emma", "bm_george")


def real_make_scorer():
    """Build a WakeScorer from the downloaded Apache-2.0 backbone. Raises
    WakeEngineUnavailable when the backbone isn't present, so the caller can
    tell the user to download it first."""
    mel = wake_models.build_onnx_session(wake_models.get_wake_model_path("melspectrogram"))
    emb = wake_models.build_onnx_session(wake_models.get_wake_model_path("embedding_model"))
    from wake_word import WakeScorer  # local import: wake_word imports wake_models
    return WakeScorer(mel, emb)


def _resample_to_16k(audio, sample_rate):
    audio = np.asarray(audio, dtype=np.float32).reshape(-1)
    if sample_rate == TARGET_SAMPLE_RATE or audio.size == 0:
        return audio
    from scipy.signal import resample_poly
    from math import gcd
    g = gcd(int(sample_rate), TARGET_SAMPLE_RATE)
    return resample_poly(audio, TARGET_SAMPLE_RATE // g, int(sample_rate) // g).astype(np.float32)


def kokoro_synthesize(engine):
    """Return a ``synthesize_fn(text, voice, speed) -> float32 16 kHz mono`` that
    renders via the app's Kokoro TTS (Apache/MIT) — the GPL-free source of
    synthetic training audio. Returns None for a failed render so one bad voice
    never aborts the whole set."""
    def _fn(text, voice, speed):
        try:
            status = engine.ensure_loaded(voice_hint=voice)
            # ensure_loaded returning a non-ok status (or a SAPI fallback) means
            # Kokoro is NOT producing audio -- previously the result was ignored
            # and _generate_kokoro_audio was called anyway, silently yielding
            # None per voice until the whole training set came up empty a minute
            # later. Fail this render explicitly instead so the caller's empty-
            # class error carries the real reason.
            if not status.get("ok"):
                raise RuntimeError(status.get("message") or "Kokoro failed to load.")
            if status.get("backend") not in {"kokoro", "kokoro_onnx"}:
                raise RuntimeError(
                    f"Wake training requires Kokoro; active backend is "
                    f"{status.get('backend', 'unknown')}."
                )
            result = engine._generate_kokoro_audio(text, float(speed), voice)
        except Exception as exc:
            logging.debug("wake-train synth failed (%s @ %s): %s", voice, speed, exc)
            return None
        if not result:
            return None
        audio, sample_rate = result
        return _resample_to_16k(audio, int(sample_rate or TARGET_SAMPLE_RATE))
    return _fn


def preflight_training(engine):
    """Fail fast with the EXACT reason a training run can't succeed, before the
    background thread spends up to a minute synthesizing audio that would only
    resolve to a generic "no positive windows" error.

    Checks, in order: both Apache-2.0 backbones present + verified + actually
    loadable by onnxruntime; a TTS engine exists; Kokoro loads (ok=True); and
    the active backend really is Kokoro (not the SAPI fallback, which cannot
    produce the training audio). Returns ``{"ok": True}`` or
    ``{"ok": False, "message": <actionable reason>}`` — never raises.
    """
    for backbone_id in ("melspectrogram", "embedding_model"):
        status = wake_models.backbone_status(backbone_id)
        if not status["downloaded"]:
            return {"ok": False, "message": f"Wake backbone not ready: {backbone_id} is not "
                                            f"downloaded. Download the feature-extractor models first."}
        if not status["verified"]:
            return {"ok": False, "message": f"Wake backbone not ready: {backbone_id} failed "
                                            f"verification ({status['error']}). Re-download it."}
        if not status["loadable"]:
            return {"ok": False, "message": f"Wake backbone not ready: {backbone_id} could not be "
                                            f"loaded ({status['error']})."}

    if engine is None:
        return {"ok": False, "message": "TTS engine unavailable for synthetic samples."}

    try:
        status = engine.ensure_loaded()
    except Exception as exc:
        return {"ok": False, "message": f"TTS engine failed to load: {exc}"}
    if not status.get("ok"):
        return {"ok": False, "message": status.get("message") or "TTS (Kokoro) failed to load."}
    if status.get("backend") not in {"kokoro", "kokoro_onnx"}:
        return {"ok": False, "message": f"Wake training requires Kokoro; the active TTS backend is "
                                        f"{status.get('backend', 'unknown')} and cannot generate "
                                        f"training audio."}
    return {"ok": True}


def train_phrase_model(
    phrase,
    *,
    engine=None,
    user_positive_clips=None,
    user_negative_clips=None,
    voices=None,
    make_scorer=None,
    synthesize_fn=None,
    progress=None,
    register=True,
):
    """Full build: assemble data (user recordings + Kokoro synthetics) -> train
    the NumPy head -> calibrate a personalised threshold + reliability verdict ->
    (optionally) register it as a loadable classifier.

    Adapters default to the real backbone/TTS but are injectable for tests.
    Returns a result dict:
      { ok, phrase, verdict, threshold, fa_rate, fr_rate, margin,
        model_id?, n_pos, n_neg, message? }
    Never raises for the expected failure modes (no backbone, empty class, TTS
    unavailable) — it returns ok=False + an actionable message.
    """
    phrase = str(phrase or "").strip()
    if not phrase:
        return {"ok": False, "message": "Enter a wake phrase first."}

    def _progress(pct, msg):
        if progress:
            try:
                progress({"percent": pct, "message": msg})
            except Exception:
                pass

    voices = list(voices or DEFAULT_SYNTHETIC_VOICES)
    try:
        make_scorer = make_scorer or real_make_scorer
        # Probe the scorer factory early so a missing backbone fails fast/clean.
        make_scorer()
    except Exception as exc:
        return {"ok": False, "message": f"Wake backbone not ready: {exc}. Download the "
                                        f"feature-extractor models first."}

    if synthesize_fn is None:
        if engine is None:
            return {"ok": False, "message": "TTS engine unavailable for synthetic samples."}
        synthesize_fn = kokoro_synthesize(engine)

    _progress(10, "Generating synthetic samples…")
    try:
        train_pos, train_neg, eval_pos, eval_neg = wake_training_data.build_training_set(
            phrase, voices, synthesize_fn, make_scorer,
            user_positive_clips=user_positive_clips,
            user_negative_clips=user_negative_clips,
        )
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    _progress(55, "Training classifier…")
    try:
        weights = wake_trainer.train_classifier(train_pos, train_neg)
    except ValueError as exc:
        return {"ok": False, "message": str(exc)}

    _progress(80, "Calibrating threshold…")
    pos_scores = wake_trainer.score_windows(weights, eval_pos)
    neg_scores = wake_trainer.score_windows(weights, eval_neg)
    calib = wake_trainer.calibrate(pos_scores, neg_scores)

    result = {
        "ok": True,
        "phrase": phrase,
        "verdict": calib["verdict"],
        "threshold": calib["threshold"],
        "fa_rate": calib["fa_rate"],
        "fr_rate": calib["fr_rate"],
        "margin": calib["margin"],
        "n_pos": int(train_pos.shape[0] + eval_pos.shape[0]),
        "n_neg": int(train_neg.shape[0] + eval_neg.shape[0]),
    }

    if register:
        _progress(92, "Saving model…")
        metadata = {
            "phrase": phrase,
            "verdict": calib["verdict"],
            "threshold": calib["threshold"],
            "fa_rate": calib["fa_rate"],
            "fr_rate": calib["fr_rate"],
            "voices": voices,
        }
        entry = wake_models.register_trained_model(phrase, weights, metadata)
        result["model_id"] = entry["id"]
    _progress(100, "Done.")
    return result
