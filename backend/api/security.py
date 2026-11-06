"""Pure startup-security policy, split out of server.py (M6).

Fail-closed decisions with no I/O and no app state — the FastAPI app object,
``app.state`` token wiring, the auth middleware, and the per-process failure
throttle stay in server.py because they touch the running app. server.py
re-imports these names so ``server.validate_startup_security`` /
``server._allowed_cors_origins`` keep resolving for callers and tests.
"""

import os
import secrets

# Hosts that count as loopback — a bind to any of these needs no remote opt-in.
_LOOPBACK_HOSTS = {"127.0.0.1", "::1", "localhost"}


def _allowed_cors_origins():
    """Browser origins allowed to call this API (Phase 0 item 5).

    The Electron renderer no longer talks to the backend at all: since Phase 3c
    every request goes through the main process (Node ``fetch``, which sends no
    ``Origin``). So there is no packaged-app origin to allow, and the opaque
    ``null`` and ``file://`` origins that used to be here are gone -- ``null`` is
    what a sandboxed iframe or a ``data:`` page sends, i.e. anyone. Only the
    electron-vite dev server (not in production) and origins the operator names
    explicitly in ``BETTERFINGERS_CORS_ORIGINS`` remain.
    """
    origins = []
    if os.getenv("BETTERFINGERS_ENV", "development").lower() != "production":
        origins.extend(["http://localhost:5173", "http://127.0.0.1:5173"])
    extra = os.getenv("BETTERFINGERS_CORS_ORIGINS", "")
    origins.extend(o.strip() for o in extra.split(",") if o.strip() and o.strip().lower() not in {"null", "file://"})
    return origins


def _split_host_header(value):
    """``"127.0.0.1:8000"`` -> ``("127.0.0.1", "8000")``; ``"[::1]:8000"`` -> ``("::1", "8000")``."""
    value = str(value or "").strip().lower()
    if not value:
        return None, None
    if value.startswith("["):
        end = value.find("]")
        if end == -1:
            return None, None
        host = value[1:end]
        rest = value[end + 1:]
        if rest.startswith(":") and rest[1:].isdigit():
            return host, rest[1:]
        return (host, "") if rest == "" else (None, None)
    if value.count(":") > 1:
        return None, None  # an unbracketed IPv6 literal is not a valid Host value
    host, _, port = value.partition(":")
    if port and not port.isdigit():
        return None, None
    return host, port


def check_request_origin(host_header, origin_header, *, server_port=None, env=None, allow_testserver=False):
    """Reject DNS-rebinding and cross-site browser requests (Phase 0 item 5).

    Returns ``None`` when the request may proceed, else a short reason (never an
    echo of a header value). Two independent checks:

    * **Host** must be a loopback name (``127.0.0.1``, ``localhost``, ``[::1]``)
      on the port the server is actually listening on. A DNS-rebinding page keeps
      its own hostname in ``Host``, so it fails here even though the TCP peer is
      127.0.0.1. Skipped only for an explicit remote bind
      (``BETTERFINGERS_ALLOW_REMOTE=1``), where the bearer token is the gate.
    * **Origin**, when the request carries one, must be a configured origin or the
      server's own origin. The app's own callers (Electron main, curl, the Stream
      Deck bridge) send none; a browser always does on a cross-site request.
    """
    env = os.environ if env is None else env
    remote = str(env.get("BETTERFINGERS_ALLOW_REMOTE", "")) == "1"

    host, port = _split_host_header(host_header)
    if not remote:
        allowed = {"127.0.0.1", "localhost", "::1"}
        extra = str(env.get("BETTERFINGERS_ALLOWED_HOSTS", ""))
        allowed.update(h.strip().lower() for h in extra.split(",") if h.strip())
        if allow_testserver:
            allowed.add("testserver")
        if host is None or host not in allowed:
            return "host_not_allowed"
        if server_port is not None and host != "testserver" and str(port or "") != str(server_port):
            return "host_not_allowed"

    if origin_header not in (None, ""):
        origin = str(origin_header).strip().rstrip("/")
        configured = {o.rstrip("/") for o in _allowed_cors_origins()}
        own = {f"http://{str(host_header or '').strip().lower()}"} if host_header and (remote or host) else set()
        if origin not in configured and origin.lower() not in own:
            return "origin_not_allowed"
    return None


def validate_startup_security(host, token, env=None, allow_remote=False):
    """Fail-closed startup policy (pure; unit-tested).

    Returns {"ok", "token", "generated", "error"}:
    - Non-loopback bind requires BOTH an explicit opt-in and a token — an
      accidental 0.0.0.0 must never expose an unauthenticated API.
    - Packaged/production mode requires a token (the Electron shell always
      supplies one; a production launch without one is a misconfiguration).
    - Standalone dev launch without a token gets a generated one, printed
      once by the caller — the API never runs open by accident.
    """
    env = (env or os.getenv("BETTERFINGERS_ENV", "development")).lower()
    host_normalized = str(host or "").strip().lower()
    loopback = host_normalized in _LOOPBACK_HOSTS

    if not loopback:
        if not allow_remote:
            return {"ok": False, "token": token, "generated": False,
                    "error": f"Refusing to bind to non-loopback host {host!r} without "
                             f"BETTERFINGERS_ALLOW_REMOTE=1."}
        if not token:
            return {"ok": False, "token": token, "generated": False,
                    "error": "Refusing a non-loopback bind without BETTERFINGERS_AUTH_TOKEN set."}

    if not token:
        if env == "production":
            return {"ok": False, "token": token, "generated": False,
                    "error": "BETTERFINGERS_AUTH_TOKEN is required in production mode."}
        return {"ok": True, "token": secrets.token_hex(32), "generated": True, "error": ""}

    return {"ok": True, "token": token, "generated": False, "error": ""}


def announce_generated_token(token, env=None, out=None):
    """Hand a generated standalone token to the developer WITHOUT printing it.

    Anything written to stdout ends up in terminal scrollback, supervisors, CI
    logs and support collections (Phase 0 item 10). If ``BETTERFINGERS_TOKEN_FILE``
    names a path, the token is written there with owner-only permissions;
    otherwise the developer is told how to choose their own. Returns a short
    description of where the token went (never the token).
    """
    env = os.environ if env is None else env
    out = print if out is None else out
    target = str(env.get("BETTERFINGERS_TOKEN_FILE", "") or "").strip()
    if target:
        try:
            fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(token)
            try:
                os.chmod(target, 0o600)
            except OSError:
                pass
            message = f"wrote the generated auth token to {target} (owner-only)"
        except OSError as exc:
            message = f"could not write BETTERFINGERS_TOKEN_FILE ({exc.__class__.__name__}); the token was not saved"
    else:
        message = ("generated an ephemeral auth token for this run; set BETTERFINGERS_AUTH_TOKEN "
                   "(or BETTERFINGERS_TOKEN_FILE=<path>) to choose or retrieve one")
    out(f"[betterfingers] {message}")
    return message


# --- the bearer token, held in memory ------------------------------------------
# Round 2, item 3. An environment variable is readable by any same-user process
# through /proc/<pid>/environ for the life of the process (and Python's os.environ.pop
# does not touch that initial copy). The Electron shell therefore hands the backend its
# bearer token over the child's stdin pipe (backend/privacy/boot_secrets.py), and it
# lives here. A standalone developer launch can still supply BETTERFINGERS_AUTH_TOKEN in
# the environment; that fallback keeps `python server.py` and the test suite working.
_runtime_token = None


def set_runtime_token(token):
    global _runtime_token
    _runtime_token = str(token) if token else None


def get_auth_token():
    """The active bearer token: the in-memory one if the shell supplied it, else the
    environment's (standalone/dev), else None."""
    return _runtime_token or os.getenv("BETTERFINGERS_AUTH_TOKEN") or None
