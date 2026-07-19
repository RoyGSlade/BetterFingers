"""Message Rescue context + generation routes (I3.2).

Thin FastAPI adapter over F2.5's ``ContextSession``/selection adapter and
F2.7's ``rescue_message``. ``create_message_rescue_router`` is a factory that
takes every side-effecting dependency (context session, LLM call function,
persona/example lookups, clock, id generator) as an explicit parameter, so
the whole router is unit-testable with fakes — no FastAPI app, real model, or
network access required for its own tests. ``router`` below is the
production-wired instance (module-level singleton, same shape as the other
extracted routers e.g. ``backend/api/routes/personas.py``) ready for
``app.include_router(routes_message_rescue.router)``.

Auth is enforced globally by ``server.py``'s bearer-token middleware once
this router is mounted on the real app — nothing route-specific is needed
here for that.

Nothing in this module calls ``logging`` or puts request content into an
``HTTPException`` detail: every error detail is a fixed, enumerable string
(a capture/context-exhaustion reason, a generation status) so no dictated or
captured text can leak into logs, error responses, or OpenAPI examples.
"""

from __future__ import annotations

import asyncio
import threading
import time
import uuid
from collections import OrderedDict
from typing import Any, Callable, Mapping, Sequence

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.domain.contracts import SpeechSignals, to_dict
from backend.services.context_session import (
    ContextCaptureError,
    ContextExhaustedError,
    ContextSession,
)
from backend.services.message_rescue import rescue_message

MAX_TRANSCRIPT_CHARS = 20_000
MAX_MANUAL_CONTEXT_CHARS = 20_000
MAX_PERSONA_NAME_CHARS = 200
DEFAULT_GENERATE_TIMEOUT_S = 190.0  # just above rescue_llm_adapter's 180s read-timeout ceiling
MAX_STORED_RESULTS = 50


class ManualContextRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=MAX_MANUAL_CONTEXT_CHARS)


class SpeechSignalsIn(BaseModel):
    """Mirrors the frozen SpeechSignals contract field-for-field.

    A caller (the renderer, echoing what the dictation pipeline computed and
    persisted on the draft) supplies this; it is never computed from
    request-supplied audio/text here.
    """

    words_per_minute: float = 0.0
    speaking_ratio: float = 0.0
    pause_count: int = 0
    pause_ratio: float = 0.0
    mean_pause_s: float = 0.0
    longest_pause_s: float = 0.0
    filler_count: int = 0
    self_correction_count: int = 0
    energy_mean: float = 0.0
    energy_variation: float = 0.0
    delivery_axes: dict[str, float] = Field(default_factory=dict)
    evidence: list[str] = Field(default_factory=list, max_length=8)
    confidence: float = 0.0

    def to_contract(self) -> SpeechSignals:
        return SpeechSignals(**self.model_dump())


class GenerateRequest(BaseModel):
    transcript: str = Field(..., min_length=1, max_length=MAX_TRANSCRIPT_CHARS)
    signals: SpeechSignalsIn | None = None
    persona: str | None = Field(None, max_length=MAX_PERSONA_NAME_CHARS)
    use_context: bool = False


def _empty_context_status() -> dict[str, Any]:
    return {
        "active": False,
        "id": None,
        "source": None,
        "captured_at": None,
        "expires_at": None,
        "use_count": None,
        "max_uses": None,
        "visible_preview": None,
    }


class _GenerationCancelled(Exception):
    """Raised by the guarded call_fn when a cancel request arrived first."""


def create_message_rescue_router(
    *,
    context_session: ContextSession,
    call_fn: Callable[[list[dict[str, str]]], str],
    persona_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
    examples_lookup: Callable[[str], Sequence[Mapping[str, Any]] | None] | None = None,
    selection_capture_fn: Callable[[], dict] | None = None,
    selection_supported_fn: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.time,
    id_factory: Callable[[], str] = lambda: uuid.uuid4().hex,
    generate_timeout_s: float = DEFAULT_GENERATE_TIMEOUT_S,
    max_stored_results: int = MAX_STORED_RESULTS,
) -> APIRouter:
    router = APIRouter()

    _lock = threading.Lock()
    _cancel_events: dict[str, threading.Event] = {}
    _results: "OrderedDict[str, dict[str, Any]]" = OrderedDict()

    def _store_result(job_id: str, status: str, result: dict[str, Any] | None) -> dict[str, Any]:
        entry = {"id": job_id, "status": status, "result": result}
        with _lock:
            _results[job_id] = entry
            _results.move_to_end(job_id)
            while len(_results) > max_stored_results:
                _results.popitem(last=False)
        return entry

    @router.post("/message-rescue/context/selection")
    async def capture_selection_route():
        try:
            await run_in_threadpool(
                context_session.capture_from_selection,
                capture_fn=selection_capture_fn,
                supported_fn=selection_supported_fn,
            )
        except ContextCaptureError as exc:
            raise HTTPException(status_code=422, detail=f"capture_{exc.reason}")
        return context_session.status() or _empty_context_status()

    @router.post("/message-rescue/context/manual")
    async def capture_manual_route(request: ManualContextRequest):
        try:
            await run_in_threadpool(context_session.capture_manual, request.text)
        except ContextCaptureError as exc:
            raise HTTPException(status_code=422, detail=f"capture_{exc.reason}")
        return context_session.status() or _empty_context_status()

    @router.get("/message-rescue/context")
    async def context_status_route():
        return context_session.status() or _empty_context_status()

    @router.delete("/message-rescue/context")
    async def clear_context_route():
        context_session.clear()
        return {"ok": True}

    @router.post("/message-rescue/generate")
    async def generate_route(request: GenerateRequest):
        context_text = None
        if request.use_context:
            try:
                context_text = await run_in_threadpool(context_session.consume)
            except ContextExhaustedError as exc:
                raise HTTPException(status_code=409, detail=f"context_{exc.reason}")

        persona_obj = None
        examples = None
        if request.persona:
            if persona_lookup is not None:
                persona_obj = persona_lookup(request.persona)
            if examples_lookup is not None:
                examples = examples_lookup(request.persona)
        signals_obj = request.signals.to_contract() if request.signals is not None else None

        job_id = id_factory()
        cancel_event = threading.Event()
        with _lock:
            _cancel_events[job_id] = cancel_event

        def guarded_call_fn(messages: list[dict[str, str]]) -> str:
            if cancel_event.is_set():
                raise _GenerationCancelled("cancelled before model call")
            return call_fn(messages)

        timed_out = False
        result = None
        try:
            result = await asyncio.wait_for(
                run_in_threadpool(
                    rescue_message,
                    request.transcript,
                    signals_obj,
                    context_text=context_text,
                    persona=persona_obj,
                    examples=examples,
                    call_fn=guarded_call_fn,
                ),
                timeout=generate_timeout_s,
            )
        except asyncio.TimeoutError:
            timed_out = True
        finally:
            with _lock:
                cancelled = cancel_event.is_set()
                _cancel_events.pop(job_id, None)

        if cancelled:
            return _store_result(job_id, "cancelled", None)
        if timed_out:
            return _store_result(job_id, "timeout", None)
        return _store_result(job_id, "done", to_dict(result))

    @router.get("/message-rescue/generate/{job_id}")
    async def get_result_route(job_id: str):
        with _lock:
            entry = _results.get(job_id)
        if entry is None:
            raise HTTPException(status_code=404, detail="unknown_or_expired_result")
        return entry

    @router.post("/message-rescue/generate/{job_id}/cancel")
    async def cancel_route(job_id: str):
        with _lock:
            event = _cancel_events.get(job_id)
        if event is None:
            raise HTTPException(status_code=404, detail="unknown_or_finished_generation")
        event.set()
        return {"id": job_id, "status": "cancel_requested"}

    def clear_state() -> dict[str, int]:
        """Privacy-wipe hook (I3.4): drop the held context and every stored
        generation result/cancellation handle. Best-effort only -- it does not
        interrupt an in-flight generation thread (that's /generate/{id}/cancel's
        job); it stops new callers from reading stale results and drops any
        rescued-message content already held in memory."""
        context_session.clear()
        with _lock:
            stored_results = len(_results)
            active_generations = len(_cancel_events)
            _results.clear()
            _cancel_events.clear()
        return {"stored_results_cleared": stored_results, "active_generations_cleared": active_generations}

    def state_counts() -> dict[str, Any]:
        """Diagnostic counts only -- never content (I3.4)."""
        with _lock:
            return {
                "context_active": bool(context_session.status()),
                "stored_results": len(_results),
                "active_generations": len(_cancel_events),
            }

    router.clear_state = clear_state
    router.state_counts = state_counts

    return router


# --- Default production wiring ------------------------------------------------
# A module-level ContextSession singleton (mirrors the module-level state every
# other extracted router already keeps, e.g. draft_queue/draft_lock in
# server.py) plus lazy, call-time resolution of the LLM engine and persona
# service — `import server` happens only inside the request path that needs
# it, exactly like backend/api/routes/personas.py's test_persona_route, so
# importing this module never pulls in server.py's full startup surface.

_context_session = ContextSession()


def _default_call_fn(messages: list[dict[str, str]]) -> str:
    import server
    from backend.services.rescue_llm_adapter import build_llm_call_fn

    engine = server.get_selected_llm_engine()
    adapter = build_llm_call_fn(engine, max_output_tokens=server.get_active_completion_tokens())
    return adapter(messages)


def _default_persona_lookup(name: str) -> Mapping[str, Any] | None:
    from backend.services import personas as persona_service

    return persona_service.get_persona(name)


router = create_message_rescue_router(
    context_session=_context_session,
    call_fn=_default_call_fn,
    persona_lookup=_default_persona_lookup,
)
