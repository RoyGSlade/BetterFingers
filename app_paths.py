"""One resolved home for all on-disk state (P2 unified paths).

Two path systems were in use: ``utils.get_user_data_path()`` put profiles,
logs, drafts, the history DB, recordings, and models under ``~/BetterFingers``
(``%APPDATA%\\BetterFingers`` on Windows), while ``platform_paths`` put cloned
voices and the graph under the XDG/Application-Support location. So a user's
data was split across two roots depending on which module wrote it — bad for
backup, migration, privacy reporting, and wipe.

``AppPaths`` is the single source of truth: one base directory with every
subpath derived from it. The base is resolved once (env override > an existing
legacy dir with data > the platform-correct default), so existing installs keep
their current location while fresh Linux installs get XDG. ``migrate_legacy_data``
consolidates any split/legacy root into the current base, idempotently.

**What "a legacy dir with data" means.** This used to be "the directory is not
empty", and that was wrong in a way that silently broke whole installs. The app
writes ``debug.log`` into whatever root it resolves, so a single boot was enough
to make an otherwise-empty ``~/BetterFingers`` look occupied; from then on the
resolver elected that root forever, every read returned defaults because no
profile/personas/voices were there, and every write landed somewhere the real
data was not. An unrelated leftover subdirectory (even a root-owned, unreadable
one) had the same effect. So "has contents" now means "holds recognisable
BetterFingers data" — one of the stores in ``_MARKER_FILES``/``_MARKER_DIRS``,
which deliberately exclude the bootstrap files the app writes about itself.
``resolve_base_report()`` exposes the whole decision so a user can see which
root won and on the strength of which files.

Pure stdlib; unit-tested in ``tests/test_app_paths.py``.
"""

import logging
import os
import shutil
from dataclasses import dataclass, field
from pathlib import Path

import platform_paths

APP_NAME = "BetterFingers"

# Files whose presence proves this directory is a BetterFingers root that got
# far enough to hold real state. Mirrors the store inventory in ``data_paths``.
#
# What is NOT here matters more than what is. ``debug.log``,
# ``.first_run_complete`` and ``app_state.yaml`` are all written by the app
# about itself on any boot, at whichever root was resolved. Counting them lets
# a root nominate itself: boot once, a log appears, and the log is then read
# back as evidence that the data lives there. Same for ``tmp/``, ``cache/`` and
# ``exports/`` — scratch and output, never the user's data.
_MARKER_FILES = (
    "personas.yaml",
    "dictionary.json",
    "macros.json",
    "contacts.json",
    "persona_learning.json",
    "graph.json",
    "mcp_servers.json",
    "app_profiles.json",
    "launcher_workflows.json",
    "application_registry.json",
    "controller_bindings.json",
    "stream_deck_config.json",
    "voice_presets.json",
    "history.db",
    "draft_history.json",
    "user_profile.json",
    # Pre-profiles single-file settings. Never created by current code — it is
    # only ever read, as a migration source — so its presence is unambiguous
    # evidence of a genuine older install.
    "config.yaml",
)

# Directories that count only when they actually contain something. An empty
# ``voices/`` is a directory the app made, not a voice the user cloned.
_MARKER_DIRS = (
    "profiles",
    "voices",
    "recordings",
    "models",
    "wake_models",
)


def _legacy_home_base():
    """The original ``utils.get_user_data_path`` location."""
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / APP_NAME if appdata else Path.home() / APP_NAME


def _platform_base():
    """XDG data (Linux) / Application Support (macOS) / AppData (Windows)."""
    return platform_paths.get_app_data_dir()


def data_markers(path):
    """The recognisable BetterFingers data found directly under ``path``.

    Empty list means "nothing here identifies this as a populated install",
    which is the only question the resolver asks. Never raises: an unreadable
    directory contributes no markers rather than taking startup down, and — the
    point of the fix — cannot elect a root by merely existing.
    """
    found = []
    try:
        if not path.is_dir():
            return found
    except OSError:
        return found
    for name in _MARKER_FILES:
        try:
            if (path / name).is_file():
                found.append(name)
        except OSError:
            continue
    for name in _MARKER_DIRS:
        entry = path / name
        try:
            if entry.is_dir() and any(entry.iterdir()):
                found.append(name + "/")
        except OSError:
            continue
    return found


@dataclass(frozen=True)
class BaseResolution:
    """Why the data root is where it is — see ``resolve_base_report``."""

    base: Path
    reason: str
    detail: str
    candidates: list = field(default_factory=list)


def resolve_base_report():
    """Resolve the data root and explain the choice.

    Priority order:

    1. ``BETTERFINGERS_DATA_DIR`` (explicit override),
    2. ``%APPDATA%/BetterFingers`` when ``APPDATA`` is set — the Windows
       convention, and how callers/tests pin the location explicitly,
    3. an existing legacy ``~/BetterFingers`` that holds recognisable
       BetterFingers data (don't move an existing install out from under
       itself),
    4. the platform-correct default (XDG on Linux) for a fresh install.

    Returns a ``BaseResolution``. ``reason`` is a stable code
    (``env_override`` / ``appdata`` / ``legacy_install`` / ``platform_default``)
    and ``candidates`` lists every root considered with the markers found in
    it, so the privacy screen and a support report can show a user which
    directory won and on the strength of which files.
    """
    override = os.getenv("BETTERFINGERS_DATA_DIR")
    if override:
        base = Path(os.path.expanduser(override))
        return BaseResolution(
            base=base, reason="env_override",
            detail="BETTERFINGERS_DATA_DIR is set, which overrides every other rule.",
            candidates=[_candidate(base, chosen=True)],
        )

    appdata = os.environ.get("APPDATA")
    if appdata:
        # P0 (2026-07-28): this branch used to `return _legacy_home_base()` --
        # the user's real ~/BetterFingers -- while ignoring the APPDATA value
        # entirely. Setting APPDATA is exactly how tests and callers pin the
        # root somewhere safe, so the one env var whose whole purpose was
        # isolation silently redirected every caller ONTO the real install.
        # tests/conftest.py set it to a temp dir believing it isolated the
        # suite; instead the suite resolved to the developer's own data root,
        # and the Wave 6 wipe/factory-reset work deleted what it found there.
        # Honour the value that was set.
        base = Path(os.path.expanduser(appdata)) / APP_NAME
        return BaseResolution(
            base=base, reason="appdata",
            detail="APPDATA is set, so the Windows application-data location is used.",
            candidates=[_candidate(base, chosen=True)],
        )

    legacy = _legacy_home_base()
    platform = _platform_base()
    legacy_markers = data_markers(legacy)
    if legacy_markers:
        return BaseResolution(
            base=legacy, reason="legacy_install",
            detail=("An earlier install at {} still holds your data ({}), so it is "
                    "used instead of the newer default location."
                    .format(legacy, ", ".join(legacy_markers[:6]))),
            candidates=[_candidate(legacy, markers=legacy_markers, chosen=True),
                        _candidate(platform)],
        )

    # Legacy holds nothing recognisable, so the platform root wins. Say which
    # of the three ways that happened: it is the difference between "your data
    # is where I am looking" and "I could not find your data anywhere", and a
    # user chasing empty settings needs to be told which.
    platform_markers = data_markers(platform)
    if platform_markers:
        detail = ("Your data is at the standard location {} ({})."
                  .format(platform, ", ".join(platform_markers[:6])))
    elif legacy.exists():
        detail = ("{} exists but holds no BetterFingers data — only files the app "
                  "writes about itself, or unrelated leftovers — so the standard "
                  "location {} is used. If your data really is in that directory, "
                  "set BETTERFINGERS_DATA_DIR to it.".format(legacy, platform))
    else:
        detail = "Fresh install: the standard location {} is used.".format(platform)
    return BaseResolution(
        base=platform, reason="platform_default", detail=detail,
        candidates=[_candidate(platform, markers=platform_markers, chosen=True),
                    _candidate(legacy, markers=legacy_markers)],
    )


def _candidate(path, markers=None, chosen=False):
    if markers is None:
        markers = data_markers(path)
    try:
        exists = path.exists()
    except OSError:
        exists = False
    return {"path": str(path), "exists": exists, "markers": markers,
            "chosen": chosen}


_logged_resolution = None


def resolve_base():
    """The one data root. See ``resolve_base_report`` for the full decision."""
    resolution = resolve_base_report()
    # Log the decision the first time it is made, and again only if it ever
    # changes: a user whose settings all read as defaults needs the elected
    # root in debug.log to have any chance of recognising this class of fault.
    global _logged_resolution
    signature = (str(resolution.base), resolution.reason)
    if signature != _logged_resolution:
        _logged_resolution = signature
        logging.info("app_paths: data root %s (%s) — %s",
                     resolution.base, resolution.reason, resolution.detail)
    return resolution.base


def _known_legacy_roots(current):
    """Other roots the app has historically written to, excluding the current
    one — the candidates a migration or wipe must also consider."""
    roots = []
    for candidate in (_legacy_home_base(), _platform_base()):
        if candidate != current and candidate not in roots:
            roots.append(candidate)
    return roots


@dataclass(frozen=True)
class AppPaths:
    data: Path
    config: Path
    cache: Path
    logs: Path
    recordings: Path
    models: Path
    voices: Path
    history_db: Path
    drafts_json: Path
    temp: Path
    exports: Path


def get_app_paths():
    """Build the immutable path set from the resolved base."""
    base = resolve_base()
    return AppPaths(
        data=base,
        config=base,
        cache=base / "cache",
        logs=base,
        recordings=base / "recordings",
        models=base / "models",
        voices=base / "voices",
        history_db=base / "history.db",
        drafts_json=base / "draft_history.json",
        temp=base / "tmp",
        exports=base / "exports",
    )


def describe_locations():
    """Every data root — current and legacy — for the privacy screen.

    Each entry carries the markers found in it, and the current one carries the
    reason it was chosen, so "my settings are all empty" is diagnosable from the
    screen the user can actually see rather than only from a log.
    """
    resolution = resolve_base_report()
    base = resolution.base
    out = [{"name": "Current data directory", "path": str(base), "current": True,
            "exists": base.exists(), "reason": resolution.reason,
            "detail": resolution.detail, "markers": data_markers(base)}]
    for legacy in _known_legacy_roots(base):
        out.append({"name": "Legacy data directory", "path": str(legacy),
                    "current": False, "exists": legacy.exists(),
                    "markers": data_markers(legacy)})
    return out


def migrate_legacy_data():
    """Consolidate any legacy/split root into the current base.

    Idempotent: an entry already present in the target is left where it is
    (never clobbered), so re-running is a no-op. Same-filesystem moves are
    instant renames. Returns {target, moved:[...], skipped:[...]}.
    """
    base = resolve_base()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        logging.warning("app_paths: could not create base %s: %s", base, exc)
        return {"target": str(base), "moved": [], "skipped": [], "error": str(exc)}

    moved, skipped = [], []
    for legacy in _known_legacy_roots(base):
        if not legacy.exists():
            continue
        try:
            entries = list(legacy.iterdir())
        except OSError:
            continue
        for entry in entries:
            target = base / entry.name
            if target.exists():
                skipped.append(entry.name)
                continue
            try:
                shutil.move(str(entry), str(target))
                moved.append(entry.name)
            except OSError as exc:
                logging.warning("app_paths: could not move %s -> %s: %s", entry, target, exc)
                skipped.append(entry.name)
        # Remove the now-empty legacy dir (best effort).
        try:
            if legacy.exists() and not any(legacy.iterdir()):
                legacy.rmdir()
        except OSError:
            pass
    return {"target": str(base), "moved": moved, "skipped": skipped}
