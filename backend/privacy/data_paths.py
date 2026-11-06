"""Wave 6 — the concrete filesystem location of every declared data category.

``data_categories`` says *what* each store is; this module says *where* it is.
Splitting them keeps the inventory readable and gives the wipe/verify machinery
in ``data_lifecycle`` one place to look up ground truth.

Three rules this module exists to enforce:

* **No side effects.** These are the callables the privacy *report* invokes, so
  asking "where does my data live?" must never create a directory. That is why
  nothing here calls ``utils.get_profiles_dir()`` (which mkdirs) — every path is
  derived from ``app_paths.resolve_base()`` directly.
* **Only paths that exist are returned.** The report shows what is really on
  disk; the wipe deletes what is really there; the agreement test compares the
  two. A phantom path in any of those three makes all three lie.
* **Lazy imports.** ``data_categories`` is imported by tests and routes that
  must not drag in FastAPI or torch, so anything heavier than stdlib is
  imported inside the function that needs it.

Two stores do not live under the unified root, and pretending otherwise would
be the exact failure this wave closes:

* ``user_profile.json`` resolves its own root (see ``user_profile_manager``),
  so on a Linux install whose base is XDG it sits in a *second* directory.
* The three Electron-owned overlay/sidecar files live under Electron's
  ``app.getPath('userData')``, which is deliberately NOT the unified root.
  ``electron_user_data_candidates()`` mirrors Electron's own resolution rule —
  see the warning on that function before changing it.

Measured on the packaged app (F1): that folder is
``%APPDATA%\\betterfingers-electron``. electron-builder's ``productName`` names
the installer and the exe but never reaches ``app.asar/package.json``, so the
runtime app name is the package ``name``. Chromium keeps its own files there
(Local Storage, Session Storage, caches, ...) — see ``ELECTRON_RUNTIME_NAMES``
for how they are declared, and ``app/src/main/rendererState.js`` for who clears
them. Do not assume "productName BetterFingers" means the two folders coincide.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

from backend.config import app_paths


def base() -> Path:
    """The one unified data root (never created as a side effect)."""
    return Path(app_paths.resolve_base())


def _existing(*candidates: Path) -> list[Path]:
    """Only the candidates that are really on disk, de-duplicated in order.

    Returning a path that does not exist would make ``size()`` lie by counting
    nothing while the report shows a location, and would make ``verify()``
    trivially pass. Everything downstream assumes this filter.
    """
    out: list[Path] = []
    for candidate in candidates:
        try:
            if candidate.exists() and candidate not in out:
                out.append(candidate)
        except OSError:
            continue
    return out


# --- Electron-owned roots ----------------------------------------------------

# The Electron main process writes the overlay position/appearance and the
# sidecar raw log under app.getPath('userData'), which is
# app.getPath('appData')/<app name> — a DIFFERENT directory from the unified
# data root on every platform.
#
# Electron names the folder after the top-level "productName" or "name" in the
# package.json INSIDE app.asar. That is "betterfingers-electron" for an
# unpackaged run AND for the packaged app: electron-builder's own
# build.productName names the installer and the exe but is not copied into the
# asar's package.json (measured on alpha.3 and alpha.4 builds; an earlier version
# of this comment claimed the opposite). "BetterFingers" is still treated as a
# candidate, because adding a top-level productName is the obvious "fix" for the
# lowercase folder and would make it the real one. Both are candidate roots and
# _existing() decides, so a factory reset sweeps whichever directory is there.
_ELECTRON_APP_NAMES = ("BetterFingers", "betterfingers-electron")


def electron_user_data_candidates() -> list[Path]:
    """Every directory Electron's ``app.getPath('userData')`` could resolve to.

    Mirrors Electron's own rule per platform. This is a mirror, exactly like
    ``app/src/main/userDataRoot.js`` mirrors ``app_paths.resolve_base()``: if
    Electron's resolution changes, this must change with it or the privacy
    report and the factory reset will both quietly miss these files.

    Returns candidate directories whether or not they exist — callers join a
    filename on and run the result through ``_existing()``.

    Which of the two names is real: ``betterfingers-electron``, for the packaged
    app and an unpackaged run alike (measured: the packaged asar's package.json
    carries ``name`` and no ``productName``). ``BetterFingers`` stays a candidate
    because it is what Electron would pick if a ``productName`` were ever added,
    the case where userData and the unified root become the same folder.
    """
    home = Path.home()
    if sys.platform == "win32":
        appdata = os.environ.get("APPDATA")
        roots = [Path(appdata)] if appdata else [home / "AppData" / "Roaming"]
    elif sys.platform == "darwin":
        roots = [home / "Library" / "Application Support"]
    else:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        roots = [Path(xdg)] if xdg else [home / ".config"]
    return [root / name for root in roots for name in _ELECTRON_APP_NAMES]


def _electron_files(filename: str) -> list[Path]:
    return _existing(*(root / filename for root in electron_user_data_candidates()))


# --- Chromium's own files inside Electron's userData -------------------------------

# Exact top-level names Chromium (not BetterFingers) creates in Electron's
# userData folder; the ones a real packaged run produced (app/artifacts/f1
# evidence) plus the other storage/cache siblings of the same engine. They are
# DECLARED rather than swept:
#
# * Chromium holds most of them open while the app runs, so the backend can
#   neither delete them nor verify their absence. The Electron main process
#   clears what it can through its session API and removes the files at the next
#   launch (``app/src/main/rendererState.js``); the uninstaller removes them
#   (``app/build/installer.nsh``).
# * On the packaged app they live in a different folder from the unified root, so
#   the residual sweep never sees them. If Electron's userData ever IS the data
#   root (add ``productName`` to package.json, or ``app.setPath``), they would
#   all show up as "files no category claims" and a factory reset could never
#   verify — measured: HTTP 500, 44 residual files. ``data_lifecycle.unmapped_files``
#   therefore skips exactly these names, and only when the root it is sweeping is
#   an Electron userData folder.
#
# The list is Chromium-only on purpose (a test fails if a BetterFingers store
# name joins it, and the source scan in test_privacy_inventory_completeness
# still fails on any undeclared name the sources write).
ELECTRON_RESET_PENDING_MARKER = ".factory-reset-pending"

# Renderer-written state: where the legacy consent flag and the first-run flags
# live. "Settings" data for the uninstaller.
ELECTRON_STATE_NAMES = (
    "Local Storage", "Session Storage", "IndexedDB", "WebStorage", "SharedStorage",
    "SharedStorage-wal", "SharedStorage-shm", "SharedStorage-journal",
    "Service Worker", "File System", "databases", "blob_storage",
)
# Caches and engine bookkeeping. "Logs and temporary data" for the uninstaller.
ELECTRON_CACHE_AND_PROFILE_NAMES = (
    "Network", "Cache", "Code Cache", "GPUCache", "DawnGraphiteCache", "DawnWebGPUCache",
    "Shared Dictionary", "Preferences", "Local State", "DIPS", "DIPS-wal", "DIPS-shm",
    "DIPS-journal", "InterestGroups", "InterestGroups-wal", "InterestGroups-shm",
    "InterestGroups-journal", "PrivateAggregation", "PrivateAggregation-wal",
    "PrivateAggregation-shm", "PrivateAggregation-journal",
    "lockfile", "DevToolsActivePort", ELECTRON_RESET_PENDING_MARKER,
)
ELECTRON_RUNTIME_NAMES = frozenset(ELECTRON_STATE_NAMES + ELECTRON_CACHE_AND_PROFILE_NAMES)


def _same_place(a: Path, b: Path) -> bool:
    try:
        return os.path.normcase(os.path.realpath(a)) == os.path.normcase(os.path.realpath(b))
    except OSError:
        return False


def is_electron_user_data(root: Path) -> bool:
    """True when ``root`` is one of the folders Electron's ``userData`` can be,
    i.e. when Chromium's files may legitimately sit directly inside it."""
    return any(_same_place(Path(root), candidate) for candidate in electron_user_data_candidates())


def is_electron_runtime_name(name: str) -> bool:
    """Case-insensitive on every platform: the names are Chromium's, and the
    filesystem that matters most (NTFS) does not distinguish case."""
    lowered = name.lower()
    return any(lowered == known.lower() for known in ELECTRON_RUNTIME_NAMES)


def electron_runtime_in(root: Path) -> list[str]:
    """Top-level Chromium-owned names present directly inside ``root`` (only
    meaningful when ``root`` is an Electron userData folder)."""
    try:
        return sorted(entry.name for entry in Path(root).iterdir()
                      if is_electron_runtime_name(entry.name))
    except OSError:
        return []


# --- Migration debris --------------------------------------------------------

# The name after ``<store>.`` for a collision-renamed quarantine:
# ``f"{path}.{int(time.time())}.corrupt"``.
_TIMESTAMPED_QUARANTINE = re.compile(r"[0-9]+\.corrupt")


def _with_migration_siblings(*candidates: Path) -> list[Path]:
    """A store's own file plus the siblings ``store_migration`` leaves beside it.

    Every store that loads through ``load_versioned_store`` can produce two
    kinds of sibling, and both are byte-for-byte copies of the store's previous
    contents (plus one store-specific copy, ``.migrated``, below):

    * ``<path>.bak-v<N>`` — written *before* each migration step, so a v1 store
      that migrates to v2 leaves a complete v1 copy on disk.
    * ``<path>.migrated`` — ``DraftStore.load_history`` renames the legacy
      ``draft_history.json`` to this once its rows are in history.db, so it is
      the full pre-SQLite draft text. Matched by exact name only.
    * a quarantined file that would not parse. The shapes the code really
      writes are ``<path>.corrupt`` and, when that name is already taken,
      ``<path>.<unix-ts>.corrupt`` (``store_migration``, ``dictionary`` and
      ``macros`` all do this). ``<path>.corrupt-<anything>`` is also declared:
      Wave 6 documented that spelling, no current code writes it, and a
      quarantine copy under any such name is still a copy of the store.

    Wave 6 found these undeclared. For ``persona_learning.json`` that meant a
    verbatim copy of the user's dictated examples sat next to a store the
    privacy screen described, invisible to the report and untouched by every
    wipe mode — and it was created by the very act of opening the store after
    an upgrade. A backup of user text is user text; it is declared with the
    store it came from, reported with it, and deleted with it.

    Wave 6 missed the ``<unix-ts>.corrupt`` spelling (it matched only names
    that *start with* ``corrupt``), so the second quarantine of any store sat
    beside it undeclared. The match for it is deliberately exact — digits, then
    ``.corrupt``, nothing else — so only the name the code writes is claimed.

    Globbed rather than enumerated because the quarantine name carries a
    timestamp and a store can accumulate one backup per version step.
    """
    out: list[Path] = list(candidates)
    for candidate in candidates:
        parent = candidate.parent
        try:
            if not parent.is_dir():
                continue
            for sibling in parent.glob(f"{candidate.name}.*"):
                name = sibling.name[len(candidate.name) + 1:]
                if (name.startswith("bak-v") or name.startswith("corrupt")
                        or name == "migrated" or _TIMESTAMPED_QUARANTINE.fullmatch(name)):
                    out.append(sibling)
        except OSError:
            continue
    return _existing(*out)


# --- Conversation data -------------------------------------------------------


def raw_recordings() -> list[Path]:
    return _existing(base() / "recordings")


def drafts() -> list[Path]:
    return _with_migration_siblings(base() / "draft_history.json")


def history_db() -> list[Path]:
    # SQLite's sidecars hold committed pages and are as readable as the DB
    # itself; wiping history.db while leaving history.db-wal behind would leave
    # recoverable transcription text on disk.
    root = base()
    return _existing(root / "history.db", root / "history.db-wal",
                     root / "history.db-shm", root / "history.db-journal")


def temp_audio() -> list[Path]:
    root = base()
    # <root>/cache is AppPaths.cache, reserved: nothing in the backend writes there.
    # When Electron's userData IS the data root, a folder of that name (NTFS ignores
    # case) is Chromium's HTTP cache, which Chromium recreates the moment it is
    # cleared. It is Electron's to clear (rendererState.js), not a temp-audio store
    # to verify, or "check what's left" would fail on a folder the browser engine
    # just rebuilt.
    candidates = [root / "tmp"]
    if not is_electron_user_data(root):
        candidates.append(root / "cache")
    return _existing(*candidates)


# --- Personal data -----------------------------------------------------------


def cloned_voices() -> list[Path]:
    return _existing(base() / "voices")


def persona_drafts() -> list[Path]:
    """``persona_drafts.json`` (``backend/services/persona_drafts.py``): the
    unconfirmed persona edits, kept apart from the confirmed ones. They hold
    the persona text the user is still writing, and the store loads through
    ``load_versioned_store``, so it can leave the same ``.bak-v<N>`` /
    ``.corrupt`` copies as any other store. Declared with the personas
    category (see ``personas``), not as a category of its own."""
    return _with_migration_siblings(base() / "persona_drafts.json")


def personas() -> list[Path]:
    # A draft is a persona the user has not saved yet, so the Personas category
    # (personal tier, in the export) owns both files: "clear personal data"
    # that kept the drafts would leave the same text behind that it just
    # removed from personas.yaml. D2 of the alpha.4 QA pass.
    return _existing(*_with_migration_siblings(base() / "personas.yaml"),
                     *persona_drafts())


def dictionary() -> list[Path]:
    return _with_migration_siblings(base() / "dictionary.json")


def macros() -> list[Path]:
    return _with_migration_siblings(base() / "macros.json")


def contacts() -> list[Path]:
    return _with_migration_siblings(base() / "contacts.json")


def persona_learning() -> list[Path]:
    return _with_migration_siblings(base() / "persona_learning.json")


def user_profile() -> list[Path]:
    """``user_profile.json`` — resolved by ``user_profile_manager``, not by
    ``app_paths``, so it can sit outside the unified root. Reproduced here
    rather than imported because importing that module instantiates a global
    manager and reads the file; a path lookup must not do that."""
    appdata = os.getenv("APPDATA") or os.path.expanduser("~")
    return _existing(Path(appdata) / "BetterFingers" / "user_profile.json")


def wake_models() -> list[Path]:
    return _existing(base() / "wake_models")


def audio_privacy_journal() -> list[Path]:
    from backend.platform.audio_privacy import journal
    return _existing(Path(journal.default_journal_path()))


def mcp_config() -> list[Path]:
    return _with_migration_siblings(base() / "mcp_servers.json")


def mcp_trust() -> list[Path]:
    """``mcp_trust.json``: which MCP servers the owner trusted on this machine (round 3,
    item 4). Written by ``backend.dev.mcp_client.trust``."""
    return _with_migration_siblings(base() / "mcp_trust.json")


def graph_data() -> list[Path]:
    return _with_migration_siblings(base() / "graph.json")


def debug_log() -> list[Path]:
    return _existing(base() / "debug.log")


def sidecar_raw_log() -> list[Path]:
    return _electron_files("sidecar_backend_raw.log")


def app_profiles() -> list[Path]:
    return _with_migration_siblings(base() / "app_profiles.json")


def launcher_workflows() -> list[Path]:
    return _with_migration_siblings(base() / "launcher_workflows.json")


def application_registry() -> list[Path]:
    return _with_migration_siblings(base() / "application_registry.json")


def controller_bindings() -> list[Path]:
    # backend.stores.controller_bindings.STORE_FILENAME, resolved against
    # utils.get_user_data_path(). Named here rather than imported because
    # importing the store module is heavier than a path lookup should be.
    return _with_migration_siblings(base() / "controller_bindings.json")


def stream_deck_config() -> list[Path]:
    return _with_migration_siblings(base() / "stream_deck_config.json")


# --- Settings / configuration ------------------------------------------------


def voice_presets() -> list[Path]:
    return _with_migration_siblings(base() / "voice_presets.json")


def profiles() -> list[Path]:
    # config.yaml is the pre-profiles settings file; utils still reads it as a
    # migration source, so a factory reset that left it behind would restore
    # the user's old settings on next launch and not be a reset at all.
    root = base()
    return _existing(root / "profiles", root / "config.yaml")


def app_state() -> list[Path]:
    root = base()
    # utils.load_app_state reads app_state.yaml through load_versioned_store, so
    # a corrupt or newer-schema file is quarantined beside it. That copy is the
    # same launch count and last profile, and an undeclared sibling is exactly
    # what stops a factory reset from verifying.
    return _existing(*_with_migration_siblings(root / "app_state.yaml"),
                     root / ".first_run_complete")


def overlay_position() -> list[Path]:
    return _electron_files("overlay-position.json")


def overlay_appearance() -> list[Path]:
    return _electron_files("overlay-appearance.json")


def onboarding_consent() -> list[Path]:
    """The Electron onboarding/consent record. Unlike the overlay files this
    one deliberately lives under the *unified* root (see
    ``app/src/main/onboardingStore.js``) precisely so Python's factory reset
    can clear it."""
    return _existing(base() / "onboarding.json")


MODEL_VERIFY_CACHE_NAME = ".verify_cache.json"


def model_runtime_metadata() -> list[Path]:
    """The model verification cache (``model_manager._VERIFY_CACHE_NAME``).

    It lives *inside* the models directory but is not a model: it is derived
    metadata (hashes keyed by file signature) that a factory reset removes,
    while the multi-gigabyte model blobs alongside it are opt-in only. The
    agreement test resolves the overlap by matching exact files before
    directories.
    """
    return _existing(base() / "models" / MODEL_VERIFY_CACHE_NAME)


def downloaded_models() -> list[Path]:
    """Everything the app downloads for itself, none of it the user's own data:
    ``models/`` (speech and language models, llama-server, the cloned-voice
    runtime), ``tts/`` (the Kokoro ONNX model and voice pack,
    ``tts_engine.kokoro_onnx_dir()``) and ``runtimes/`` (the optional GPU
    runtime pack ``stt/cuda_runtime.py`` looks for; nothing downloads one yet).

    One category on purpose. The Kokoro "voices" are a downloaded model, not
    the user's cloned voices (``voices/``): filing them under a personal tier
    would let "clear personal data" delete 350 MB the user never asked to lose,
    and filing them nowhere is what made a factory reset fail on D2. They share
    the models' lifecycle: kept by every wipe, removed only by the explicit
    "also delete downloaded models" choice (and, on uninstall, by the
    "Downloaded models and runtimes" box)."""
    root = base()
    return _existing(root / "models", root / "tts", root / "runtimes")
