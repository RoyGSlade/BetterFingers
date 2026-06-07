"""
StudioBlackboard — the shared state surface specialist agents read and write.

Instead of agents calling each other directly, each specialist publishes its result as a typed
*artifact* on the blackboard and posts a short status note. The Producer schedules an agent only
once the artifacts it depends on are present. This is the asynchronous-blackboard pattern from
docs/agent_blackboard.md, scoped to story production and persisted in the project SQLite so a run
is inspectable and resumable.

Artifacts are keyed (e.g. "premise", "world", "characters", "treatment", "beats", "shots",
"panels", "continuity") and versioned; posts are an append-only log of `[AGENT] STATUS: topic`.
"""

import studio_memory as memory
from studio_memory import get_connection, utc_now, _json_dumps, _json_loads, _row_to_dict, _require_project


def put_artifact(project_name, project_id, key, content, produced_by="", status="ready"):
    """Create or replace an artifact, bumping its version on update."""
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    now = utc_now()
    existing = conn.execute(
        "SELECT version FROM blackboard_artifacts WHERE project_id = ? AND key = ?",
        (project_id, key),
    ).fetchone()
    payload = _json_dumps(content)
    if existing:
        conn.execute(
            "UPDATE blackboard_artifacts SET content = ?, produced_by = ?, status = ?, "
            "version = version + 1, updated_at = ? WHERE project_id = ? AND key = ?",
            (payload, produced_by, status, now, project_id, key),
        )
    else:
        conn.execute(
            "INSERT INTO blackboard_artifacts (project_id, key, produced_by, status, content, "
            "version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, 1, ?, ?)",
            (project_id, key, produced_by, status, payload, now, now),
        )
    conn.commit()
    conn.close()


def get_artifact(project_name, project_id, key):
    """Return the artifact's parsed content, or None if absent."""
    conn = get_connection(project_name)
    row = conn.execute(
        "SELECT content FROM blackboard_artifacts WHERE project_id = ? AND key = ?",
        (project_id, key),
    ).fetchone()
    conn.close()
    if not row:
        return None
    return _json_loads(row["content"], default=None)


def list_artifacts(project_name, project_id):
    """Return a summary (key, status, version, produced_by) of every artifact."""
    conn = get_connection(project_name)
    rows = conn.execute(
        "SELECT key, produced_by, status, version, updated_at FROM blackboard_artifacts "
        "WHERE project_id = ? ORDER BY updated_at",
        (project_id,),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def has_all(project_name, project_id, keys):
    """True when every key is present with status 'ready' (dependency gate)."""
    if not keys:
        return True
    conn = get_connection(project_name)
    placeholders = ",".join("?" for _ in keys)
    rows = conn.execute(
        f"SELECT key FROM blackboard_artifacts WHERE project_id = ? AND status = 'ready' "
        f"AND key IN ({placeholders})",
        (project_id, *keys),
    ).fetchall()
    conn.close()
    return {r["key"] for r in rows} >= set(keys)


def post(project_name, project_id, agent, status, topic="", detail=""):
    """Append a status post (the agent message log)."""
    conn = get_connection(project_name)
    project_id = _require_project(conn, project_id)
    conn.execute(
        "INSERT INTO blackboard_posts (project_id, agent, status, topic, detail, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (project_id, agent, status, topic, detail, utc_now()),
    )
    conn.commit()
    conn.close()


def get_posts(project_name, project_id, limit=200):
    """Return the most recent status posts in chronological order."""
    conn = get_connection(project_name)
    rows = conn.execute(
        "SELECT agent, status, topic, detail, created_at FROM blackboard_posts "
        "WHERE project_id = ? ORDER BY id DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in reversed(rows)]
