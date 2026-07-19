"""Persona CRUD/lint/preview routes (A1.2).

Thin FastAPI adapters over backend.services.personas — lifted out of
server.py with paths, status codes, and bodies unchanged. Registered on the
app via ``app.include_router`` at the end of server.py, same as the other
extracted route modules (routes_foundry.py etc.). ``import server`` is lazy
inside the one handler that needs the selected LLM engine, since server.py
imports this module only after every server-level name is defined.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel, Field

from backend.services import personas as persona_service
from backend.services.persona_learning import PersonaLearningStore

router = APIRouter()
logger = logging.getLogger(__name__)

# Bound on a single learned example's raw/out text (I3.3). Mirrors the
# paired-text size discipline backend.services.message_rescue already uses
# for its rewrite variants (MAX_VARIANT_CHARS=4000) -- same domain shape (a
# short utterance/message pair), same ceiling. Oversize requests fail
# pydantic validation (422) before ever reaching PersonaLearningStore, whose
# own hard cap (default 50, FIFO eviction) bounds example *count* per persona.
MAX_LEARNING_EXAMPLE_CHARS = 4000

# Maps PersonaLearningStore's structured {"ok": False, "error": ...} results
# to HTTP status. Anything not listed here (there is nothing else today)
# falls back to 400 -- the store never raises, so this is exhaustive over its
# documented error codes, not a catch-all for unexpected exceptions.
_LEARNING_ERROR_STATUS = {
    "invalid_persona_name": 400,
    "consent_required": 400,
    "empty_example": 400,
    "write_failed": 500,
}


def _learning_store() -> PersonaLearningStore:
    # Fresh instance per call: PersonaLearningStore re-reads from disk on
    # every method anyway (no in-memory cache), and resolving the path lazily
    # per-instance means each request picks up the current
    # utils.get_user_data_path() rather than one cached at import time --
    # matters for test isolation (tests point APPDATA at a tmp dir per test).
    return PersonaLearningStore()


class PersonaExampleRequest(BaseModel):
    raw: str = Field(..., min_length=1, max_length=MAX_LEARNING_EXAMPLE_CHARS)
    out: str = Field(..., min_length=1, max_length=MAX_LEARNING_EXAMPLE_CHARS)
    # No default of True: every learn request must explicitly opt in. There
    # is no persisted "this persona has consent" flag anywhere in the system
    # (F2.6) -- omitting this field means consent=False, which the store
    # rejects with consent_required rather than silently learning.
    consent: bool = False


class PersonaRequest(BaseModel):
    name: str
    prompt: str
    # Optional persona schema v2 fields (U7). Omitted fields are left untouched on
    # update, so legacy {name, prompt} clients keep working unchanged.
    temperature: Optional[float] = None
    model_hint: Optional[str] = None
    dictionary_scope: Optional[str] = None
    voice: Optional[dict] = None
    format: Optional[dict] = None
    few_shot: Optional[list] = None
    # Phase 7 builder fields:
    output_policy: Optional[str] = None
    safety_mode: Optional[str] = None
    max_completion_tokens: Optional[int] = None
    chunk_size: Optional[int] = None
    # Persona Foundry field:
    persona_card: Optional[dict] = None


@router.get("/personas")
async def list_personas_route():
    return persona_service.list_personas()


@router.get("/personas-builtins")
async def list_builtin_persona_names_route():
    """Names of the built-in personas, so the renderer doesn't have to keep
    its own hardcoded list in sync with llm_engine._DEFAULT_PERSONAS."""
    return {"builtins": persona_service.list_builtin_persona_names()}


@router.get("/personas/{name}")
async def get_persona_route(name: str):
    """Return the full schema v2 persona dict for the editor."""
    entry = persona_service.get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    return entry


@router.post("/personas")
async def save_persona_route(request: PersonaRequest):
    # Build a v2 payload from the provided fields; drop unspecified ones so an
    # update preserves prior rich values (upsert_persona merges partial dicts).
    payload = {"prompt": request.prompt}
    for key in (
        "temperature", "model_hint", "dictionary_scope", "voice", "format", "few_shot",
        "output_policy", "safety_mode", "max_completion_tokens", "chunk_size", "persona_card",
    ):
        value = getattr(request, key)
        if value is not None:
            payload[key] = value
    ok, msg = persona_service.save_persona(request.name, payload)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


class PersonaLintRequest(BaseModel):
    prompt: str = ""
    temperature: Optional[float] = None
    safety_mode: Optional[str] = None
    output_policy: Optional[str] = None
    chunk_size: Optional[int] = None


@router.post("/personas/lint")
async def lint_persona_route(request: PersonaLintRequest):
    """Non-blocking builder warnings for the persona currently being edited."""
    payload = {k: v for k, v in request.model_dump().items() if v is not None}
    return {"warnings": persona_service.lint_persona(payload)}


class PersonaTestRequest(BaseModel):
    prompt: str
    sample: str
    temperature: Optional[float] = None
    few_shot: Optional[list] = None
    format: Optional[dict] = None
    dictionary_scope: Optional[str] = None
    output_policy: Optional[str] = None
    safety_mode: Optional[str] = None
    max_completion_tokens: Optional[int] = None


@router.post("/personas/test")
async def test_persona_route(request: PersonaTestRequest):
    """Run one sample utterance through an unsaved persona for the test panel."""
    sample = str(request.sample or "").strip()
    if not sample:
        raise HTTPException(status_code=400, detail="A sample utterance is required.")
    persona = {k: v for k, v in request.model_dump().items() if k != "sample" and v is not None}
    import server
    engine = server.get_selected_llm_engine()
    try:
        result = await run_in_threadpool(
            persona_service.run_persona_preview,
            engine,
            persona,
            sample,
            max_output_tokens=server.get_active_completion_tokens(),
        )
    except Exception:
        logger.exception("Persona preview failed")
        raise HTTPException(
            status_code=500,
            detail="Persona test failed. Check the application logs for details.",
        )
    return {"result": result}


@router.delete("/personas/{name}")
async def delete_persona_route(name: str):
    ok, msg = persona_service.delete_persona(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"message": msg}


# --- Persona example learning (F2.6 store, I3.3 routes) ---------------------
#
# persona_name here is an opaque key into PersonaLearningStore's own store,
# independent of llm_engine's persona registry (see persona_learning.py's
# module docstring) -- by design there is no existence check against
# `/personas/{name}` above, so these routes work the same whether `name`
# refers to a saved persona, a built-in, or one that doesn't exist yet.


@router.get("/personas/{name}/examples")
async def list_persona_examples_route(name: str):
    """Every learned example for one persona. Explicitly requested by name,
    so (unlike a diagnostics/privacy view) this is allowed to include the
    example text, not just counts."""
    examples = await run_in_threadpool(_learning_store().list_examples, name)
    return {"persona": name, "examples": examples}


@router.post("/personas/{name}/examples")
async def add_persona_example_route(name: str, request: PersonaExampleRequest):
    """Learn one new few-shot example for a persona. Requires consent=True on
    this exact request -- there is no persisted consent flag to rely on."""
    result = await run_in_threadpool(
        _learning_store().add_example, name, request.raw, request.out,
        consent=request.consent,
    )
    if not result["ok"]:
        status = _LEARNING_ERROR_STATUS.get(result["error"], 400)
        raise HTTPException(status_code=status, detail=result.get("message", result["error"]))
    return result


@router.delete("/personas/{name}/examples/{example_id}")
async def delete_persona_example_route(name: str, example_id: str):
    """Delete a single learned example by id."""
    result = await run_in_threadpool(_learning_store().delete_example, name, example_id)
    if not result["ok"]:
        status = _LEARNING_ERROR_STATUS.get(result["error"], 500)
        raise HTTPException(status_code=status, detail=result.get("message", result["error"]))
    if not result["deleted"]:
        raise HTTPException(status_code=404, detail="Learned example not found.")
    return result


@router.delete("/personas/{name}/examples")
async def clear_persona_examples_route(name: str):
    """Privacy clear: delete every learned example for one persona. The
    persona key is dropped, not blacklisted -- a later learn (with fresh
    consent) recreates it."""
    result = await run_in_threadpool(_learning_store().clear_persona, name)
    if not result["ok"]:
        status = _LEARNING_ERROR_STATUS.get(result["error"], 500)
        raise HTTPException(status_code=status, detail=result.get("message", result["error"]))
    return result
