"""Redact user-dictated content from logs by default (DESIGN §9.3).

Dictated text, TTS phrases, prompts, and command utterances can leak into Python
logs, the sidecar log, CI artifacts, and diagnostics exports. A local-first app's
transcripts may be the most sensitive text on the machine (patient info, legal
work, journals), so the default posture is: **never write raw user content to a
log**. Callers log a redacted summary instead — the character count, so log volume
and flow are still debuggable without exposing what the user actually said.

A developer who genuinely needs raw text while debugging can opt in for the
process with the env var ``BETTERFINGERS_LOG_RAW_TEXT=1``. End users never need to.

Pure module: no logging config, no I/O beyond one env read — trivially testable.
"""

import os
import re

_ENV_ALLOW_RAW = "BETTERFINGERS_LOG_RAW_TEXT"
_TRUTHY = {"1", "true", "yes", "on"}

# llama-server stderr line filter (DESIGN §9.3, Tier-3 M4 A2): the runtime-
# validation UX and its tests depend on loader/system diagnostic fragments
# (e.g. "libmtmd.so.0") surviving verbatim — a blanket redact_user_text() over
# the whole blob would break validate_llama_server_runtime's error surfacing.
# At higher verbosity, llama-server stderr can also echo prompt content, which
# is exactly what must NOT survive. Line-level allowlist splits the
# difference: keep lines that look like loader/system diagnostics, redact
# everything else per-line.
_STDERR_ALLOWLIST_RE = re.compile(
    r"error|failed|missing|lib|\.so|\.dll|cuda|vulkan|version|build|load",
    re.IGNORECASE,
)


def raw_text_logging_enabled():
    """True when the operator has opted into logging raw user content this run."""
    return os.getenv(_ENV_ALLOW_RAW, "").strip().lower() in _TRUTHY


def redact_user_text(text):
    """Return a log-safe representation of user content.

    Default: ``"<redacted N chars>"`` (``"<empty>"`` for empty/None). When raw
    logging is opted in via the env var, returns the text unchanged so local
    debugging is unaffected. The length is intentionally *not* redacted — a count
    leaks nothing about content but keeps logs useful for spotting truncation,
    empty-input, and size-related bugs.
    """
    if raw_text_logging_enabled():
        return "" if text is None else str(text)
    if text is None:
        return "<empty>"
    s = str(text)
    n = len(s)
    if n == 0:
        return "<empty>"
    return f"<redacted {n} chars>"


def redacted_len(text):
    """Character count of user content, safe to log unconditionally."""
    return 0 if text is None else len(str(text))


def redact_exc(exc):
    """Redact an exception's message while preserving its type.

    TARGETED, not a blanket rule: use this ONLY at the specific call sites
    audited in docs/redaction-audit.md, where the exception's message can
    embed user-dictated content (a transcript/prompt/final_text flowing
    through a broad try/except). Elsewhere in the codebase an exception
    message is usually a file path or config value — diagnostic information,
    not user content — and should keep logging unredacted, same as any other
    FileNotFoundError-style message.
    """
    return f"{type(exc).__name__}: {redact_user_text(str(exc))}"


def redact_stderr_lines(text):
    """Line-level filter for llama-server stderr (DESIGN §9.3): keep lines
    that look like loader/system diagnostics (see _STDERR_ALLOWLIST_RE —
    validate_llama_server_runtime's error surfacing depends on fragments like
    "libmtmd.so.0" surviving verbatim), replace every other line with a
    per-line redaction marker. Preserves line count, same "count survives,
    content doesn't" philosophy as redact_user_text.
    """
    if raw_text_logging_enabled():
        return "" if text is None else str(text)
    if not text:
        return ""
    lines = str(text).splitlines()
    return "\n".join(
        line if _STDERR_ALLOWLIST_RE.search(line) else f"<redacted {len(line)} chars>"
        for line in lines
    )
