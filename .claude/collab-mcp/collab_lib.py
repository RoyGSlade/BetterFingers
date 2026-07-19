"""Shared state helpers for the BetterFingers multi-session collab workspace.

All state lives in .claude/collab/ (gitignored):
  sessions.json   {session_id: {name, focus, started, last_seen}}
  claims.json     {repo_rel_path: {session, claude_pid, reason, ts}}
  messages.jsonl  one JSON object per line: {ts, from, kind, text, to}
  cursors/<id>    byte offset into messages.jsonl already delivered to that session
  viewer.pid      pid of the running viewer HTTP server
  backlog/        message logs archived by clear_messages (collab_clear)

Sessions are identified client-neutrally (see my_session_id()) so both Claude
Code and Codex CLI converge on one identity without a handshake:

  1. An explicit COLLAB_SESSION_ID env var, if set (identity "env:<value>").
     Any launcher (Claude, Codex, a script) can set this once and every child
     process — MCP server, hook scripts — inherits it, guaranteeing agreement
     even when process ancestry is unusual (containers, remote executors).
  2. Otherwise, the nearest ancestor process named "claude" or "codex" (walked
     via /proc), same trick the original Claude-only implementation used to
     make the MCP server (direct child) and hook scripts (grandchild, via a
     shell wrapper) agree despite different getppid() answers.

`claims.json` keeps the historical field name `claude_pid` for backward
compatibility (existing readers only ever compare it as an opaque string);
its value is now either a numeric pid string or an "env:"-prefixed string.

A pid-identified session is "live" iff its PID is alive (os.kill(pid, 0)).
An "env:"-identified session has no OS pid to poll, so it's "live" iff it
heartbeated within ENV_SESSION_TIMEOUT_S — hooks call heartbeat() on every
event, so any active session refreshes this well inside the window.

COLLAB_WS_DIR / COLLAB_VIEWER_PORT env overrides exist so tests (and any
other tooling that needs an isolated workspace) never have to swap the real
.claude/collab/ directory out from under a live room to get isolation — that
swap-based approach was tried once (test_collab.py's original design) and is
NOT safe against a concurrently running second collab process touching the
same real path; see the C0.1 handoff for the incident that prompted this.
"""
import fcntl
import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WS = Path(os.environ["COLLAB_WS_DIR"]) if os.environ.get("COLLAB_WS_DIR") else REPO_ROOT / ".claude" / "collab"
LOCKFILE = WS / ".lock"
SESSIONS = WS / "sessions.json"
CLAIMS = WS / "claims.json"
MESSAGES = WS / "messages.jsonl"
CURSORS = WS / "cursors"
BACKLOG = WS / "backlog"
VIEWER_PID = WS / "viewer.pid"
VIEWER_PORT = int(os.environ.get("COLLAB_VIEWER_PORT", "4517"))

# Ancestor process names that identify a supported collab client.
CLIENT_COMMS = ("claude", "codex")

# "env:"-identified sessions (no OS pid to poll) are considered live if they
# heartbeated within this many seconds. Hooks heartbeat on every event, so an
# actively-working session refreshes this constantly; it only matters for
# detecting a session that's gone quiet.
ENV_SESSION_TIMEOUT_S = 15 * 60


def ensure_ws():
    CURSORS.mkdir(parents=True, exist_ok=True)


class locked:
    """Cross-process mutex around all state mutations."""

    def __enter__(self):
        ensure_ws()
        self.fh = open(LOCKFILE, "w")
        fcntl.flock(self.fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self.fh, fcntl.LOCK_UN)
        self.fh.close()


def _read_json(path, default):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return default


def _write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    tmp.replace(path)


def alive(session_id, last_seen=None):
    sid = str(session_id)
    if sid.startswith("env:"):
        return last_seen is not None and (time.time() - last_seen) < ENV_SESSION_TIMEOUT_S
    try:
        pid = int(sid)
    except ValueError:
        return False
    try:
        os.kill(pid, 0)
    except (OSError, ValueError):
        return False
    try:  # a zombie answers kill(0) but is dead for our purposes
        with open(f"/proc/{pid}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def _nearest_client_ancestor_pid(start_pid):
    """Walk /proc ancestry from start_pid for the nearest process named
    'claude' or 'codex'. Returns its pid as a string, or str(start_pid) if
    none is found (bounded walk, tolerant of /proc read races — see
    my_session_id())."""
    p = start_pid
    for _ in range(20):
        if p <= 1:
            break
        try:
            with open(f"/proc/{p}/comm") as fh:
                comm = fh.read().strip()
            with open(f"/proc/{p}/stat") as fh:
                ppid = int(fh.read().rsplit(")", 1)[1].split()[1])
        except (OSError, ValueError, IndexError):
            break
        if comm in CLIENT_COMMS:
            return str(p)
        p = ppid
    return str(start_pid)


def my_session_id():
    """Client-neutral session identity — works for both Claude Code and Codex.

    1. COLLAB_SESSION_ID env var, if set: an explicit identity the launcher
       supplied. Every child process (MCP server, hook scripts) inherits the
       parent's environment, so this is the most reliable way to agree on
       identity regardless of client or process-tree shape.
    2. Otherwise, the nearest ancestor process named 'claude' or 'codex' (see
       _nearest_client_ancestor_pid). The MCP server is a direct child of the
       CLI, but hook commands run under a shell wrapper (client -> sh ->
       python3), and Bash-tool scripts run even deeper. A bare getppid()
       therefore gives DIFFERENT answers in the MCP server vs hooks, making a
       session's own claims look foreign (self-blocking writes). Walking up
       /proc to the first ancestor named 'claude' or 'codex' makes every
       process in the session converge on the same identity.
    """
    explicit = os.environ.get("COLLAB_SESSION_ID", "").strip()
    if explicit:
        return f"env:{explicit}"
    return _nearest_client_ancestor_pid(os.getppid())


# Backward-compatible alias — existing callers (and this module's own prior
# behavior for Claude sessions) keep working unchanged.
my_claude_pid = my_session_id


def get_sessions(prune=True):
    sessions = _read_json(SESSIONS, {})
    if prune:
        livemap = {p: s for p, s in sessions.items() if alive(p, s.get("last_seen"))}
        if len(livemap) != len(sessions):
            _write_json(SESSIONS, livemap)
            # drop claims held by dead sessions
            claims = _read_json(CLAIMS, {})
            kept = {f: c for f, c in claims.items() if str(c.get("claude_pid")) in livemap}
            if len(kept) != len(claims):
                _write_json(CLAIMS, kept)
        return livemap
    return sessions


def register_session(name, focus):
    sid = my_session_id()
    with locked():
        sessions = get_sessions()
        sessions[sid] = {
            "name": name,
            "focus": focus,
            "started": sessions.get(sid, {}).get("started", time.time()),
            "last_seen": time.time(),
        }
        _write_json(SESSIONS, sessions)
    return sid, sessions


def heartbeat():
    sid = my_session_id()
    with locked():
        sessions = get_sessions()
        if sid in sessions:
            sessions[sid]["last_seen"] = time.time()
            _write_json(SESSIONS, sessions)
        return sessions, sid


def session_name(sid=None):
    sid = sid or my_session_id()
    s = get_sessions(prune=False).get(str(sid))
    return s["name"] if s else f"session-{sid}"


def get_claims():
    with locked():
        get_sessions()  # prunes dead sessions' claims too
        return _read_json(CLAIMS, {})


def claim_paths(paths, reason):
    """Claim repo-relative paths. Returns (granted, conflicts)."""
    sid = my_session_id()
    granted, conflicts = [], {}
    with locked():
        sessions = get_sessions()
        claims = _read_json(CLAIMS, {})
        for p in paths:
            p = normalize(p)
            holder = claims.get(p)
            if holder and str(holder["claude_pid"]) != sid and str(holder["claude_pid"]) in sessions:
                conflicts[p] = holder
            else:
                claims[p] = {
                    "session": session_name(sid),
                    "claude_pid": sid,
                    "reason": reason,
                    "ts": time.time(),
                }
                granted.append(p)
        _write_json(CLAIMS, claims)
    return granted, conflicts


def release_paths(paths=None):
    """Release given paths (or all of this session's claims if None)."""
    sid = my_session_id()
    released = []
    with locked():
        claims = _read_json(CLAIMS, {})
        targets = [normalize(p) for p in paths] if paths else [
            f for f, c in claims.items() if str(c["claude_pid"]) == sid
        ]
        for p in targets:
            if p in claims and str(claims[p]["claude_pid"]) == sid:
                del claims[p]
                released.append(p)
        _write_json(CLAIMS, claims)
    return released


def claim_holder(path):
    """Return the live claim on path held by ANOTHER session, or None."""
    path = normalize(path)
    sid = my_session_id()
    with locked():
        sessions = get_sessions()
        claims = _read_json(CLAIMS, {})
    c = claims.get(path)
    if c and str(c["claude_pid"]) != sid and str(c["claude_pid"]) in sessions:
        return c
    return None


def normalize(path):
    p = Path(path)
    if p.is_absolute():
        try:
            p = p.resolve().relative_to(REPO_ROOT)
        except ValueError:
            pass
    return str(p)


def post_message(kind, text, to=None, sender=None):
    ensure_ws()
    msg = {
        "ts": time.time(),
        "from": sender or session_name(),
        "kind": kind,  # info | urgent | question | handoff | system
        "text": text,
        "to": to,
    }
    with locked():
        with open(MESSAGES, "a") as fh:
            fh.write(json.dumps(msg) + "\n")
    return msg


def read_new_messages(mark_read=True):
    """Messages appended since this session's cursor, excluding its own."""
    ensure_ws()
    sid = my_session_id()
    # ":" (from an "env:"-prefixed identity) isn't a safe filename character
    # on every filesystem this repo targets (Windows builds), so sanitize it
    # for the cursor filename only — the raw sid is still used as identity.
    cursor_file = CURSORS / sid.replace(":", "_")
    try:
        offset = int(cursor_file.read_text())
    except (OSError, ValueError):
        offset = 0
    msgs = []
    try:
        with open(MESSAGES) as fh:
            fh.seek(offset)
            for line in fh:
                try:
                    msgs.append(json.loads(line))
                except ValueError:
                    pass
            end = fh.tell()
    except OSError:
        return []
    if mark_read:
        cursor_file.write_text(str(end))
    me = session_name(sid)
    return [m for m in msgs if m.get("from") != me and m.get("to") in (None, me)]


def all_messages(limit=200):
    try:
        lines = MESSAGES.read_text().splitlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()]
    except (OSError, ValueError):
        return []


def clear_messages(mode="archive", note=None):
    """Clear the shared message log so new sessions start with a quiet room.

    mode="archive" (default) saves the current log to backlog/ first so
    nothing is lost; mode="discard" drops it outright. Every session's read
    cursor is deleted so all sessions agree on the fresh log (a surviving
    cursor could point past EOF and silently skip future messages). Posts a
    system notice recording who cleared, how many messages, and where the
    archive went. Returns (cleared_count, archive_path_or_None)."""
    who = session_name()
    with locked():
        try:
            raw = MESSAGES.read_text()
        except OSError:
            raw = ""
        count = sum(1 for line in raw.splitlines() if line.strip())
        archive = None
        if mode == "archive" and count:
            BACKLOG.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            archive = BACKLOG / f"messages-{stamp}.jsonl"
            n = 1
            while archive.exists():
                n += 1
                archive = BACKLOG / f"messages-{stamp}.{n}.jsonl"
            archive.write_text(raw)
        MESSAGES.write_text("")
        for cursor in CURSORS.glob("*"):
            try:
                cursor.unlink()
            except OSError:
                pass
    if count:
        detail = f"archived to {archive}" if archive else "discarded"
        text = f"chat cleared by {who}: {count} message(s) {detail}"
        if note:
            text += f" — {note}"
        post_message("system", text, sender="workspace")
    return count, (str(archive) if archive else None)


def list_backlog():
    """Archived message logs saved by clear_messages, oldest first."""
    entries = []
    for p in sorted(BACKLOG.glob("messages-*.jsonl")):
        try:
            n = sum(1 for line in p.read_text().splitlines() if line.strip())
        except OSError:
            n = 0
        entries.append({"file": str(p), "messages": n})
    return entries


def viewer_running():
    try:
        pid = int(VIEWER_PID.read_text())
        return alive(pid)
    except (OSError, ValueError):
        return False


def start_viewer_if_needed():
    """Start the live viewer when >=2 sessions are active. Returns URL or None."""
    import subprocess, sys
    if len(get_sessions()) < 2:
        return None
    url = f"http://localhost:{VIEWER_PORT}"
    if viewer_running():
        return url
    viewer = Path(__file__).parent / "viewer.py"
    proc = subprocess.Popen(
        [sys.executable, str(viewer)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    VIEWER_PID.write_text(str(proc.pid))
    return url
