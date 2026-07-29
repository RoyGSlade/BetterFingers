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
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import app_paths


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
# The app name is genuinely ambiguous between builds: Electron uses the
# top-level "productName" or "name" from app/package.json, which is
# "betterfingers-electron" for an unpackaged dev run, while electron-builder
# writes "BetterFingers" into the packaged app's package.json. Guessing one
# would silently miss the other, so both are treated as candidate roots and
# _existing() decides. That is honest in a way a guess is not: a factory reset
# sweeps whichever directory is actually there.
_ELECTRON_APP_NAMES = ("BetterFingers", "betterfingers-electron")


def electron_user_data_candidates() -> list[Path]:
    """Every directory Electron's ``app.getPath('userData')`` could resolve to.

    Mirrors Electron's own rule per platform. This is a mirror, exactly like
    ``app/src/main/userDataRoot.js`` mirrors ``app_paths.resolve_base()``: if
    Electron's resolution changes, this must change with it or the privacy
    report and the factory reset will both quietly miss these files.

    Returns candidate directories whether or not they exist — callers join a
    filename on and run the result through ``_existing()``.
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


# --- Migration debris --------------------------------------------------------


def _with_migration_siblings(*candidates: Path) -> list[Path]:
    """A store's own file plus the siblings ``store_migration`` leaves beside it.

    Every store that loads through ``load_versioned_store`` can produce two
    kinds of sibling, and both are byte-for-byte copies of the store's previous
    contents:

    * ``<path>.bak-v<N>`` — written *before* each migration step, so a v1 store
      that migrates to v2 leaves a complete v1 copy on disk.
    * ``<path>.corrupt`` / ``<path>.corrupt-<timestamp>`` — a quarantined file
      that would not parse.

    Wave 6 found these undeclared. For ``persona_learning.json`` that meant a
    verbatim copy of the user's dictated examples sat next to a store the
    privacy screen described, invisible to the report and untouched by every
    wipe mode — and it was created by the very act of opening the store after
    an upgrade. A backup of user text is user text; it is declared with the
    store it came from, reported with it, and deleted with it.

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
                if name.startswith("bak-v") or name.startswith("corrupt"):
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
    return _existing(root / "tmp", root / "cache")


# --- Personal data -----------------------------------------------------------


def cloned_voices() -> list[Path]:
    return _existing(base() / "voices")


def personas() -> list[Path]:
    return _with_migration_siblings(base() / "personas.yaml")


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
    return _existing(root / "app_state.yaml", root / ".first_run_complete")


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
    return _existing(base() / "models")
