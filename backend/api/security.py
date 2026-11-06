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
    origins = ["null", "file://", "http://localhost:5173", "http://127.0.0.1:5173"]
    extra = os.getenv("BETTERFINGERS_CORS_ORIGINS", "")
    origins.extend(o.strip() for o in extra.split(",") if o.strip())
    return origins


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
