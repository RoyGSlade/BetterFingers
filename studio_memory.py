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
VALID_APPROVAL_ITEM_TYPES = {"panel", "dialogue", "dialogue_line", "character", "episode", "page", "minute", "asset"}
VALID_WARNING_SEVERITIES = {"low", "medium", "high", "critical"}

# --- GEST (Graph of Events in Space and Time) vocabulary ---
# Node kinds: "exists" anchors (actors/objects/locations present in the world), plus
# action and event nodes that occur over time.
VALID_GEST_NODE_TYPES = {"exists", "action", "event", "location"}
# Allen's-interval temporal relations between event nodes.
GEST_TEMPORAL_RELATIONS = {"before", "after", "same_time", "concurrent"}
# Causal/dependency relations populated by the Logical Relations agent.
GEST_LOGICAL_RELATIONS = {"causes", "enables", "prevents", "requires"}
# Narrative-coherence relations populated by the Semantic Relations agent.
GEST_SEMANTIC_RELATIONS = {"observes", "interrupts", "motivates", "sets_context_for", "contrasts_with"}
# Relation -> class lookup, so callers may pass just the relation name.
GEST_RELATION_CLASS = {
    **{rel: "temporal" for rel in GEST_TEMPORAL_RELATIONS},
    **{rel: "logical" for rel in GEST_LOGICAL_RELATIONS},
    **{rel: "semantic" for rel in GEST_SEMANTIC_RELATIONS},
}
# Temporal relations that impose a strict precedence ordering (used for cycle detection).
# Stored as a normalized "source occurs before target" edge.
GEST_ORDERING_RELATIONS = {"before", "after"}

DEFAULT_USER_PREFERENCES = {
    "render_resolution": "1920x1080",
    "animation_framerate": 24,
    "default_tts_voice": "alloy",
    "director_style": "Anime",
    "target_audience": "General",
}


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
    for key in ("content", "metadata", "arguments", "result", "value", "voice_profile"):
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
            primary_image_path TEXT,
            voice_profile TEXT,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS character_assets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            character_id INTEGER NOT NULL,
            asset_type TEXT NOT NULL,
            path TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(character_id) REFERENCES characters(id) ON DELETE CASCADE
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

        CREATE TABLE IF NOT EXISTS pages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            episode_id INTEGER NOT NULL,
            page_number INTEGER NOT NULL,
            title TEXT,
            summary TEXT,
            status TEXT NOT NULL DEFAULT 'draft',
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
            page_id INTEGER,
            panel_number INTEGER NOT NULL,
            visual_description TEXT,
            style_prompt TEXT,
            approved INTEGER NOT NULL DEFAULT 0,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(minute_id) REFERENCES minutes(id) ON DELETE CASCADE,
            FOREIGN KEY(page_id) REFERENCES pages(id) ON DELETE SET NULL
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

        CREATE TABLE IF NOT EXISTS pronunciations (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            word TEXT NOT NULL,
            phonemes TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(project_id, word),
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
        );

        -- GEST: Graph of Events in Space and Time (directed graph G = (V, E)).
        -- Nodes are the "Exists" anchors (actors/objects/locations), actions, and events;
        -- edges carry Allen's-interval temporal relations plus logical/semantic relations.
        CREATE TABLE IF NOT EXISTS gest_nodes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            episode_id INTEGER,
            node_type TEXT NOT NULL,
            label TEXT NOT NULL,
            ref_type TEXT,
            ref_id INTEGER,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(episode_id) REFERENCES episodes(id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS gest_edges (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id INTEGER NOT NULL,
            source_id INTEGER NOT NULL,
            target_id INTEGER NOT NULL,
            relation_class TEXT NOT NULL,
            relation TEXT NOT NULL,
            metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id) REFERENCES gest_nodes(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id) REFERENCES gest_nodes(id) ON DELETE CASCADE
        );

        CREATE INDEX IF NOT EXISTS idx_characters_project ON characters(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_locations_project ON locations(project_id, name);
        CREATE INDEX IF NOT EXISTS idx_episodes_project ON episodes(project_id, id);
        CREATE INDEX IF NOT EXISTS idx_minutes_episode ON minutes(project_id, episode_id, minute_number);
        CREATE INDEX IF NOT EXISTS idx_pages_episode ON pages(project_id, episode_id, page_number);
        CREATE INDEX IF NOT EXISTS idx_panels_minute ON panels(project_id, minute_id, panel_number);
        CREATE INDEX IF NOT EXISTS idx_panels_page ON panels(project_id, page_id, panel_number);
        CREATE INDEX IF NOT EXISTS idx_dialogue_panel ON dialogue_lines(project_id, panel_id);
        CREATE INDEX IF NOT EXISTS idx_assets_project ON assets(project_id, type);
        CREATE INDEX IF NOT EXISTS idx_canon_project ON canon_events(project_id, time_index);
        CREATE INDEX IF NOT EXISTS idx_warnings_project ON continuity_warnings(project_id, resolved, severity);
        CREATE INDEX IF NOT EXISTS idx_approvals_item ON approvals(project_id, item_type, item_id);
        CREATE INDEX IF NOT EXISTS idx_tool_calls_project ON tool_calls(project_id, timestamp);
        CREATE INDEX IF NOT EXISTS idx_pronunciations_project ON pronunciations(project_id, word);
        CREATE INDEX IF NOT EXISTS idx_character_assets_character ON character_assets(project_id, character_id);
        CREATE INDEX IF NOT EXISTS idx_gest_nodes_project ON gest_nodes(project_id, episode_id, node_type);
        CREATE INDEX IF NOT EXISTS idx_gest_edges_project ON gest_edges(project_id, source_id, target_id);
        CREATE INDEX IF NOT EXISTS idx_gest_edges_relation ON gest_edges(project_id, relation_class, relation);
        """
    )

    # Safe migrations for existing databases
    columns_query = cursor.execute("PRAGMA table_info(characters)").fetchall()
    column_names = [col["name"] for col in columns_query]
    if "primary_image_path" not in column_names:
        cursor.execute("ALTER TABLE characters ADD COLUMN primary_image_path TEXT;")
    if "voice_profile" not in column_names:
        cursor.execute("ALTER TABLE characters ADD COLUMN voice_profile TEXT;")

    panel_columns_query = cursor.execute("PRAGMA table_info(panels)").fetchall()
    panel_column_names = [col["name"] for col in panel_columns_query]
    if "page_id" not in panel_column_names:
        cursor.execute("ALTER TABLE panels ADD COLUMN page_id INTEGER;")

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

def delete_project(project_name):
    import shutil
    safe_name = safe_project_name(project_name)
    project_dir = Path(get_studio_projects_dir()) / safe_name
    if project_dir.exists():
        shutil.rmtree(project_dir)
        return True
    return False


def list_projects():
    projects_dir = Path(get_studio_projects_dir())
    projects = []
    for db_path in sorted(projects_dir.glob("*/studio.db")):
        try:
            conn = sqlite3.connect(db_path)
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
            conn.close()
        except sqlite3.Error:
            continue
        projects.extend(_rows_to_dicts(rows))
    projects.sort(key=lambda item: item.get("updated_at", ""), reverse=True)
    return projects


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


def add_character(project_name, project_id, name, description="", role="", archetype="", status="draft", primary_image_path=None, voice_profile=None, metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    name = _require_text(name, "Character name")
    status = _require_text(status, "Character status")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO characters (project_id, name, description, role, archetype, status, primary_image_path, voice_profile, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, name, description, role, archetype, status, primary_image_path, _json_dumps(voice_profile) if voice_profile else None, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    character_id = cursor.lastrowid
    conn.close()
    return character_id


def update_character(project_name, project_id, character_id, **fields):
    allowed = {"name", "description", "role", "archetype", "status", "primary_image_path", "voice_profile", "metadata"}
    updates = {key: value for key, value in fields.items() if key in allowed and value is not None}
    if not updates:
        return get_character(project_name, project_id, character_id)
    if "metadata" in updates:
        updates["metadata"] = _json_dumps(updates["metadata"])
    if "voice_profile" in updates and not isinstance(updates["voice_profile"], str):
        updates["voice_profile"] = _json_dumps(updates["voice_profile"])
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


def add_character_asset(project_name, project_id, character_id, asset_type, path, metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    character_id = _require_row(conn, "characters", project_id, character_id, "character_id")
    asset_type = _require_text(asset_type, "Asset type")
    path = _require_text(path, "Asset path")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO character_assets (project_id, character_id, asset_type, path, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, character_id, asset_type, path, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    asset_id = cursor.lastrowid
    conn.close()
    return asset_id


def get_character_assets(project_name, project_id, character_id=None):
    conn = get_connection(project_name)
    if character_id is None:
        rows = conn.execute("SELECT * FROM character_assets WHERE project_id = ? ORDER BY character_id ASC, id ASC", (project_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM character_assets WHERE project_id = ? AND character_id = ? ORDER BY id ASC",
            (project_id, character_id),
        ).fetchall()
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


def add_page(project_name, project_id, episode_id, page_number, title="", summary="", status="draft", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    episode_id = _require_row(conn, "episodes", project_id, episode_id, "episode_id")
    page_number = _require_int(page_number, "page_number")
    duplicate = conn.execute(
        "SELECT id FROM pages WHERE project_id = ? AND episode_id = ? AND page_number = ?",
        (project_id, episode_id, page_number),
    ).fetchone()
    if duplicate:
        conn.close()
        raise ValueError("A page with that number already exists for this episode.")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO pages (project_id, episode_id, page_number, title, summary, status, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, episode_id, page_number, title, summary, _require_text(status, "Page status"), _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    page_id = cursor.lastrowid
    conn.close()
    return page_id


def get_pages(project_name, project_id, episode_id=None):
    conn = get_connection(project_name)
    if episode_id is None:
        rows = conn.execute(
            "SELECT * FROM pages WHERE project_id = ? ORDER BY episode_id ASC, page_number ASC",
            (project_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM pages WHERE project_id = ? AND episode_id = ? ORDER BY page_number ASC",
            (project_id, episode_id),
        ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def ensure_page(project_name, project_id, episode_id, page_number, title="", summary="", metadata=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    episode_id = _require_row(conn, "episodes", project_id, episode_id, "episode_id")
    page_number = _require_int(page_number, "page_number")
    row = conn.execute(
        "SELECT id FROM pages WHERE project_id = ? AND episode_id = ? AND page_number = ?",
        (project_id, episode_id, page_number),
    ).fetchone()
    if row:
        conn.close()
        return row["id"]
    conn.close()
    return add_page(project_name, project_id, episode_id, page_number, title=title, summary=summary, metadata=metadata)


def add_panel(project_name, project_id, minute_id, panel_number, visual_description="", style_prompt="", metadata=None, page_id=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    minute_id = _require_row(conn, "minutes", project_id, minute_id, "minute_id")
    if page_id is not None:
        page_id = _require_row(conn, "pages", project_id, page_id, "page_id")
    panel_number = _require_int(panel_number, "panel_number")
    duplicate = conn.execute(
        """
        SELECT id FROM panels
        WHERE project_id = ?
          AND panel_number = ?
          AND ((page_id IS NOT NULL AND page_id = ?) OR (page_id IS NULL AND minute_id = ?))
        """,
        (project_id, panel_number, page_id, minute_id),
    ).fetchone()
    if duplicate:
        conn.close()
        raise ValueError("A panel with that number already exists for this page/minute.")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO panels (project_id, minute_id, page_id, panel_number, visual_description, style_prompt, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, minute_id, page_id, panel_number, visual_description, style_prompt, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    panel_id = cursor.lastrowid
    conn.close()
    return panel_id

def update_panel(project_name, project_id, panel_id, visual_description=None, metadata=None, page_id=None):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    panel_id = _require_row(conn, "panels", project_id, panel_id, "panel_id")
    now = utc_now()
    
    updates = ["updated_at = ?"]
    params = [now]
    
    if visual_description is not None:
        updates.append("visual_description = ?")
        params.append(visual_description)
    if metadata is not None:
        updates.append("metadata = ?")
        params.append(_json_dumps(metadata))
    if page_id is not None:
        page_id = _require_row(conn, "pages", project_id, page_id, "page_id")
        updates.append("page_id = ?")
        params.append(page_id)
        
    params.extend([project_id, panel_id])
    
    conn.execute(
        f"UPDATE panels SET {', '.join(updates)} WHERE project_id = ? AND id = ?",
        params
    )
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()
    return panel_id

def clear_dialogue_lines(project_name, project_id, panel_id):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    panel_id = _require_row(conn, "panels", project_id, panel_id, "panel_id")
    conn.execute("DELETE FROM dialogue_lines WHERE project_id = ? AND panel_id = ?", (project_id, panel_id))
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()


def get_panels(project_name, project_id, minute_id=None, page_id=None):
    conn = get_connection(project_name)
    if page_id is not None:
        rows = conn.execute(
            "SELECT * FROM panels WHERE project_id = ? AND page_id = ? ORDER BY panel_number ASC",
            (project_id, page_id),
        ).fetchall()
    elif minute_id is None:
        rows = conn.execute(
            """
            SELECT * FROM panels
            WHERE project_id = ?
            ORDER BY COALESCE(page_id, 0) ASC, minute_id ASC, panel_number ASC
            """,
            (project_id,),
        ).fetchall()
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
    elif item_type == "page":
        _require_row(conn, "pages", project_id, item_id, "item_id")
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


# --- GEST graph: nodes, edges, temporal validation -------------------------

def add_gest_node(project_name, project_id, node_type, label, ref_type=None, ref_id=None, episode_id=None, metadata=None):
    """Add a node (vertex) to the project's GEST graph.

    node_type is one of VALID_GEST_NODE_TYPES. ref_type/ref_id optionally link the node
    back to an existing row (e.g. a character or panel) for grounding.
    """
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    node_type = _require_choice(node_type, "node_type", VALID_GEST_NODE_TYPES)
    label = _require_text(label, "GEST node label")
    if episode_id is not None:
        episode_id = _require_row(conn, "episodes", project_id, episode_id, "episode_id")
    if ref_id is not None:
        ref_id = _require_int(ref_id, "ref_id")
    now = utc_now()
    cursor = conn.execute(
        """
        INSERT INTO gest_nodes (project_id, episode_id, node_type, label, ref_type, ref_id, metadata, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (project_id, episode_id, node_type, label, ref_type, ref_id, _json_dumps(metadata), now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    node_id = cursor.lastrowid
    conn.close()
    return node_id


def get_gest_nodes(project_name, project_id, episode_id=None):
    conn = get_connection(project_name)
    if episode_id is None:
        rows = conn.execute("SELECT * FROM gest_nodes WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM gest_nodes WHERE project_id = ? AND episode_id = ? ORDER BY id ASC",
            (project_id, episode_id),
        ).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def _ordered_pair(source_id, target_id, relation):
    """Normalize an ordering relation to a (precedes, follows) pair.

    'before' means source precedes target; 'after' means the reverse. This lets cycle
    detection operate on a single canonical precedence direction.
    """
    if relation == "after":
        return target_id, source_id
    return source_id, target_id


def _temporal_precedence_edges(conn, project_id):
    """Return existing precedence edges as a list of (precedes, follows) id pairs."""
    rows = conn.execute(
        "SELECT source_id, target_id, relation FROM gest_edges WHERE project_id = ? AND relation IN ('before', 'after')",
        (project_id,),
    ).fetchall()
    return [_ordered_pair(row["source_id"], row["target_id"], row["relation"]) for row in rows]


def _creates_temporal_cycle(edges, precedes, follows):
    """Return True if adding precedes->follows would create a cycle in the precedence graph.

    A cycle exists iff `follows` can already reach `precedes` through existing precedence
    edges (then the new edge closes the loop). Plain DFS reachability — the graphs here are
    small (a handful of events per reel), so an O(V+E) walk is more than sufficient.
    """
    if precedes == follows:
        return True
    adjacency = {}
    for a, b in edges:
        adjacency.setdefault(a, []).append(b)
    stack = [follows]
    seen = set()
    while stack:
        current = stack.pop()
        if current == precedes:
            return True
        if current in seen:
            continue
        seen.add(current)
        stack.extend(adjacency.get(current, []))
    return False


def add_gest_edge(project_name, project_id, source_id, target_id, relation, relation_class=None, metadata=None):
    """Add a directed edge to the GEST graph, enforcing simulator-valid constraints.

    The relation must be a known temporal/logical/semantic relation. For ordering temporal
    relations ('before'/'after') the edge is rejected with a ValueError if it would introduce
    a temporal cycle, so the resulting graph stays a valid DAG for execution.
    """
    conn = get_connection(project_name)
    try:
        project_id = _require_project(conn, project_id)
        source_id = _require_row(conn, "gest_nodes", project_id, source_id, "source_id")
        target_id = _require_row(conn, "gest_nodes", project_id, target_id, "target_id")
        if source_id == target_id:
            raise ValueError("A GEST edge cannot connect a node to itself.")
        relation = _require_text(relation, "relation").lower()
        if relation not in GEST_RELATION_CLASS:
            allowed = ", ".join(sorted(GEST_RELATION_CLASS))
            raise ValueError(f"relation must be one of: {allowed}.")
        derived_class = GEST_RELATION_CLASS[relation]
        if relation_class is not None and str(relation_class).strip().lower() != derived_class:
            raise ValueError(f"relation '{relation}' belongs to the '{derived_class}' class, not '{relation_class}'.")

        if relation in GEST_ORDERING_RELATIONS:
            precedes, follows = _ordered_pair(source_id, target_id, relation)
            existing = _temporal_precedence_edges(conn, project_id)
            if _creates_temporal_cycle(existing, precedes, follows):
                raise ValueError("Rejected GEST edge: it would create a temporal cycle.")

        now = utc_now()
        cursor = conn.execute(
            """
            INSERT INTO gest_edges (project_id, source_id, target_id, relation_class, relation, metadata, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, source_id, target_id, derived_class, relation, _json_dumps(metadata), now, now),
        )
        _touch_project(conn, project_id)
        conn.commit()
        edge_id = cursor.lastrowid
        return edge_id
    finally:
        conn.close()


def get_gest_edges(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM gest_edges WHERE project_id = ? ORDER BY id ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_gest_graph(project_name, project_id):
    """Return the full GEST graph for a project as {nodes, edges}."""
    return {
        "nodes": get_gest_nodes(project_name, project_id),
        "edges": get_gest_edges(project_name, project_id),
    }


def compute_gest_timeline(project_name, project_id):
    """Resolve the GEST graph's temporal ordering into a single execution timeline.

    Only the ordering relations (before/after) constrain the sequence; 'after' is
    normalized to a 'precedes' edge in the opposite direction. A deterministic
    Kahn topological sort (ties broken by node id) yields the execution order.
    If the order cannot include every node a temporal cycle exists, so the graph
    is reported invalid. Returns ``{valid, has_cycle, order, node_count}``.
    """
    nodes = get_gest_nodes(project_name, project_id)
    edges = get_gest_edges(project_name, project_id)
    ids = [node["id"] for node in nodes]
    indegree = {node_id: 0 for node_id in ids}
    adjacency = {node_id: [] for node_id in ids}

    for edge in edges:
        if edge["relation"] not in ("before", "after"):
            continue
        if edge["relation"] == "before":
            precedes, follows = edge["source_id"], edge["target_id"]
        else:
            precedes, follows = edge["target_id"], edge["source_id"]
        if precedes in adjacency and follows in indegree:
            adjacency[precedes].append(follows)
            indegree[follows] += 1

    import heapq
    ready = [node_id for node_id in ids if indegree[node_id] == 0]
    heapq.heapify(ready)
    order = []
    while ready:
        node_id = heapq.heappop(ready)
        order.append(node_id)
        for follows in sorted(adjacency[node_id]):
            indegree[follows] -= 1
            if indegree[follows] == 0:
                heapq.heappush(ready, follows)

    valid = len(order) == len(ids)
    return {"valid": valid, "has_cycle": not valid, "order": order, "node_count": len(ids)}


def set_pronunciation(project_name, project_id, word, phonemes):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    word = _require_text(word, "word")
    phonemes = _require_text(phonemes, "phonemes")
    now = utc_now()
    conn.execute(
        """
        INSERT INTO pronunciations (project_id, word, phonemes, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(project_id, word) DO UPDATE SET phonemes = excluded.phonemes, updated_at = excluded.updated_at
        """,
        (project_id, word, phonemes, now, now),
    )
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()


def get_pronunciations(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT * FROM pronunciations WHERE project_id = ? ORDER BY word ASC", (project_id,)).fetchall()
    conn.close()
    return _rows_to_dicts(rows)


def get_pronunciation_dict(project_name, project_id):
    conn = get_connection(project_name)
    rows = conn.execute("SELECT word, phonemes FROM pronunciations WHERE project_id = ?", (project_id,)).fetchall()
    conn.close()
    return {row["word"]: row["phonemes"] for row in rows}


def delete_pronunciation(project_name, project_id, word):
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    conn.execute("DELETE FROM pronunciations WHERE project_id = ? AND word = ?", (project_id, word))
    _touch_project(conn, project_id)
    conn.commit()
    conn.close()


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
        "character_assets": get_character_assets(project_name, project_id),
        "locations": get_locations(project_name, project_id),
        "episodes": get_episodes(project_name, project_id),
        "pages": get_pages(project_name, project_id),
        "minutes": get_minutes(project_name, project_id),
        "panels": get_panels(project_name, project_id),
        "dialogue_lines": get_dialogue_lines(project_name, project_id),
        "assets": get_assets(project_name, project_id),
        "canon_events": get_canon_events(project_name, project_id),
        "continuity_warnings": get_continuity_warnings(project_name, project_id),
        "approvals": get_approvals(project_name, project_id),
        "tool_calls": get_tool_calls(project_name, project_id),
        "pronunciations": get_pronunciations(project_name, project_id),
        "gest": get_gest_graph(project_name, project_id),
    }
