"""Keep credentials out of child processes and out of text that gets logged.

Two small, pure helpers shared by the Phase 0 security fixes:

* ``scrubbed_child_env`` builds the environment for a subprocess the backend
  launches on behalf of something it does not control (an MCP server, the
  llama-server runtime). The backend's own environment carries the sidecar bearer
  token (``BETTERFINGERS_AUTH_TOKEN``) and the approval key
  (``BETTERFINGERS_APPROVAL_KEY``), and the user's shell may carry provider keys;
  none of that may leak by inheritance. The child gets an ALLOWLIST of variables
  it needs to run, plus whatever the caller names explicitly.
* ``redact_secrets`` / ``redact_args`` mask bearer tokens, ``token=`` query
  parameters, ``auth:`` first-frame messages and well-known key shapes in any
  string headed for a log, an error message or an API response.

No logging configuration and no I/O beyond reading the mapping it is handed.
"""

from __future__ import annotations

import os
import re
from typing import Iterable, Mapping, Optional

REDACTED = "[redacted]"

# What a child process legitimately needs to start and find its own files. Exact
# names compared case-insensitively (Windows environment names are
# case-insensitive), plus the LC_* locale family.
CHILD_ENV_ALLOWLIST = frozenset(
    name.upper()
    for name in (
        "PATH", "PATHEXT", "HOME", "USER", "USERNAME", "LOGNAME", "SHELL", "TERM", "LANG", "LANGUAGE",
        "TZ", "TMPDIR", "TEMP", "TMP", "USERPROFILE", "HOMEDRIVE", "HOMEPATH", "APPDATA",
        "LOCALAPPDATA", "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "COMMONPROGRAMFILES",
        "SYSTEMROOT", "SYSTEMDRIVE", "WINDIR", "COMSPEC", "NUMBER_OF_PROCESSORS",
        "PROCESSOR_ARCHITECTURE", "OS", "XDG_RUNTIME_DIR", "DISPLAY", "WAYLAND_DISPLAY",
    )
)

# Never forwarded, not even when a caller's explicit ``extra`` mapping names them:
# these are the app's own credentials, and a child has no business holding them.
_PROTECTED_PREFIXES = ("BETTERFINGERS_",)


def _is_protected(name: str) -> bool:
    upper = name.upper()
    return upper.startswith(_PROTECTED_PREFIXES)


def scrubbed_child_env(
    base: Optional[Mapping[str, str]] = None,
    extra: Optional[Mapping[str, str]] = None,
    *,
    drop_prefixes: Iterable[str] = (),
) -> dict:
    """The environment a launched child process should get.

    ``base`` (default ``os.environ``) contributes only allowlisted names.
    ``extra`` is the caller's explicit, deliberate additions (for an MCP server,
    the ``env`` block the user wrote for that server); it is applied on top
    except for the app's own ``BETTERFINGERS_*`` credentials, which are refused.
    ``drop_prefixes`` removes further name prefixes from the result (the
    llama-server runtime drops ``LLAMA_ARG_`` this way, because those variables
    silently change how it runs).
    """
    source = os.environ if base is None else base
    env = {}
    for name, value in source.items():
        upper = str(name).upper()
        if upper in CHILD_ENV_ALLOWLIST or upper.startswith("LC_"):
            env[str(name)] = str(value)
    for name, value in (extra or {}).items():
        if _is_protected(str(name)):
            continue
        env[str(name)] = str(value)
    prefixes = tuple(prefix.upper() for prefix in drop_prefixes)
    if prefixes:
        env = {k: v for k, v in env.items() if not k.upper().startswith(prefixes)}
    return env


def without_prefixes(env: Mapping[str, str], prefixes: Iterable[str]) -> dict:
    """A copy of ``env`` minus every variable whose name starts with a prefix
    (case-insensitive). The llama-server runtime keeps the rest of the
    environment (GPU drivers, ``CUDA_*``, ``VK_*``, ``LD_LIBRARY_PATH`` all matter
    to it) and only loses the names that would change how it listens or what it
    trusts."""
    drop = tuple(prefix.upper() for prefix in prefixes)
    return {k: v for k, v in env.items() if not str(k).upper().startswith(drop)}


# --- redaction ---------------------------------------------------------------

# "Authorization: Bearer abc", "authorization=Bearer abc", bare "Bearer abc".
_BEARER_RE = re.compile(r"(?i)\b(bearer)([\s:=]+)([A-Za-z0-9._~+/=\-]{6,})")
# token=..., access_token=..., api_key=..., apikey=..., auth_token=, secret=, password=
# in a query string, a form body or a "key=value" log line.
_KV_RE = re.compile(
    r"(?i)\b((?:[a-z0-9]*[_\-])*(?:token|api[_\-]?key|apikey|secret|password|passwd|auth))"
    r"(=|:\s*)(?!\[redacted\])([^\s&\"'<>,;]{3,})"
)
# Quoted keys, as in JSON bodies and Python dict reprs: {"token": "abc"}, {'Authorization': 'x'}.
# The unquoted pattern above never matched these because the key is followed by a quote, not
# by = or : (Codex re-review). The value is masked whatever its shape.
_QUOTED_KV_RE = re.compile(
    r"""(?ix)
    (["'])((?:[a-z0-9]*[_\-])*(?:token|api[_\-]?key|apikey|secret|password|passwd|auth|authorization|credential|credentials))\1
    (\s*:\s*)
    (["'])(.*?)(?<!\\)\4
    """
)
# The WebSocket first-frame form: "auth:<token>".
_AUTH_FRAME_RE = re.compile(r"(?i)\b(auth:)([A-Za-z0-9._~+/=\-]{6,})")
# Well-known shapes that are secrets wherever they appear.
_KEY_SHAPE_RE = re.compile(
    r"\b(sk-ant-[A-Za-z0-9_\-]{8,}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abpr]-[A-Za-z0-9\-]{10,}|"
    r"AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,})\b"
)
# 48+ hex characters: this app's own token is secrets.token_hex(32) (64 chars).
_LONG_HEX_RE = re.compile(r"\b[0-9a-fA-F]{48,}\b")

_SECRET_FLAG_RE = re.compile(r"(?i)^--?(?:[a-z0-9_\-]*)(?:token|api[_\-]?key|apikey|secret|password|passwd|auth)(?:[a-z0-9_\-]*)$")


def redact_secrets(text) -> str:
    """Mask credential-shaped substrings. Idempotent; never raises."""
    if text is None:
        return ""
    out = str(text)
    out = _QUOTED_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(1)}{m.group(3)}{m.group(4)}{REDACTED}{m.group(4)}", out)
    out = _BEARER_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    out = _AUTH_FRAME_RE.sub(lambda m: f"{m.group(1)}{REDACTED}", out)
    out = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}", out)
    out = _KEY_SHAPE_RE.sub(REDACTED, out)
    out = _LONG_HEX_RE.sub(REDACTED, out)
    return out


def redact_args(args) -> list:
    """A command line safe to show in an API response.

    Masks the value after a secret-looking flag (``--api-key X``), the value in
    ``--token=X`` / ``KEY=value`` forms, and any argument shaped like a key.
    """
    out = []
    mask_next = False
    for raw in args or []:
        arg = str(raw)
        if mask_next:
            out.append(REDACTED)
            mask_next = False
            continue
        if _SECRET_FLAG_RE.match(arg):
            out.append(arg)
            mask_next = True
            continue
        redacted = redact_secrets(arg)
        if redacted == arg and "=" in arg:
            name, _, value = arg.partition("=")
            if _SECRET_FLAG_RE.match(name if name.startswith("-") else f"--{name}"):
                redacted = f"{name}={REDACTED}"
        out.append(redacted)
    return out


# --- logging -----------------------------------------------------------------

import logging as _logging


class SecretRedactingFilter(_logging.Filter):
    """Rewrites a log record so credentials never reach a handler.

    uvicorn's access log prints the request line (``GET /path?token=... HTTP/1.1``)
    and anything logged with ``%s`` may embed an ``Authorization`` value; this
    filter masks both before the record is formatted by any handler.
    """

    def filter(self, record: _logging.LogRecord) -> bool:  # noqa: A003 - logging API name
        try:
            message = record.getMessage()
        except Exception:  # a malformed format string must not become a logging crash
            return True
        redacted = redact_secrets(message)
        if redacted != message:
            record.msg = redacted
            record.args = ()
        # Exception and stack text is formatted by the HANDLER from exc_info, after this filter
        # has run, so scrubbing the message alone left tracebacks (which routinely quote the
        # failing request, headers included) untouched. Format it here once, scrub it, and let the
        # formatter reuse the cached, scrubbed text (logging.Formatter does when exc_text is set).
        if record.exc_info and not record.exc_text:
            try:
                record.exc_text = redact_secrets(_logging.Formatter().formatException(record.exc_info))
            except Exception:
                record.exc_text = "[traceback withheld: it could not be formatted safely]"
        elif record.exc_text:
            record.exc_text = redact_secrets(record.exc_text)
        if record.stack_info:
            record.stack_info = redact_secrets(record.stack_info)
        return True


_FILTER_ATTR = "_bf_secret_filter"

#: Loggers whose records can carry request lines or headers.
HTTP_LOGGER_NAMES = ("uvicorn", "uvicorn.access", "uvicorn.error", "fastapi", "starlette")


def install_log_redaction(extra_loggers: Iterable[str] = HTTP_LOGGER_NAMES) -> None:
    """Attach the redacting filter to the root handlers and the HTTP loggers.

    Idempotent. A logger-level filter only sees records logged ON that logger, so
    the filter is also put on every handler: that is the point every record,
    from any logger, passes through before it is written.
    """
    targets = [_logging.getLogger()] + [_logging.getLogger(name) for name in extra_loggers]
    for target in targets:
        for holder in [target, *target.handlers]:
            if not any(isinstance(f, SecretRedactingFilter) for f in holder.filters):
                holder.addFilter(SecretRedactingFilter())
