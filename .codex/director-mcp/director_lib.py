#!/usr/bin/env python3
"""Runtime and durable state for the BetterFingers Codex director MCP.

The server deliberately launches Codex, not Claude, through ``codex exec
--json``.  It is Linux/POSIX-only for the same reasons as the repository's
collaboration server: process identity comes from /proc, locking uses fcntl,
and stop targets a verified process group.
"""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
STATE_ROOT = Path(
    os.environ.get(
        "CODEX_DIRECTOR_ROOT_DIR",
        REPO_ROOT / ".claude" / "collab" / "codex-director",
    )
).resolve(strict=False)
LOCKFILE = STATE_ROOT / ".lock"
FLEET_FILE = STATE_ROOT / "fleet.json"
PRINCIPALS_FILE = STATE_ROOT / "principals.json"
MESSAGES_FILE = STATE_ROOT / "messages.jsonl"
CURSORS_DIR = STATE_ROOT / "cursors"
LOGS_DIR = STATE_ROOT / "logs"

CODEX_CLI = os.environ.get("CODEX_DIRECTOR_CLI", "codex")
MAX_SUPERVISORS = int(os.environ.get("CODEX_DIRECTOR_MAX_SUPERVISORS", "2"))
MAX_WORKERS = int(os.environ.get("CODEX_DIRECTOR_MAX_WORKERS", "4"))
HEALTHCHECK_S = float(os.environ.get("CODEX_DIRECTOR_HEALTHCHECK_S", "0.35"))
SESSION_TIMEOUT_S = int(os.environ.get("CODEX_DIRECTOR_SESSION_TIMEOUT_S", "900"))
MAX_TASK_CHARS = int(os.environ.get("CODEX_DIRECTOR_MAX_TASK_CHARS", "30000"))
MAX_RESULT_CHARS = int(os.environ.get("CODEX_DIRECTOR_MAX_RESULT_CHARS", "12000"))

ROLE_DEFAULTS = {
    "supervisor": {
        "model": os.environ.get("CODEX_DIRECTOR_SUPERVISOR_MODEL", "gpt-5.6-sol"),
        "reasoning_effort": os.environ.get("CODEX_DIRECTOR_SUPERVISOR_EFFORT", "high"),
        "sandbox": "read-only",
    },
    "worker": {
        "model": os.environ.get("CODEX_DIRECTOR_WORKER_MODEL", "gpt-5.6-terra"),
        "reasoning_effort": os.environ.get("CODEX_DIRECTOR_WORKER_EFFORT", "medium"),
        "sandbox": "workspace-write",
    },
}
ROLE_CAPS = {"supervisor": MAX_SUPERVISORS, "worker": MAX_WORKERS}
REASONING_EFFORTS = ("low", "medium", "high", "xhigh")
SANDBOXES = ("read-only", "workspace-write")
SESSION_NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SESSION_NAME_MAX = 48


def _validate_state_root() -> None:
    protected = {
        Path("/").resolve(),
        Path("/tmp").resolve(),
        Path("/var/tmp").resolve(),
        Path.home().resolve(),
        REPO_ROOT.resolve(),
        (REPO_ROOT / ".claude" / "collab").resolve(strict=False),
    }
    if STATE_ROOT in protected or STATE_ROOT.parent == STATE_ROOT:
        raise RuntimeError(
            f"CODEX_DIRECTOR_ROOT_DIR must name a dedicated state subdirectory, not {STATE_ROOT}"
        )


def _private_dir(path: Path) -> Path:
    path = path.resolve(strict=False)
    try:
        path.relative_to(STATE_ROOT)
    except ValueError as exc:
        raise RuntimeError(f"director state path escapes root: {path}") from exc
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not path.is_symlink():
        os.chmod(path, 0o700)
    return path


def _private_file(path: Path) -> Path:
    if path.exists() and not path.is_symlink():
        os.chmod(path, 0o600)
    return path


def ensure_state() -> None:
    _validate_state_root()
    _private_dir(STATE_ROOT)
    _private_dir(CURSORS_DIR)
    _private_dir(LOGS_DIR)


@contextmanager
def locked():
    ensure_state()
    with open(LOCKFILE, "a+", encoding="utf-8") as handle:
        _private_file(LOCKFILE)
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return default


def _write_json(path: Path, value) -> None:
    ensure_state()
    tmp = path.with_name(f".{path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    _private_file(tmp)
    os.replace(tmp, path)
    _private_file(path)


def _boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text().strip()
    except OSError:
        return "unknown-boot"


def process_identity(pid: int) -> str | None:
    try:
        fields = Path(f"/proc/{int(pid)}/stat").read_text().split()
        return f"{_boot_id()}:{fields[21]}"
    except (OSError, ValueError, IndexError):
        return None


def process_alive(pid: int, identity: str | None) -> bool:
    try:
        os.kill(int(pid), 0)
        fields = Path(f"/proc/{int(pid)}/stat").read_text().split()
    except (OSError, ValueError):
        return False
    # A killed detached runner may remain as a zombie until its parent reaps
    # it.  kill(pid, 0) still succeeds for zombies, but they do not consume a
    # usable fleet slot and must never be treated as signalable workers.
    return bool(fields[2] != "Z" and identity and process_identity(int(pid)) == identity)


def _nearest_codex_pid() -> int | None:
    pid = os.getppid()
    seen = set()
    while pid > 1 and pid not in seen:
        seen.add(pid)
        try:
            comm = Path(f"/proc/{pid}/comm").read_text().strip()
            if comm == "codex":
                return pid
            stat = Path(f"/proc/{pid}/stat").read_text().split()
            pid = int(stat[3])
        except (OSError, ValueError, IndexError):
            break
    return None


def session_id() -> str:
    explicit = os.environ.get("CODEX_DIRECTOR_SESSION_ID")
    if explicit:
        return f"env:{explicit}"
    pid = _nearest_codex_pid() or os.getppid()
    return f"pid:{pid}:{process_identity(pid) or 'unknown'}"


def current_role() -> str:
    role = os.environ.get("CODEX_DIRECTOR_ROLE", "director")
    if role not in ("director", "supervisor", "worker"):
        raise RuntimeError(f"invalid CODEX_DIRECTOR_ROLE: {role}")
    return role


def current_agent_id() -> str | None:
    return os.environ.get("CODEX_DIRECTOR_AGENT_ID") or None


def _principal_live(sid: str, principal: dict, fleet: dict) -> bool:
    agent_id = principal.get("agent_id")
    if agent_id:
        rec = fleet.get(agent_id)
        return bool(rec and record_alive(rec))
    if sid.startswith("pid:"):
        parts = sid.split(":", 2)
        try:
            return process_alive(int(parts[1]), parts[2])
        except (ValueError, IndexError):
            return False
    return time.time() - float(principal.get("last_seen", 0)) <= SESSION_TIMEOUT_S


def get_principals() -> dict:
    with locked():
        principals = _read_json(PRINCIPALS_FILE, {})
        fleet = _read_json(FLEET_FILE, {})
        live = {
            sid: principal
            for sid, principal in principals.items()
            if _principal_live(sid, principal, fleet)
        }
        if live != principals:
            _write_json(PRINCIPALS_FILE, live)
        return live


def register(name: str, focus: str) -> dict:
    validate_name(name)
    focus = str(focus).strip()
    if not focus or "\n" in focus or len(focus) > 300:
        raise ValueError("focus must be one non-empty line of at most 300 characters")
    sid = session_id()
    role = current_role()
    agent_id = current_agent_id()
    with locked():
        principals = _read_json(PRINCIPALS_FILE, {})
        fleet = _read_json(FLEET_FILE, {})
        if agent_id:
            record = fleet.get(agent_id)
            if not record:
                raise RuntimeError("spawned Codex identity is missing from the director fleet")
            if record.get("name") != name or record.get("role") != role:
                raise RuntimeError(
                    f"spawned identity must register as assigned {record.get('role')} "
                    f"'{record.get('name')}'"
                )
        principals = {
            key: value
            for key, value in principals.items()
            if key == sid or _principal_live(key, value, fleet)
        }
        conflict = next(
            (value for key, value in principals.items() if key != sid and value.get("name") == name),
            None,
        )
        if conflict:
            raise RuntimeError(f"name '{name}' is already registered by a live {conflict.get('role')} session")
        now = time.time()
        principals[sid] = {
            "name": name,
            "focus": focus,
            "role": role,
            "agent_id": agent_id,
            "started": principals.get(sid, {}).get("started", now),
            "last_seen": now,
        }
        _write_json(PRINCIPALS_FILE, principals)
        if agent_id and agent_id in fleet:
            fleet[agent_id]["registered_name"] = name
            fleet[agent_id]["last_seen"] = now
            _write_json(FLEET_FILE, fleet)
    return principals[sid]


def heartbeat() -> None:
    sid = session_id()
    with locked():
        principals = _read_json(PRINCIPALS_FILE, {})
        if sid in principals:
            principals[sid]["last_seen"] = time.time()
            _write_json(PRINCIPALS_FILE, principals)


def require_principal() -> dict:
    heartbeat()
    principal = get_principals().get(session_id())
    if not principal:
        raise RuntimeError("call codex_director_register before using director tools")
    return principal


def validate_name(name: str) -> None:
    if not isinstance(name, str) or len(name) > SESSION_NAME_MAX or not SESSION_NAME_RE.fullmatch(name):
        raise ValueError(f"name must be kebab-case and at most {SESSION_NAME_MAX} characters")


def _redact(text: str, limit: int = 1400) -> str:
    text = str(text or "")
    patterns = (
        (r"(?i)\bauthorization\s*[:=]?\s*(?:bearer\s+)?\S+", "Authorization [redacted]"),
        (r"(?i)\bbearer\s+\S+", "Bearer [redacted]"),
        (r"(?i)\b(api[_-]?key|token|password|secret)\s*[:=]\s*\S+", r"\1=[redacted]"),
        (r"\b(?:sk|sk-ant|ghp|github_pat)-[A-Za-z0-9_-]{8,}\b", "[redacted-token]"),
        (r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", "[redacted-email]"),
    )
    for pattern, replacement in patterns:
        text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
    return text[-max(1, int(limit)) :]


def _task_summary(task: str) -> dict:
    raw = task.encode("utf-8", errors="replace")
    return {"sha256_12": hashlib.sha256(raw).hexdigest()[:12], "chars": len(task)}


def _check_codex_ready(cli: str, env: dict) -> None:
    try:
        result = subprocess.run(
            [cli, "login", "status"],
            cwd=REPO_ROOT,
            env=env,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=8,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError("Codex login readiness check timed out; no agent was spawned") from exc
    except OSError as exc:
        raise RuntimeError(f"Codex CLI readiness check could not run: {exc}") from exc
    combined = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0 or "logged in" not in combined.lower():
        tail = _redact(combined)
        raise RuntimeError(
            "Codex CLI is not authenticated for noninteractive spawning; run `codex login` "
            "interactively, then retry. No agent or fleet record was created."
            + (f" Output: {tail}" if tail.strip() else "")
        )


def record_alive(rec: dict) -> bool:
    return process_alive(rec.get("pid", -1), rec.get("process_identity"))


def _status_from_log(log_path: str) -> int | None:
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()[-30:]
    except OSError:
        return None
    marker = "--- codex-director exit status="
    for line in reversed(lines):
        if line.startswith(marker):
            try:
                return int(line[len(marker) :].split()[0])
            except (ValueError, IndexError):
                return None
    return None


def _refresh_record(rec: dict) -> dict:
    rec = dict(rec)
    rec["running"] = record_alive(rec)
    rec["exit_status"] = None if rec["running"] else _status_from_log(rec.get("log", ""))
    return rec


def get_fleet() -> dict:
    with locked():
        return {agent_id: _refresh_record(rec) for agent_id, rec in _read_json(FLEET_FILE, {}).items()}


def cap_usage(fleet: dict | None = None) -> dict:
    fleet = fleet if fleet is not None else get_fleet()
    return {
        role: sum(1 for rec in fleet.values() if rec.get("role") == role and rec.get("running"))
        for role in ROLE_CAPS
    }


def _allowed_spawn(caller_role: str, role: str) -> bool:
    if caller_role == "director":
        return role in ("supervisor", "worker")
    if caller_role == "supervisor":
        return role == "worker"
    return False


def _spawn_prompt(name: str, role: str, task: str, parent_name: str) -> str:
    common = (
        f"You are '{name}', a headless Codex {role} spawned by '{parent_name}' in the shared "
        f"BetterFingers checkout. Read AGENTS.md before acting. You cannot ask the user questions; "
        f"report missing contracts to your parent. Register first with codex_director_register. "
        f"Use the collab MCP lifecycle before every edit: register, inspect status/inbox, claim exact "
        f"files, post START, edit only claims, verify, handoff, release. Never run Git mutation commands. "
    )
    if role == "supervisor":
        workflow = (
            "You are an integrator, not a broad implementation lane. Split the objective into at most "
            "three non-overlapping worker tasks, spawn only workers with codex_director_spawn (never "
            "collab_spawn), wait for them, inspect their actual results and diffs, run appropriate targeted "
            "verification, and produce one reviewed final handoff. Use codex_director_inbox between "
            "stages. Always send blockers and the final parent handoff through codex_director_report; "
            "collab_post remains the separate repo-global coordination channel. "
        )
    else:
        workflow = (
            "Do exactly this bounded task. Do not spawn agents. Check codex_director_inbox before "
            "verification, then always send a precise parent handoff with codex_director_report and "
            "finish. Use collab_post separately when the repository lifecycle requires a shared-room "
            "handoff; it does not replace codex_director_report. "
        )
    return f"{common}{workflow}\n\nOBJECTIVE\n{task}"


def _runner_argv(model: str, effort: str, sandbox: str, resume_thread_id: str | None) -> list[str]:
    if resume_thread_id:
        return [
            CODEX_CLI,
            "exec",
            "resume",
            "-m",
            model,
            "-c",
            f'model_reasoning_effort="{effort}"',
            "-c",
            'approval_policy="never"',
            "--json",
            resume_thread_id,
            "-",
        ]
    return [
        CODEX_CLI,
        "exec",
        "-C",
        str(REPO_ROOT),
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{effort}"',
        "-c",
        'approval_policy="never"',
        "--sandbox",
        sandbox,
        "--json",
        "-",
    ]


def _child_env(agent_id: str, role: str, parent_agent_id: str | None) -> dict:
    env = dict(os.environ)
    env.update(
        {
            "CODEX_DIRECTOR_ROLE": role,
            "CODEX_DIRECTOR_AGENT_ID": agent_id,
            "CODEX_DIRECTOR_PARENT_ID": parent_agent_id or "",
            "CODEX_DIRECTOR_SESSION_ID": f"agent-{agent_id}",
        }
    )
    # Do not force COLLAB_SESSION_ID for spawned Codex processes. The collab
    # server and hooks both see the real Codex process in their ancestry, so
    # PID liveness removes the session immediately on exit instead of retaining
    # an env-identified session for the heartbeat timeout.
    env.pop("COLLAB_SESSION_ID", None)
    return env


def _launch_runner(agent_id: str, prompt: str, argv: list[str], env: dict, log_path: Path) -> tuple[int, str]:
    payload = json.dumps(
        {
            "agent_id": agent_id,
            "argv": argv,
            "cwd": str(REPO_ROOT),
            "env": env,
            "log": str(log_path),
            "prompt": prompt,
        }
    )
    proc = subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "__runner"],
        cwd=REPO_ROOT,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        text=True,
        start_new_session=True,
    )
    if proc.stdin is None:
        raise RuntimeError("failed to open runner input")
    proc.stdin.write(payload)
    proc.stdin.close()
    identity = process_identity(proc.pid)
    if not identity:
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except OSError:
            pass
        raise RuntimeError("could not establish Codex runner process identity")
    return proc.pid, identity


def spawn(name: str, task: str, role: str, model: str | None = None,
          reasoning_effort: str | None = None, sandbox: str | None = None) -> dict:
    principal = require_principal()
    validate_name(name)
    if role not in ROLE_DEFAULTS:
        raise ValueError("role must be 'supervisor' or 'worker'")
    if not _allowed_spawn(principal["role"], role):
        raise RuntimeError(f"a {principal['role']} may not spawn a {role}")
    task = str(task).strip()
    if not task or len(task) > MAX_TASK_CHARS:
        raise ValueError(f"task must contain 1..{MAX_TASK_CHARS} characters")
    defaults = ROLE_DEFAULTS[role]
    model = str(model or defaults["model"])
    effort = str(reasoning_effort or defaults["reasoning_effort"])
    sandbox = str(sandbox or defaults["sandbox"])
    if effort not in REASONING_EFFORTS:
        raise ValueError(f"reasoning_effort must be one of {', '.join(REASONING_EFFORTS)}")
    if sandbox not in SANDBOXES:
        raise ValueError(f"sandbox must be one of {', '.join(SANDBOXES)}")
    if role == "supervisor" and sandbox != "read-only":
        raise ValueError("supervisors are read-only integrators; delegate claimed edits to workers")

    env = _child_env("pending", role, current_agent_id())
    _check_codex_ready(CODEX_CLI, env)
    agent_id = uuid.uuid4().hex
    env = _child_env(agent_id, role, current_agent_id())
    prompt = _spawn_prompt(name, role, task, principal["name"])
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = LOGS_DIR / f"{stamp}-{name}-{agent_id[:8]}.jsonl"
    log_path.touch(mode=0o600, exist_ok=False)
    _private_file(log_path)

    with locked():
        fleet = _read_json(FLEET_FILE, {})
        refreshed = {key: _refresh_record(value) for key, value in fleet.items()}
        if any(rec.get("name") == name and rec.get("running") for rec in refreshed.values()):
            log_path.unlink(missing_ok=True)
            raise RuntimeError(f"a live Codex agent already uses name '{name}'")
        used = cap_usage(refreshed)[role]
        if used >= ROLE_CAPS[role]:
            log_path.unlink(missing_ok=True)
            raise RuntimeError(f"{role} cap reached: {used}/{ROLE_CAPS[role]}; wait or stop a direct child")
        argv = _runner_argv(model, effort, sandbox, None)
        pid, identity = _launch_runner(agent_id, prompt, argv, env, log_path)
        now = time.time()
        record = {
            "id": agent_id,
            "name": name,
            "role": role,
            "model": model,
            "reasoning_effort": effort,
            "sandbox": sandbox,
            "pid": pid,
            "process_identity": identity,
            "parent_session_id": session_id(),
            "parent_agent_id": current_agent_id(),
            "parent_name": principal["name"],
            "task_summary": _task_summary(task),
            "generation": 1,
            "thread_id": None,
            "log": str(log_path),
            "cwd": str(REPO_ROOT),
            "created_at": now,
            "updated_at": now,
        }
        fleet[agent_id] = record
        _write_json(FLEET_FILE, fleet)

    time.sleep(max(0.0, min(HEALTHCHECK_S, 2.0)))
    refreshed = _refresh_record(record)
    if not refreshed["running"]:
        with locked():
            fleet = _read_json(FLEET_FILE, {})
            fleet.pop(agent_id, None)
            _write_json(FLEET_FILE, fleet)
        tail = _redact(log_path.read_text(encoding="utf-8", errors="replace"))
        log_path.unlink(missing_ok=True)
        raise RuntimeError(
            f"Codex agent exited during startup with status {refreshed['exit_status']}; "
            "no fleet record was retained."
            + (f" Output: {tail}" if tail.strip() else "")
        )
    return _refresh_record(record)


def _direct_child_by_name(name: str, require_stopped: bool | None = None) -> tuple[str, dict]:
    matches = [
        (agent_id, rec)
        for agent_id, rec in get_fleet().items()
        if rec.get("name") == name and rec.get("parent_session_id") == session_id()
    ]
    if not matches:
        raise RuntimeError(f"'{name}' is not a child spawned by this exact session")
    agent_id, rec = max(matches, key=lambda item: item[1].get("created_at", 0))
    if require_stopped is True and rec.get("running"):
        raise RuntimeError(f"'{name}' is still running; wait or stop it before resuming")
    if require_stopped is False and not rec.get("running"):
        raise RuntimeError(f"'{name}' is not running")
    return agent_id, rec


def resume(name: str, task: str) -> dict:
    principal = require_principal()
    agent_id, rec = _direct_child_by_name(name, require_stopped=True)
    thread_id = rec.get("thread_id") or extract_thread_id(rec.get("log", ""))
    if not thread_id:
        raise RuntimeError(f"'{name}' has no resumable Codex thread id")
    task = str(task).strip()
    if not task or len(task) > MAX_TASK_CHARS:
        raise ValueError(f"task must contain 1..{MAX_TASK_CHARS} characters")
    _check_codex_ready(CODEX_CLI, _child_env(agent_id, rec["role"], current_agent_id()))
    stamp = time.strftime("%Y%m%d-%H%M%S")
    log_path = LOGS_DIR / f"{stamp}-{name}-{agent_id[:8]}-g{int(rec.get('generation', 1)) + 1}.jsonl"
    log_path.touch(mode=0o600, exist_ok=False)
    _private_file(log_path)
    prompt = (
        f"Follow-up from parent '{principal['name']}'. Check codex_director_inbox first. "
        f"Keep the original role and repository lifecycle.\n\nFOLLOW-UP\n{task}"
    )
    env = _child_env(agent_id, rec["role"], current_agent_id())
    argv = _runner_argv(rec["model"], rec["reasoning_effort"], rec["sandbox"], thread_id)
    pid, identity = _launch_runner(agent_id, prompt, argv, env, log_path)
    with locked():
        fleet = _read_json(FLEET_FILE, {})
        current = fleet.get(agent_id, rec)
        current.update(
            {
                "pid": pid,
                "process_identity": identity,
                "generation": int(current.get("generation", 1)) + 1,
                "task_summary": _task_summary(task),
                "log": str(log_path),
                "updated_at": time.time(),
                "thread_id": thread_id,
            }
        )
        fleet[agent_id] = current
        _write_json(FLEET_FILE, fleet)
    time.sleep(max(0.0, min(HEALTHCHECK_S, 2.0)))
    refreshed = _refresh_record(current)
    if not refreshed["running"]:
        raise RuntimeError(
            f"Codex resume for '{name}' exited during startup with status {refreshed['exit_status']}: "
            f"{_redact(log_path.read_text(encoding='utf-8', errors='replace'))}"
        )
    return refreshed


def stop(name: str) -> dict:
    require_principal()
    agent_id, rec = _direct_child_by_name(name, require_stopped=False)
    actual = process_identity(rec["pid"])
    if actual != rec.get("process_identity"):
        raise RuntimeError("process identity mismatch; refusing to signal a possibly reused PID")
    try:
        os.killpg(int(rec["pid"]), signal.SIGTERM)
    except ProcessLookupError as exc:
        raise RuntimeError(f"'{name}' exited before it could be stopped") from exc
    return {"id": agent_id, **rec}


def _cursor_path(sid: str) -> Path:
    digest = hashlib.sha256(sid.encode()).hexdigest()
    return CURSORS_DIR / f"sid-{digest}.cursor"


def _exit_cursor_path(sid: str) -> Path:
    digest = hashlib.sha256(sid.encode()).hexdigest()
    return CURSORS_DIR / f"sid-{digest}.exits.json"


def _unseen_exits(fleet: dict) -> list[dict]:
    cursor = _exit_cursor_path(session_id())
    with locked():
        seen = _read_json(cursor, {})
        exited = [
            rec
            for agent_id, rec in fleet.items()
            if rec.get("parent_session_id") == session_id()
            and not rec.get("running")
            and int(seen.get(agent_id, 0)) < int(rec.get("generation", 1))
        ]
        if exited:
            for rec in exited:
                seen[rec["id"]] = int(rec.get("generation", 1))
            _write_json(cursor, seen)
        return exited


def send_message(kind: str, text: str, to: str) -> dict:
    principal = require_principal()
    if kind not in ("info", "question", "urgent", "handoff", "bug"):
        raise ValueError("kind must be info, question, urgent, handoff, or bug")
    text = str(text).strip()
    if not text or len(text) > 12000:
        raise ValueError("message must contain 1..12000 characters")
    target = next((p for p in get_principals().values() if p.get("name") == to), None)
    if not target:
        raise RuntimeError(f"target '{to}' is not a live registered Codex director session")
    my_agent = current_agent_id()
    target_agent = target.get("agent_id")
    fleet = get_fleet()
    related = False
    if target_agent and fleet.get(target_agent, {}).get("parent_session_id") == session_id():
        related = True
    if my_agent and fleet.get(my_agent, {}).get("parent_session_id"):
        parent_sid = fleet[my_agent]["parent_session_id"]
        parent_agent = fleet[my_agent].get("parent_agent_id")
        if parent_agent:
            related = target_agent == parent_agent
        else:
            related = any(
                sid == parent_sid and p.get("name") == to for sid, p in get_principals().items()
            )
    if not related:
        raise RuntimeError("messages are limited to a direct parent or direct child")
    msg = {
        "ts": time.time(),
        "from": principal["name"],
        "from_session_id": session_id(),
        "to": to,
        "kind": kind,
        "text": text,
    }
    with locked():
        with open(MESSAGES_FILE, "a", encoding="utf-8") as handle:
            handle.write(json.dumps(msg) + "\n")
        _private_file(MESSAGES_FILE)
    return msg


def read_messages() -> list[dict]:
    principal = require_principal()
    cursor = _cursor_path(session_id())
    with locked():
        try:
            offset = int(cursor.read_text())
        except (OSError, ValueError):
            offset = 0
        messages = []
        end = offset
        try:
            with open(MESSAGES_FILE, encoding="utf-8") as handle:
                handle.seek(offset)
                for line in handle:
                    try:
                        messages.append(json.loads(line))
                    except ValueError:
                        pass
                end = handle.tell()
        except OSError:
            pass
        cursor.write_text(str(end))
        _private_file(cursor)
    return [msg for msg in messages if msg.get("to") == principal["name"]]


def report(kind: str, text: str) -> dict:
    require_principal()
    agent_id = current_agent_id()
    if not agent_id:
        raise RuntimeError("the top-level director has no parent to report to")
    rec = get_fleet().get(agent_id)
    if not rec:
        raise RuntimeError("current spawned agent is missing from the fleet")
    return send_message(kind, text, rec["parent_name"])


def wait_for_activity(seconds: float = 60) -> dict:
    require_principal()
    deadline = time.monotonic() + max(0.0, min(float(seconds), 240.0))
    while True:
        messages = read_messages()
        fleet = get_fleet()
        exited = _unseen_exits(fleet)
        if messages or exited or time.monotonic() >= deadline:
            return {"messages": messages, "exited": exited}
        time.sleep(0.1)


def extract_thread_id(log_path: str) -> str | None:
    try:
        lines = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        if event.get("type") == "thread.started" and event.get("thread_id"):
            return str(event["thread_id"])
    return None


def result_for(name: str) -> dict:
    require_principal()
    agent_id, rec = _direct_child_by_name(name)
    thread_id = rec.get("thread_id") or extract_thread_id(rec.get("log", ""))
    final = None
    try:
        lines = Path(rec["log"]).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        lines = []
    for line in lines:
        try:
            event = json.loads(line)
        except ValueError:
            continue
        item = event.get("item") or {}
        if event.get("type") == "item.completed" and item.get("type") == "agent_message":
            final = item.get("text")
    return {
        "id": agent_id,
        "name": rec["name"],
        "role": rec["role"],
        "running": rec.get("running"),
        "exit_status": rec.get("exit_status"),
        "generation": rec.get("generation", 1),
        "thread_id": thread_id,
        "final_message": _redact(final or "", MAX_RESULT_CHARS) if final else None,
        "log": rec["log"],
    }


def _update_runner_record(agent_id: str, thread_id: str | None) -> None:
    if not thread_id:
        return
    with locked():
        fleet = _read_json(FLEET_FILE, {})
        if agent_id in fleet:
            fleet[agent_id]["thread_id"] = thread_id
            fleet[agent_id]["updated_at"] = time.time()
            _write_json(FLEET_FILE, fleet)


def runner_main() -> int:
    payload = json.loads(sys.stdin.read())
    log_path = Path(payload["log"])
    argv = [str(value) for value in payload["argv"]]
    env = {str(key): str(value) for key, value in payload["env"].items()}
    prompt = str(payload["prompt"])
    agent_id = str(payload["agent_id"])
    thread_id = None
    status = 127
    with open(log_path, "a", encoding="utf-8", buffering=1) as log:
        try:
            proc = subprocess.Popen(
                argv,
                cwd=payload["cwd"],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )
            if proc.stdin is None or proc.stdout is None:
                raise RuntimeError("Codex process pipes unavailable")
            proc.stdin.write(prompt)
            proc.stdin.close()
            for line in proc.stdout:
                log.write(line)
                try:
                    event = json.loads(line)
                except ValueError:
                    continue
                if event.get("type") == "thread.started" and event.get("thread_id"):
                    thread_id = str(event["thread_id"])
                    _update_runner_record(agent_id, thread_id)
            status = proc.wait()
        except BaseException as exc:  # runner must leave bounded diagnostics for the parent
            log.write(json.dumps({"type": "director.runner_error", "message": _redact(str(exc))}) + "\n")
            status = 125
        log.write(f"--- codex-director exit status={status} thread_id={thread_id or '-'} ---\n")
    return status


if __name__ == "__main__" and sys.argv[1:] == ["__runner"]:
    raise SystemExit(runner_main())
