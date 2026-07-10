import collections
import importlib
import logging
import os
import queue
import re
import sys
import threading
from typing import Dict, Optional, Tuple, Union

import numpy as np
import sounddevice as sd
from utils import get_user_data_path
from tts_text import apply_pause_style, normalize_for_speech
import voice_blend
import voice_modulation

# Regex-based pronunciation fixes
_PRONUNCIATION_MAP = {
    r"\bSQL\b": "Sequel",
    r"\bGUI\b": "Gooey",
    r"\bAPIs?\b": "A P I",
    r"\bLLM\b": "L L M",
    r"\bTTS\b": "T T S",
}


def _blend_signature(blend: Optional[dict]) -> tuple:
    """Deterministic, hashable summary of a blend dict for cache keys."""
    if not blend:
        return ()
    parts = []
    for k, v in blend.items():
        try:
            parts.append((str(k), round(float(v), 4)))
        except (TypeError, ValueError):
            parts.append((str(k), 0.0))
    return tuple(sorted(parts))


def _modulation_signature(modulation: Optional[dict]) -> tuple:
    """Deterministic, hashable summary of a modulation dict for cache keys."""
    if not modulation:
        return ()
    keys = ("pitch", "energy", "warmth", "brightness", "pause_style")
    parts = []
    for key in keys:
        value = modulation.get(key)
        if key == "pause_style":
            parts.append(str(value or ""))
        else:
            try:
                parts.append(round(float(value), 3) if value is not None else 0.0)
            except (TypeError, ValueError):
                parts.append(0.0)
    return tuple(parts)


class ReviewTTSEngine:
    """
    Runtime TTS service for review playback.

    Backend selection:
    1) Kokoro (primary, when supported runtime is available)
    2) Windows SAPI fallback
    """
    DEFAULT_VOICE_HINTS = [
        "english",
        "af_heart",
        "af_bella",
        "af_nicole",
        "af_sarah",
        "am_adam",
        "am_michael",
        "am_puck",
        "bf_emma",
        "bm_george",
    ]
    # Kokoro can truncate very long phoneme streams; keep chunks conservative.
    MAX_KOKORO_TEXT_CHARS = 220

    def __init__(self):
        self._lock = threading.RLock()
        self._queue = queue.Queue(maxsize=1)
        self._worker: Optional[threading.Thread] = None
        self._worker_running = False

        self.on_start = None
        self.on_stop = None

        self._loaded = False
        self._backend = "none"
        self._fallback = False
        self._status_message = "TTS is not loaded."

        self._kokoro_pipeline = None
        self._kokoro_onnx = None
        self._kokoro_runtime = None
        self._kokoro_voice = "af_heart"
        self._onnx_providers_used = []
        self._prefer_gpu = True
        self._auto_unload_when_idle = False
        self._audio_cache = collections.OrderedDict()
        self._cache_max_size = 24
        self._current_playback = ""

    def is_loaded(self) -> bool:
        with self._lock:
            return self._loaded

    def backend(self) -> str:
        with self._lock:
            return self._backend

    @classmethod
    def default_voice_hints(cls):
        return list(cls.DEFAULT_VOICE_HINTS)

    def get_voice_hints(self):
        hints = list(self.DEFAULT_VOICE_HINTS)
        with self._lock:
            onnx_voices = self._extract_onnx_voice_names()
        for voice in onnx_voices:
            if voice and voice not in hints:
                hints.append(voice)
        return hints

    def set_prefer_gpu(self, prefer_gpu: bool):
        prefer = bool(prefer_gpu)
        with self._lock:
            changed = prefer != self._prefer_gpu
            self._prefer_gpu = prefer
            backend = self._backend
        # Recreate ONNX engine on next use so provider preference is applied.
        if changed and backend == "kokoro_onnx":
            self.unload()

    def set_keep_loaded(self, keep_loaded: bool):
        with self._lock:
            self._auto_unload_when_idle = not bool(keep_loaded)

    def _release_backend_resources(self, message="TTS auto-unloaded after playback."):
        with self._lock:
            self._kokoro_pipeline = None
            self._kokoro_onnx = None
            self._kokoro_runtime = None
            self._onnx_providers_used = []
            self._loaded = False
            self._backend = "none"
            self._fallback = False
            self._status_message = message

    def ensure_loaded(self, voice_hint: str = "english") -> Dict[str, object]:
        with self._lock:
            if self._loaded:
                return {
                    "ok": True,
                    "backend": self._backend,
                    "fallback": self._fallback,
                    "message": self._status_message,
                }

            kokoro_ok, kokoro_msg = self._load_kokoro_backend(
                voice_hint=voice_hint,
                prefer_gpu=self._prefer_gpu,
                quantization=getattr(self, "_kokoro_quantization", "fp32"),
            )
            if kokoro_ok:
                self._loaded = True
                self._backend = "kokoro_onnx" if self._kokoro_runtime == "onnx" else "kokoro"
                self._fallback = False
                self._status_message = kokoro_msg
                return {
                    "ok": True,
                    "backend": self._backend,
                    "fallback": self._fallback,
                    "message": self._status_message,
                }

            sapi_ok, sapi_msg = self._load_sapi_backend()
            if sapi_ok:
                self._loaded = True
                self._backend = "sapi"
                self._fallback = True
                self._status_message = f"{kokoro_msg} Using Windows SAPI fallback."
                logging.warning(self._status_message)
                return {
                    "ok": True,
                    "backend": self._backend,
                    "fallback": self._fallback,
                    "message": self._status_message,
                }

            self._loaded = False
            self._backend = "none"
            self._fallback = False
            self._status_message = f"{kokoro_msg} {sapi_msg}".strip()
            logging.error(self._status_message)
            return {
                "ok": False,
                "backend": self._backend,
                "fallback": self._fallback,
                "message": self._status_message,
            }

    def speak(
        self,
        text: str,
        speed: float = 1.5,
        voice_hint: str = "english",
        blend: Optional[dict] = None,
        modulation: Optional[dict] = None,
    ) -> Dict[str, object]:
        phrase = (text or "").strip()
        if not phrase:
            return {
                "ok": False,
                "backend": "none",
                "fallback": False,
                "message": "No text to speak.",
            }

        with self._lock:
            status = self.ensure_loaded(voice_hint=voice_hint)
            if not status.get("ok", False):
                return status

            self.stop_current()
            # 1a. Normalize written forms to speech (currency, %, abbreviations…).
            text = normalize_for_speech(text)
            # 1b. Apply pronunciation fixes
            for pattern, replacement in _PRONUNCIATION_MAP.items():
                text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
            # 1c. Bias punctuation-driven pause length (no-op for "natural").
            if modulation:
                text = apply_pause_style(text, modulation.get("pause_style"))

            # 2. Check Cache
            cache_key = (text, speed, voice_hint, _blend_signature(blend), _modulation_signature(modulation))
            if cache_key in self._audio_cache:
                logging.info("TTS Cache Hit")
                audio, rate = self._audio_cache[cache_key]
                # Move to end (LRU)
                self._audio_cache.move_to_end(cache_key)
                self.stop_current() # Stop any current playback before playing from cache
                if self.on_start:
                    try:
                        self.on_start(text)
                    except Exception as e:
                        logging.warning(f"Failed to run TTS on_start callback: {e}")
                sd.play(audio, rate)
                if self.on_stop:
                    try:
                        duration = len(audio) / rate
                        threading.Timer(duration, lambda: self.on_stop() if (hasattr(self, "on_stop") and self.on_stop) else None).start()
                    except Exception as e:
                        logging.warning(f"Failed to schedule TTS on_stop callback: {e}")
                self._current_playback = text
                return {
                    "ok": True,
                    "backend": status.get("backend", "none"),
                    "fallback": bool(status.get("fallback", False)),
                    "message": "Playback from cache.",
                }

            # 3. Generate & Play (via worker queue)
            self._clear_queue()
            self._start_worker_if_needed()

            payload = {
                "text": phrase,
                "speed": float(speed),
                "voice_hint": (voice_hint or "english").strip() or "english",
                "blend": blend or None,
                "modulation": modulation or None,
            }
            try:
                self._queue.put_nowait(payload)
            except queue.Full:
                self._clear_queue()
                self._queue.put_nowait(payload)

        return {
            "ok": True,
            "backend": status.get("backend", "none"),
            "fallback": bool(status.get("fallback", False)),
            "message": str(status.get("message", "")).strip(),
        }

    def stop_current(self):
        # Stop possible Kokoro playback stream
        try:
            import sounddevice as sd

            sd.stop()
        except Exception:
            pass

        # Purge SAPI queue if active
        try:
            comtypes = importlib.import_module("comtypes")
            comtypes_client = importlib.import_module("comtypes.client")
            initialized = False
            if hasattr(comtypes, "CoInitialize"):
                comtypes.CoInitialize()
                initialized = True
            try:
                voice = comtypes_client.CreateObject("SAPI.SpVoice")
                # 1 = async, 2 = purge
                voice.Speak("", 3)
            finally:
                if initialized and hasattr(comtypes, "CoUninitialize"):
                    comtypes.CoUninitialize()
        except Exception:
            pass

    def unload(self):
        self.stop_current()
        self._stop_worker()
        self._release_backend_resources(message="TTS unloaded.")
        self._clear_queue()

    def shutdown(self):
        self.unload()

    def _start_worker_if_needed(self):
        with self._lock:
            if self._worker and self._worker.is_alive():
                return
            self._worker_running = True
            self._worker = threading.Thread(target=self._worker_loop, daemon=True)
            self._worker.start()

    def _stop_worker(self):
        with self._lock:
            self._worker_running = False
        try:
            self._queue.put_nowait(None)
        except Exception:
            pass
        worker = self._worker
        if worker and worker.is_alive():
            worker.join(timeout=1.5)
        self._worker = None

    def _clear_queue(self):
        while True:
            try:
                self._queue.get_nowait()
            except queue.Empty:
                break
            except Exception:
                break

    def _worker_loop(self):
        while self._worker_running:
            try:
                item = self._queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if item is None:
                continue

            text = (item.get("text", "") or "").strip()
            if not text:
                continue

            speed = float(item.get("speed", 1.5))
            voice_hint = (item.get("voice_hint", "english") or "english").strip() or "english"
            blend = item.get("blend") or None
            modulation = item.get("modulation") or None

            try:
                backend = self.backend()
                if backend == "none":
                    recovered = self.ensure_loaded(voice_hint=voice_hint)
                    if not recovered.get("ok", False):
                        logging.error(
                            "TTS backend unavailable at playback time: %s",
                            recovered.get("message", "unknown backend error"),
                        )
                        continue
                    backend = self.backend()
                if backend in {"kokoro", "kokoro_onnx"}:
                    if self.on_start:
                        try:
                            self.on_start(text)
                        except Exception as e:
                            logging.warning(f"TTS on_start callback error: {e}")
                    try:
                        self._speak_kokoro_chunked(
                            text=text, speed=speed, voice_hint=voice_hint,
                            blend=blend, modulation=modulation,
                        )
                    finally:
                        if self.on_stop:
                            try:
                                self.on_stop()
                            except Exception as e:
                                logging.warning(f"TTS on_stop callback error: {e}")
                elif backend == "sapi":
                    if self.on_start:
                        try:
                            self.on_start(text)
                        except Exception as e:
                            logging.warning(f"TTS on_start callback error: {e}")
                    try:
                        self._speak_sapi(text=text, speed=speed, voice_hint=voice_hint)
                    finally:
                        if self.on_stop:
                            try:
                                self.on_stop()
                            except Exception as e:
                                logging.warning(f"TTS on_stop callback error: {e}")
                else:
                    logging.error("TTS backend unavailable at playback time.")
            except Exception as exc:
                logging.error(f"TTS playback failed: {exc}")
            finally:
                should_release = False
                with self._lock:
                    should_release = self._auto_unload_when_idle and self._queue.empty()
                if should_release:
                    self._release_backend_resources()

    def _load_kokoro_backend(
        self,
        voice_hint: str = "english",
        prefer_gpu: bool = True,
        quantization: str = "fp32",
    ) -> Tuple[bool, str]:
        onnx_ok, onnx_msg = self._load_kokoro_onnx_backend(
            voice_hint=voice_hint,
            prefer_gpu=prefer_gpu,
            quantization=quantization,
        )
        if onnx_ok:
            return True, onnx_msg

        native_msg = ""
        try:
            kokoro = importlib.import_module("kokoro")
        except BaseException as exc:
            if isinstance(exc, ModuleNotFoundError):
                if sys.version_info >= (3, 13):
                    native_msg = (
                        "Kokoro unavailable on this runtime: Python 3.13 environment detected."
                    )
                else:
                    native_msg = "Kokoro unavailable (module not installed; run `pip install kokoro`)."
            else:
                native_msg = f"Kokoro unavailable ({exc})."
        else:
            pipeline_cls = getattr(kokoro, "KPipeline", None)
            if pipeline_cls is None:
                native_msg = "Kokoro runtime found but KPipeline is unavailable."
            else:
                try:
                    try:
                        pipeline = pipeline_cls(lang_code="a")
                    except TypeError:
                        pipeline = pipeline_cls("a")
                    self._kokoro_pipeline = pipeline
                    self._kokoro_onnx = None
                    self._kokoro_runtime = "native"
                    self._kokoro_voice = self._resolve_kokoro_voice(voice_hint)
                    return True, "Kokoro backend loaded."
                except BaseException as exc:
                    self._kokoro_pipeline = None
                    native_msg = f"Kokoro load failed ({exc})."

        if native_msg:
            return False, f"{native_msg} {onnx_msg}".strip()
        return False, onnx_msg

    def _load_kokoro_onnx_backend(
        self,
        voice_hint: str = "english",
        prefer_gpu: bool = True,
        quantization: str = "fp32",
    ) -> Tuple[bool, str]:
        try:
            kokoro_onnx = importlib.import_module("kokoro_onnx")
        except Exception as exc:
            return False, f"kokoro-onnx unavailable ({exc})."

        kokoro_cls = getattr(kokoro_onnx, "Kokoro", None)
        if kokoro_cls is None:
            return False, "kokoro-onnx runtime found but Kokoro class is unavailable."

        quant_norm = (quantization or "fp32").lower()
        if quant_norm == "fp16" or quant_norm == "16":
            model_filename = "kokoro-v1.0.fp16.onnx"
        elif quant_norm == "int8" or quant_norm == "8":
            model_filename = "kokoro-v1.0.int8.onnx"
        else:
            model_filename = "kokoro-v1.0.onnx"

        base_dir = os.path.join(get_user_data_path(), "tts", "kokoro_onnx")
        os.makedirs(base_dir, exist_ok=True)
        model_path = os.path.join(base_dir, model_filename)
        voices_path = os.path.join(base_dir, "voices-v1.0.bin")

        model_url = (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            f"model-files-v1.0/{model_filename}"
        )
        voices_url = (
            "https://github.com/thewh1teagle/kokoro-onnx/releases/download/"
            "model-files-v1.0/voices-v1.0.bin"
        )

        ok_model, model_msg = self._ensure_artifact(model_path, model_url, "kokoro-onnx model")
        if not ok_model:
            return False, model_msg
        ok_voices, voices_msg = self._ensure_artifact(voices_path, voices_url, "kokoro-onnx voices")
        if not ok_voices:
            return False, voices_msg

        providers, provider_note = self._resolve_onnx_providers(prefer_gpu=prefer_gpu)

        engine = None
        errors = []
        candidate_kwargs = []
        if providers:
            candidate_kwargs.append(
                {"model_path": model_path, "voices_path": voices_path, "providers": providers}
            )
        candidate_kwargs.append({"model_path": model_path, "voices_path": voices_path})

        for kwargs in candidate_kwargs:
            try:
                engine = kokoro_cls(**kwargs)
                break
            except Exception as exc:
                errors.append(str(exc))

        if engine is None:
            self._kokoro_onnx = None
            joined = "; ".join(errors[-2:]) if errors else "unknown error"
            return False, f"kokoro-onnx load failed ({joined})."

        try:
            self._kokoro_pipeline = None
            self._kokoro_onnx = engine
            self._kokoro_runtime = "onnx"
            self._kokoro_voice = self._resolve_kokoro_voice(voice_hint)
            self._onnx_providers_used = self._extract_onnx_providers(engine, fallback=providers)
            providers_text = ", ".join(self._onnx_providers_used) if self._onnx_providers_used else "default"
            msg = f"kokoro-onnx backend loaded ({providers_text}). {provider_note} {model_msg} {voices_msg}".strip()
            return True, msg
        except Exception as exc:
            self._kokoro_onnx = None
            self._onnx_providers_used = []
            return False, f"kokoro-onnx load failed ({exc})."

    @staticmethod
    def _resolve_onnx_providers(prefer_gpu: bool = True):
        providers = ["CPUExecutionProvider"]
        if not prefer_gpu:
            return providers, "TTS GPU disabled in settings."

        try:
            onnxruntime = importlib.import_module("onnxruntime")
            available = set(onnxruntime.get_available_providers() or [])
            if "CUDAExecutionProvider" in available:
                return ["CUDAExecutionProvider", "CPUExecutionProvider"], "Using CUDA provider for TTS."
            return providers, "CUDA provider unavailable, using CPU provider for TTS."
        except Exception as exc:
            return providers, f"Could not probe ONNX providers ({exc}); using CPU provider."

    @staticmethod
    def _extract_onnx_providers(engine, fallback=None):
        fallback = list(fallback or [])
        for attr in ("session", "sess", "_session"):
            session = getattr(engine, attr, None)
            if session is not None and hasattr(session, "get_providers"):
                try:
                    providers = session.get_providers() or []
                    return [str(p) for p in providers]
                except Exception:
                    break
        return [str(p) for p in fallback]

    @staticmethod
    def _ensure_artifact(path: str, url: str, label: str) -> Tuple[bool, str]:
        if os.path.exists(path) and os.path.getsize(path) > 0:
            return True, f"{label} ready."

        tmp_path = f"{path}.part"
        try:
            requests = importlib.import_module("requests")
            with requests.get(url, stream=True, timeout=60) as response:
                response.raise_for_status()
                with open(tmp_path, "wb") as handle:
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            handle.write(chunk)
            os.replace(tmp_path, path)
            return True, f"{label} downloaded."
        except Exception as exc:
            try:
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)
            except Exception:
                pass
            return False, f"{label} download failed ({exc})."

    @staticmethod
    def _load_sapi_backend() -> Tuple[bool, str]:
        try:
            comtypes = importlib.import_module("comtypes")
            comtypes_client = importlib.import_module("comtypes.client")
            initialized = False
            if hasattr(comtypes, "CoInitialize"):
                comtypes.CoInitialize()
                initialized = True
            try:
                # Probe object creation once so fallback status is definitive.
                _ = comtypes_client.CreateObject("SAPI.SpVoice")
            finally:
                if initialized and hasattr(comtypes, "CoUninitialize"):
                    comtypes.CoUninitialize()
            return True, "Windows SAPI backend loaded."
        except Exception as exc:
            return False, f"Windows SAPI unavailable ({exc})."

    @staticmethod
    def _resolve_kokoro_voice(voice_hint: str) -> str:
        hint = (voice_hint or "").strip().lower()
        if not hint:
            return "af_heart"

        # Accept direct voice IDs first.
        if "_" in hint:
            return hint

        aliases = {
            "english": "af_heart",
            "female": "af_heart",
            "woman": "af_heart",
            "male": "am_puck",
            "man": "am_puck",
            "british": "bf_emma",
            "brit": "bf_emma",
            "uk": "bf_emma",
        }
        for key, voice in aliases.items():
            if key in hint:
                return voice
        return "af_heart"

    def _resolve_voice_spec(self, base: str, blend: Optional[dict]) -> Union[str, np.ndarray]:
        """Resolve a base voice hint + optional blend dict into either a
        plain (alias-resolved) voice-id string, or a blended style tensor
        ready to hand straight to kokoro-onnx's `create(voice=...)`.

        Never raises: unknown blend voices are dropped (logged) and blending
        silently falls back to the base voice alone when the ONNX voices
        table isn't available (e.g. the native/SAPI backends don't support
        raw tensor voices).
        """
        base_voice = self._resolve_kokoro_voice(base)
        blend = blend or {}
        if not blend:
            return base_voice

        if self._kokoro_runtime != "onnx" or self._kokoro_onnx is None:
            logging.info(
                "Voice blending requested but only supported on the ONNX backend; using base voice %r.",
                base_voice,
            )
            return base_voice

        names = [base_voice]
        weights = [1.0]
        for name, weight in blend.items():
            resolved = self._resolve_kokoro_voice(name)
            if not self._onnx_voice_exists(resolved):
                logging.warning("Unknown blend voice %r (resolved %r); skipping.", name, resolved)
                continue
            try:
                w = float(weight)
            except (TypeError, ValueError):
                continue
            if w <= 0:
                continue
            names.append(resolved)
            weights.append(w)

        if len(names) < 2:
            return base_voice

        if not self._onnx_voice_exists(base_voice):
            logging.warning("Base voice %r not found for blending; using first available voice.", base_voice)
            return self._first_onnx_voice() or base_voice

        try:
            tensors = [self._kokoro_onnx.voices[name] for name in names]
            blended = voice_blend.blend_many(tensors, weights=weights)
        except Exception as exc:
            logging.warning("Voice blend failed (%s); using base voice %r.", exc, base_voice)
            return base_voice
        return blended

    def _speak_kokoro(
        self,
        text: str,
        speed: float,
        voice_hint: str,
        voice_spec: Optional[Union[str, np.ndarray]] = None,
        modulation: Optional[dict] = None,
    ):
        try:
            import sounddevice as sd
        except Exception as exc:
            raise RuntimeError(f"sounddevice unavailable for Kokoro playback ({exc}).")

        audio_tuple = self._generate_kokoro_audio(
            text, speed, voice_hint, voice_spec=voice_spec, modulation=modulation,
        )
        if audio_tuple is None:
            raise RuntimeError("Kokoro generated no audio frames.")
        merged, sample_rate = audio_tuple
        sd.stop()
        sd.play(merged, samplerate=sample_rate, blocking=True)

    def _onnx_voice_exists(self, voice: str) -> bool:
        voices = getattr(self._kokoro_onnx, "voices", None)
        if voices is None:
            return False
        if hasattr(voices, "files"):
            return voice in list(getattr(voices, "files"))
        if hasattr(voices, "keys"):
            try:
                return voice in voices.keys()
            except Exception:
                return False
        try:
            return voice in voices
        except Exception:
            return False

    def _first_onnx_voice(self) -> Optional[str]:
        voices = getattr(self._kokoro_onnx, "voices", None)
        if voices is None:
            return None
        if hasattr(voices, "files"):
            files = list(getattr(voices, "files"))
            return files[0] if files else None
        if hasattr(voices, "keys"):
            try:
                keys = list(voices.keys())
                return keys[0] if keys else None
            except Exception:
                return None
        return None

    def _extract_onnx_voice_names(self):
        voices = getattr(self._kokoro_onnx, "voices", None)
        if voices is None:
            return []
        if hasattr(voices, "files"):
            return [str(v).strip().lower() for v in list(getattr(voices, "files")) if str(v).strip()]
        if hasattr(voices, "keys"):
            try:
                return [str(v).strip().lower() for v in list(voices.keys()) if str(v).strip()]
            except Exception:
                return []
        return []

    @staticmethod
    def _sapi_rate_from_speed(speed: float) -> int:
        # 1.0x ~= 0, 1.5x ~= +4, 2.0x ~= +8
        value = int(round((float(speed) - 1.0) * 8.0))
        return max(-10, min(10, value))

    def _speak_sapi(self, text: str, speed: float, voice_hint: str):
        comtypes = importlib.import_module("comtypes")
        comtypes_client = importlib.import_module("comtypes.client")
        initialized = False
        if hasattr(comtypes, "CoInitialize"):
            comtypes.CoInitialize()
            initialized = True
        try:
            voice = comtypes_client.CreateObject("SAPI.SpVoice")
            voice.Rate = self._sapi_rate_from_speed(speed)

            hint = (voice_hint or "").strip().lower()
            if hint:
                try:
                    voices = voice.GetVoices()
                    for idx in range(int(voices.Count)):
                        token = voices.Item(idx)
                        desc = str(token.GetDescription() or "").lower()
                        if hint in desc:
                            voice.Voice = token
                            break
                except Exception:
                    pass

            voice.Speak(text, 0)
        finally:
            if initialized and hasattr(comtypes, "CoUninitialize"):
                comtypes.CoUninitialize()

    @staticmethod
    def _split_words_to_max_chars(text: str, max_chars: int):
        if not text:
            return []
        max_chars = max(32, int(max_chars))
        words = [token for token in text.split() if token]
        if not words:
            return []

        chunks = []
        current = words[0]
        for word in words[1:]:
            candidate = f"{current} {word}"
            if len(candidate) <= max_chars:
                current = candidate
                continue
            chunks.append(current)
            current = word
        if current:
            chunks.append(current)

        # Guard for single very long tokens without spaces.
        final_chunks = []
        for chunk in chunks:
            if len(chunk) <= max_chars:
                final_chunks.append(chunk)
                continue
            start = 0
            while start < len(chunk):
                final_chunks.append(chunk[start : start + max_chars])
                start += max_chars
        return final_chunks

    @classmethod
    def _split_text_for_tts(cls, text: str, max_chars: int = None):
        phrase = re.sub(r"\s+", " ", (text or "")).strip()
        if not phrase:
            return []

        safe_max = max(32, int(max_chars or cls.MAX_KOKORO_TEXT_CHARS))
        if len(phrase) <= safe_max:
            return [phrase]

        chunks = []
        current = ""

        def append_piece(piece: str):
            nonlocal current
            piece = piece.strip()
            if not piece:
                return
            if not current:
                if len(piece) <= safe_max:
                    current = piece
                    return
                for split_piece in cls._split_words_to_max_chars(piece, safe_max):
                    if split_piece:
                        chunks.append(split_piece)
                return

            merged = f"{current} {piece}"
            if len(merged) <= safe_max:
                current = merged
                return

            chunks.append(current)
            current = ""
            append_piece(piece)

        sentence_like = [part.strip() for part in re.split(r"(?<=[.!?])\s+", phrase) if part.strip()]
        if not sentence_like:
            sentence_like = [phrase]

        for sentence in sentence_like:
            if len(sentence) <= safe_max:
                append_piece(sentence)
                continue
            clauses = [part.strip() for part in re.split(r"(?<=[,;:])\s+", sentence) if part.strip()]
            if not clauses:
                clauses = [sentence]
            for clause in clauses:
                if len(clause) <= safe_max:
                    append_piece(clause)
                    continue
                for split_piece in cls._split_words_to_max_chars(clause, safe_max):
                    append_piece(split_piece)

        if current:
            chunks.append(current)
        return chunks or [phrase]

    def render_prepared_chunks(self, chunks: list, export_dir: str) -> list:
        """
        Render audio for each chunk and save to export_dir.
        chunks: [{"text": "...", "voice": "...", "speed": 0.95}, ...]
        Returns list of generated file paths.
        """
        import os
        import soundfile as sf
        
        os.makedirs(export_dir, exist_ok=True)
        saved_files = []
        
        for idx, chunk in enumerate(chunks):
            text = chunk.get("text", "")
            voice = chunk.get("voice", "af_heart")
            speed = float(chunk.get("speed", 0.95))
            
            if not text:
                continue
                
            try:
                audio_tuple = self._generate_kokoro_audio(text, speed, voice)
                if audio_tuple:
                    audio_data, sample_rate = audio_tuple
                    filename = f"chunk_{idx+1:04d}.wav"
                    filepath = os.path.join(export_dir, filename)
                    sf.write(filepath, audio_data, sample_rate)
                    saved_files.append(filepath)
            except Exception as exc:
                logging.error(f"Failed to render chunk {idx}: {exc}")
                
        return saved_files

    def _speak_kokoro_chunked(
        self,
        text: str,
        speed: float,
        voice_hint: str,
        blend: Optional[dict] = None,
        modulation: Optional[dict] = None,
    ):
        """Speak text with concurrent generation and playback to avoid pauses between chunks."""
        chunks = self._split_text_for_tts(text=text, max_chars=self.MAX_KOKORO_TEXT_CHARS)

        if not chunks:
            return

        # Resolve once (base + blend don't vary per chunk) and reuse for every chunk.
        voice_spec = self._resolve_voice_spec(voice_hint, blend)

        if len(chunks) == 1:
            # Single chunk - no need for concurrent processing
            self._speak_kokoro(
                text=chunks[0], speed=speed, voice_hint=voice_hint,
                voice_spec=voice_spec, modulation=modulation,
            )
            return

        logging.debug("Chunking TTS input into %d segments for Kokoro playback.", len(chunks))

        try:
            import sounddevice as sd
        except Exception as exc:
            raise RuntimeError(f"sounddevice unavailable for Kokoro playback ({exc}).")

        # Use a queue to hold pre-generated audio chunks
        audio_queue = queue.Queue(maxsize=3)  # Buffer up to 3 chunks ahead
        generation_done = threading.Event()
        generation_error = [None]  # Use list to allow mutation in nested function

        full_audio_buffer = []  # For caching


        def generate_audio_chunks():
            """Background thread that generates audio chunks ahead of playback."""
            try:
                for chunk_text in chunks:
                    # Allow direct/manual invocations of _speak_kokoro_chunked outside worker loop.
                    if self._worker is not None and not self._worker_running:
                        break
                    audio_data = self._generate_kokoro_audio(
                        chunk_text, speed, voice_hint, voice_spec=voice_spec, modulation=modulation,
                    )
                    if audio_data is not None:
                        audio_queue.put(audio_data, timeout=30)
            except Exception as e:
                generation_error[0] = e
                logging.error(f"TTS generation error: {e}")
            finally:
                generation_done.set()
        
        # Start generation thread
        gen_thread = threading.Thread(target=generate_audio_chunks, daemon=True)
        gen_thread.start()
        
        # Play audio as it becomes available
        first_chunk = True
        while True:
            try:
                # Wait for audio with timeout
                audio_data, sample_rate = audio_queue.get(timeout=0.1)
                
                if len(text) < 100:
                    full_audio_buffer.append(audio_data)
                
                if first_chunk:
                    sd.stop()
                    first_chunk = False
                
                # Play this chunk (blocking)
                sd.play(audio_data, samplerate=sample_rate, blocking=True)
                
            except queue.Empty:
                # Check if generation is done
                if generation_done.is_set():
                    # Drain any remaining items
                    while True:
                        try:
                            audio_data, sample_rate = audio_queue.get_nowait()
                            if len(text) < 100:
                                full_audio_buffer.append(audio_data)
                            sd.play(audio_data, samplerate=sample_rate, blocking=True)
                        except queue.Empty:
                            break
                    break
                # Otherwise, wait a bit more for generation
                continue
        
        gen_thread.join(timeout=1.0)
        
        # Cache the result if we captured everything and it was short enough
        if full_audio_buffer and len(text) < 100 and not generation_error[0]:
            try:
                final_audio = np.concatenate(full_audio_buffer)
                if len(self._audio_cache) >= self._cache_max_size:
                    self._audio_cache.popitem(last=False)
                # Store with the same key used in speak()
                cache_key = (text, speed, voice_hint, _blend_signature(blend), _modulation_signature(modulation))
                self._audio_cache[cache_key] = (final_audio, sample_rate)
                logging.debug("Cached audio for: %r", text)
            except Exception as e:
                logging.warning(f"Failed to cache audio: {e}")
        
        if generation_error[0]:
            raise generation_error[0]

    def _generate_kokoro_audio(
        self,
        text: str,
        speed: float,
        voice_hint: str,
        voice_spec: Optional[Union[str, np.ndarray]] = None,
        modulation: Optional[dict] = None,
    ):
        """Generate audio for a single chunk without playing it. Returns (audio_array, sample_rate) or None.

        `voice_spec`, if given, is either a resolved voice-id string or a
        blended style tensor (see `_resolve_voice_spec`) and takes priority
        over `voice_hint`. `modulation`, if given, is applied to the
        generated audio before it's returned (see voice_modulation.apply_modulation).
        Both default to None so existing callers (e.g. `render_prepared_chunks`)
        see identical behavior to before this parameter was added.
        """
        if self._kokoro_runtime == "native":
            if self._kokoro_pipeline is None:
                raise RuntimeError("Kokoro pipeline is not initialized.")

            if isinstance(voice_spec, np.ndarray):
                # Native backend doesn't accept raw tensor voices; fall back
                # to the (alias-resolved) base voice hint.
                voice = self._resolve_kokoro_voice(voice_hint)
            else:
                voice = voice_spec if voice_spec else self._resolve_kokoro_voice(voice_hint)
            generated = self._kokoro_pipeline(text, voice=voice, speed=max(0.5, min(3.0, float(speed))))

            audio_chunks = []
            for item in generated:
                audio = None
                if isinstance(item, tuple):
                    if len(item) >= 3:
                        audio = item[2]
                    elif len(item) > 0:
                        audio = item[-1]
                else:
                    audio = item
                if audio is None:
                    continue
                arr = np.asarray(audio, dtype=np.float32).flatten()
                if arr.size > 0:
                    audio_chunks.append(arr)

            if not audio_chunks:
                return None

            merged = np.concatenate(audio_chunks, axis=0)
            merged = voice_modulation.apply_modulation(merged, 24000, modulation)
            return (merged, 24000)

        if self._kokoro_runtime == "onnx":
            if self._kokoro_onnx is None:
                raise RuntimeError("kokoro-onnx engine is not initialized.")
            if isinstance(voice_spec, np.ndarray):
                voice = voice_spec
            else:
                voice = voice_spec if voice_spec else self._resolve_kokoro_voice(voice_hint)
                if not self._onnx_voice_exists(voice):
                    voice = self._first_onnx_voice() or "af_heart"
            audio, sample_rate = self._kokoro_onnx.create(
                text=text,
                voice=voice,
                speed=max(0.5, min(2.0, float(speed))),
                lang="en-us",
            )
            merged = np.asarray(audio, dtype=np.float32).flatten()
            if merged.size == 0:
                return None
            merged = voice_modulation.apply_modulation(merged, int(sample_rate), modulation)
            return (merged, int(sample_rate))

        raise RuntimeError("Kokoro backend is not initialized.")
