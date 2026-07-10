"""Shared state helpers for the BetterFingers multi-session collab workspace.

All state lives in .claude/collab/ (gitignored):
  sessions.json   {claude_pid: {name, focus, started, last_seen}}
  claims.json     {repo_rel_path: {session, claude_pid, reason, ts}}
  messages.jsonl  one JSON object per line: {ts, from, kind, text, to}
  cursors/<pid>   byte offset into messages.jsonl already delivered to that session
  viewer.pid      pid of the running viewer HTTP server

Sessions are identified by the PID of the `claude` process that spawned the
MCP server / hook (os.getppid() in both cases), so hooks and MCP tools agree
on identity without any handshake. A session is "live" iff its PID is alive.
"""
import fcntl
import json
import os
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WS = REPO_ROOT / ".claude" / "collab"
LOCKFILE = WS / ".lock"
SESSIONS = WS / "sessions.json"
CLAIMS = WS / "claims.json"
MESSAGES = WS / "messages.jsonl"
CURSORS = WS / "cursors"
VIEWER_PID = WS / "viewer.pid"
VIEWER_PORT = 4517


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


def alive(pid):
    try:
        os.kill(int(pid), 0)
    except (OSError, ValueError):
        return False
    try:  # a zombie answers kill(0) but is dead for our purposes
        with open(f"/proc/{int(pid)}/stat") as fh:
            return fh.read().rsplit(")", 1)[1].split()[0] != "Z"
    except OSError:
        return False


def my_claude_pid():
    """Nearest 'claude' ancestor pid — the session identity.

    The MCP server is a direct child of the claude CLI, but hook commands run
    under a shell wrapper (claude -> sh -> python3), and Bash-tool scripts run
    even deeper. A bare getppid() therefore gives DIFFERENT answers in the MCP
    server vs hooks, making a session's own claims look foreign (self-blocking
    writes). Walking up /proc to the first ancestor named 'claude' makes every
    process in the session converge on the same identity.
    """
    pid = os.getppid()
    p = pid
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
        if comm == "claude":
            return str(p)
        p = ppid
    return str(pid)


def get_sessions(prune=True):
    sessions = _read_json(SESSIONS, {})
    if prune:
        livemap = {p: s for p, s in sessions.items() if alive(p)}
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
    pid = my_claude_pid()
    with locked():
        sessions = get_sessions()
        sessions[pid] = {
            "name": name,
            "focus": focus,
            "started": sessions.get(pid, {}).get("started", time.time()),
            "last_seen": time.time(),
        }
        _write_json(SESSIONS, sessions)
    return pid, sessions


def heartbeat():
    pid = my_claude_pid()
    with locked():
        sessions = get_sessions()
        if pid in sessions:
            sessions[pid]["last_seen"] = time.time()
            _write_json(SESSIONS, sessions)
        return sessions, pid


def session_name(pid=None):
    pid = pid or my_claude_pid()
    s = get_sessions(prune=False).get(str(pid))
    return s["name"] if s else f"session-{pid}"


def get_claims():
    with locked():
        get_sessions()  # prunes dead sessions' claims too
        return _read_json(CLAIMS, {})


def claim_paths(paths, reason):
    """Claim repo-relative paths. Returns (granted, conflicts)."""
    pid = my_claude_pid()
    granted, conflicts = [], {}
    with locked():
        sessions = get_sessions()
        claims = _read_json(CLAIMS, {})
        for p in paths:
            p = normalize(p)
            holder = claims.get(p)
            if holder and str(holder["claude_pid"]) != pid and str(holder["claude_pid"]) in sessions:
                conflicts[p] = holder
            else:
                claims[p] = {
                    "session": session_name(pid),
                    "claude_pid": pid,
                    "reason": reason,
                    "ts": time.time(),
                }
                granted.append(p)
        _write_json(CLAIMS, claims)
    return granted, conflicts


def release_paths(paths=None):
    """Release given paths (or all of this session's claims if None)."""
    pid = my_claude_pid()
    released = []
    with locked():
        claims = _read_json(CLAIMS, {})
        targets = [normalize(p) for p in paths] if paths else [
            f for f, c in claims.items() if str(c["claude_pid"]) == pid
        ]
        for p in targets:
            if p in claims and str(claims[p]["claude_pid"]) == pid:
                del claims[p]
                released.append(p)
        _write_json(CLAIMS, claims)
    return released


def claim_holder(path):
    """Return the live claim on path held by ANOTHER session, or None."""
    path = normalize(path)
    pid = my_claude_pid()
    with locked():
        sessions = get_sessions()
        claims = _read_json(CLAIMS, {})
    c = claims.get(path)
    if c and str(c["claude_pid"]) != pid and str(c["claude_pid"]) in sessions:
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
    pid = my_claude_pid()
    cursor_file = CURSORS / pid
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
    me = session_name(pid)
    return [m for m in msgs if m.get("from") != me and m.get("to") in (None, me)]


def all_messages(limit=200):
    try:
        lines = MESSAGES.read_text().splitlines()[-limit:]
        return [json.loads(l) for l in lines if l.strip()]
    except (OSError, ValueError):
        return []


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
