"""Shared test configuration.

Default to lazy server startup so importing/starting `server` in tests does
not load the real Whisper/LLM/TTS model stack. Without this, the server-route
suites (test_server_drafts.py peaked at ~5 GB RSS; the full suite at ~11 GB)
load real models despite mocking their engines, which OOM-killed the machine
when two sessions ran pytest concurrently (2026-07-09).

setdefault only: tests that explicitly exercise eager vs lazy startup
(test_server_lazy_startup.py) patch the variable themselves and are
unaffected. Set BETTERFINGERS_LAZY_STARTUP="" in the environment to force
eager startup for the whole suite if ever needed.
"""
import os
import tempfile

os.environ.setdefault("BETTERFINGERS_LAZY_STARTUP", "1")

# Isolate the app data/config dirs from the developer's real profile.
# server.startup_event() warm-loads any model the profile marks
# model_keep_*_loaded EVEN under lazy startup, so tests that spin up a
# TestClient against the real user profile pull multi-GB Whisper/LLM weights
# into every server-test module (OOM #3, 2026-07-09). A pristine temp profile
# has no keep-loaded models and default settings, which also fixes tests that
# assert defaults (e.g. selected_model_size == "base.en") against whatever
# the developer's real config happens to contain.
_isolated = tempfile.mkdtemp(prefix="betterfingers-tests-")
for _var in ("XDG_DATA_HOME", "XDG_CONFIG_HOME", "APPDATA"):
    os.environ[_var] = _isolated

# keep-loaded defaults to True for LLM/STT (server.warm_start_resident_models),
# so even a pristine profile warm-loads real multi-GB models on every server
# TestClient startup. Seed the isolated profile with residency off; tests that
# exercise warmup behavior patch load_profile explicitly.
_profiles = os.path.join(_isolated, "BetterFingers", "profiles")
os.makedirs(_profiles, exist_ok=True)
with open(os.path.join(_profiles, "Default.yaml"), "w") as _fh:
    _fh.write(
        "model_keep_llm_loaded: false\n"
        "model_keep_stt_loaded: false\n"
        "model_keep_tts_loaded: false\n"
    )
