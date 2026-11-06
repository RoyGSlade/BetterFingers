"""Receive the backend's credentials from the Electron shell WITHOUT the environment.

Round 2, item 3 (Codex re-review). The shell used to pass the bearer token and the
approval-signing key as environment variables. On Linux the initial environment of a
process stays readable through ``/proc/<pid>/environ`` as long as the process lives,
whatever ``os.environ.pop`` does later, so any same-user program (an MCP server, a
download, a script) could read both and then forge approvals. Now:

* the shell starts this process with ``BETTERFINGERS_SECRETS_STDIN=1`` (a flag, not a
  secret) and writes ``{"token": ..., "approval_key": ...}`` to the child's stdin pipe,
  then closes it. A pipe is not visible in ``/proc/<pid>/environ``;
* ``load_from_stdin`` reads it once, before anything else starts, keeps the token in
  memory (``backend.api.security``) and the key in the approvals verifier, and
* ``harden_process`` marks the process non-dumpable (Linux ``PR_SET_DUMPABLE=0``) so
  other same-user processes cannot read ``/proc/<pid>/{environ,mem,maps}`` or attach a
  debugger to it. (Windows and macOS: see docs/DEVELOPMENT.md for what is and is not
  covered.)

Nothing here logs a value.
"""

from __future__ import annotations

import json
import os
import sys
import threading

FLAG = "BETTERFINGERS_SECRETS_STDIN"
MAX_BYTES = 16 * 1024
READ_TIMEOUT_S = 15.0

_PR_SET_DUMPABLE = 4
_PR_GET_DUMPABLE = 3


def harden_process() -> bool:
    """Make this process non-dumpable where the platform allows. True if applied."""
    if not sys.platform.startswith("linux"):
        return False
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(_PR_SET_DUMPABLE, 0, 0, 0, 0) == 0
    except Exception:
        return False


def is_dumpable():
    """Linux only: the process's dumpable flag (None elsewhere)."""
    if not sys.platform.startswith("linux"):
        return None
    try:
        import ctypes

        libc = ctypes.CDLL(None, use_errno=True)
        return libc.prctl(_PR_GET_DUMPABLE, 0, 0, 0, 0)
    except Exception:
        return None


def _read_all(stream, limit=MAX_BYTES, timeout=None) -> bytes:
    """Read the pipe to EOF on a helper thread so a shell that never closes it cannot
    hang startup forever."""
    box = {"data": b""}

    def reader():
        try:
            box["data"] = stream.read(limit + 1) or b""
        except Exception:
            box["data"] = b""

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    thread.join(READ_TIMEOUT_S if timeout is None else timeout)
    return box["data"][: limit + 1]


def load_from_stdin(env=None, stream=None, harden: bool = True) -> bool:
    """If the shell announced a stdin hand-off, consume it. Returns True when a token
    and/or key were installed."""
    environ = os.environ if env is None else env
    if environ.get(FLAG) != "1":
        return False
    environ.pop(FLAG, None)
    source = stream if stream is not None else getattr(sys.stdin, "buffer", None)
    if source is None:
        return False
    raw = _read_all(source)
    if not raw or len(raw) > MAX_BYTES:
        return False
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeError):
        return False
    if not isinstance(payload, dict):
        return False

    installed = False
    token = payload.get("token")
    if isinstance(token, str) and token:
        from backend.api.security import set_runtime_token

        set_runtime_token(token)
        installed = True
    key = payload.get("approval_key")
    if isinstance(key, str) and key:
        from backend.services import approvals

        try:
            approvals.configure(key)
            installed = True
        except ValueError:
            pass
    if harden:
        harden_process()
    return installed
