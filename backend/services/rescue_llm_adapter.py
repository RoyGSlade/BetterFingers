"""Local-LLM call adapter for Message Rescue (I3.2).

Bridges backend.services.message_rescue's injected ``call_fn`` boundary
(``list[dict] -> str``) to the real local llama-server OpenAI-compatible
endpoint. Uses the same (connect, read) timeout-scaling idea as
``llm_engine.compute_api_read_timeout`` — duplicated here rather than
imported, so this module (and message_rescue.py, which it feeds) stays
importable without pulling in llm_engine's heavier subprocess/model-lifecycle
surface. Mirrors message_rescue.py's own MAX_FEW_SHOT_EXAMPLES precedent for
why that duplication is deliberate.

Never logs anything: a failed call is surfaced to the caller as a raised
exception (TimeoutError for a request timeout, so
backend.services.message_rescue's own timeout detection maps it to a safe
fallback) — no message content, prompt, or completion ever reaches logging.
"""

from __future__ import annotations

from typing import Protocol

import requests

_ASSUMED_TOKENS_PER_SEC = 8.0
_CONNECT_TIMEOUT_S = 5.0
_READ_TIMEOUT_FLOOR_S = 45.0
_READ_TIMEOUT_CEILING_S = 180.0
DEFAULT_MAX_OUTPUT_TOKENS = 1100


def compute_read_timeout_s(
    max_tokens,
    tokens_per_second: float = _ASSUMED_TOKENS_PER_SEC,
    floor: float = _READ_TIMEOUT_FLOOR_S,
    ceiling: float = _READ_TIMEOUT_CEILING_S,
) -> float:
    """Scale the HTTP read timeout to the requested token budget (never raises)."""
    try:
        tokens = max(1, int(max_tokens))
    except (TypeError, ValueError):
        tokens = DEFAULT_MAX_OUTPUT_TOKENS
    estimated = tokens / max(0.1, float(tokens_per_second))
    return max(floor, min(ceiling, estimated))


class _EngineLike(Protocol):
    api_url: str


def build_llm_call_fn(
    engine: _EngineLike,
    *,
    max_output_tokens: int | None = None,
    temperature: float = 0.2,
):
    """Return a ``list[dict] -> str`` callable bound to ``engine.api_url``.

    The returned callable is the exact ``call_fn`` boundary
    ``backend.services.message_rescue.rescue_message`` expects: it takes the
    OpenAI-style chat messages ``build_rescue_prompt`` produces and returns
    the raw completion string, or raises. A request timeout is re-raised as a
    plain ``TimeoutError`` so ``rescue_message``'s own
    ``_looks_like_timeout`` classification (which checks
    ``isinstance(exc, TimeoutError)`` first) reliably takes the "model call
    timed out" branch rather than the generic failure one.
    """
    safe_max_tokens = max(64, min(4096, int(max_output_tokens or DEFAULT_MAX_OUTPUT_TOKENS)))
    read_timeout = compute_read_timeout_s(safe_max_tokens)

    def call_fn(messages: list[dict[str, str]]) -> str:
        try:
            response = requests.post(
                f"{engine.api_url}/v1/chat/completions",
                json={
                    "messages": messages,
                    "temperature": temperature,
                    "max_tokens": safe_max_tokens,
                    "stream": False,
                },
                timeout=(_CONNECT_TIMEOUT_S, read_timeout),
            )
            response.raise_for_status()
            data = response.json()
            return str(data["choices"][0]["message"]["content"])
        except requests.exceptions.Timeout as exc:
            raise TimeoutError("local LLM call timed out") from exc

    return call_fn
