"""The one build version source (D-0008).

Before Wave 11 the release identity was invented in three places that did not
agree: ``app/package.json`` said ``0.1.0``, ``server.py`` hard-coded
``"0.1.0"`` twice (``/runtime/version`` and the support report), and the
Signal Desk preview page printed a marketing ``v1.2.0`` that was never any
build. D-0008 requires exactly one source feeding the Electron package, the
Python backend, the renderer display, the support report and the release
manifest naming.

That source is the repo-root ``VERSION`` file. Everything else reads it:

* Python (``/runtime/version``, the support report) imports this module;
* ``app/package.json``'s ``version`` field is kept equal to it, enforced by
  ``tests/test_version_source.py`` and ``app/tests/versionSource.test.mjs``
  so drift fails the suite instead of shipping;
* Electron reads that package version via ``app.getVersion()`` -> ``config.js``
  ``APP_VERSION`` -> the ``app:get-version`` IPC -> the renderer's
  ``.sd-nav__version-num`` cell, and electron-builder uses the same field for
  artifact filenames.

``app/package.json`` is a second *copy*, not a second source: npm requires a
literal there, so it cannot import this file. The tests make the copy
non-authoritative -- change ``VERSION`` and the suite tells you exactly which
copy is stale.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

__all__ = ["APP_VERSION", "BACKEND_VERSION", "RELEASE_TAG", "VERSION_FILE", "read_version"]

_FALLBACK_RELATIVE = "VERSION"


def _candidate_roots() -> list[Path]:
    """Where VERSION can live, dev checkout and frozen sidecar alike."""
    roots = [Path(__file__).resolve().parent]
    # PyInstaller --onefile unpacks bundled data under sys._MEIPASS; the
    # build adds VERSION to the bundle root (app/scripts/build-backend.js).
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.insert(0, Path(meipass))
    if getattr(sys, "frozen", False):
        roots.append(Path(sys.executable).resolve().parent)
    return roots


def read_version() -> str:
    """The release version string, e.g. ``1.1.0-alpha.1``.

    Raises rather than guessing: a build that cannot state its own version
    must fail loudly at import, not report a plausible wrong number into a
    support report a user is about to paste into an issue.
    """
    override = os.environ.get("BETTERFINGERS_VERSION_FILE")
    candidates = [Path(override)] if override else []
    candidates += [root / _FALLBACK_RELATIVE for root in _candidate_roots()]

    for candidate in candidates:
        try:
            text = candidate.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if text:
            return text

    searched = ", ".join(str(candidate) for candidate in candidates)
    raise RuntimeError(f"VERSION file not found or empty (searched: {searched})")


#: The release version, e.g. ``1.1.0-alpha.1``.
APP_VERSION = read_version()

#: The backend reports the SAME number as the app. They were allowed to
#: diverge before Wave 11 and never actually did anything useful apart; the
#: /runtime/version contract keeps `schema_version` for the compatibility
#: check that genuinely needs its own cadence (see app/src/main/config.js).
BACKEND_VERSION = APP_VERSION

#: Tag / manifest form, e.g. ``v1.1.0-alpha.1``.
RELEASE_TAG = f"v{APP_VERSION}"

#: Where the value came from, for support reports and tests.
VERSION_FILE = _FALLBACK_RELATIVE
