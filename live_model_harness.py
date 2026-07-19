"""Live-model Message Rescue integration harness (Build Week I3.10).

Pure decision/report logic (readiness classification, one preservation-critical
probe run, and structural-only report building) is here so it is fully unit
testable with fakes — no network, no subprocess, no real model required. The
HTTP/CLI glue that wires this to the real local llama-server sidecar lives in
``tools/live_model_harness.py``, and ``tests/test_live_model_integration.py``
wires it into pytest with an explicit skip when no live model is available.
Mirrors ``reliability_benchmark.py`` / ``tools/reliability_benchmark.py``'s
existing split between testable logic and I/O glue.

Every dependency (readiness check, model-status lookup, the model call
itself) is injected, exactly like ``backend.services.message_rescue.rescue_message``'s
own ``call_fn`` boundary — this module never imports ``requests``,
``llm_engine``, or ``model_manager`` directly.

Privacy: nothing here ever inspects, logs, or returns transcript or model
*content*. The report is structural only — booleans, counts, category names,
elapsed seconds — matching ``backend/services/message_rescue.py``'s own
"count survives, content doesn't" convention.
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping

from backend.domain.contracts import SpeechSignals
from backend.services.message_rescue import check_preservation, parse_rescue_response, rescue_message

# One hand-authored synthetic transcript (matches docs/TEST_DATA_POLICY.md's
# provenance rule: no real person's speech, no PII-shaped strings) engineered
# to exercise every preservation category check_preservation() knows about:
# a name ("Marcus"), a weekday + ISO date, a phone-shaped and a currency-shaped
# number, negation ("won't"), modality ("can"/"won't"), and a commitment
# phrase ("I'll follow up").
PRESERVATION_TRANSCRIPT = (
    "Tell Marcus I can meet on Friday at 4 PM, but I won't send the contract to "
    "555-0148 before he confirms the $12,000 budget. I'll follow up by 2026-08-01."
)

# Deliberately disjoint from PRESERVATION_TRANSCRIPT so a verbatim slice of
# this showing up in the model's output is unambiguous evidence of a context
# leak, never a coincidental overlap with the transcript's own wording.
DEFAULT_CONTEXT_TEXT = (
    "Earlier thread: quarterly planning notes about staffing levels and the "
    "warehouse relocation timeline discussed last week."
)

_LEAK_WINDOW = 24


def _context_leaked(context_text: str | None, candidate_text: str) -> bool:
    """Same sliding-window verbatim-slice check as message_rescue._context_leak,
    duplicated (not imported) so this harness can assert on leakage
    independently of the module under test, matching the duplication
    precedent already set by ``backend/services/rescue_llm_adapter.py``."""
    if not context_text or not candidate_text:
        return False
    ctx = context_text.strip()
    if len(ctx) < _LEAK_WINDOW:
        return False
    step = max(1, _LEAK_WINDOW // 2)
    for i in range(0, len(ctx) - _LEAK_WINDOW + 1, step):
        window = ctx[i : i + _LEAK_WINDOW]
        if window.strip() and window in candidate_text:
            return True
    return False


def discover_readiness(
    *,
    is_server_running: Callable[[], bool],
    get_model_status: Callable[[str | None], Mapping[str, Any]] | None = None,
    model_id: str | None = None,
) -> dict[str, Any]:
    """Classify whether a real local model is available to probe.

    ``is_server_running`` is the sidecar health check (e.g.
    ``llm_engine.is_server_running``); ``get_model_status`` is an optional
    model-file lookup (e.g. ``model_manager.get_model_file_status``) used only
    to make the "unavailable" reason more specific (missing vs. incomplete vs.
    "server just isn't started"). Never raises: a failing ``get_model_status``
    degrades to a less specific reason rather than aborting the check.
    """
    running = False
    try:
        running = bool(is_server_running())
    except Exception:
        running = False

    model_status: Mapping[str, Any] | None = None
    if get_model_status is not None:
        try:
            model_status = get_model_status(model_id)
        except Exception:
            model_status = None
    model_ok = bool(model_status.get("ok")) if isinstance(model_status, Mapping) else None

    if running:
        return {
            "available": True,
            "reason": "local model server responded healthy on its health endpoint",
            "model_id": model_id,
            "model_ok": model_ok,
        }

    reason = "local model server did not respond to its health endpoint"
    if isinstance(model_status, Mapping) and not model_status.get("ok", True):
        attention = list(model_status.get("attention") or [])
        detail = ", ".join(attention) if attention else "not ok"
        reason = f"model file not ready ({detail}); server also did not respond"

    return {
        "available": False,
        "reason": reason,
        "model_id": model_id,
        "model_ok": model_ok,
    }


def _wrap_call_fn(call_fn: Callable[[list[dict[str, str]]], str], telemetry: dict[str, Any]):
    """Wrap ``call_fn`` to record structural (never content) telemetry about
    whether the real model call actually happened and what shape it returned,
    while still delegating to it (and re-raising) so rescue_message's own
    fallback behavior is exercised unchanged."""

    def wrapped(messages: list[dict[str, str]]) -> str:
        telemetry["invoked"] = True
        try:
            response = call_fn(messages)
        except Exception as exc:
            telemetry["raised"] = True
            telemetry["exception_type"] = type(exc).__name__
            raise
        telemetry["response_char_count"] = len(response) if isinstance(response, str) else 0
        telemetry["response_parsed_as_json"] = parse_rescue_response(response) is not None
        return response

    return wrapped


def run_preservation_probe(
    call_fn: Callable[[list[dict[str, str]]], str],
    *,
    transcript: str = PRESERVATION_TRANSCRIPT,
    context_text: str | None = DEFAULT_CONTEXT_TEXT,
) -> dict[str, Any]:
    """Run exactly one Message Rescue request through the real ``call_fn`` and
    return a structural-only report.

    Status is one of:
      - ``CALL_FAILED``: the real model call raised (network/timeout/adapter
        error) — the readiness check said available but the call itself
        still failed, which is a distinct, more actionable signal than a
        preservation failure.
      - ``FAIL``: the call succeeded but the final ``faithful`` variant is
        empty, dropped a preserved fact, or leaked captured context — this
        would mean ``rescue_message``'s own safety net failed against real
        (messier than any hand-crafted fake) model output.
      - ``PASS``: the call succeeded and the final faithful variant is
        non-empty, preserves every checked category, and does not leak
        context — whether the raw model output got there directly or via
        the safety-net fallback to the raw transcript.
    """
    telemetry: dict[str, Any] = {
        "invoked": False,
        "raised": False,
        "exception_type": None,
        "response_char_count": 0,
        "response_parsed_as_json": False,
    }
    wrapped = _wrap_call_fn(call_fn, telemetry)

    signals = SpeechSignals(confidence=0.8)
    started = time.monotonic()
    result = rescue_message(transcript, signals, context_text=context_text, call_fn=wrapped)
    elapsed_s = round(time.monotonic() - started, 3)

    faithful = result.variants.get("faithful", "")
    non_empty = bool(faithful.strip())
    checks = check_preservation(transcript, faithful, label="faithful") if non_empty else []
    categories = sorted({c["name"].split("/", 1)[1] for c in checks})
    all_passed = non_empty and all(c["passed"] for c in checks)
    leaked = non_empty and _context_leaked(context_text, faithful)

    if telemetry["raised"]:
        status = "CALL_FAILED"
    elif non_empty and all_passed and not leaked:
        status = "PASS"
    else:
        status = "FAIL"

    return {
        "status": status,
        "model_call_invoked": telemetry["invoked"],
        "model_call_raised": telemetry["raised"],
        "model_call_exception_type": telemetry["exception_type"],
        "response_char_count": telemetry["response_char_count"],
        "response_parsed_as_json": telemetry["response_parsed_as_json"],
        "faithful_non_empty": non_empty,
        "faithful_char_count": len(faithful),
        "preservation_categories_checked": categories,
        "preservation_all_passed": all_passed,
        "context_leak_detected": leaked,
        "model_warnings_count": len(result.warnings),
        "elapsed_s": elapsed_s,
    }


def run_harness(
    *,
    is_server_running: Callable[[], bool],
    call_fn: Callable[[list[dict[str, str]]], str],
    get_model_status: Callable[[str | None], Mapping[str, Any]] | None = None,
    model_id: str | None = None,
    context_text: str | None = DEFAULT_CONTEXT_TEXT,
    transcript: str = PRESERVATION_TRANSCRIPT,
) -> dict[str, Any]:
    """Discover readiness, then run the probe only if a model is available.

    Returns ``{"status": "UNAVAILABLE"|"CALL_FAILED"|"FAIL"|"PASS", "reason": str,
    "readiness": {...}, "probe": {...}|None}``. ``UNAVAILABLE`` is never
    conflated with ``PASS`` — callers (CLI exit code, pytest skip) must branch
    on it explicitly.
    """
    readiness = discover_readiness(
        is_server_running=is_server_running, get_model_status=get_model_status, model_id=model_id
    )
    if not readiness["available"]:
        return {"status": "UNAVAILABLE", "reason": readiness["reason"], "readiness": readiness, "probe": None}

    probe = run_preservation_probe(call_fn, transcript=transcript, context_text=context_text)
    return {"status": probe["status"], "reason": readiness["reason"], "readiness": readiness, "probe": probe}
