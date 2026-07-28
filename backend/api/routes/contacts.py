"""Contact CRUD + the model-run interview (Stage 11b).

Thin FastAPI adapters over ``backend.services.contacts`` and
``backend.services.contact_interview``. Registered via ``app.include_router``
at the end of server.py like every other extracted route module.

Two things here are decisions rather than plumbing.

**Nothing persists until the user approves.** ``/contacts/interview/*`` and
``/contacts/compile`` touch no store at all — the interview is a conversation,
not a recording. Only ``POST /contacts`` writes, and it takes the reviewed,
edited fields the user actually approved (design doc §4).

**Compile does not boot a model.** The Persona Foundry calls ``ensure_ready()``
and waits, which is right for a feature whose whole name is "Build with AI".
Spinning up a multi-gigabyte model to write two sentences about someone's
brother is not: rule 2's friction budget says a feature heavy enough to go
unused protects nobody. So compile uses the model *if one is already up* and
otherwise assembles the user's own answers, reporting which happened. A caller
that genuinely wants to wait passes ``wait_for_model``.
"""

import logging
import time
import uuid

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from typing import Any, Optional

from backend.services import contact_interview
from backend.services.contacts import MAX_NAME_LEN, MAX_TEXT_LEN, ContactStore

router = APIRouter()
logger = logging.getLogger(__name__)

# In-memory only, like the Foundry's: losing an in-progress interview on restart
# is acceptable because nothing in it was ever promised to survive.
_interview_sessions: dict = {}
_SESSION_CAP = 20

# Maps ContactStore's structured {"ok": False, "error": ...} results to HTTP
# status. Exhaustive over the store's documented error codes -- it never raises,
# so anything unlisted is a code change that should surface as a 400 rather than
# a 500 pretending to be a server fault.
_STORE_ERROR_STATUS = {
    "name_required": 400,
    "invalid_id": 400,
    "invalid_payload": 400,
    "not_found": 404,
    "cap_reached": 409,
    "write_failed": 500,
}


def _store() -> ContactStore:
    # Fresh per call, like _learning_store(): the store re-reads from disk on
    # every method anyway, and resolving the path per-instance means each
    # request picks up the current utils.get_user_data_path() rather than one
    # cached at import time -- which is what keeps tests isolated.
    return ContactStore()


def _fail(result: dict):
    status = _STORE_ERROR_STATUS.get(result.get("error"), 400)
    raise HTTPException(status_code=status, detail=result.get("message") or result.get("error"))


def _evict_if_full():
    if len(_interview_sessions) < _SESSION_CAP:
        return
    oldest = min(_interview_sessions, key=lambda sid: _interview_sessions[sid].get("created", 0))
    _interview_sessions.pop(oldest, None)


def _get_session(session_id):
    session = _interview_sessions.get(str(session_id or ""))
    if session is None:
        raise HTTPException(status_code=404, detail=f"Contact interview '{session_id}' not found.")
    return session


# --- Request models ----------------------------------------------------------


class ContactRequest(BaseModel):
    """Create/update payload.

    Deliberately no email/phone/handle field, and extra keys are not rejected
    here -- ContactStore.sanitize_contact drops them and reports what it
    dropped, so a client that tries gets told rather than 422'd into silence
    about which field was the problem.
    """
    name: Optional[str] = Field(default=None, max_length=MAX_NAME_LEN)
    relationship: Optional[str] = Field(default=None, max_length=MAX_NAME_LEN)
    notes: Optional[str] = Field(default=None, max_length=MAX_TEXT_LEN)
    tone_guidance: Optional[str] = Field(default=None, max_length=MAX_TEXT_LEN)
    preferred_persona: Optional[str] = Field(default=None, max_length=MAX_NAME_LEN)

    model_config = {"extra": "allow"}


class InterviewAnswerRequest(BaseModel):
    session_id: str
    answer: Any = None


class CompileRequest(BaseModel):
    session_id: str
    # Off by default: see the module docstring. True boots the model and waits.
    wait_for_model: bool = False


# --- Collection routes -------------------------------------------------------
#
# ROUTE ORDER MATTERS. FastAPI matches in registration order, so every literal
# path under /contacts (interview/start, interview/answer, compile) has to be
# registered BEFORE /contacts/{contact_id} -- otherwise the parameterised route
# swallows them and POST /contacts/compile arrives as a request to update a
# contact whose id is the string "compile". That is exactly what happened when
# the POST alias for update was added, and it presented as a 404 on compile.


# --- CRUD --------------------------------------------------------------------


@router.get("/contacts")
async def list_contacts_route():
    return {"ok": True, "contacts": _store().list_contacts()}


@router.post("/contacts")
async def create_contact_route(request: ContactRequest):
    """Create a contact. A name alone is enough — the interview is an offer to
    make one better, never a gate on having one."""
    result = _store().create(request.model_dump(exclude_none=True))
    if not result.get("ok"):
        _fail(result)
    return result


# --- Interview ---------------------------------------------------------------


@router.post("/contacts/interview/start")
async def start_contact_interview():
    _evict_if_full()
    session = contact_interview.new_session()
    session["created"] = time.monotonic()
    session_id = str(uuid.uuid4())
    _interview_sessions[session_id] = session
    return {
        "session_id": session_id,
        "question": contact_interview.next_prompt(session),
        "done": False,
    }


@router.post("/contacts/interview/answer")
async def answer_contact_interview(request: InterviewAnswerRequest):
    session = _get_session(request.session_id)
    result = contact_interview.submit_answer(session, request.answer)
    return {
        "question": contact_interview.next_prompt(session),
        "pushback": result.get("pushback"),
        "done": bool(result.get("done")),
    }


def _resolve_generator(wait_for_model: bool):
    """A ``(prompt) -> str`` callable, or None if no model should be used.

    Returns None rather than raising when nothing is loaded: an unavailable
    model is a reason to compile from the user's own answers, not a reason the
    request fails.
    """
    import server

    try:
        engine = server.get_selected_llm_engine()
    except Exception as exc:  # noqa: BLE001 - engine resolution is best-effort
        logger.info(f"Contact compile: no LLM engine available ({exc})")
        return None

    if wait_for_model:
        ready = bool(engine.ensure_ready())
    else:
        # Already up, or not at all. ensure_ready() would spawn llama-server and
        # load the model -- a multi-second hang to write two sentences.
        ready = bool(getattr(engine, "_ready", False))
        if not ready:
            from llm_engine import is_server_running
            ready = is_server_running() and bool(engine.ensure_ready())

    if not ready:
        return None

    return lambda prompt: engine.process_custom_prompt(
        prompt, contact_interview.COMPILE_INSTRUCTIONS, max_output_tokens=200,
    )


@router.post("/contacts/compile")
async def compile_contact_route(request: CompileRequest):
    """Turn a finished interview into a contact for review. Saves nothing.

    Always 200: a compile that could not reach a model still returns the
    contact assembled from the user's own answers, with a warning saying so.
    Failing the request instead would throw away an interview they just sat
    through.
    """
    session = _get_session(request.session_id)
    if not session.get("done"):
        raise HTTPException(status_code=400, detail="The interview is not finished yet.")

    generate = await run_in_threadpool(_resolve_generator, request.wait_for_model)
    # Generation is a blocking model call: on the event loop it would starve
    # /health and invite Electron's restart watchdog.
    result = await run_in_threadpool(contact_interview.compile_contact, session, generate)
    return {"ok": True, **result}


# --- Item routes (parameterised — registered last, see the note above) --------


@router.get("/contacts/{contact_id}")
async def get_contact_route(contact_id: str):
    contact = _store().get(contact_id)
    if contact is None:
        raise HTTPException(status_code=404, detail=f"Contact '{contact_id}' not found.")
    return {"ok": True, "contact": contact}


@router.patch("/contacts/{contact_id}")
@router.post("/contacts/{contact_id}")
async def update_contact_route(contact_id: str, request: ContactRequest):
    """Patch a contact. Only fields actually sent are touched, so the
    correction flow (design §9.3) can send one at a time without blanking the
    rest by omission.

    Registered on POST as well as PATCH. The Electron proxy's allowlist is keyed
    by method and only carries GET/POST/DELETE, so a PATCH-only route would be
    unreachable from the renderer; `POST /settings/profiles/:name` is the same
    update-by-POST shape this repo already uses. PATCH stays for anyone talking
    to the API directly.
    """
    payload = request.model_dump(exclude_unset=True)
    result = _store().update(contact_id, payload)
    if not result.get("ok"):
        _fail(result)
    return result


@router.delete("/contacts/{contact_id}")
async def delete_contact_route(contact_id: str):
    result = _store().delete(contact_id)
    if not result.get("ok"):
        _fail(result)
    return result


