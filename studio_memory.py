import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from utils import get_user_data_path


STUDIO_SPEC_TITLE = (
    "Source Arcanum Studio v1 is a local-first AI-assisted storyboarding "
    "and voiced comic reel generator."
)

PROJECT_ASSET_DIRS = (
    "assets",
    "assets/images",
    "assets/audio",
    "assets/video",
    "assets/references",
    "exports",
)

VALID_ASSET_TYPES = {"image", "audio", "video", "reference", "export", "other"}
VALID_APPROVAL_ITEM_TYPES = {"panel", "dialogue", "dialogue_line", "character", "episode", "minute", "asset"}
VALID_WARNING_SEVERITIES = {"low", "medium", "high", "critical"}


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def safe_project_name(project_name):
    value = str(project_name or "").strip()
    value = re.sub(r"[^A-Za-z0-9 _-]+", "", value)
    value = re.sub(r"\s+", " ", value).strip()
    if not value:
        raise ValueError("Project name is required.")
    return value[:80]


def get_studio_projects_dir():
    path = Path(get_user_data_path()) / "studio_projects"
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def get_project_dir(project_name):
    safe_name = safe_project_name(project_name)
    parent = Path(get_studio_projects_dir()).resolve()
    result = (parent / safe_name).resolve()
    if not str(result).startswith(str(parent) + os.sep) and result != parent:
        raise ValueError(f"Invalid project name: resolves outside projects directory")
    return result


def ensure_project_structure(project_name):
    project_dir = get_project_dir(project_name)
    project_dir.mkdir(parents=True, exist_ok=True)
    for relative in PROJECT_ASSET_DIRS:
        (project_dir / relative).mkdir(parents=True, exist_ok=True)
    return project_dir


def get_project_db_path(project_name):
    project_dir = ensure_project_structure(project_name)
    return str(project_dir / "studio.db"), str(project_dir)


def get_connection(project_name):
    db_path, _project_dir = get_project_db_path(project_name)
    conn = sqlite3.connect(db_path, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    conn.execute("PRAGMA busy_timeout = 30000;")
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA synchronous = NORMAL;")
    return conn


def _json_dumps(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, sort_keys=True)


def _json_loads(value, default=None):
    if value in (None, ""):
        return {} if default is None else default
    try:
        return json.loads(value)
    except Exception:
        return {} if default is None else default


def _row_to_dict(row):
    if row is None:
        return None
    data = dict(row)
    for key in ("content", "metadata", "arguments", "result", "value"):
        if key in data and isinstance(data[key], str):
            data[key] = _json_loads(data[key], data[key])
    return data


def _rows_to_dicts(rows):
    return [_row_to_dict(row) for row in rows]


def _touch_project(conn, project_id):
    conn.execute("UPDATE projects SET updated_at = ? WHERE id = ?", (utc_now(), project_id))


def _require_text(value, field_name):
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field_name} is required.")
    return text


def _require_int(value, field_name, minimum=1):
    try:
        number = int(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field_name} must be an integer.")
    if number < minimum:
        raise ValueError(f"{field_name} must be at least {minimum}.")
    return number


def _require_choice(value, field_name, choices):
    text = _require_text(value, field_name).lower()
    if text not in choices:
        allowed = ", ".join(sorted(choices))
        raise ValueError(f"{field_name} must be one of: {allowed}.")
    return text


def _require_project(conn, project_id):
    project_id = _require_int(project_id, "project_id")
    row = conn.execute("SELECT id FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        raise ValueError("Studio project not found.")
    return project_id


def _require_row(conn, table, project_id, row_id, field_name):
    row_id = _require_int(row_id, field_name)
    row = conn.execute(f"SELECT id FROM {table} WHERE project_id = ? AND id = ?", (project_id, row_id)).fetchone()
    if not row:
        raise ValueError(f"{field_name} does not exist in this project.")
    return row_id


def init_project_db(project_name, preferences=None):
    safe_name = safe_project_name(project_name)
    db_path, project_dir = get_project_db_path(safe_name)
    conn = get_connection(safe_name)
    cursor = conn.cursor()

    cursor.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            path TEXT NOT NULL,
            spec_title TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_preferences (
            project_id INTEGER NOT NULL,
            key TEXT NOT NULL,
            value TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (project_id, key),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS bibles (
            project_id INTEGER PRIMARY KEY,
            content TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS characters (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            role TEXT,
            archetype TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS locations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            description TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS episodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            summary TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS minutes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            episode_id INTEGER NOT NULL,
            minute_number INTEGER NOT NULL,
            summary TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(episode_id) REFERENCES episodes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS panels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            minute_id INTEGER NOT NULL,
            panel_number INTEGER NOT NULL,
            visual_description TEXT,
            style_prompt TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(minute_id) REFERENCES minutes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS dialogue_lines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            panel_id INTEGER NOT NULL,
            speaker TEXT NOT NULL,
            text TEXT NOT NULL,
            audio_path TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(panel_id) REFERENCES panels(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            path TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS canon_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            description TEXT NOT NULL,
            time_index TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS continuity_warnings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            target_type TEXT NOT NULL,
            target_id INTEGER,
            severity TEXT NOT NULL,
            message TEXT NOT NULL,
            resolved INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS approvals (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            item_type TEXT NOT NULL,
            item_id INTEGER NOT NULL,
            approved INTEGER NOT NULL,
            approved_by TEXT,
            note TEXT,
            timestamp TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS tool_calls (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            tool_name TEXT NOT NULL,
            arguments TEXT NOT NULL DEFAULT '{}',
            result TEXT NOT NULL DEFAULT '{}',
            timestamp TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_locations_project ON locations(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id, id);
        CREATE INDEX IF NOT EXISTS idx_minutes_episode ON minutes(project_id, episode_id, minute_number);
        CREATE INDEX IF NOT EXISTS idx_panels_minute ON panels(project_id, minute_id, panel_number);
        CREATE INDEX IF NOT EXISTS idx_dialogue_panel ON dialogue_lines(project_id, panel_id);
        CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id, type);
        CREATE INDEX IF NOT EXISTS idx_canon_project ON canon_events(project_id, time_index);
        CREATE INDEX IF NOT EXISTS idx_warnings_project ON continuity_warnings(project_id, resolved, severity);
        CREATE INDEX IF NOT EXISTS idx_approvals_item ON approvals(project_id, item_type, item_id);
        CREATE INDEX IF NOT EXISTS idx_tool_calls_project ON tool_calls(project_id, timestamp);
        """
    )

    now = utc_now()
    row = cursor.execute("SELECT id FROM projects WHERE name = ?", (safe_name,)).fetchone()
    if row:
        project_id = row["id"]
        cursor.execute(
            "UPDATE projects SET path = ?, spec_title = ?, updated_at = ? WHERE id = ?",
            (project_dir, STUDIO_SPEC_TITLE, now, project_id),
        )
    else:
        cursor.execute(
            "INSERT INTO projects (name, path, spec_title, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            (safe_name, project_dir, STUDIO_SPEC_TITLE, now, now),
        )
        project_id = cursor.lastrowid

    for key, value in (preferences or {}).items():
        cursor.execute(
            """
            INSERT INTO user_preferences (project_id, key, value, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(project_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
            """,
            (project_id, str(key), _json_dumps(value), now),
        )

    conn.commit()
    conn.close()
    return project_id


def create_project(project_name, preferences=None):
    project_id = init_project_db(project_name, preferences=preferences)
    return get_project_by_id(project_name, project_id)


def get_project_by_id(project_name, project_id):
    conn = get_connection(project_name)
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def get_project_by_name(project_name):
    safe_name = safe_project_name(project_name)
    conn = get_connection(safe_name)
    row = conn.execute("SELECT * FROM projects WHERE name = ?", (safe_name,)).fetchone()
    conn.close()
    return _row_to_dict(row)


def set_user_preference(project_name, project_id, key, value):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    key = _require_text(key, "preference key")
    now = utc_now()
    conn.execute(
        """
        INSERT INTO user_preferences (project_id, key, value, updated_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(project_id, key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at
        """,
        (project_id, str(key), _json_dumps(value), now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()


def get_user_preferences(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT key, value FROM user_preferences WHERE project_id = ?", (project_id,)).fetchall()
    conn.close()
    return {row["key"]: _json_loads(row["value"], row["value"]) for row in rows}


def save_bible(project_name, project_id, content_dict):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO bibles (project_id, content, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(project_id) DO UPDATE SET content = excluded.content, updated_at = excluded.updated_at
        """,
        (project_id, _json_dumps(content_dict), now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()


def get_bible(project_name, project_id):
    conn = get_connection(project_name)
    row = conn.execute("SELECT content FROM bibles WHERE project_id = ?", (project_id,)).fetchone()
    conn.close()
    return _json_loads(row["content"]) if row else {}


def add_character(project_name, project_id, name, description="", role="", archetype="", status="draft", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    name = _require_text(name, "Character name")
    status = _require_text(status, "Character status")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO characters (project_id, name, description, role, archetype, status, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, name, description, role, archetype, status, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    character_id = cursor.lastrowid
    conn.close()
    return character_id


def update_character(project_name, project_id, character_id, **fields):
    allowed = {"name", "description", "role", "archetype", "status", "metadata"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    if not updates:
        return get_character(project_name, project_id, character_id)
    if "metadata" in updates:
        updates["metadata"] = _json_dumps(updates["metadata"])
    if "name" in updates:
        updates["name"] = _require_text(updates["name"], "Character name")
    if "status" in updates:
        updates["status"] = _require_text(updates["status"], "Character status")
    updates["updated_at"] = utc_now()
    assignments = ", ".join(f"{key} = ?" for key in updates)
    values = list(updates.values()) + [project_id, character_id]
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    character_id = _require_row(conn, "characters", project_id, character_id, "character_id")
    values = list(updates.values()) + [project_id, character_id]
    conn.execute(f"UPDATE characters SET {assignments} WHERE project_id = ? AND id = ?", values)
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()
    return get_character(project_name, project_id, character_id)


def get_character(project_name, project_id, character_id):
    conn = get_connection(project_name)
    row = conn.execute("SELECT * FROM characters WHERE project_id = ? AND id = ?", (project_id, character_id)).fetchone()
    conn.close()
    return _row_to_dict(row)


def get_characters(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM characters WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_location(project_name, project_id, name, description="", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    name = _require_text(name, "Location name")
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO locations (project_id, name, description, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, name, description, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    location_id = cursor.lastrowid
    conn.close()
    return location_id


def get_locations(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM locations WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_episode(project_name, project_id, name, summary="", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    name = _require_text(name, "Episode name")
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO episodes (project_id, name, summary, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, name, summary, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    episode_id = cursor.lastrowid
    conn.close()
    return episode_id


def get_episodes(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM episodes WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_minute(project_name, project_id, episode_id, minute_number, summary="", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    episode_id = _require_row(conn, "episodes", project_id, episode_id, "episode_id")
    minute_number = _require_int(minute_number, "minute_number")
    duplicate = conn.execute(
        "SELECT id FROM minutes WHERE project_id = ? AND episode_id = ? AND minute_number = ?",
        (project_id, episode_id, minute_number),
    ).fetchone()
    if duplicate:
        conn.close()
        raise ValueError("A minute with that number already exists for this episode.")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO minutes (project_id, episode_id, minute_number, summary, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, episode_id, minute_number, summary, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    minute_id = cursor.lastrowid
    conn.close()
    return minute_id


def get_minutes(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM minutes WHERE project_id = ? ORDER BY episode_id ASC, minute_number ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_panel(project_name, project_id, minute_id, panel_number, visual_description="", style_prompt="", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    minute_id = _require_row(conn, "minutes", project_id, minute_id, "minute_id")
    panel_number = _require_int(panel_number, "panel_number")
    duplicate = conn.execute(
        "SELECT id FROM panels WHERE project_id = ? AND minute_id = ? AND panel_number = ?",
        (project_id, minute_id, panel_number),
    ).fetchone()
    if duplicate:
        conn.close()
        raise ValueError("A panel with that number already exists for this minute.")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO panels (project_id, minute_id, panel_number, visual_description, style_prompt, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, minute_id, panel_number, visual_description, style_prompt, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    panel_id = cursor.lastrowid
    conn.close()
    return panel_id


def get_panels(project_name, project_id, minute_id=None):
    conn = get_connection(project_name)
    if minute_id is None:
        rows = conn.execute("SELECT * FROM panels WHERE project_id = ? ORDER BY minute_id ASC, panel_number ASC", (project_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM panels WHERE project_id = ? AND minute_id = ? ORDER BY panel_number ASC",
            (project_id, minute_id),
        ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_dialogue_line(project_name, project_id, panel_id, speaker, text, audio_path=None, metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    panel_id = _require_row(conn, "panels", project_id, panel_id, "panel_id")
    speaker = _require_text(speaker, "Dialogue speaker")
    text = _require_text(text, "Dialogue text")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO dialogue_lines (project_id, panel_id, speaker, text, audio_path, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, panel_id, speaker, text, audio_path, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    line_id = cursor.lastrowid
    conn.close()
    return line_id


def get_dialogue_lines(project_name, project_id, panel_id=None):
    conn = get_connection(project_name)
    if panel_id is None:
        rows = conn.execute("SELECT * FROM dialogue_lines WHERE project_id = ? ORDER BY panel_id ASC, id ASC", (project_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM dialogue_lines WHERE project_id = ? AND panel_id = ? ORDER BY id ASC",
            (project_id, panel_id),
        ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_asset(project_name, project_id, asset_type, path, metadata=None):
    asset_type = _require_choice(asset_type, "asset_type", VALID_ASSET_TYPES)
    project_dir = get_project_dir(project_name).resolve()
    asset_path = Path(path)
    if not asset_path.is_absolute():
        asset_path = project_dir / asset_path
    resolved = asset_path.resolve()
    if project_dir not in resolved.parents and resolved != project_dir:
        raise ValueError("Assets must live inside the project folder.")
    resolved.parent.mkdir(parents=True, exist_ok=True)

    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    now = utc_now()
    relative_path = str(resolved.relative_to(project_dir))
    cursor = conn.execute(
        "INSERT INTO assets (project_id, type, path, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, asset_type, relative_path, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    asset_id = cursor.lastrowid
    conn.close()
    return asset_id


def get_assets(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM assets WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_canon_event(project_name, project_id, description, time_index=None, metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    description = _require_text(description, "Canon event description")
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO canon_events (project_id, description, time_index, metadata, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, description, time_index, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    event_id = cursor.lastrowid
    conn.close()
    return event_id


def get_canon_events(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM canon_events WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def add_continuity_warning(project_name, project_id, target_type, target_id, severity, message, metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    target_type = _require_text(target_type, "target_type")
    severity = _require_choice(severity, "severity", VALID_WARNING_SEVERITIES)
    message = _require_text(message, "Continuity warning message")
    if target_id is not None:
        target_id = _require_int(target_id, "target_id")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO continuity_warnings (project_id, target_type, target_id, severity, message, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, target_type, target_id, severity, message, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    warning_id = cursor.lastrowid
    conn.close()
    return warning_id


def get_continuity_warnings(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM continuity_warnings WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def resolve_continuity_warning(project_name, warning_id):
    conn = get_connection(project_name)
    warning_id = _require_int(warning_id, "warning_id")
    cursor = conn.execute("UPDATE continuity_warnings SET resolved = 1, updated_at = ? WHERE id = ?", (utc_now(), warning_id))
    if cursor.rowcount == 0:
        conn.close()
        raise ValueError("Continuity warning not found.")
    conn.commit()
    conn.close()


def record_approval(project_name, project_id, item_type, item_id, approved, approved_by="User", note=""):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    item_type = _require_choice(item_type, "item_type", VALID_APPROVAL_ITEM_TYPES)
    item_id = _require_int(item_id, "item_id")
    if item_type == "panel":
        _require_row(conn, "panels", project_id, item_id, "item_id")
    elif item_type in ("dialogue", "dialogue_line"):
        _require_row(conn, "dialogue_lines", project_id, item_id, "item_id")
    elif item_type == "character":
        _require_row(conn, "characters", project_id, item_id, "item_id")
    elif item_type == "episode":
        _require_row(conn, "episodes", project_id, item_id, "item_id")
    elif item_type == "minute":
        _require_row(conn, "minutes", project_id, item_id, "item_id")
    elif item_type == "asset":
        _require_row(conn, "assets", project_id, item_id, "item_id")
    now = utc_now()
    cursor = conn.execute(
        "INSERT INTO approvals (project_id, item_type, item_id, approved, approved_by, note, timestamp) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (project_id, item_type, item_id, 1 if approved else 0, approved_by, note, now),
    )
    if item_type == "panel":
        conn.execute("UPDATE panels SET approved = ?, updated_at = ? WHERE project_id = ? AND id = ?", (1 if approved else 0, now, project_id, item_id))
    elif item_type in ("dialogue", "dialogue_line"):
        conn.execute(
            "UPDATE dialogue_lines SET approved = ?, updated_at = ? WHERE project_id = ? AND id = ?",
            (1 if approved else 0, now, project_id, item_id),
        )
    _touch_project(conn, project_id)
    conn.commit()
    approval_id = cursor.lastrowid
    conn.close()
    return approval_id


def get_approvals(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM approvals WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def log_tool_call(project_name, project_id, tool_name, arguments_dict=None, result_dict=None):
    conn = get_connection(project_name)
    cursor = conn.execute(
        "INSERT INTO tool_calls (project_id, tool_name, arguments, result, timestamp) VALUES (?, ?, ?, ?, ?)",
        (project_id, tool_name, _json_dumps(arguments_dict), _json_dumps(result_dict), utc_now()),
    )
    conn.commit()
    call_id = cursor.lastrowid
    conn.close()
    return call_id


def get_tool_calls(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM tool_calls WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def export_project_json(project_name, project_id):
    project = get_project_by_id(project_name, project_id)
    if not project:
        return None
    return {
        "spec": STUDIO_SPEC_TITLE,
        "project": project,
        "user_preferences": get_user_preferences(project_name, project_id),
        "bible": get_bible(project_name, project_id),
        "characters": get_characters(project_name, project_id),
        "locations": get_locations(project_name, project_id),
        "episodes": get_episodes(project_name, project_id),
        "minutes": get_minutes(project_name, project_id),
        "panels": get_panels(project_name, project_id),
        "dialogue_lines": get_dialogue_lines(project_name, project_id),
        "assets": get_assets(project_name, project_id),
        "canon_events": get_canon_events(project_name, project_id),
        "continuity_warnings": get_continuity_warnings(project_name, project_id),
        "approvals": get_approvals(project_name, project_id),
        "tool_calls": get_tool_calls(project_name, project_id),
    }
