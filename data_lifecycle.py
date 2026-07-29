"""Wave 6 — the machinery that acts on the data inventory.

``data_registry`` defines the vocabulary, ``data_categories`` declares the
stores, ``data_paths`` locates them; this module is the only place that
measures, deletes, and verifies them. Everything a wipe mode does is derived
from the registry, so the privacy report and the filesystem cannot disagree by
construction rather than by a reviewer noticing.

Design notes worth keeping:

* **Verify re-reads the disk.** A ``WipeResult`` says what we *asked* for; a
  ``VerificationResult`` says what is *there*. ``ok`` upstream is computed from
  the second, never the first, because "we called unlink" is not evidence.
* **Deletion is confined to known roots.** ``_assert_within_known_roots``
  refuses any path that is not under the unified data root, a legacy root, or
  an Electron user-data root. A bug in a ``paths`` callable should raise, not
  recursively delete someone's home directory.
* **Failures are per-category and reported.** One store that will not delete
  must not abort the sweep or, worse, be swallowed — the caller gets every
  result and decides.
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path
from typing import Callable, Iterable

import app_paths
import data_paths
from data_registry import (
    DataCategory,
    VerificationResult,
    WipeResult,
    WIPE_MODES,
    WIPE_MODE_FACTORY_RESET,
)


# --- Safety ------------------------------------------------------------------


def known_roots() -> list[Path]:
    """Every directory this module is permitted to delete inside of."""
    current = Path(app_paths.resolve_base())
    roots = [current]
    roots.extend(Path(r) for r in app_paths._known_legacy_roots(current))
    roots.extend(data_paths.electron_user_data_candidates())
    # user_profile.json's self-resolved root (see data_paths.user_profile).
    appdata = os.getenv("APPDATA") or os.path.expanduser("~")
    roots.append(Path(appdata) / "BetterFingers")
    seen: list[Path] = []
    for root in roots:
        if root not in seen:
            seen.append(root)
    return seen


class UnsafePathError(RuntimeError):
    """A category's paths() returned something outside every known data root."""


def _assert_within_known_roots(path: Path) -> None:
    resolved = path.resolve()
    for root in known_roots():
        try:
            resolved.relative_to(root.resolve())
            return
        except (ValueError, OSError):
            continue
    raise UnsafePathError(
        f"refusing to touch {path} — not under any known data root "
        f"({[str(r) for r in known_roots()]})"
    )


# --- Measurement -------------------------------------------------------------


def path_size(path: Path) -> int:
    """Bytes on disk for a file or directory tree. Unreadable entries count as
    zero rather than raising — a privacy report must render even when one
    subdirectory has hostile permissions."""
    try:
        if path.is_file() or path.is_symlink():
            return path.lstat().st_size
        if not path.is_dir():
            return 0
    except OSError:
        return 0
    total = 0
    for dirpath, _dirnames, filenames in os.walk(path, onerror=lambda _e: None):
        for name in filenames:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                continue
    return total


def make_size(paths_fn: Callable[[], list[Path]]) -> Callable[[], int]:
    def _size() -> int:
        return sum(path_size(p) for p in paths_fn())
    return _size


# --- Deletion ----------------------------------------------------------------


def _remove(path: Path) -> None:
    if path.is_dir() and not path.is_symlink():
        # No ignore_errors: a suppressed failure must not be reported as
        # success. verify() re-reads the disk regardless.
        shutil.rmtree(path)
    else:
        path.unlink()


def make_wipe(paths_fn: Callable[[], list[Path]],
              *, after: Callable[[], None] | None = None) -> Callable[[], WipeResult]:
    """A wipe callable that removes every path the category owns.

    ``after`` runs only once deletion succeeded — used by stores that must be
    left in a valid empty state rather than simply absent (the history DB is
    recreated so the app keeps working after a wipe).
    """
    def _wipe() -> WipeResult:
        removed: list[str] = []
        errors: list[str] = []
        for path in paths_fn():
            try:
                _assert_within_known_roots(path)
                _remove(path)
                removed.append(str(path))
            except UnsafePathError:
                raise
            except OSError as exc:
                logging.warning("data_lifecycle: could not remove %s: %s", path, exc)
                errors.append(f"{path}: {exc}")
        if not errors and after is not None:
            try:
                after()
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                logging.warning("data_lifecycle: post-wipe step failed: %s", exc)
                errors.append(f"post-wipe step: {exc}")
        if errors:
            return WipeResult(ok=False, removed=removed, error="remove_failed",
                              message="; ".join(errors))
        return WipeResult(ok=True, removed=removed,
                          message=f"removed {len(removed)} path(s)")
    return _wipe


def make_verify(paths_fn: Callable[[], list[Path]],
                *, allow: Callable[[Path], bool] | None = None
                ) -> Callable[[], VerificationResult]:
    """A verify callable that re-reads the disk and reports what survived.

    ``allow`` whitelists paths that are *expected* to exist after a wipe (the
    recreated-empty history DB), so "present" and "not wiped" stay distinct.
    """
    def _verify() -> VerificationResult:
        remaining = [str(p) for p in paths_fn() if not (allow and allow(p))]
        if remaining:
            return VerificationResult(
                ok=False, remaining=remaining,
                detail=f"{len(remaining)} path(s) still present")
        return VerificationResult(ok=True, detail="no paths remain")
    return _verify


def never_wiped_verify(paths_fn: Callable[[], list[Path]]
                       ) -> Callable[[], VerificationResult]:
    """Verification for opt-in categories no standard wipe removes.

    ``downloaded_models`` surviving a wipe is correct behaviour, so its verify
    reports presence as ``ok`` — the alternative (reusing make_verify) would
    make every successful wipe report a false failure.
    """
    def _verify() -> VerificationResult:
        present = [str(p) for p in paths_fn()]
        return VerificationResult(
            ok=True, remaining=present,
            detail="retained by design (opt-in deletion only)")
    return _verify


# --- Mode execution ----------------------------------------------------------


def execute_mode(registry, mode: str, *, skip: Iterable[str] = ()) -> dict:
    """Wipe every category the mode includes, then verify each by re-reading.

    Returns ``{ok, mode, categories: {id: {...}}, failed: [...]}``. ``ok`` is
    the AND of every *verification*, not of the wipe calls.

    ``skip`` exists for the one honest exception: categories a caller has
    already handled through a specialised path (the history DB has to be
    recreated by ``history_store`` so its schema is valid, not merely deleted).
    Skipped categories are still verified.
    """
    if mode not in WIPE_MODES:
        raise ValueError(f"Unknown wipe mode: {mode!r}")
    skip = set(skip)
    results: dict[str, dict] = {}
    failed: list[str] = []
    for category in registry.in_mode(mode):
        entry: dict = {"label": category.label, "owner": category.owner,
                       "skipped": category.id in skip}
        if category.id not in skip:
            wipe_result = category.wipe()
            entry["wiped"] = wipe_result.ok
            entry["removed"] = wipe_result.removed
            # Store-specific facts (see WipeResult.detail). Kept under its own
            # key so it cannot collide with the verification's "detail" string.
            if wipe_result.detail:
                entry["wipe_detail"] = dict(wipe_result.detail)
            if wipe_result.error:
                entry["error"] = wipe_result.error
                entry["message"] = wipe_result.message
        verification = category.verify()
        entry["verified"] = verification.ok
        entry["remaining"] = verification.remaining
        entry["detail"] = verification.detail
        if not verification.ok:
            failed.append(category.id)
        results[category.id] = entry
    return {"ok": not failed, "mode": mode, "categories": results, "failed": failed}


def preview_mode(registry, mode: str) -> dict:
    """What a mode WOULD remove, without removing anything.

    The confirmation dialog for a destructive action has to be able to name the
    stores it is about to delete, and it has to name them from the same source
    the deletion reads. A hand-written list in the UI is how "wipe my data"
    ended up deleting two stores its own confirmation text never mentioned.
    """
    if mode not in WIPE_MODES:
        raise ValueError(f"Unknown wipe mode: {mode!r}")
    categories = []
    total = 0
    for category in registry.in_mode(mode):
        paths = category.paths()
        size = sum(path_size(p) for p in paths)
        total += size
        categories.append({
            "id": category.id,
            "label": category.label,
            "owner": category.owner,
            "sensitivity": category.sensitivity,
            "may_contain_user_text": category.may_contain_user_text,
            "present": bool(paths),
            "bytes": size,
            "paths": [str(p) for p in paths],
        })
    return {"mode": mode, "categories": categories, "bytes": total,
            "present_count": sum(1 for c in categories if c["present"])}


# --- Factory reset -----------------------------------------------------------


def factory_reset(registry, *, include_models: bool = False) -> dict:
    """The Wave 1 backlog item: something that actually PERFORMS the mode
    ``data_registry`` has declared since 2.1.

    A factory reset is not a bigger privacy wipe — it is the claim that this
    install is indistinguishable from a fresh one. Three things follow, and
    each is a line of code below rather than a line of documentation:

    * **It must cross the Python/Electron boundary.** The onboarding consent
      record, the overlay position/appearance, the sidecar raw log, and the
      confirmed-application registry are written by the Electron main process,
      not by Python. They are reachable here only because every one of them is
      a declared category with a real ``paths`` callable, three of them under
      Electron's own ``userData`` root rather than ours. A reset that swept
      only the Python root would leave the consent record behind and the next
      launch would skip onboarding — visibly not a fresh install.
    * **It must verify, not assert.** ``ok`` is the AND of the per-category
      *verifications*, which re-read the disk. "We called unlink" is not
      evidence, and the Settings surface shows this result verbatim.
    * **It must not silently delete the models.** Multi-gigabyte downloads are
      opt-in on the way out exactly as they were on the way in; the caller
      passes ``include_models`` only when the user ticked that box.

    Returns the ``execute_mode`` shape plus ``residual_files`` — anything left
    under the data root that no category claimed. A reset that finishes with a
    non-empty residual list has not produced a fresh install, whatever the
    per-category verifications say, so ``ok`` accounts for it.
    """
    result = execute_mode(registry, WIPE_MODE_FACTORY_RESET)

    # Remove the empty envelopes the mode legitimately leaves behind.
    #
    # Several stores wipe through their own API rather than by unlinking, which
    # is correct for a privacy wipe: ContactStore.clear_all() leaves a valid
    # `{"contacts": []}` file so the app keeps working, and the history DB is
    # recreated with an empty schema for the same reason. Both verify as
    # cleared, and they are — of user data.
    #
    # A factory reset makes a stronger claim: that this install is
    # indistinguishable from a fresh one. A fresh install has no contacts.json
    # and no history.db at all, so the envelopes go too. They are recreated on
    # first use exactly as they were originally. Anything that fails to delete
    # here is reported rather than ignored, and the verification below is what
    # decides the outcome either way.
    envelopes: list[str] = []
    for category in registry.in_mode(WIPE_MODE_FACTORY_RESET):
        for path in category.paths():
            try:
                _assert_within_known_roots(path)
                _remove(path)
                envelopes.append(str(path))
            except UnsafePathError:
                raise
            except OSError as exc:
                logging.warning("factory_reset: could not remove envelope %s: %s",
                                path, exc)
    result["envelopes_removed"] = envelopes

    # Re-verify after the envelope sweep: the per-category results above were
    # computed before it, and this function's `ok` must describe the disk as it
    # stands at the end, not midway.
    for category in registry.in_mode(WIPE_MODE_FACTORY_RESET):
        verification = category.verify()
        entry = result["categories"].setdefault(category.id, {})
        entry["verified"] = verification.ok
        entry["remaining"] = verification.remaining
        entry["detail"] = verification.detail
    result["failed"] = [cid for cid, e in result["categories"].items()
                        if not e.get("verified")]
    result["ok"] = not result["failed"]

    models = None
    if include_models:
        category = registry.get("downloaded_models")
        wipe_result = make_wipe(category.paths)()
        remaining = [str(p) for p in category.paths()]
        models = {"requested": True, "wiped": wipe_result.ok,
                  "removed": wipe_result.removed, "remaining": remaining,
                  "message": wipe_result.message}
        if remaining:
            result["failed"].append("downloaded_models")
        result["categories"]["downloaded_models"] = {
            "label": category.label, "owner": category.owner, "skipped": False,
            "wiped": wipe_result.ok, "removed": wipe_result.removed,
            "verified": not remaining, "remaining": remaining,
            "detail": "opt-in deletion requested",
        }
    else:
        models = {"requested": False, "wiped": False, "removed": [],
                  "remaining": [str(p) for p in registry.get("downloaded_models").paths()],
                  "message": "downloaded models retained (not requested)"}

    # The models directory legitimately survives a reset that did not ask for
    # it, so it is excluded from the residual sweep rather than counted as a
    # store nobody declared.
    residual = [f for f in unmapped_files(registry)]
    if not include_models:
        model_roots = [str(p) for p in registry.get("downloaded_models").paths()]
        residual = [f for f in residual
                    if not any(f.startswith(root) for root in model_roots)]

    result["residual_files"] = residual[:50]
    result["residual_count"] = len(residual)
    result["models"] = models
    result["ok"] = bool(result["ok"] and not residual)
    return result


def verify_factory_reset(registry) -> dict:
    """Prove a reset landed, by re-reading the disk only — no deletion.

    Separate from ``factory_reset`` on purpose: the Settings surface offers
    "check again" after a failed reset, and the user re-running a *verification*
    must never be able to trigger a second *deletion*.
    """
    result = verify_mode(registry, WIPE_MODE_FACTORY_RESET)
    residual = unmapped_files(registry)
    model_roots = [str(p) for p in registry.get("downloaded_models").paths()]
    residual = [f for f in residual
                if not any(f.startswith(root) for root in model_roots)]
    result["residual_files"] = residual[:50]
    result["residual_count"] = len(residual)
    result["ok"] = bool(result["ok"] and not residual)
    return result


def verify_mode(registry, mode: str) -> dict:
    """Verification only — no deletion. Used to re-check a wipe after the fact
    and by the Settings surface to prove a factory reset really landed."""
    if mode not in WIPE_MODES:
        raise ValueError(f"Unknown wipe mode: {mode!r}")
    results, failed = {}, []
    for category in registry.in_mode(mode):
        verification = category.verify()
        results[category.id] = {"ok": verification.ok,
                                "remaining": verification.remaining,
                                "detail": verification.detail}
        if not verification.ok:
            failed.append(category.id)
    return {"ok": not failed, "mode": mode, "categories": results, "failed": failed}


# --- Reporting / agreement ---------------------------------------------------


def declared_paths(registry) -> dict[str, list[Path]]:
    """Every path every category currently owns, keyed by category id."""
    return {c.id: c.paths() for c in registry.all()}


def report_rows(registry) -> list[dict]:
    """The privacy screen's data table, generated from the registry.

    Hand-maintaining this list beside the inventory is how a store ends up
    declared but unlisted, so the screen reads the same source the wipe does.
    """
    rows = []
    for category in registry.all():
        if not category.included_in_report:
            continue
        paths = category.paths()
        rows.append({
            "id": category.id,
            "name": category.label,
            "owner": category.owner,
            "sensitivity": category.sensitivity,
            "retention": category.retention,
            "may_contain_user_text": category.may_contain_user_text,
            "included_in_export": category.included_in_export,
            "wipe_modes": sorted(category.wipe_modes),
            "paths": [str(p) for p in paths],
            "path": str(paths[0]) if paths else "",
            "present": bool(paths),
            "bytes": sum(path_size(p) for p in paths),
        })
    return rows


def unmapped_files(registry, root: Path | None = None) -> list[str]:
    """Files under the data root that no declared category accounts for.

    This is the anti-lie-by-omission check: the privacy report enumerates
    categories, so anything on disk outside that enumeration is invisible to
    the user. Exact-file declarations win over directory declarations, which is
    how the model verify-cache (its own category) and the model blobs (an
    opt-in category) can share a directory without either shadowing the other.
    """
    root = Path(root) if root is not None else Path(app_paths.resolve_base())
    if not root.is_dir():
        return []

    declared_files: set[Path] = set()
    declared_dirs: list[Path] = []
    for paths in declared_paths(registry).values():
        for path in paths:
            try:
                resolved = path.resolve()
            except OSError:
                continue
            if path.is_dir() and not path.is_symlink():
                declared_dirs.append(resolved)
            else:
                declared_files.add(resolved)

    unmapped: list[str] = []
    for dirpath, dirnames, filenames in os.walk(root, onerror=lambda _e: None):
        here = Path(dirpath).resolve()
        # Do not descend into a directory a category already owns wholesale.
        if any(here == d or _is_under(here, d) for d in declared_dirs):
            dirnames[:] = []
            continue
        for name in filenames:
            candidate = (here / name)
            if candidate in declared_files:
                continue
            if _is_transient(name):
                continue
            unmapped.append(str(candidate))
    return sorted(unmapped)


def _is_under(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _is_transient(name: str) -> bool:
    """In-flight artifacts of atomic writes, not stores.

    Every store here writes via write-temp-then-rename, so a crash can leave a
    ``.<name>.tmp-<pid>-<ts>`` or ``<name>.tmp`` sibling. Those are debris from
    a declared store's own write, not an undeclared store, and they are removed
    with it. Anything else must be declared.
    """
    return name.endswith(".tmp") or ".tmp-" in name or name.startswith(".privacy-journal-")


def category_for_path(registry, path: Path) -> DataCategory | None:
    """Which declared category owns ``path`` (exact file first, then directory)."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return None
    dir_match = None
    for category in registry.all():
        for declared in category.paths():
            try:
                declared_resolved = declared.resolve()
            except OSError:
                continue
            if declared_resolved == resolved:
                return category
            if declared.is_dir() and _is_under(resolved, declared_resolved):
                dir_match = dir_match or category
    return dir_match
