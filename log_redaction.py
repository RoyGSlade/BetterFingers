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

_ENV_ALLOW_RAW = "BETTERFINGERS_LOG_RAW_TEXT"
_TRUTHY = {"1", "true", "yes", "on"}


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
