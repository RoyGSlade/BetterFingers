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

Pure stdlib; unit-tested in ``tests/test_app_paths.py``.
"""

import logging
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

import platform_paths

APP_NAME = "BetterFingers"


def _legacy_home_base():
    """The original ``utils.get_user_data_path`` location."""
    appdata = os.environ.get("APPDATA")
    return Path(appdata) / APP_NAME if appdata else Path.home() / APP_NAME


def _platform_base():
    """XDG data (Linux) / Application Support (macOS) / AppData (Windows)."""
    return platform_paths.get_app_data_dir()


def _has_contents(path):
    try:
        return path.exists() and any(path.iterdir())
    except OSError:
        return False


def resolve_base():
    """The one data root, in priority order:

    1. ``BETTERFINGERS_DATA_DIR`` (explicit override),
    2. ``%APPDATA%/BetterFingers`` when ``APPDATA`` is set — the Windows
       convention, and how callers/tests pin the location explicitly,
    3. an existing legacy ``~/BetterFingers`` that already holds data (don't
       move an existing install out from under itself),
    4. the platform-correct default (XDG on Linux) for a fresh install.
    """
    override = os.getenv("BETTERFINGERS_DATA_DIR")
    if override:
        return Path(os.path.expanduser(override))
    if os.environ.get("APPDATA"):
        return _legacy_home_base()
    legacy = _legacy_home_base()
    if _has_contents(legacy):
        return legacy
    return _platform_base()


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
    """Every data root — current and legacy — for the privacy screen."""
    base = resolve_base()
    out = [{"name": "Current data directory", "path": str(base), "current": True,
            "exists": base.exists()}]
    for legacy in _known_legacy_roots(base):
        out.append({"name": "Legacy data directory", "path": str(legacy),
                    "current": False, "exists": legacy.exists()})
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
