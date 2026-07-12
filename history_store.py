"""Searchable, uncapped draft history (C8).

The in-memory draft_queue (and draft_history.json) stays a 100-item working set;
this module is a parallel SQLite FTS5 archive that accumulates every draft so the
user can search their whole history. Kept fully defensive: any failure here must
never disrupt the dictation pipeline.
"""
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
            final_text TEXT
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
    return (
        int(draft.get("id")),
        str(draft.get("created_at", "")),
        str(draft.get("status", "")),
        str(draft.get("metadata", {}).get("profile", "") or draft.get("profile", "")),
        str(draft.get("raw_text", "") or ""),
        str(draft.get("final_text", "") or ""),
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
                    INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        created_at=excluded.created_at,
                        status=excluded.status,
                        profile=excluded.profile,
                        raw_text=excluded.raw_text,
                        final_text=excluded.final_text
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
                    INSERT INTO drafts (id, created_at, status, profile, raw_text, final_text)
                    VALUES (?, ?, ?, ?, ?, ?)
                    ON CONFLICT(id) DO UPDATE SET
                        created_at=excluded.created_at,
                        status=excluded.status,
                        profile=excluded.profile,
                        raw_text=excluded.raw_text,
                        final_text=excluded.final_text
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
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "status": row["status"],
        "profile": row["profile"],
        "raw_text": row["raw_text"],
        "final_text": row["final_text"],
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


def wipe_database():
    """Physically remove the database plus its -wal/-shm companions, then
    recreate an empty store. A logical DELETE leaves content recoverable in
    SQLite free pages and the WAL; a privacy wipe must remove the files.
    (Without at-rest encryption this is still logical deletion at the
    filesystem level — SSD forensics are out of scope — but nothing readable
    remains through SQLite or the files themselves.)

    Returns {"ok": bool, "removed": [...], "failed": [...], "leftover": [...]}.
    """
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
    try:
        init()  # recreate an empty schema so the app keeps working
    except Exception as exc:
        logging.warning(f"history_store wipe: reinit failed: {exc}")
    return {"ok": not failed and not leftover, "removed": removed, "failed": failed, "leftover": leftover}


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
