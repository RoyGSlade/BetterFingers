"""Persona Foundry routes: guided interview -> compile -> stress-test (M6).

A self-contained vertical slice lifted out of server.py: the in-memory session
store, its helpers, the request models, and the four endpoints. Registered on
the app via ``app.include_router`` at the end of server.py. Shared runtime bits
(the selected LLM engine) are reached through ``server`` at request time, so the
``import server`` here is not a load-order hazard.
"""

import time
import typing
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel

# NOTE: `server` is imported lazily inside the handlers, not at module top —
# server.py imports this module at the end of its own load, so a top-level
# `import server` here would be a partially-initialized circular import.

router = APIRouter()

# In-memory only (like draft_queue) — losing an in-progress session on restart is
# acceptable. Capped at 20 concurrent sessions; oldest evicted. server.py
# re-binds server._foundry_sessions to this same dict so existing callers/tests
# keep working.
_foundry_sessions = {}
_FOUNDRY_SESSION_CAP = 20


def _foundry_evict_if_full():
    if len(_foundry_sessions) < _FOUNDRY_SESSION_CAP:
        return
    oldest_id = min(_foundry_sessions, key=lambda sid: _foundry_sessions[sid].get("created", 0))
    _foundry_sessions.pop(oldest_id, None)


def _foundry_get_session(session_id):
    session = _foundry_sessions.get(str(session_id or ""))
    if session is None:
        raise HTTPException(status_code=404, detail=f"Foundry session '{session_id}' not found.")
    return session


class FoundryAnswerRequest(BaseModel):
    session_id: str
    answer: typing.Any = None


class FoundrySessionRequest(BaseModel):
    session_id: str


class FoundryStressTestRequest(BaseModel):
    session_id: Optional[str] = None
    persona: Optional[dict] = None


@router.post("/personas/interview/start")
async def start_foundry_interview():
    from llm_engine import foundry_new_session, foundry_next_prompt
    _foundry_evict_if_full()
    session = foundry_new_session()
    session["created"] = time.monotonic()
    session_id = str(uuid.uuid4())
    _foundry_sessions[session_id] = session
    return {"session_id": session_id, "question": foundry_next_prompt(session), "done": False}


@router.post("/personas/interview/answer")
async def answer_foundry_interview(request: FoundryAnswerRequest):
    from llm_engine import foundry_next_prompt, foundry_submit_answer
    session = _foundry_get_session(request.session_id)
    result = foundry_submit_answer(session, request.answer)
    return {
        "question": foundry_next_prompt(session),
        "pushback": result.get("pushback"),
        "done": bool(result.get("done")),
    }


@router.post("/personas/compile")
async def compile_foundry_persona_route(request: FoundrySessionRequest):
    import server
    session = _foundry_get_session(request.session_id)
    if not session.get("done"):
        raise HTTPException(status_code=400, detail="Interview is not complete yet.")
    engine = server.get_selected_llm_engine()
    try:
        # LLM work must not run on the event loop: it starves /health and
        # invites Electron's restart watchdog (review finding #2).
        result = await run_in_threadpool(engine.compile_foundry_persona, session)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Persona compile failed: {exc}")
    return result


@router.post("/personas/test-suite/run")
async def run_foundry_stress_suite_route(request: FoundryStressTestRequest):
    import server

    from llm_engine import normalize_persona
    engine = server.get_selected_llm_engine()
    if request.persona is not None:
        persona = normalize_persona(request.persona)
    elif request.session_id is not None:
        session = _foundry_get_session(request.session_id)
        if not session.get("done"):
            raise HTTPException(status_code=400, detail="Interview is not complete yet.")
        try:
            compiled = await run_in_threadpool(engine.compile_foundry_persona, session)
            persona = compiled["persona"]
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"Persona compile failed: {exc}")
    else:
        raise HTTPException(status_code=400, detail="Provide either session_id or persona.")
    try:
        # Seven LLM cases in one request — the single worst event-loop hog.
        cases = await run_in_threadpool(engine.run_foundry_stress_suite, persona)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Stress test failed: {exc}")
    return {"cases": cases}
