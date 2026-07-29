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
import sys
import tempfile

import pytest

os.environ.setdefault("BETTERFINGERS_LAZY_STARTUP", "1")

# --- Smoke suite definition (release-packaging gate) -------------------------
# `build-installer.yml` runs `pytest -m smoke` as a fast, hardware-free
# critical-path gate before packaging. Rather than scatter @pytest.mark.smoke
# across dozens of files, the smoke set is curated HERE, in one auditable place:
# every test in the files below is marked smoke at collection time. These cover
# the release-critical invariants that must never silently break — privacy
# (redaction, wipe), config/upgrade discipline (migrations), supply-chain
# download safety, hardware tiering / accelerator fallback, and the wake-phrase
# trainer. All run in a few seconds with no models or GPU. To add a file to the
# gate, add its basename here; keep it fast and hardware-free.
SMOKE_FILES = frozenset({
    "test_log_redaction.py",
    "test_privacy_wipe_verified.py",
    "test_store_migration.py",
    "test_profile_migration.py",
    "test_supply_chain_existing_verify.py",
    "test_download_verification.py",
    "test_hardware_tier.py",
    "test_gpu_detection.py",
    "test_wake_trainer.py",
    "test_model_manager_status.py",
    "test_setup_venv.py",
})


def pytest_collection_modifyitems(config, items):
    """Auto-apply the ``smoke`` marker to every test in :data:`SMOKE_FILES`.

    Centralizes the smoke-suite definition so ``pytest -m smoke`` (the
    release-packaging gate in build-installer.yml) always collects a real,
    non-empty set — previously it collected zero tests and exited 5, failing
    the Windows installer job on every run.
    """
    smoke = pytest.mark.smoke
    for item in items:
        if os.path.basename(str(item.fspath)) in SMOKE_FILES:
            item.add_marker(smoke)

# Model verification (supply-chain gate, §11) rejects any GGUF that isn't the
# exact pinned size + digest. Tests use tiny fixture files, so opt them into the
# tiny-model allowance here; production never sets this flag and always verifies.
os.environ.setdefault("BETTERFINGERS_ALLOW_TINY_MODELS", "1")

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

# NOT pinned here: BETTERFINGERS_DATA_DIR. It was tried (2026-07-28) as a
# belt-and-braces session-wide pin, on the reasoning that it is the FIRST rule
# app_paths.resolve_base() checks and would therefore hold even if a later
# branch were wrong. Measured result: 43 failures across 12 files.
#
# The reason is structural, not incidental. ~40 test modules isolate themselves
# by re-pointing APPDATA at their own per-test temp dir. A session-wide
# BETTERFINGERS_DATA_DIR out-ranks every one of them, so they all collapse onto
# ONE shared root and leak state into each other — test_voice_presets alone went
# from 28 passing to 8 failing with "3 != 1" preset counts, because every test
# in the file was writing into the same file. A pin that silently destroys
# per-test isolation buys nothing: it protects the real root by breaking the
# thing that was already protecting it.
#
# The protection that does work is _forbid_real_data_root() below, which checks
# the ANSWER rather than trusting any environment variable, and so cannot be
# out-ranked or forgotten. Tests wanting an explicit root use the
# `isolated_data_root` fixture, which sets both vars together.

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


def _temp_roots():
    """Every prefix a test is allowed to resolve a data root under."""
    roots = {os.path.realpath(tempfile.gettempdir()), os.path.realpath(_isolated)}
    # Honour the platform temp vars too — CI and sandboxes re-point these, and
    # a guard that fired on a legitimately-isolated root would be worse than no
    # guard at all, because the first fix would be to delete it.
    for var in ("TMPDIR", "TEMP", "TMP", "PYTEST_DEBUG_TEMPROOT"):
        value = os.environ.get(var)
        if value:
            roots.add(os.path.realpath(value))
    return roots


def _is_under_temp(path):
    resolved = os.path.realpath(str(path))
    return any(resolved == root or resolved.startswith(root + os.sep)
               for root in _temp_roots())


@pytest.fixture(autouse=True)
def _forbid_real_data_root(monkeypatch):
    """Fail loudly if a test ever resolves a data root outside a temp dir.

    The suite contains genuinely destructive coverage — privacy wipe, factory
    reset, store migration — and those tests delete whatever
    ``app_paths.resolve_base()`` hands them. Isolation is currently spread
    across four environment variables set at import time, ~40 test modules that
    re-point APPDATA at their own temp dirs, and every branch of the resolver
    agreeing to honour them. Any one of those going wrong points a recursive
    delete at a real install, and the failure is silent: the test still passes,
    because it deleted exactly what it was asked to delete.

    So this does not trust the environment. It wraps the resolver itself and
    checks the ANSWER, which is the only thing that actually matters. A test
    that reaches a real root now fails with a message naming the path, instead
    of quietly destroying it.
    """
    import app_paths

    real_resolve = app_paths.resolve_base

    def guarded_resolve_base():
        base = real_resolve()
        if not _is_under_temp(base):
            raise RuntimeError(
                "REFUSING to run a test against a real data root.\n"
                f"  app_paths.resolve_base() returned: {base}\n"
                f"  allowed temp prefixes:            {sorted(_temp_roots())}\n"
                "  BETTERFINGERS_DATA_DIR="
                f"{os.environ.get('BETTERFINGERS_DATA_DIR')!r}\n"
                f"  APPDATA={os.environ.get('APPDATA')!r}\n"
                "This suite deletes what it resolves (privacy wipe / factory "
                "reset / migration). If this test needs its own root, point "
                "BETTERFINGERS_DATA_DIR at a tmp_path — do not remove this guard."
            )
        return base

    monkeypatch.setattr(app_paths, "resolve_base", guarded_resolve_base)
    yield


@pytest.fixture
def isolated_data_root(tmp_path, monkeypatch):
    """Point every data-root lookup at this test's own tmp_path.

    Sets BETTERFINGERS_DATA_DIR (the highest-priority rule) alongside APPDATA,
    so a test cannot end up half-redirected — which is what happens when a test
    sets only APPDATA while conftest's session pin is still in force.
    """
    root = tmp_path / "BetterFingers"
    root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("BETTERFINGERS_DATA_DIR", str(root))
    monkeypatch.setenv("APPDATA", str(tmp_path))
    return root


@pytest.fixture(autouse=True)
def _reset_server_model_singletons():
    """Reset server.py's module-level model singletons around every test.

    `server.transcriber` and `server.tts_engine` are process-global caches
    (server.ensure_transcriber_initialized / get_tts_engine populate them
    lazily). A test that installs one — directly, or by running the pipeline
    with server.Transcriber patched to a dummy — leaves it set, so a later
    test that patches server.Transcriber but assumes a fresh global silently
    runs against the leaked instance instead of its own dummy. That is an
    order-dependent failure (e.g. test_token_concepts passed alone but failed
    in the full suite). Several test files already reset these by hand in
    setUp/tearDown; centralizing it here makes every test hermetic regardless
    of collection order. Only touches the module if it is already imported, so
    tests that never load `server` are unaffected.
    """
    def _reset():
        server_mod = sys.modules.get("server")
        if server_mod is None:
            return
        for _name in ("transcriber", "tts_engine"):
            if hasattr(server_mod, _name):
                setattr(server_mod, _name, None)

    _reset()
    yield
    _reset()


@pytest.fixture(autouse=True)
def _no_warm_start_model_loads(request, monkeypatch):
    """Neutralize startup model warm-loading for every test except the suite
    that tests it.

    TestClient startup warm-loads any model the active profile marks
    keep-loaded. Many test files re-point APPDATA at their own pristine temp
    dirs (bypassing the residency-off profile this conftest seeds), whose
    default profile keeps LLM/STT loaded — so app startup inside those tests
    began REAL multi-GB model downloads. On Windows the download thread's open
    .part handle then broke TemporaryDirectory cleanup with WinError 32
    (POSIX allows deleting open files, which is why only Windows CI failed:
    test_server_drafts, then test_server_foundry_routes, then
    test_server_persona_routes — one per run, whack-a-mole). No-opping
    warm-start at the source fixes every current and future fixture at once.

    test_server_lazy_startup exercises warm-start on purpose (with its own
    mocks of the inner loaders), so it is excluded.
    """
    if request.module.__name__ == "test_server_lazy_startup":
        yield
        return
    server_mod = sys.modules.get("server")
    if server_mod is not None and hasattr(server_mod, "warm_start_resident_models"):
        monkeypatch.setattr(
            server_mod, "warm_start_resident_models", lambda settings=None: {}
        )
    yield
