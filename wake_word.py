"""Wake-word service (C5 / Phase 9) — hands-free activation.

Owns a pluggable WakeDetector adapter, applies threshold + cooldown + optional
VAD gating, and calls back into the app's existing recording start path
(HotkeyManager.request_start(reason="wake_word")) on a real detection.
Disabled by default (see wake_word_enabled in the profile schema).

WakeWordService itself only decides whether a given audio chunk should
trigger `on_detect` — the cooldown/threshold/VAD state machine is fully
testable with a FakeWakeDetector and no real microphone or ML dependency.
WakeListener (below) is the thing that consumes live audio; since Wave 8A it
subscribes to audio_input_broker (the one process-wide microphone owner,
D-0013) instead of opening its own stream. It is constructed/started/stopped
at runtime by routes_wake.py's /wake/enable and /wake/disable (not tied to
app startup), so enabling wake word never requires an app restart and
disabling it releases the microphone as soon as nothing else holds it.
"""
import logging
import time

DEFAULT_THRESHOLD = 0.55
DEFAULT_COOLDOWN_MS = 2500
_MAX_SCORE_LOG = 200


class WakeDetector:
    """Adapter interface. Real implementations (openWakeWord, ...) wrap a
    model and score one audio chunk at a time."""

    def predict(self, audio_chunk, sample_rate):
        """Return {"detected": bool, "score": float, "label": str}."""
        raise NotImplementedError


class FakeWakeDetector(WakeDetector):
    """Deterministic detector for tests: yields queued scores in order, 0.0
    once the queue is empty."""

    def __init__(self, scores=None, label="hey_betterfingers"):
        self._scores = list(scores or [])
        self._label = label

    def queue_score(self, score):
        self._scores.append(score)

    def predict(self, audio_chunk, sample_rate):
        score = self._scores.pop(0) if self._scores else 0.0
        return {"detected": score >= 1.0, "score": score, "label": self._label}


class OpenWakeWordDetector(WakeDetector):
    """Real detector: streams audio through the ONNX melspec->embedding
    pipeline (wake_models.WakeScorer) and, once enough embedding history has
    accumulated, scores it with a wake-phrase classifier model.

    ``classifier_session`` is optional -- the catalog ships zero bundled
    classifiers (license gate, see wake_models.py), so a freshly-built
    detector with no classifier is a legitimate "pipeline works, nothing to
    score yet" state: predict() reports label="unavailable" rather than
    raising, matching the graceful-degradation requirement (D1).
    """

    def __init__(
        self,
        melspec_session,
        embedding_session,
        classifier_session=None,
        label="wake_word",
        embed_window=None,
    ):
        from wake_models import EMBED_WINDOW_DEFAULT, WakeScorer

        self.scorer = WakeScorer(melspec_session, embedding_session)
        self.classifier_session = classifier_session
        self.label = label
        self.embed_window = int(embed_window or EMBED_WINDOW_DEFAULT)

    def set_classifier(self, classifier_session, label="wake_word"):
        self.classifier_session = classifier_session
        self.label = label

    def predict(self, audio_chunk, sample_rate):
        if audio_chunk is not None:
            self.scorer.push_audio(audio_chunk)

        if self.classifier_session is None:
            return {"detected": False, "score": 0.0, "label": "unavailable"}

        features = self.scorer.get_features(self.embed_window)
        if features is None:
            # Pipeline is warming up (needs ~0.8s of audio before the first
            # embedding window exists) -- not an error, just not scoreable yet.
            return {"detected": False, "score": 0.0, "label": self.label}

        import numpy as np

        input_name = self.classifier_session.get_inputs()[0].name
        output = self.classifier_session.run(None, {input_name: features})
        score = float(np.asarray(output[0]).reshape(-1)[0])
        return {"detected": False, "score": score, "label": self.label}


def build_openwakeword_detector(classifier_id=None, classifier_origin="bundled"):
    """Assemble a real OpenWakeWordDetector from on-disk models, verifying
    everything (§11) before it's trusted. Returns
    ``(detector_or_none, available, reason)`` instead of raising, so a
    missing/corrupt/undownloaded model degrades to a truthful "unavailable"
    status (D1) rather than crashing the caller.
    """
    import wake_models

    # License gate, enforced by the code and not only by a test (WMP-3). It
    # runs first, before any file is hashed or loaded: whether an artifact may
    # be used at all is a prior question to whether it is intact.
    for model_id in ("melspectrogram", "embedding_model") + ((classifier_id,) if classifier_id else ()):
        recorded = wake_models.model_license(model_id)
        if recorded is None:
            # Unknown id: not a licensing question. The verification path below
            # reports it accurately as unknown/missing.
            continue
        try:
            wake_models.assert_license_allowed(model_id, recorded)
        except wake_models.WakeModelLicenseRefused as exc:
            # Safe to surface verbatim: it states a policy and a license name,
            # never internal error text or a path.
            return None, False, f"unavailable: {exc}"

    for backbone_id in ("melspectrogram", "embedding_model"):
        if not wake_models.is_backbone_model_downloaded(backbone_id):
            return None, False, f"unavailable: model not downloaded ({backbone_id})"
        verification = wake_models.verify_wake_model_file(backbone_id)
        if not verification["ok"]:
            return None, False, f"unavailable: {backbone_id} failed verification ({verification['reason']})"

    try:
        melspec_session = wake_models.build_onnx_session(wake_models.get_wake_model_path("melspectrogram"))
        embedding_session = wake_models.build_onnx_session(wake_models.get_wake_model_path("embedding_model"))
    except wake_models.WakeEngineUnavailable as exc:
        # Log the detail server-side; the reason string travels to HTTP
        # clients via /wake/* responses, so it must not echo internal error
        # text (py/stack-trace-exposure).
        logging.error("Wake backbone session failed to load: %s", exc)
        return None, False, "unavailable: wake engine failed to load (see server log)"

    classifier_session = None
    label = "wake_word"
    if classifier_id:
        try:
            # user-imported .onnx and self-trained .npz classifiers share one
            # manifest (verify/path helpers), so both resolve the same way; only
            # the SESSION construction differs by file type below.
            if classifier_origin in ("user-imported", "trained"):
                verification = wake_models.verify_imported_model(classifier_id)
                path = wake_models.get_imported_model_path(classifier_id) if verification["ok"] else None
            else:
                verification = wake_models.verify_wake_model_file(classifier_id)
                path = wake_models.get_wake_model_path(classifier_id) if verification["ok"] else None
            if not verification["ok"]:
                return None, False, f"unavailable: classifier failed verification ({verification['reason']})"
            if path and path.lower().endswith(".npz"):
                # Locally-trained NumPy head — no ONNX, plugs in via the
                # duck-typed session wake_trainer provides.
                import wake_trainer
                classifier_session = wake_trainer.NumpyClassifierSession(wake_trainer.load_model(path))
            else:
                classifier_session = wake_models.build_onnx_session(path)
            label = classifier_id
        except (KeyError, wake_models.WakeEngineUnavailable) as exc:
            logging.error("Wake classifier %s failed to load: %s", classifier_id, exc)
            return None, False, "unavailable: classifier failed to load (see server log)"

    detector = OpenWakeWordDetector(melspec_session, embedding_session, classifier_session, label=label)
    if classifier_session is None:
        return detector, False, "unavailable: no wake-phrase classifier selected"
    return detector, True, "ready"


class WakeWordService:
    """Cooldown/threshold/VAD gating around a WakeDetector. `on_detect` is
    called with no arguments on an accepted trigger — the caller wires that
    to hotkey_manager.request_start(reason="wake_word")."""

    def __init__(
        self,
        detector,
        on_detect,
        threshold=DEFAULT_THRESHOLD,
        cooldown_ms=DEFAULT_COOLDOWN_MS,
        requires_vad=True,
    ):
        self.detector = detector
        self.on_detect = on_detect
        self.threshold = threshold
        self.cooldown_ms = cooldown_ms
        self.requires_vad = requires_vad
        self._last_trigger_time = None
        # False-trigger log for the settings-panel test view (Phase 13).
        self.score_log = []

    def _in_cooldown(self, now):
        if self._last_trigger_time is None:
            return False
        return (now - self._last_trigger_time) * 1000.0 < self.cooldown_ms

    def process_chunk(self, audio_chunk, sample_rate, has_speech=True, now=None):
        """Feed one audio chunk through the detector. Returns True iff this
        chunk triggered `on_detect`. `has_speech` should come from an
        upstream VAD gate; ignored when requires_vad is False."""
        now = time.time() if now is None else now
        result = self.detector.predict(audio_chunk, sample_rate)
        score = result.get("score", 0.0)

        triggered = False
        if score >= self.threshold and not self._in_cooldown(now):
            if not self.requires_vad or has_speech:
                triggered = True
                self._last_trigger_time = now
                self.on_detect()

        self.score_log.append({"score": score, "triggered": triggered, "ts": now})
        if len(self.score_log) > _MAX_SCORE_LOG:
            self.score_log.pop(0)
        return triggered

    def status(self, now=None):
        now = time.time() if now is None else now
        return {
            "threshold": self.threshold,
            "cooldown_ms": self.cooldown_ms,
            "requires_vad": self.requires_vad,
            "in_cooldown": self._in_cooldown(now),
            "recent_scores": list(self.score_log[-20:]),
        }


class WakeListener:
    """Feeds a WakeWordService from the shared microphone stream. Fully
    runtime-controlled (start()/stop() are called by routes_wake.py's
    /wake/enable and /wake/disable, and by the privacy-wipe path) rather than
    tied to app startup/shutdown -- enabling wake word never needs a restart,
    and disabling it (or wiping privacy data) always releases the listener's
    hold on the microphone, never just pauses it.

    Since Wave 8A the listener does NOT open the device itself: it subscribes
    to :mod:`audio_input_broker`, the single process-wide microphone owner
    (D-0013). That is what lets wake detection and an active dictation share
    one capture stream instead of racing for the device, and it means
    stopping the listener releases the hardware only when nothing else (a
    live recording, a level meter) still holds it.

    VAD gating reuses audio_gate.py's existing near-silent thresholds (the
    same ones TrailingSilenceDetector and the no-audio gate use) rather than
    inventing a second definition of "silence".
    """

    def __init__(self, service, sample_rate=16000, channels=1, device_index=None, chunk_frames=1280,
                 broker=None):
        self.service = service
        self.sample_rate = sample_rate
        # channels/chunk_frames are retained for API compatibility with
        # routes_wake.py and existing callers. The broker owns the capture
        # format now and opens the shared stream at the same 16 kHz mono /
        # 1280-frame settings this listener always used, so nothing changes.
        self.channels = channels
        self.device_index = device_index
        self.chunk_frames = chunk_frames
        # Injectable so a test can hand in its own broker; defaults to the
        # process-wide owner, resolved lazily in start().
        self._broker = broker
        self._subscription = None
        self._lock = None  # lazily built in start() to avoid a hard threading import at module load
        self._running = False
        self._last_error = ""
        # Wave 8B: the wake handoff's pre-trigger ring is fed from here. Set by
        # routes_wake when it arms the handoff; a plain callable rather than a
        # WakeHandoff reference so this module keeps knowing nothing about the
        # recorder. Never retains audio itself — the ring is bounded and
        # in-memory, and it is the ring's owner that wipes it.
        self.chunk_observer = None

        from audio_gate import TrailingSilenceDetector

        _gate_defaults = TrailingSilenceDetector()
        self._rms_threshold = _gate_defaults.rms_threshold
        self._peak_threshold = _gate_defaults.peak_threshold

    def is_listening(self):
        subscription = self._subscription
        return bool(self._running and subscription is not None and subscription.active)

    def _get_broker(self):
        if self._broker is None:
            import audio_input_broker

            self._broker = audio_input_broker.get_broker()
        return self._broker

    def _has_speech(self, chunk):
        import numpy as np

        if chunk.size == 0:
            return False
        rms = float(np.sqrt(np.mean(np.square(chunk))))
        peak = float(np.max(np.abs(chunk)))
        return not (rms < self._rms_threshold and peak < self._peak_threshold)

    def _on_chunk(self, indata, sample_rate):
        """Broker subscriber callback: one shared capture block in, one
        scoring decision out. The block is shared read-only with the other
        subscribers, so it is never modified in place here."""
        del sample_rate
        import numpy as np

        chunk = np.asarray(indata, dtype=np.float32).reshape(-1)
        # Feed the pre-trigger ring BEFORE scoring: the phrase is only
        # recognized a few hundred milliseconds after it finished, so the
        # audio that must survive the handoff is the audio arriving now, and a
        # detection inside process_chunk drains the ring synchronously.
        observer = self.chunk_observer
        if observer is not None:
            try:
                observer(chunk, self.sample_rate)
            except Exception as exc:
                # A broken pre-roll must never stop wake detection working.
                logging.debug(f"Wake pre-trigger observer failed: {exc}")
        try:
            self.service.process_chunk(chunk, self.sample_rate, has_speech=self._has_speech(chunk))
        except Exception as exc:
            logging.error(f"Wake listener chunk processing failed: {exc}")

    def _on_stream_error(self, reason):
        self._last_error = str(reason or "")

    def start(self, device_index=None):
        """Idempotent: returns True if already listening. Never persists raw
        audio -- chunks only ever pass through WakeWordService.process_chunk
        (score log only, no audio retained) per the privacy requirement."""
        import threading

        if self._lock is None:
            self._lock = threading.Lock()
        with self._lock:
            if self.is_listening():
                return True
            device = device_index if device_index is not None else self.device_index
            self._last_error = ""
            subscription = self._get_broker().subscribe(
                "wake",
                self._on_chunk,
                device=device,
                on_stream_error=self._on_stream_error,
            )
            if subscription is None:
                logging.error(
                    "Wake listener could not acquire the microphone: %s", self._last_error or "unknown"
                )
                return False
            self._subscription = subscription
            self._running = True
            return True

    def stop(self):
        """Full quiesce: release this listener's hold on the shared microphone.
        Idempotent and safe to call even if never started (used
        unconditionally by the privacy-wipe path, mirroring how it drains the
        recorder). The device itself closes once no other subscriber -- a live
        recording, say -- still needs it."""
        if self._lock is None:
            import threading

            self._lock = threading.Lock()
        with self._lock:
            self._running = False
            subscription = self._subscription
            self._subscription = None
        if subscription is not None:
            try:
                subscription.close()
            except Exception as exc:
                logging.warning(f"Wake listener failed to release the microphone: {exc}")

    def status(self, now=None):
        merged = self.service.status(now=now)
        merged["listening"] = self.is_listening()
        if self._last_error:
            merged["input_error"] = self._last_error
        return merged
