"""Searchable, uncapped draft history (C8).

The in-memory draft_queue (and draft_history.json) stays a 100-item working set;
this module is a parallel SQLite FTS5 archive that accumulates every draft so the
user can search their whole history. Kept fully defensive: any failure here must
never disrupt the dictation pipeline.
"""
import json
import logging
import os
import sqlite3
import threading

from utils import get_user_data_path

_lock = threading.Lock()
_initialized_path = None

# Unlike recordings.py's MAX_RECORDINGS, this store previously had no retention
# limit and accumulated every draft forever. Cap it so the DB doesn't grow
# unbounded across months of use.
MAX_HISTORY_RECORDS = 5000
_PRUNE_EVERY_N_WRITES = 100
_write_count = 0


def get_db_path():
    return os.path.join(get_user_data_path(), "history.db")


def _db_path():
    return get_db_path()


def _connect():
    conn = sqlite3.connect(_db_path(), timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_schema(conn):
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS drafts (
            id INTEGER PRIMARY KEY,
            created_at TEXT,
            status TEXT,
            profile TEXT,
            raw_text TEXT,
            final_text TEXT,
            data TEXT,
            pinned INTEGER NOT NULL DEFAULT 0,
            pinned_at TEXT,
            preset TEXT
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS drafts_fts USING fts5(
            raw_text, final_text, content='drafts', content_rowid='id'
        );
        CREATE TRIGGER IF NOT EXISTS drafts_ai AFTER INSERT ON drafts BEGIN
            INSERT INTO drafts_fts(rowid, raw_text, final_text)
            VALUES (new.id, new.raw_text, new.final_text);
        END;
        CREATE TRIGGER IF NOT EXISTS drafts_ad AFTER DELETE ON drafts BEGIN
            INSERT INTO drafts_fts(drafts_fts, rowid, raw_text, final_text)
            VALUES ('delete', old.id, old.raw_text, old.final_text);
        END;
        CREATE TRIGGER IF NOT EXISTS drafts_au AFTER UPDATE ON drafts BEGIN
            INSERT INTO drafts_fts(drafts_fts, rowid, raw_text, final_text)
            VALUES ('delete', old.id, old.raw_text, old.final_text);
            INSERT INTO drafts_fts(rowid, raw_text, final_text)
            VALUES (new.id, new.raw_text, new.final_text);
        END;
        """
    )
    # Back-compat: DBs created before the full-record column gets it added here,
    # so an existing archive keeps working and starts storing complete drafts.
    columns = {row[1] for row in conn.execute("PRAGMA table_info(drafts)").fetchall()}
    if "data" not in columns:
        conn.execute("ALTER TABLE drafts ADD COLUMN data TEXT")
    # Wave 3: pinned columns, same additive guard. A pre-Wave-3 database keeps
    # working unchanged and starts recording pin state on the next write —
    # nothing here rewrites existing rows.
    if "pinned" not in columns:
        conn.execute("ALTER TABLE drafts ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0")
    if "pinned_at" not in columns:
        conn.execute("ALTER TABLE drafts ADD COLUMN pinned_at TEXT")
    # Amendment A1: a dedicated `preset` column (the Library persona, e.g.
    # "True Janitor" -- draft["preset"]) so persona filtering can be pushed
    # into SQL too. Deliberately NOT the same thing as `profile`, which is
    # the application/settings profile from draft["metadata"]["profile"];
    # query()'s persona filter reads `preset` with a json_extract(data,
    # '$.preset') fallback so rows written before this column existed are
    # still found.
    if "preset" not in columns:
        conn.execute("ALTER TABLE drafts ADD COLUMN preset TEXT")


def init():
    """Ensure the schema exists for the current data path.

    Keyed by resolved db path (not a plain bool) so switching user-data
    directories mid-process — e.g. across tests, or a profile/data-dir
    change — re-creates the schema instead of silently skipping it.
    """
    global _initialized_path
    db_path = get_db_path()
    with _lock:
        if _initialized_path == db_path:
            return
        try:
            conn = _connect()
            try:
                _ensure_schema(conn)
                conn.commit()
                _initialized_path = db_path
            finally:
                conn.close()
        except Exception as exc:
            logging.warning(f"history_store init failed: {exc}")
            return
    # Outside the lock (prune_history takes it itself); catches a store that
    # grew past the limit before this version, or between app runs.
    prune_history()


def _row_from_draft(draft):
    metadata = draft.get("metadata") or {}
    profile = str((metadata.get("profile") if isinstance(metadata, dict) else "") or draft.get("profile", ""))
    # Repair the pinned/pinned_at invariant at write time too (mirrors
    # domain.library.normalize_draft_record's rule): pinned False always
    # forces pinned_at None, even if the caller's dict disagrees.
    pinned = bool(draft.get("pinned", False))
    pinned_at = draft.get("pinned_at") if pinned else None
    pinned_at = str(pinned_at) if pinned_at is not None else None
    preset = draft.get("preset")
    preset = str(preset) if preset is not None else None
    return (
        int(draft.get("id")),
        str(draft.get("created_at", "")),
        str(draft.get("status", "")),
        profile,
        str(draft.get("raw_text", "") or ""),
        str(draft.get("final_text", "") or ""),
        # The complete draft record, so the store holds everything the queue does
        # (confidence, gate_reasons, send state, review fields, …), not just the
        # searchable subset — the basis for SQLite becoming the canonical store.
        json.dumps(draft, default=str),
        1 if pinned else 0,
        pinned_at,
        preset,
    )


def upsert_draft(draft):
    global _write_count
    if not isinstance(draft, dict) or draft.get("id") is None:
        return
    init()
    try:
        row = _row_from_draft(draft)
    except (TypeError, ValueError):
        return
    with _lock:
        try:
            conn = _connect()
            try:
                conn.execute(
                    """
                    INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text, data, pinned, pinned_at, preset)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        created_at=excluded.created_at,
                        status=excluded.status,
                        profile=excluded.profile,
                        raw_text=excluded.raw_text,
                        final_text=excluded.final_text,
                        data=excluded.data,
                        pinned=excluded.pinned,
                        pinned_at=excluded.pinned_at,
                        preset=excluded.preset
                    """,
                    row,
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store upsert failed: {exc}")

    _write_count += 1
    if _write_count % _PRUNE_EVERY_N_WRITES == 0:
        prune_history()


def upsert_many(drafts):
    """Batch upsert in ONE connection and ONE transaction. The previous
    per-draft connection/commit turned every full-queue mirror into ~100
    transactions — visible on slow disks and antivirus-heavy systems."""
    global _write_count
    rows = []
    for draft in drafts or []:
        if not isinstance(draft, dict) or draft.get("id") is None:
            continue
        try:
            rows.append(_row_from_draft(draft))
        except (TypeError, ValueError):
            continue
    if not rows:
        return
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                conn.executemany(
                    """
                    INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text, data, pinned, pinned_at, preset)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        created_at=excluded.created_at,
                        status=excluded.status,
                        profile=excluded.profile,
                        raw_text=excluded.raw_text,
                        final_text=excluded.final_text,
                        data=excluded.data,
                        pinned=excluded.pinned,
                        pinned_at=excluded.pinned_at,
                        preset=excluded.preset
                    """,
                    rows,
                )
                conn.commit()
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store batch upsert failed: {exc}")

    _write_count += len(rows)
    if _write_count >= _PRUNE_EVERY_N_WRITES and _write_count % _PRUNE_EVERY_N_WRITES < len(rows):
        prune_history()


def _row_to_dict(row):
    # try/except rather than a blanket default: rows from a DB opened before
    # the Wave 3 migration ran in this process still lack the columns, and a
    # missing sqlite3.Row key raises IndexError rather than returning None.
    try:
        pinned = row["pinned"]
    except (IndexError, KeyError):
        pinned = 0
    try:
        pinned_at = row["pinned_at"]
    except (IndexError, KeyError):
        pinned_at = None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "profile": row["profile"],
        "raw_text": row["raw_text"],
        "final_text": row["final_text"],
        "pinned": bool(pinned),
        "pinned_at": pinned_at,
    }


def search(query, limit=50):
    init()
    query = str(query or "").strip()
    if not query:
        return recent(limit)
    # Build a safe prefix MATCH: quote each term, add * for prefix search.
    terms = [t for t in query.replace('"', " ").split() if t]
    if not terms:
        return recent(limit)
    match = " ".join(f'"{t}"*' for t in terms)
    with _lock:
        try:
            conn = _connect()
            try:
                rows = conn.execute(
                    """
                    SELECT d.* FROM drafts d
                    JOIN drafts_fts f ON d.id = f.rowid
                    WHERE drafts_fts MATCH ?
                    ORDER BY rank
                    LIMIT ?
                    """,
                    (match, int(limit)),
                ).fetchall()
                return [_row_to_dict(r) for r in rows]
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store search failed: {exc}")
            return []


def recent(limit=50):
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM drafts ORDER BY created_at DESC, id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
                return [_row_to_dict(r) for r in rows]
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store recent failed: {exc}")
            return []


def _full_from_row(row):
    """Reconstruct a complete draft dict from a row: the stored full-record JSON
    if present, else the typed columns (rows written before the data column)."""
    try:
        raw = row["data"]
    except (IndexError, KeyError):
        raw = None
    if raw:
        try:
            obj = json.loads(raw)
            if isinstance(obj, dict):
                return obj
        except (ValueError, TypeError):
            pass
    # No JSON body (row predates the data column): the typed-column fallback
    # in _row_to_dict already carries pinned/pinned_at, defaulted from the
    # columns (False/None for rows written before Wave 3's migration too).
    return _row_to_dict(row)


def load_recent_full(limit=100):
    """The most recent ``limit`` drafts as COMPLETE records, oldest-first so they
    map straight onto the in-memory draft_queue order. Full fields come from the
    stored JSON; rows predating the data column degrade to the typed subset."""
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                rows = conn.execute(
                    "SELECT * FROM drafts ORDER BY created_at DESC, id DESC LIMIT ?",
                    (int(limit),),
                ).fetchall()
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store load_recent_full failed: {exc}")
            return []
    return [_full_from_row(r) for r in reversed(rows)]


# --- §1/§2 record normalization --------------------------------------------
# The sibling Wave 3 domain module (backend/domain/library.py) is the
# authority for what the §1 defaults are and how the pinned/pinned_at
# invariant is repaired. It is being built concurrently by another worker
# against the same contract and may not exist yet, so it is imported lazily
# (inside the function, not at module load) and defensively: if the import
# fails for any reason, fall back to an inline copy of the same §1 defaults
# so this module and its tests stand alone either way.
_FALLBACK_LIBRARY_FIELD_DEFAULTS = {
    "pinned": False,
    "pinned_at": None,
    "duplicated_from_id": None,
    "reopened_from_id": None,
    "revision_of_id": None,
    "restored_from_recording_id": None,
    "restored_from_draft_id": None,
}


def _fallback_normalize_draft_record(draft):
    if not isinstance(draft, dict):
        return draft
    normalized = dict(draft)
    for key, default in _FALLBACK_LIBRARY_FIELD_DEFAULTS.items():
        normalized.setdefault(key, default)
    if not normalized.get("pinned"):
        normalized["pinned_at"] = None
    return normalized


def _normalize_record(draft):
    try:
        from backend.domain.library import normalize_draft_record
    except Exception:
        return _fallback_normalize_draft_record(draft)
    try:
        return normalize_draft_record(draft)
    except Exception:
        return _fallback_normalize_draft_record(draft)


def get(draft_id):
    """One complete archive record by exact id, or None.

    Amendment A2: a single indexed lookup (WHERE id = ?), not a scan --
    delete_item(kind="history_entry") needs to resolve a target that may
    exist ONLY in the archive (draft_queue is bounded at 100; the archive
    holds up to MAX_HISTORY_RECORDS), and query({}, limit=<total>) plus a
    scan would deserialize every row's JSON just to find one. Passed through
    _normalize_record (same lazy/defensive domain.library.normalize_draft_
    record import as query()) so the caller gets a Wave-3-shaped record with
    the §1 defaults filled and pin state populated from the columns even for
    a legacy row. Defensive like the rest of this module: never raises,
    returns None on a missing row and on any failure.
    """
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                row = conn.execute("SELECT * FROM drafts WHERE id = ?", (int(draft_id),)).fetchone()
                if row is None:
                    return None
                return _normalize_record(_full_from_row(row))
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store get failed: {exc}")
            return None


def set_pinned(draft_id, pinned, pinned_at):
    """Update the pinned columns AND the pinned/pinned_at keys inside the
    stored `data` JSON so the archive stays self-consistent -- a later
    load_recent_full/query must see the pin without a separate re-read of the
    columns. Returns False if no such row exists. Defensive like the rest of
    this module: never raises."""
    init()
    pinned = bool(pinned)
    pinned_at_val = str(pinned_at) if (pinned and pinned_at is not None) else None
    with _lock:
        try:
            conn = _connect()
            try:
                row = conn.execute("SELECT * FROM drafts WHERE id = ?", (int(draft_id),)).fetchone()
                if row is None:
                    return False
                record = dict(_full_from_row(row))
                record["pinned"] = pinned
                record["pinned_at"] = pinned_at_val
                conn.execute(
                    "UPDATE drafts SET pinned = ?, pinned_at = ?, data = ? WHERE id = ?",
                    (1 if pinned else 0, pinned_at_val, json.dumps(record, default=str), int(draft_id)),
                )
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as exc:
            logging.warning(f"history_store set_pinned failed: {exc}")
            return False


def delete_draft(draft_id):
    """Delete one archive row by exact id. The existing drafts_ad trigger
    keeps FTS in sync. Idempotent: returns False (not an error) when the row
    is already absent."""
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                cur = conn.execute("DELETE FROM drafts WHERE id = ?", (int(draft_id),))
                conn.commit()
                return cur.rowcount > 0
            finally:
                conn.close()
        except Exception as exc:
            logging.warning(f"history_store delete_draft failed: {exc}")
            return False


def query(filters, limit=50, offset=0):
    """Backend-driven filtering: does the filtering in SQL rather than
    pulling every row into Python. `filters` is expected to be the output of
    domain.library.parse_filters (persona/date_from/date_to/status/pinned/
    query), but this function stays defensive about its shape since the
    domain module may be unavailable.

    persona -> the `preset` column, NOT `profile` (Amendment A1; see the
    comment on the persona clause below -- `profile` is an unrelated
    application/settings profile and filtering persona on it would silently
    return wrong rows); status -> status column (accepts a single
    value or a collection, per contract §2's matches_filters); pinned ->
    pinned column; date_from/date_to -> inclusive created_at range; query ->
    FTS5 MATCH over the same row set, reusing the safe prefix-term quoting
    from search() (never interpolates user text into SQL).

    Returns {"results": [full records], "total", "limit", "offset"} where
    total is the match count BEFORE limit/offset is applied. Ordering is
    pinned DESC, created_at DESC, id DESC. Never raises; on failure returns
    an empty result set and logs.
    """
    init()
    filters = filters or {}
    limit = int(limit)
    offset = int(offset)
    empty = {"results": [], "total": 0, "limit": limit, "offset": offset}

    where = []
    params = []

    persona = filters.get("persona")
    if persona:
        # Amendment A1: persona is draft["preset"] (e.g. "True Janitor"), NOT
        # draft["metadata"]["profile"] (the `profile` column, an unrelated
        # application/settings profile) -- matches domain.library.matches_
        # filters, which tests draft["preset"]. COALESCE falls back to
        # extracting it out of the JSON body for rows written before the
        # `preset` column existed, so a persona filter still finds them.
        # json_extract is SQLite's JSON1 extension, compiled in by default on
        # every Python 3.9+ build this project targets; if it's ever
        # unavailable this whole function still degrades to an empty result
        # rather than raising, per the try/except around the query below.
        where.append("COALESCE(d.preset, json_extract(d.data, '$.preset')) = ?")
        params.append(str(persona))

    status = filters.get("status")
    if status:
        statuses = list(status) if isinstance(status, (list, tuple, set, frozenset)) else [status]
        statuses = [str(s) for s in statuses if s is not None]
        if statuses:
            where.append(f"d.status IN ({','.join('?' for _ in statuses)})")
            params.extend(statuses)

    pinned = filters.get("pinned")
    if pinned is not None:
        where.append("d.pinned = ?")
        params.append(1 if pinned else 0)

    date_from = filters.get("date_from")
    if date_from:
        where.append("d.created_at >= ?")
        params.append(str(date_from))

    date_to = filters.get("date_to")
    if date_to:
        where.append("d.created_at <= ?")
        params.append(str(date_to))

    # Same safe prefix-MATCH construction as search(): quote each term and
    # add a trailing * for prefix search. User text is never interpolated
    # directly into the SQL string -- it only ever reaches sqlite as a bound
    # FTS5 query-string parameter.
    query_text = str(filters.get("query") or "").strip()
    match = None
    if query_text:
        terms = [t for t in query_text.replace('"', " ").split() if t]
        if terms:
            match = " ".join(f'"{t}"*' for t in terms)

    if match:
        from_clause = "FROM drafts d JOIN drafts_fts f ON d.id = f.rowid"
        where = ["drafts_fts MATCH ?"] + where
        params = [match] + params
    else:
        from_clause = "FROM drafts d"

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    with _lock:
        try:
            conn = _connect()
            try:
                total = int(
                    conn.execute(f"SELECT COUNT(*) AS c {from_clause} {where_sql}", params).fetchone()["c"]
                )
                rows = conn.execute(
                    f"""
                    SELECT d.* {from_clause} {where_sql}
                    ORDER BY d.pinned DESC, d.created_at DESC, d.id DESC
                    LIMIT ? OFFSET ?
                    """,
                    params + [limit, offset],
                ).fetchall()
                results = [_normalize_record(_full_from_row(r)) for r in rows]
                return {"results": results, "total": total, "limit": limit, "offset": offset}
            finally:
                conn.close()
        except Exception as exc:
            logging.debug(f"history_store query failed: {exc}")
            return empty


def count():
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                return int(conn.execute("SELECT COUNT(*) AS c FROM drafts").fetchone()["c"])
            finally:
                conn.close()
        except Exception:
            return 0


def prune_history(max_keep=MAX_HISTORY_RECORDS):
    """Delete rows beyond the newest max_keep (by created_at, then id).

    The FTS index stays in sync automatically via the drafts_ad trigger.
    Returns the number of rows removed.
    """
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                cur = conn.execute(
                    """
                    DELETE FROM drafts WHERE id IN (
                        SELECT id FROM drafts
                        ORDER BY created_at DESC, id DESC
                        LIMIT -1 OFFSET ?
                    )
                    """,
                    (int(max_keep),),
                )
                conn.commit()
                return max(cur.rowcount, 0)
            finally:
                conn.close()
        except Exception as exc:
            logging.warning(f"history_store prune failed: {exc}")
            return 0


def clear():
    init()
    with _lock:
        try:
            conn = _connect()
            try:
                conn.execute("DELETE FROM drafts")
                conn.commit()
                return True
            finally:
                conn.close()
        except Exception as exc:
            logging.warning(f"history_store clear failed: {exc}")
            return False


def verify_schema():
    """Prove the store is usable: both tables exist and a row round-trips.

    Distinguishes an *empty* database (healthy, count 0) from a *broken or
    missing-schema* one — the latter previously masqueraded as empty because
    count() swallowed the "no such table" error as 0. Returns
    {"ok", "drafts_table", "fts_table", "roundtrip", "error"}.
    """
    result = {"ok": False, "drafts_table": False, "fts_table": False, "roundtrip": False, "error": ""}
    with _lock:
        try:
            conn = _connect()
            try:
                tables = {
                    row[0]
                    for row in conn.execute(
                        "SELECT name FROM sqlite_master WHERE type IN ('table')"
                    ).fetchall()
                }
                result["drafts_table"] = "drafts" in tables
                result["fts_table"] = "drafts_fts" in tables
                if not (result["drafts_table"] and result["fts_table"]):
                    result["error"] = "missing table(s)"
                    return result
                # Round-trip a sentinel row through insert + FTS retrieval, then
                # remove it, so we prove the triggers and FTS index actually work.
                probe_id = -999_999
                conn.execute("DELETE FROM drafts WHERE id = ?", (probe_id,))
                conn.execute(
                    "INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text) "
                    "VALUES (?, '', 'probe', '', 'schemaprobe', 'schemaprobe')",
                    (probe_id,),
                )
                got = conn.execute(
                    "SELECT d.id FROM drafts d JOIN drafts_fts f ON d.id = f.rowid "
                    "WHERE drafts_fts MATCH 'schemaprobe' AND d.id = ?",
                    (probe_id,),
                ).fetchone()
                conn.execute("DELETE FROM drafts WHERE id = ?", (probe_id,))
                conn.commit()
                result["roundtrip"] = got is not None
                result["ok"] = result["roundtrip"]
                if not result["roundtrip"]:
                    result["error"] = "insert/retrieve round-trip failed"
            finally:
                conn.close()
        except Exception as exc:
            result["error"] = str(exc)
    return result


def wipe_database():
    """Physically remove the database plus its -wal/-shm companions, then
    recreate and *verify* an empty store. A logical DELETE leaves content
    recoverable in SQLite free pages and the WAL; a privacy wipe must remove
    the files. (Without at-rest encryption this is still logical deletion at
    the filesystem level — SSD forensics are out of scope — but nothing
    readable remains through SQLite or the files themselves.)

    Returns {"ok", "removed", "failed", "leftover", "recreated", "schema"}.
    """
    global _initialized_path, _write_count
    base = _db_path()
    targets = [base, base + "-wal", base + "-shm"]
    removed, failed = [], []
    with _lock:
        for path in targets:
            try:
                if os.path.exists(path):
                    os.remove(path)
                    removed.append(os.path.basename(path))
            except OSError as exc:
                logging.warning(f"history_store wipe: could not remove {path}: {exc}")
                failed.append(os.path.basename(path))
        leftover = [os.path.basename(p) for p in targets if os.path.exists(p)]
        # Critical: the schema cache still points at the just-deleted db, so a
        # plain init() would early-return and leave a schemaless file behind.
        # Reset the cached path and write counter so the store is rebuilt.
        _initialized_path = None
        _write_count = 0
    try:
        init()  # recreate an empty schema so the app keeps working
    except Exception as exc:
        logging.warning(f"history_store wipe: reinit failed: {exc}")
    schema = verify_schema()
    return {
        "ok": (not failed and not leftover and schema["ok"]),
        "removed": removed,
        "failed": failed,
        "leftover": leftover,
        "recreated": schema["ok"],
        "schema": schema,
    }


def migrate_from_json(json_path):
    """One-time backfill from draft_history.json when the archive is empty."""
    init()
    if count() > 0:
        return 0
    try:
        import json

        if not os.path.exists(json_path):
            return 0
        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, list):
            return 0
        upsert_many([d for d in data if isinstance(d, dict) and d.get("id") is not None])
        return count()
    except Exception as exc:
        logging.debug(f"history_store migration failed: {exc}")
        return 0
