"""Shared state helpers for the BetterFingers multi-session collab workspace.

State is split between the repo-global ROOT and per-tier ROOMS to support the
director -> supervisor -> worker hierarchy:

ROOT (.claude/collab/ — shared by every room in the repo, gitignored):
  claims.json     {repo_rel_path: {session, claude_pid, reason, ts}} — GLOBAL,
                  so two supervisors' workers can never edit the same file
  fleet.json      every spawned session across all rooms; the model-family
                  caps (2 Opus / 4 Sonnet running) are enforced against this
  spawn-logs/     stdout+stderr of each spawned session, one log per launch
  rooms/<name>-<generation>/ a supervisor's private, non-reused room

Per room (the ROOT dir doubles as the director's room):
  sessions.json   {session_id: {name, focus, started, last_seen}}
  messages.jsonl  one JSON object per line: {ts, from, kind, text, to}
  cursors/<id>    byte offset into messages.jsonl already delivered to that session
  viewer.pid      pid of the running viewer HTTP server
  backlog/        message logs archived by clear_messages (collab_clear)
  spawns.json     {name: {pid, model, role, ...}} sessions THIS room spawned
  stop-state/<id> consecutive quiet Stop-hook blocks (wake/keepalive bookkeeping)

Room wiring env vars (set automatically by spawn_worker for children):
  COLLAB_WS_DIR         the room this session talks in (default: ROOT)
  COLLAB_ROOT_DIR       repo-global state dir (default: COLLAB_WS_DIR if that
                        is set — keeps tests fully isolated — else .claude/collab)
  COLLAB_PARENT_WS_DIR  the spawner's room, for collab_report_up/check_up
  COLLAB_PARENT_NAME    the spawner's session name (default report_up target)

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
import hashlib
import json
import os
import re
import secrets
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
WS = Path(os.environ["COLLAB_WS_DIR"]) if os.environ.get("COLLAB_WS_DIR") else REPO_ROOT / ".claude" / "collab"
# Repo-global state (claims, fleet, lock). When COLLAB_WS_DIR is set without
# COLLAB_ROOT_DIR (tests, ad-hoc rooms) the root follows the room so nothing
# leaks outside the isolated workspace.
ROOT_WS = Path(os.environ["COLLAB_ROOT_DIR"]) if os.environ.get("COLLAB_ROOT_DIR") else WS
PARENT_WS = Path(os.environ["COLLAB_PARENT_WS_DIR"]) if os.environ.get("COLLAB_PARENT_WS_DIR") else None
PARENT_NAME = os.environ.get("COLLAB_PARENT_NAME") or None
ROOMS = ROOT_WS / "rooms"

LOCKFILE = ROOT_WS / ".lock"
CLAIMS = ROOT_WS / "claims.json"
FLEET = ROOT_WS / "fleet.json"
SPAWN_LOGS = ROOT_WS / "spawn-logs"

SESSIONS = WS / "sessions.json"
MESSAGES = WS / "messages.jsonl"
CURSORS = WS / "cursors"
BACKLOG = WS / "backlog"
VIEWER_PID = WS / "viewer.pid"
VIEWER_PORT = int(os.environ.get("COLLAB_VIEWER_PORT", "4517"))
SPAWNS = WS / "spawns.json"
STOPSTATE = WS / "stop-state"

# Fleet policy (user-approved budget): concurrently-RUNNING spawned sessions
# are capped per model family across the whole repo (every room combined):
# at most 2 Opus (supervisors) and 4 Sonnet (workers). Models outside those
# families fall back to the legacy MAX_SPAWNS cap.
MAX_OPUS = int(os.environ.get("COLLAB_MAX_OPUS", "2"))
MAX_SONNET = int(os.environ.get("COLLAB_MAX_SONNET", "4"))
MAX_SPAWNS = int(os.environ.get("COLLAB_MAX_SPAWNS", "2"))
SPAWN_MODEL = os.environ.get("COLLAB_SPAWN_MODEL", "claude-opus-5")
SPAWN_EFFORT = os.environ.get("COLLAB_SPAWN_EFFORT", "medium")
SPAWN_HEALTHCHECK_S = float(os.environ.get("COLLAB_SPAWN_HEALTHCHECK_S", "0.35"))
SPAWN_RETENTION_DAYS = int(os.environ.get("COLLAB_SPAWN_RETENTION_DAYS", "14"))

# Default headless contract: manual mode plus an explicit allowlist permits
# listed tools without an interactive prompt; unlisted actions cannot silently
# expand the session's authority in a headless run. The defaults cover ordinary
# repo reads/edits and narrowly matched verification commands. Callers may
# replace this list for one spawn. Full permission bypass is a separate,
# explicit permission_mode.
TASK_SAFE_ALLOWED_TOOLS = (
    "Read",
    "Glob",
    "Grep",
    "Edit",
    "Write",
    "Bash(git diff *)",
    "Bash(git status *)",
    "Bash(python3 -m py_compile *)",
    "Bash(python3 -m pytest *)",
    "Bash(python -m pytest *)",
    # The qualified interpreter lives in .venv; system python3 lacks the
    # project deps (Wave 8A finding — a lane had to smuggle site-packages in
    # through a pytest plugin because these two were missing).
    "Bash(.venv/bin/python -m pytest *)",
    "Bash(.venv/bin/python -m py_compile *)",
    # Repo tooling and the Electron QA runner. Wave 11C finding: a lane asked
    # to make a QA area pass standalone could not run that area at all, and a
    # lane owning a generated ledger could not invoke its own generator except
    # through `python3 -` stdin. Verification a lane cannot perform is
    # verification the director inherits by default.
    "Bash(python3 tools/*)",
    "Bash(node tests/qa/run.mjs *)",
    "Bash(node app/tests/qa/run.mjs *)",
    "Bash(npm --prefix app run *)",
    "Bash(npm test *)",
    "Bash(npm run test *)",
    # `npm run test *` only matches a script literally named "test"; this
    # repo's renderer suite is "test:unit" (Wave 1 finding — three sessions
    # were unable to run any test and honestly reported UNRUN).
    "Bash(npm run test:*)",
    "Bash(node --test *)",
    "Bash(npx vitest *)",
    "mcp__collab__collab_register",
    "mcp__collab__collab_status",
    "mcp__collab__collab_inbox",
    "mcp__collab__collab_claim",
    "mcp__collab__collab_release",
    "mcp__collab__collab_post",
    "mcp__collab__collab_report_up",
    "mcp__collab__collab_check_up",
    "mcp__collab__collab_spawn",
    "mcp__collab__collab_workers",
    "mcp__collab__collab_fleet",
    "mcp__collab__collab_wait",
    "mcp__collab__collab_stop",
)
PERMISSION_MODES = ("taskSafe", "acceptEdits", "auto", "manual", "bypassPermissions")

# Hierarchy role presets for spawn_worker. A supervisor gets a fresh room under
# rooms/<name>-<generation>/ (its workers report there); a worker joins the
# spawner's room.
ROLES = {
    "supervisor": {"model": "claude-opus-5", "effort": "medium"},
    "worker": {"model": "claude-sonnet-5", "effort": "medium"},
}

# Message kinds that should wake a sleeping/finishing session (see hooks.py
# stop/post_tool) — plus any message whose text starts with WAKE_CODE.
WAKE_KINDS = ("urgent", "wake")
WAKE_CODE = "WAKE:"

# Human-facing names are routing keys inside a room, so keep them deliberately
# small and unambiguous. Pseudo-claims are virtual repo-wide mutexes rather
# than filesystem paths (for example, the expensive full test suite).
SESSION_NAME_MAX = 48
SESSION_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
PSEUDO_CLAIM_RE = re.compile(r"^__[A-Za-z0-9][A-Za-z0-9_-]*__$")
SESSION_ID_MAX = 128
SESSION_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@-]*$")
_PRIVACY_MIGRATED = False


def model_family(model):
    m = (model or "").lower()
    for fam in ("opus", "sonnet", "haiku"):
        if fam in m:
            return fam
    return "other"


def family_cap(fam):
    return {"opus": MAX_OPUS, "sonnet": MAX_SONNET}.get(fam, MAX_SPAWNS)

# Ancestor process names that identify a supported collab client.
CLIENT_COMMS = ("claude", "codex")

# "env:"-identified sessions (no OS pid to poll) are considered live if they
# heartbeated within this many seconds. Hooks heartbeat on every event, so an
# actively-working session refreshes this constantly; it only matters for
# detecting a session that's gone quiet.
ENV_SESSION_TIMEOUT_S = 15 * 60


def _inside_root(path):
    """True only when path resolves at or below ROOT_WS."""
    try:
        Path(path).resolve(strict=False).relative_to(ROOT_WS.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _chmod_private(path, mode):
    """chmod a non-symlink only inside ROOT_WS; never cross the state boundary."""
    path = Path(path)
    try:
        if path.is_symlink() or not _inside_root(path):
            return
        os.chmod(path, mode)
    except OSError:
        pass


def _private_dir(path):
    path = Path(path)
    if not _inside_root(path):
        raise RuntimeError(f"collab state path escapes ROOT_WS: {path}")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private(path, 0o700)
    return path


def _private_file(path):
    _chmod_private(path, 0o600)
    return Path(path)


def _migrate_privacy():
    """Tighten legacy collab state without following links or leaving ROOT_WS."""
    global _PRIVACY_MIGRATED
    if _PRIVACY_MIGRATED:
        return
    root = ROOT_WS.resolve(strict=False)
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    _chmod_private(root, 0o700)
    for current, dirs, files in os.walk(root, topdown=True, followlinks=False):
        current_path = Path(current)
        dirs[:] = [d for d in dirs if not (current_path / d).is_symlink()]
        _chmod_private(current_path, 0o700)
        for directory in dirs:
            _chmod_private(current_path / directory, 0o700)
        for filename in files:
            _chmod_private(current_path / filename, 0o600)
    _PRIVACY_MIGRATED = True


def ensure_ws():
    if not _inside_root(WS):
        raise RuntimeError(f"COLLAB_WS_DIR must be inside COLLAB_ROOT_DIR: {WS}")
    if PARENT_WS is not None and not _inside_root(PARENT_WS):
        raise RuntimeError(f"COLLAB_PARENT_WS_DIR must be inside COLLAB_ROOT_DIR: {PARENT_WS}")
    _migrate_privacy()
    _private_dir(WS)
    _private_dir(CURSORS)


class locked:
    """Cross-process mutex around all state mutations."""

    def __enter__(self):
        ensure_ws()
        self.fh = open(LOCKFILE, "w")
        _private_file(LOCKFILE)
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
    path = Path(path)
    if not _inside_root(path):
        raise RuntimeError(f"refusing to write collab metadata outside ROOT_WS: {path}")
    _private_dir(Path(path).parent)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=1))
    _private_file(tmp)
    tmp.replace(path)
    _private_file(path)


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


def process_identity(pid):
    """Stable Linux process identity for PID-reuse-safe spawned-session state.

    A PID alone is not authority: it may be recycled after the recorded child
    exits. Pair the kernel start-time ticks with this boot's id. None means the
    process cannot be proved to be the recorded one.
    """
    try:
        pid = int(pid)
        with open(f"/proc/{pid}/stat") as fh:
            fields = fh.read().rsplit(")", 1)[1].split()
        if fields[0] == "Z":
            return None
        start_ticks = fields[19]  # proc_pid_stat(5) field 22
        boot_id = Path("/proc/sys/kernel/random/boot_id").read_text().strip()
        if not boot_id or not start_ticks:
            return None
        return f"{boot_id}:{start_ticks}"
    except (OSError, ValueError, IndexError):
        return None


def spawn_record_alive(rec):
    """True only when pid AND persisted process identity still match."""
    if not isinstance(rec, dict):
        return False
    expected = rec.get("process_identity")
    return bool(expected and process_identity(rec.get("pid", -1)) == expected)


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
        if len(explicit) > SESSION_ID_MAX or not SESSION_ID_RE.fullmatch(explicit):
            raise ValueError(
                f"COLLAB_SESSION_ID must be 1-{SESSION_ID_MAX} characters using "
                "letters, digits, '.', '_', ':', '@', or '-' (no path separators)"
            )
        return f"env:{explicit}"
    return _nearest_client_ancestor_pid(os.getppid())


def session_state_key(sid=None):
    """Fixed safe filename component; distinct raw ids never alias."""
    raw = str(sid if sid is not None else my_session_id())
    return "sid-" + hashlib.sha256(raw.encode("utf-8", errors="strict")).hexdigest()


# Backward-compatible alias — existing callers (and this module's own prior
# behavior for Claude sessions) keep working unchanged.
my_claude_pid = my_session_id


def _live_sids_all_rooms():
    """Live session ids across the root room and every rooms/* room. Claims
    and the fleet are repo-global, so their liveness checks must see every
    room's sessions — a room-local view would prune claims held by live
    sessions in OTHER rooms."""
    files = {ROOT_WS / "sessions.json", SESSIONS}
    if ROOMS.is_dir():
        try:
            files.update(d / "sessions.json" for d in ROOMS.iterdir() if d.is_dir())
        except OSError:
            pass
    sids = set()
    for f in files:
        for sid, s in _read_json(f, {}).items():
            if alive(sid, s.get("last_seen")):
                sids.add(str(sid))
    return sids


def get_sessions(prune=True):
    sessions = _read_json(SESSIONS, {})
    if prune:
        livemap = {p: s for p, s in sessions.items() if alive(p, s.get("last_seen"))}
        if len(livemap) != len(sessions):
            _write_json(SESSIONS, livemap)
        # drop claims held by dead sessions (checked repo-globally: a claim
        # holder may live in another room)
        claims = _read_json(CLAIMS, {})
        if claims:
            live_all = _live_sids_all_rooms()
            kept = {f: c for f, c in claims.items() if str(c.get("claude_pid")) in live_all}
            if len(kept) != len(claims):
                _write_json(CLAIMS, kept)
        return livemap
    return sessions


def validate_session_name(name):
    """Return a valid short kebab-case routing name, otherwise raise."""
    if not isinstance(name, str):
        raise ValueError("session name must be a string")
    if len(name) > SESSION_NAME_MAX or not SESSION_NAME_RE.fullmatch(name):
        raise ValueError(
            f"session name must be 1-{SESSION_NAME_MAX} characters of short kebab-case "
            "(lowercase letters/digits separated by single dashes)"
        )
    return name


def register_session(name, focus):
    """Register or refresh this session.

    A live name may occur only once in a room because direct messages route by
    name. The same session id may re-register to update its focus (or rename
    itself to another currently unused valid name).
    """
    name = validate_session_name(name)
    sid = my_session_id()
    with locked():
        sessions = get_sessions()
        duplicate = next(
            (
                (other_sid, session)
                for other_sid, session in sessions.items()
                if str(other_sid) != sid and session.get("name") == name
            ),
            None,
        )
        if duplicate:
            raise ValueError(
                f"session name '{name}' is already used by another live session in this room"
            )
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


def claim_route(sid=None):
    """Safe, repo-local routing metadata for a claim holder.

    A claimant name alone is ambiguous across private rooms. The opaque room
    path identifies the generation, while supervisor tells another room whom
    to contact through the shared parent channel.
    """
    sid = str(sid or my_session_id())
    claimant = session_name(sid)
    room_path = WS.resolve(strict=False)
    root_path = ROOT_WS.resolve(strict=False)
    try:
        relative = room_path.relative_to(root_path)
    except ValueError as exc:
        raise RuntimeError("claiming room is outside ROOT_WS") from exc
    if relative == Path("."):
        room = "main"
    elif all(re.fullmatch(r"[A-Za-z0-9._-]+", part) for part in relative.parts):
        room = relative.as_posix()
    else:
        digest = hashlib.sha256(relative.as_posix().encode("utf-8")).hexdigest()[:16]
        room = f"opaque/{digest}"
    if room == "main":
        supervisor = claimant
    elif has_parent_room():
        supervisor = claimant
    else:
        supervisor = PARENT_NAME or claimant
    try:
        supervisor = validate_session_name(supervisor)
    except ValueError:
        supervisor = claimant
    return {
        "room": room,
        "claimant": claimant,
        "supervisor": supervisor,
    }


def describe_claim_route(claim):
    route = claim.get("route") if isinstance(claim, dict) else None
    if not isinstance(route, dict) or not route.get("room"):
        return "route unavailable (legacy claim; check collab_status)"
    room = route["room"]
    claimant = route.get("claimant") or claim.get("session", "unknown")
    supervisor = route.get("supervisor") or claimant
    if room == "main":
        return f"main room; contact '{claimant}' with collab_post"
    return (
        f"private route {supervisor}@{room}; contact supervisor '{supervisor}' "
        "through the shared parent room (collab_post from main or collab_report_up)"
    )


def claim_paths(paths, reason):
    """Claim repo-relative paths. Returns (granted, conflicts)."""
    sid = my_session_id()
    granted, conflicts = [], {}
    # Validate the whole request before changing any claim. dict preserves
    # order while collapsing aliases repeated in one batch.
    normalized = list(dict.fromkeys(normalize(p) for p in paths))
    with locked():
        get_sessions()  # prune own room + stale claims
        live_all = _live_sids_all_rooms()
        claims = _read_json(CLAIMS, {})
        for p in normalized:
            holder = claims.get(p)
            if holder and str(holder["claude_pid"]) != sid and str(holder["claude_pid"]) in live_all:
                conflicts[p] = holder
            else:
                claims[p] = {
                    "session": session_name(sid),
                    "claude_pid": sid,
                    "reason": reason,
                    "route": claim_route(sid),
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
        get_sessions()
        live_all = _live_sids_all_rooms()
        claims = _read_json(CLAIMS, {})
    c = claims.get(path)
    if c and str(c["claude_pid"]) != sid and str(c["claude_pid"]) in live_all:
        return c
    return None


def normalize(path):
    """Canonicalize a claim to a repo-relative path or a virtual pseudo-claim.

    Relative paths are always interpreted from REPO_ROOT, independent of the
    MCP process cwd. Existing symlinks are followed; an alias to an in-repo
    target canonicalizes to that target, while an alias escaping the repo is
    rejected. A symlink must not be retargeted while a claim is live.
    """
    if not isinstance(path, (str, os.PathLike)):
        raise ValueError("claim path must be a string or path-like value")
    raw = os.fspath(path)
    if not isinstance(raw, str):
        raise ValueError("claim path must be text, not bytes")
    if not raw or "\0" in raw:
        raise ValueError("claim path cannot be empty or contain a NUL byte")
    if PSEUDO_CLAIM_RE.fullmatch(raw):
        return raw

    p = Path(raw)
    root = REPO_ROOT.resolve()
    try:
        resolved = (p if p.is_absolute() else root / p).resolve(strict=False)
        relative = resolved.relative_to(root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise ValueError(f"claim path must resolve inside the repo: {raw!r}") from exc
    if relative == Path("."):
        raise ValueError("claim path cannot be the repo root, '.', or an equivalent path")
    return relative.as_posix()


def _room_paths(base=None):
    """(messages.jsonl, cursors/) for a room. base=None means this session's
    own room (WS); pass PARENT_WS to talk in / read from the parent room."""
    b = Path(base) if base else WS
    if not _inside_root(b):
        raise RuntimeError(f"room path escapes ROOT_WS: {b}")
    return b / "messages.jsonl", b / "cursors"


def post_message(kind, text, to=None, sender=None, base=None):
    ensure_ws()
    msgfile, _ = _room_paths(base)
    _private_dir(msgfile.parent)
    msg = {
        "ts": time.time(),
        "from": sender or session_name(),
        "kind": kind,  # info | urgent | question | handoff | bug | wake | system
        "text": text,
        "to": to,
    }
    with locked():
        with open(msgfile, "a") as fh:
            fh.write(json.dumps(msg) + "\n")
        _private_file(msgfile)
    return msg


def _cursor_file(cursors, sid=None):
    cursors = _private_dir(cursors)
    return cursors / session_state_key(sid)


def read_new_messages(mark_read=True, base=None, with_token=False):
    """Messages appended since this session's cursor, excluding its own.
    base selects the room (None = own room, PARENT_WS = parent room); each
    room keeps its own per-session cursor so the two never interfere.

    with_token=True returns (messages, token). The token names the exact byte
    boundary read, so a caller may format that batch and advance only through
    it even if another message is appended in between.
    """
    ensure_ws()
    msgfile, cursors = _room_paths(base)
    sid = my_session_id()
    cursor_file = _cursor_file(cursors, sid)
    with locked():
        try:
            offset = int(cursor_file.read_text())
        except (OSError, ValueError):
            offset = 0
        msgs = []
        file_identity = None
        try:
            with open(msgfile) as fh:
                stat = os.fstat(fh.fileno())
                file_identity = [stat.st_dev, stat.st_ino]
                fh.seek(offset)
                for line in fh:
                    try:
                        msgs.append(json.loads(line))
                    except ValueError:
                        pass
                end = fh.tell()
        except OSError:
            end = offset
        if mark_read:
            cursor_file.write_text(str(end))
            _private_file(cursor_file)
    me = session_name(sid)
    visible = [m for m in msgs if m.get("from") != me and m.get("to") in (None, me)]
    token = {
        "room": str(Path(base or WS).resolve(strict=False)),
        "end": end,
        "file_identity": file_identity,
    }
    return (visible, token) if with_token else visible


def advance_message_cursor(token, base=None):
    """Advance through exactly token.end, never through later appends."""
    ensure_ws()
    msgfile, cursors = _room_paths(base)
    expected_room = str(Path(base or WS).resolve(strict=False))
    if not isinstance(token, dict) or token.get("room") != expected_room:
        raise ValueError("message cursor token belongs to a different room")
    try:
        end = max(0, int(token["end"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("invalid message cursor token") from exc
    cursor_file = _cursor_file(cursors)
    with locked():
        try:
            stat = msgfile.stat()
            current_identity = [stat.st_dev, stat.st_ino]
        except OSError:
            current_identity = None
        if token.get("file_identity") != current_identity:
            return False
        try:
            current_size = msgfile.stat().st_size
        except OSError:
            current_size = 0
        if end > current_size:
            return False
        try:
            current = int(cursor_file.read_text())
        except (OSError, ValueError):
            current = 0
        cursor_file.write_text(str(max(current, end)))
        _private_file(cursor_file)
    return True


def has_parent_room():
    """True when this session was spawned into the hierarchy with a parent
    room DIFFERENT from its own (supervisors). Workers share their room with
    their supervisor, so their parent room IS their own room."""
    return PARENT_WS is not None and PARENT_WS.resolve() != WS.resolve()


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
            _private_dir(BACKLOG)
            stamp = time.strftime("%Y%m%d-%H%M%S")
            archive = BACKLOG / f"messages-{stamp}.jsonl"
            n = 1
            while archive.exists():
                n += 1
                archive = BACKLOG / f"messages-{stamp}.{n}.jsonl"
            archive.write_text(raw)
            _private_file(archive)
        fresh = MESSAGES.with_suffix(".fresh")
        fresh.write_text("")
        _private_file(fresh)
        fresh.replace(MESSAGES)
        _private_file(MESSAGES)
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
    _private_file(VIEWER_PID)
    return url


# --------------------------------------------------------------------------- #
# Spawned workers (collab_spawn / collab_workers / collab_stop)
# --------------------------------------------------------------------------- #

def find_claude_cli():
    """Locate a runnable Claude Code CLI.

    Order: COLLAB_CLAUDE_CLI env override, `claude` on PATH, then the newest
    copy bundled inside Claude Desktop on supported Linux development hosts
    (~/.config/Claude/claude-code/<ver>/claude)."""
    override = os.environ.get("COLLAB_CLAUDE_CLI")
    if override:
        return override if os.access(override, os.X_OK) else None
    import shutil
    on_path = shutil.which("claude")
    if on_path:
        return on_path
    bundle = Path.home() / ".config" / "Claude" / "claude-code"
    try:
        versions = sorted(
            (d for d in bundle.iterdir() if os.access(d / "claude", os.X_OK)),
            key=lambda d: tuple(int(x) for x in d.name.split(".") if x.isdigit()),
        )
    except OSError:
        return None
    return str(versions[-1] / "claude") if versions else None


def _redact_sensitive(text, limit=1200):
    """Bound and redact diagnostic text before returning it through MCP."""
    text = str(text or "")
    patterns = (
        (r"(?i)\bauthorization\s*[:=]?\s*(?:bearer\s+)?\S+", "Authorization [redacted]"),
        (r"(?i)\bbearer\s+\S+", "Bearer [redacted]"),
        (r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", r"\1=[redacted]"),
        (r"\b(?:sk|sk-ant|ghp|github_pat)-[A-Za-z0-9_-]{8,}\b", "[redacted-token]"),
        (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[redacted-email]"),
        (r"https?://[^\s]+", "[redacted-url]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text[-max(1, int(limit)):]


def _task_summary(task):
    """Non-reversible metadata only; no task text is ever persisted."""
    digest = hashlib.sha256(str(task).encode("utf-8", errors="replace")).hexdigest()[:12]
    return {"sha256_12": digest, "chars": len(str(task))}


def _check_cli_ready(cli, env):
    """Fail closed unless the selected CLI reports usable authentication.

    COLLAB_CLAUDE_CLI remains the E2E seam: a fake executable implements this
    same `auth status --json` call, so tests never need real credentials.
    """
    import subprocess
    try:
        result = subprocess.run(
            [cli, "auth", "status", "--json"],
            cwd=str(REPO_ROOT),
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Claude CLI readiness check timed out; no session was spawned") from exc
    except OSError as exc:
        raise RuntimeError(f"Claude CLI readiness check could not run: {exc}") from exc
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    try:
        status = json.loads(result.stdout or "{}")
    except ValueError as exc:
        tail = _redact_sensitive(combined)
        raise RuntimeError(
            f"Claude CLI readiness check returned invalid JSON; no session was spawned"
            + (f". Output: {tail}" if tail.strip() else "")
        ) from exc
    if result.returncode != 0 or not status.get("loggedIn"):
        method = _redact_sensitive(status.get("authMethod") or "none", limit=80)
        provider = _redact_sensitive(status.get("apiProvider") or "unknown", limit=80)
        raise RuntimeError(
            "Claude CLI is not authenticated for noninteractive spawning "
            f"(loggedIn=false, authMethod={method}, provider={provider}); "
            "run `claude auth login` interactively outside Codex, then retry. "
            "No session or fleet record was created."
        )
    return status


def _spawn_log_tail(log_path):
    try:
        lines = Path(log_path).read_text(errors="replace").splitlines()[-12:]
    except OSError:
        return ""
    return _redact_sensitive("\n".join(lines))


def _spawn_exit_status(log_path):
    """Exit status the sh wrapper appended to the log, or None if still absent."""
    try:
        tail = Path(log_path).read_text()[-2000:]
    except OSError:
        return None
    marker = "--- worker exited status="
    pos = tail.rfind(marker)
    if pos < 0:
        return None
    try:
        return int(tail[pos + len(marker):].split()[0])
    except (ValueError, IndexError):
        return None


def get_spawns():
    """All spawn records, each annotated with running/exit_status. Never prunes:
    exited workers stay listed (their logs are the hand-back channel)."""
    spawns = _read_json(SPAWNS, {})
    for rec in spawns.values():
        rec["running"] = spawn_record_alive(rec)
        rec["exit_status"] = None if rec["running"] else _spawn_exit_status(rec.get("log", ""))
    return spawns


def get_fleet():
    """Every spawned session across ALL rooms (repo-global), annotated with
    running/exit_status. Never prunes — logs are the hand-back channel."""
    fleet = _read_json(FLEET, {})
    for rec in fleet.values():
        rec["running"] = spawn_record_alive(rec)
        rec["exit_status"] = None if rec["running"] else _spawn_exit_status(rec.get("log", ""))
    return fleet


def fleet_counts():
    """{family: running_count} across the whole fleet."""
    counts = {}
    for rec in get_fleet().values():
        if rec["running"]:
            fam = model_family(rec.get("model"))
            counts[fam] = counts.get(fam, 0) + 1
    return counts


def _prune_expired_spawn_records(records):
    """Drop expired, proved-dead metadata and private logs.

    Running records are never removed. A non-positive retention setting keeps
    history indefinitely for operators who need a longer audit window.
    """
    if SPAWN_RETENTION_DAYS <= 0:
        return records
    cutoff = time.time() - (SPAWN_RETENTION_DAYS * 86400)
    kept = {}
    log_root = SPAWN_LOGS.resolve()
    for key, rec in records.items():
        if rec.get("ts", 0) >= cutoff or spawn_record_alive(rec):
            kept[key] = rec
            continue
        try:
            log = Path(rec.get("log", "")).resolve()
            if log.parent == log_root:
                log.unlink(missing_ok=True)
        except (OSError, RuntimeError):
            pass
        if rec.get("role") == "supervisor":
            try:
                import shutil
                room = Path(rec.get("room", "")).resolve()
                if room.parent == ROOMS.resolve() and room.name.startswith(
                    f"{rec.get('name', '')}-"
                ):
                    shutil.rmtree(room, ignore_errors=True)
            except (OSError, RuntimeError):
                pass
    return kept


def _discard_failed_spawn_artifacts(log, room, role):
    """A failed spawn has no handoff to retain, so remove its private artifacts."""
    try:
        Path(log).unlink(missing_ok=True)
    except OSError:
        pass
    if role == "supervisor":
        try:
            import shutil
            target = Path(room).resolve()
            if target.parent == ROOMS.resolve():
                shutil.rmtree(target, ignore_errors=True)
        except (OSError, RuntimeError):
            pass


def _spawn_preamble(role, name, task, dispatcher):
    if role == "supervisor":
        return (
            f"You are '{name}', an Opus 5 SUPERVISOR in the {REPO_ROOT.name} collab hierarchy, "
            f"spawned by director '{dispatcher}'. You have your OWN collab room — your workers "
            f"live there — and you reach the director's room with collab_report_up / collab_check_up.\n"
            f"Protocol:\n"
            f"1. collab_register as '{name}', then collab_check_up for any extra context.\n"
            f"2. Review your objective; break it into at most 3 self-contained worker tasks, each "
            f"with file paths and explicit done-criteria (workers cannot ask the user anything).\n"
            f"3. Launch workers with collab_spawn(role='worker') — Sonnet 5. The repo-wide budget "
            f"is 4 Sonnet workers across ALL supervisors: if the cap blocks a spawn, run what fits "
            f"and start the rest as slots free up.\n"
            f"4. While workers run, loop collab_wait — it returns when a worker posts or exits. "
            f"Review EVERY handoff: read the actual diff, check the code is sound, run the "
            f"relevant tests. Send fixes back as follow-up tasks if needed.\n"
            f"5. Triage 'bug' reports from workers: fold them into tasks or pass them upward.\n"
            f"6. When the objective is done and reviewed, collab_report_up kind='handoff' to "
            f"'{dispatcher}' with what shipped, how it was verified, and open findings. Then stop.\n"
            f"File claims are repo-global — collab_claim before ANY edit of your own.\n\n"
            f"YOUR OBJECTIVE:\n{task}"
        )
    if role == "worker":
        return (
            f"You are '{name}', a Sonnet 5 WORKER spawned by supervisor '{dispatcher}' in the "
            f"{REPO_ROOT.name} collab workspace. Before anything else: collab_register as "
            f"'{name}', read collab_inbox, and collab_claim every file before you edit it (a "
            f"hook hard-blocks edits to files claimed by others).\n"
            f"While working: report bugs you notice along your task lines — even ones you don't "
            f"fix — as collab_post kind='bug' to '{dispatcher}'. Blocking questions: "
            f"kind='question' to '{dispatcher}'.\n"
            f"When done: collab_release your claims, then post a 'handoff' to '{dispatcher}' "
            f"summarizing what changed, how you verified it, and any findings.\n\n"
            f"YOUR TASK:\n{task}"
        )
    return (
        f"You are '{name}', a worker session spawned into the {REPO_ROOT.name} collab "
        f"workspace by '{dispatcher}'. Before anything else: collab_register as '{name}', "
        f"read collab_inbox, and collab_claim every file before you edit it (a hook "
        f"hard-blocks edits to files claimed by others). Post progress and questions with "
        f"collab_post (direct questions to '{dispatcher}'), and collab_release your claims "
        f"when done, ending with a 'handoff' message summarizing what changed.\n\n"
        f"YOUR TASK:\n{task}"
    )


def spawn_worker(name, task, model=None, effort=None, permission_mode="taskSafe",
                 role=None, allowed_tools=None):
    """Launch a headless Claude Code session (`claude -p`) into the hierarchy.

    role='supervisor' -> Opus 5, gets its own room under rooms/<name>/ and a
    parent link back to the spawner's room. role='worker' -> Sonnet 5, joins
    the spawner's room. No role -> legacy behavior (SPAWN_MODEL, own room).

    Concurrency is capped per model family against the repo-global fleet:
    at most MAX_OPUS (2) Opus and MAX_SONNET (4) Sonnet sessions running.

    The session starts from the repo root — NOT the caller's cwd — because a
    session started outside the repo doesn't load .mcp.json or the claim-
    enforcement hooks (that failure mode is silent). Authentication is checked
    before launch; the child must survive a short synchronous health window
    before any fleet record or room announcement is written."""
    import shlex, subprocess
    name = validate_session_name(name)
    if not task or not task.strip():
        raise ValueError("task cannot be empty")
    if role is not None and role not in ROLES:
        raise ValueError(f"role must be one of {sorted(ROLES)} (or omitted), got '{role}'")
    if permission_mode not in PERMISSION_MODES:
        raise ValueError(
            f"permission_mode must be one of {list(PERMISSION_MODES)}, got '{permission_mode}'"
        )
    if allowed_tools is not None:
        if permission_mode != "taskSafe":
            raise ValueError("allowed_tools may only be supplied with permission_mode='taskSafe'")
        if not isinstance(allowed_tools, list) or not allowed_tools or not all(
            isinstance(tool, str) and tool.strip() and len(tool) <= 160 for tool in allowed_tools
        ):
            raise ValueError("allowed_tools must be a non-empty list of tool permission strings")
        selected_tools = tuple(dict.fromkeys(tool.strip() for tool in allowed_tools))
    else:
        selected_tools = TASK_SAFE_ALLOWED_TOOLS
    cli = find_claude_cli()
    if not cli:
        raise RuntimeError(
            "no claude CLI found (checked COLLAB_CLAUDE_CLI, PATH, and "
            "~/.config/Claude/claude-code/*/claude)"
        )
    preset = ROLES.get(role, {})
    model = model or preset.get("model") or SPAWN_MODEL
    effort = effort or preset.get("effort") or SPAWN_EFFORT
    fam = model_family(model)
    cap = family_cap(fam)
    workdir = REPO_ROOT

    dispatcher = session_name()
    dispatcher_sid = my_session_id()
    generation = f"{time.time_ns():x}-{secrets.token_hex(4)}"
    room = ROOMS / f"{name}-{generation}" if role == "supervisor" else WS
    preamble = _spawn_preamble(role, name, task, dispatcher)
    cmd = [cli, "-p", preamble, "--model", model, "--effort", effort,
           "--no-session-persistence"]
    if permission_mode == "taskSafe":
        cmd.extend(["--permission-mode", "manual", "--allowedTools", ",".join(selected_tools)])
    elif permission_mode == "bypassPermissions":
        cmd.extend(["--allow-dangerously-skip-permissions",
                    "--permission-mode", "bypassPermissions"])
    else:
        cmd.extend(["--permission-mode", permission_mode])

    # Never inherit the dispatcher's explicit collab identity. The child must
    # resolve its own Claude process. Explicit room pointers also prevent a
    # supervisor's worker from accidentally inheriting grandparent routing.
    env = {k: v for k, v in os.environ.items() if k != "COLLAB_SESSION_ID"}
    env["COLLAB_ROOT_DIR"] = str(ROOT_WS)
    env["COLLAB_WS_DIR"] = str(room)
    env["COLLAB_PARENT_WS_DIR"] = str(WS)
    env["COLLAB_PARENT_NAME"] = dispatcher
    _check_cli_ready(cli, env)

    with locked():
        room_sessions = _read_json(room / "sessions.json", {})
        name_holder = next(
            (
                session
                for room_sid, session in room_sessions.items()
                if session.get("name") == name
                and alive(room_sid, session.get("last_seen"))
            ),
            None,
        )
        if name_holder:
            raise RuntimeError(
                f"cannot spawn '{name}': a live session in the destination room "
                "already uses that routing name"
            )
        raw_spawns = _read_json(SPAWNS, {})
        spawns = _prune_expired_spawn_records(raw_spawns)
        if spawns != raw_spawns:
            _write_json(SPAWNS, spawns)
        old = spawns.get(name)
        if old and spawn_record_alive(old):
            raise RuntimeError(f"a session named '{name}' is still running (pid {old['pid']})")
        raw_fleet = _read_json(FLEET, {})
        fleet = _prune_expired_spawn_records(raw_fleet)
        if fleet != raw_fleet:
            _write_json(FLEET, fleet)
        running_fam = [
            r.get("name", fleet_id)
            for fleet_id, r in fleet.items()
            if spawn_record_alive(r) and model_family(r.get("model")) == fam
        ]
        if len(running_fam) >= cap:
            raise RuntimeError(
                f"{fam} cap reached: {len(running_fam)}/{cap} {fam} sessions running repo-wide "
                f"({', '.join(running_fam)}). Wait for one to finish or collab_stop it."
            )
        _private_dir(SPAWN_LOGS)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        log = SPAWN_LOGS / f"{name}-{stamp}-{generation[-8:]}.log"
        log.touch(mode=0o600, exist_ok=False)
        _private_file(log)
        # sh wrapper: redirect everything to the log and record the exit status
        # there when the worker finishes (we don't hold a waiter process).
        script = (
            f"umask 077; exec >>{shlex.quote(str(log))} 2>&1; "
            + " ".join(shlex.quote(a) for a in cmd)
            + '; s=$?; echo; echo "--- worker exited status=$s"; exit "$s"'
        )
        if role == "supervisor":
            _private_dir(room)
            cursors_dir = room / "cursors"
            if cursors_dir.exists():
                raise RuntimeError(f"generated supervisor room already exists: {room}")
            cursors_dir.mkdir(mode=0o700)
            _chmod_private(cursors_dir, 0o700)
        try:
            proc = subprocess.Popen(
                ["/bin/sh", "-c", script],
                cwd=str(workdir),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
                env=env,
            )
        except OSError:
            _discard_failed_spawn_artifacts(log, room, role)
            raise
        identity = process_identity(proc.pid)
        if not identity:
            try:
                proc.terminate()
            except OSError:
                pass
            _discard_failed_spawn_artifacts(log, room, role)
            raise RuntimeError("spawned process identity could not be verified; no fleet record was created")

        # Catch auth/model/settings/argv failures before claiming success. The
        # lock prevents concurrent spawns from overbooking the cap during this
        # short bounded window.
        deadline = time.monotonic() + max(0.05, min(SPAWN_HEALTHCHECK_S, 3.0))
        while proc.poll() is None and time.monotonic() < deadline:
            time.sleep(0.02)
        if proc.poll() is not None:
            status = _spawn_exit_status(log)
            tail = _spawn_log_tail(log)
            _discard_failed_spawn_artifacts(log, room, role)
            raise RuntimeError(
                f"Claude child exited during spawn health-check (status "
                f"{status if status is not None else proc.returncode}); no fleet record was created"
                + (f". Redacted log tail:\n{tail}" if tail else "")
            )

        summary = _task_summary(task)
        fleet_id = f"{name}@{generation}"
        rec = {
            "name": name,
            "generation": generation,
            "fleet_id": fleet_id,
            "pid": proc.pid,
            "process_identity": identity,
            "model": model,
            "effort": effort,
            "role": role,
            "room": str(room),
            "permission_mode": permission_mode,
            "allowed_tools": list(selected_tools) if permission_mode == "taskSafe" else None,
            "cwd": str(workdir),
            "log": str(log),
            "task_summary": summary,
            "spawned_by": dispatcher,
            "spawned_by_sid": dispatcher_sid,
            "owner_room": str(WS.resolve()),
            "ts": time.time(),
        }
        spawns[name] = rec
        _write_json(SPAWNS, spawns)
        fleet[fleet_id] = rec
        _write_json(FLEET, fleet)
    label = role or "worker"
    post_message("system", f"{dispatcher} spawned {label} '{name}' ({model}, {effort})",
                 sender="workspace")
    return rec


def wait_for_activity(seconds=60):
    """Block until something this session cares about happens: a new message
    in its room or parent room, or one of its spawned children exiting.
    Returns (exited_children, msgs, parent_msgs); messages are consumed.
    All three empty means the wait timed out with no activity."""
    seconds = max(1, min(int(seconds or 60), 240))

    def running_children():
        # Same owner filter as stop_report(): only children this exact
        # session spawned count as "its" children in a shared room.
        me = my_session_id()
        return {
            n for n, r in _read_json(SPAWNS, {}).items()
            if spawn_record_alive(r) and r.get("spawned_by_sid") == me
        }

    before = running_children()
    deadline = time.time() + seconds
    while True:
        msgs, own_token = read_new_messages(mark_read=False, with_token=True)
        if has_parent_room():
            up, parent_token = read_new_messages(
                mark_read=False, base=PARENT_WS, with_token=True
            )
        else:
            up, parent_token = [], None
        exited = before - running_children()
        if msgs or up or exited:
            if msgs:
                advance_message_cursor(own_token)
            if up:
                advance_message_cursor(parent_token, base=PARENT_WS)
            return sorted(exited), msgs, up
        if time.time() >= deadline:
            return [], [], []
        time.sleep(2)


def stop_report():
    """What should keep this session awake at Stop time: pending messages in
    its room / parent room (NOT consumed), exact cursor tokens for those
    batches, and its still-running children."""
    msgs, own_token = read_new_messages(mark_read=False, with_token=True)
    if has_parent_room():
        up, parent_token = read_new_messages(
            mark_read=False, base=PARENT_WS, with_token=True
        )
    else:
        up, parent_token = [], None
    # Only sessions THIS caller spawned. spawns.json is room-scoped and a
    # supervisor's workers share its room, so without the owner filter a leaf
    # worker's Stop hook attributed its siblings to it and kept it awake for
    # children it never had (found by w-sweep-qa, Wave 1).
    me = my_session_id()
    running = sorted(
        n for n, r in _read_json(SPAWNS, {}).items()
        if spawn_record_alive(r) and r.get("spawned_by_sid") == me
    )
    return msgs, up, running, own_token, parent_token


def consume_pending(own_token, parent_token=None):
    """Advance exactly through batches already copied into hook output."""
    advance_message_cursor(own_token)
    if parent_token is not None:
        advance_message_cursor(parent_token, base=PARENT_WS)


def is_wake(msg):
    """A message that should wake a sleeping/finishing session: addressed
    directly to it, a wake/urgent kind, or carrying the literal wake code."""
    return bool(msg.get("to")) or msg.get("kind") in WAKE_KINDS or \
        str(msg.get("text", "")).startswith(WAKE_CODE)


def stop_block_count(bump=None):
    """Consecutive quiet Stop-hook blocks for this session (keepalive while
    children run). bump=True increments, bump=False resets, None just reads."""
    _private_dir(STOPSTATE)
    f = STOPSTATE / session_state_key()
    try:
        n = int(f.read_text())
    except (OSError, ValueError):
        n = 0
    if bump is True:
        n += 1
        f.write_text(str(n))
        _private_file(f)
    elif bump is False:
        n = 0
        f.write_text("0")
        _private_file(f)
    return n


def stop_worker(name):
    """SIGTERM a direct child, after authority and PID identity checks.

    Fleet visibility is intentionally not fleet-wide kill authority: only the
    exact session id in the spawning room that created a child may stop it.
    """
    import signal
    with locked():
        spawns = _read_json(SPAWNS, {})
        rec = spawns.get(name)
    if rec is None:
        raise ValueError(
            f"no direct child named '{name}' in this room (collab_fleet is visibility only)"
        )
    if rec.get("owner_room") != str(WS.resolve()) or rec.get("spawned_by_sid") != my_session_id():
        raise PermissionError(
            f"not authorized to stop '{name}': only its spawning session in its owner room may stop it"
        )
    pid = rec.get("pid", -1)
    current_identity = process_identity(pid)
    if not rec.get("process_identity") or current_identity != rec.get("process_identity"):
        if current_identity is not None:
            raise RuntimeError(
                f"refusing to signal pid {pid} for '{name}': process identity mismatch (possible PID reuse)"
            )
        raise ValueError(f"worker '{name}' is not running (exit status "
                         f"{_spawn_exit_status(rec.get('log', ''))})")
    try:
        os.killpg(pid, signal.SIGTERM)
    except OSError:
        os.kill(pid, signal.SIGTERM)
    post_message("system", f"worker '{name}' stopped by {session_name()}", sender="workspace")
    return rec
