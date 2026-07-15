"""Shared config-store persistence discipline (DESIGN §9.5, Tier-3 M4 B1).

Generalizes the load/migrate/quarantine/atomic-write pattern already proven
separately in dictionary.py, macros.py, and utils.py's save_profile — one
reusable module instead of N near-identical copies, so every store gets the
same guarantees:

- A corrupt/unparseable file is quarantined (`<path>.corrupt`, timestamped on
  collision — same convention dictionary.py/macros.py already use), never
  silently dropped or left to crash the caller.
- Migrations are a versioned ladder (schema_version N -> N+1, ...), backed up
  once per version step before that step runs, and idempotent by
  construction (each step advances the loop's local version counter exactly
  once; a file already at current_version takes the no-op "loaded" branch).
- A file from a NEWER schema_version than this build understands is NEVER
  touched destructively — read-only in-memory defaults instead, with a
  visible warning the caller surfaces (startup log / `/health` degraded
  note). This is the one deliberately asymmetric case: forward migration
  writes to disk (via backups + the caller's own save), a refused downgrade
  never does.
- Writes are atomic: staged to a pid+uuid-suffixed temp file in the same
  directory, promoted with `os.replace()`, cleaned up on any failure. Same
  guarantee save_profile() and recordings.py already rely on, factored out.

Pure stdlib; unit-tested in tests/test_store_migration.py.
"""

import json
import logging
import os
import time
import uuid

_CORRUPT_SUFFIX = ".corrupt"


def _quarantine_path(path):
    """``<path>.corrupt``, or ``<path>.<ts>.corrupt`` if that's already
    taken — same collision-timestamp convention as dictionary.py/macros.py."""
    candidate = f"{path}{_CORRUPT_SUFFIX}"
    if os.path.exists(candidate):
        candidate = f"{path}.{int(time.time())}{_CORRUPT_SUFFIX}"
    return candidate


def quarantine_corrupt_file(path):
    """Move an unparseable/invalid store file aside instead of losing it or
    crashing — best-effort, failures here are non-fatal (mirrors
    dictionary.py's ``_quarantine_corrupt_file``). Returns the quarantine
    path, or "" if the move failed or the source didn't exist."""
    if not os.path.exists(path):
        return ""
    dest = _quarantine_path(path)
    try:
        os.replace(path, dest)
        return dest
    except OSError as exc:
        logging.error("Failed to quarantine %s: %s", path, exc)
        return ""


def write_atomic(path, text, encoding="utf-8"):
    """Write ``text`` to ``path`` atomically: stage to a pid+uuid-suffixed
    temp file in the same directory (never left behind — cleaned up in a
    finally on any failure), then ``os.replace()`` it into place. Factors out
    the pattern save_profile()/recordings.py already use by hand so every
    store gets it instead of another direct-open-and-write site."""
    directory = os.path.dirname(os.path.abspath(path)) or "."
    os.makedirs(directory, exist_ok=True)
    tmp_path = os.path.join(
        directory, f".{os.path.basename(path)}.{os.getpid()}-{uuid.uuid4().hex[:8]}.tmp"
    )
    try:
        with open(tmp_path, "w", encoding=encoding) as fh:
            fh.write(text)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def backup_before_migration(path, from_version):
    """``<path>.bak-v<from_version>``, written once per version step, before
    that step's migration runs — so a bad migration can always be undone by
    hand. Best-effort; a backup failure logs and lets migration continue
    (matches save_profile's existing "log and continue" backup posture)."""
    if not os.path.exists(path):
        return ""
    backup_path = f"{path}.bak-v{from_version}"
    try:
        with open(path, "rb") as src, open(backup_path, "wb") as dst:
            dst.write(src.read())
        return backup_path
    except OSError as exc:
        logging.warning("Failed to back up %s before v%s migration: %s", path, from_version, exc)
        return ""


def load_versioned_store(path, current_version, migrations, *, default_factory, parse=None, backup=True):
    """Load a versioned on-disk store with migrate/quarantine/downgrade discipline.

    Args:
      path: file path.
      current_version: the schema version THIS BUILD understands (an int).
      migrations: ``{from_version(int): fn(data: dict) -> dict}``. Applied in
        order starting from the file's own ``schema_version`` (default 1 if
        absent) up to ``current_version``. Each fn receives/returns the raw
        parsed dict — this helper manages the ``schema_version`` key itself,
        migration functions don't need to touch it.
      default_factory: zero-arg callable returning a fresh default dict, used
        when the file doesn't exist, is corrupt, or is a refused downgrade.
      parse: callable(text: str) -> dict. Defaults to ``json.loads``; pass
        ``yaml.safe_load`` for YAML-backed stores.
      backup: write a ``.bak-v<from>`` before each migration step (default True).

    Returns ``(data, report)``. ``report`` keys: ``ok`` (bool — False only
    for a refused downgrade, the one case needing a visible degraded-state
    warning), ``action`` ("new"|"loaded"|"migrated"|"quarantined"|
    "downgrade_refused"), ``from_version``, ``to_version``,
    ``quarantine_path``, ``backup_paths`` (list), ``warnings`` (list of str).
    """
    parse = parse or json.loads
    report = {
        "ok": True, "action": "new", "from_version": None,
        "to_version": current_version, "quarantine_path": "",
        "backup_paths": [], "warnings": [],
    }

    if not os.path.exists(path):
        data = default_factory()
        data["schema_version"] = current_version
        return data, report

    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw_text = fh.read()
        data = parse(raw_text)
        if data is None:
            # An empty/whitespace-only file is a legitimate "nothing stored
            # yet" state (yaml.safe_load("") -> None, json.loads fails
            # instead but callers of an empty JSON file get the same
            # courtesy) — not corruption.
            data = {}
        if not isinstance(data, dict):
            raise ValueError(f"expected a mapping at the top level, got {type(data).__name__}")
    except Exception as exc:
        logging.warning("%s is corrupted (%s); quarantining it and starting fresh.", path, exc)
        report["quarantine_path"] = quarantine_corrupt_file(path)
        report["action"] = "quarantined"
        report["warnings"].append(f"quarantined: {exc}")
        data = default_factory()
        data["schema_version"] = current_version
        return data, report

    file_version = int(data.get("schema_version", 1) or 1)
    report["from_version"] = file_version

    if file_version > current_version:
        # DOWNGRADE POLICY: never touch a file from a schema_version newer
        # than this build understands. Read-only in-memory defaults, visible
        # warning, the on-disk file is left completely alone — no backup, no
        # write, nothing destructive to data a newer build produced.
        report["action"] = "downgrade_refused"
        report["ok"] = False
        report["warnings"].append(
            f"{path} is schema_version {file_version}, newer than this build's "
            f"{current_version}; using in-memory defaults and NOT touching the file."
        )
        logging.warning(report["warnings"][-1])
        return default_factory(), report

    if file_version == current_version:
        report["action"] = "loaded"
        return data, report

    # Migrate forward one version step at a time. Idempotent by construction:
    # `version` only ever advances by 1 per successful step and the loop
    # condition re-checks against current_version each time, so calling this
    # function again on the now-migrated data (file_version == current_version)
    # takes the "loaded" branch above and does nothing further.
    version = file_version
    while version < current_version:
        if backup:
            backup_path = backup_before_migration(path, version)
            if backup_path:
                report["backup_paths"].append(backup_path)
        fn = migrations.get(version)
        if fn is None:
            report["warnings"].append(
                f"no migration registered for schema_version {version} -> {version + 1}; stopping short."
            )
            logging.error(report["warnings"][-1])
            break
        data = fn(data)
        version += 1
        data["schema_version"] = version

    report["action"] = "migrated"
    report["to_version"] = version
    return data, report
