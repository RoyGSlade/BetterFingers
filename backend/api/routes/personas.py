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
from backend.services import persona_drafts
from backend.services.persona_schema import (
    get_field_guidance,
    migrate_legacy_persona,
    normalize_structured_persona,
    validate_structured_persona,
)

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
    prompt: str = ""
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
    # Stage 10: five user-set register dials. Optional like every other v2
    # field, so a client that has never heard of traits keeps working.
    traits: Optional[dict] = None
    structured: Optional[dict] = None
    migration: Optional[dict] = None
    revision: Optional[int] = None
    confirmed_revision: Optional[int] = None
    writing_preset_id: Optional[str] = None


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
        "traits",
        "structured", "migration", "revision", "confirmed_revision", "writing_preset_id",
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
    # Lint needs traits to warn about the detail/output_policy corners.
    traits: Optional[dict] = None


@router.post("/personas/lint")
async def lint_persona_route(request: PersonaLintRequest):
    """Non-blocking builder warnings for the persona currently being edited."""
    payload = {k: v for k, v in request.model_dump().items() if v is not None}
    return {"warnings": persona_service.lint_persona(payload)}


class PersonaTestRequest(BaseModel):
    prompt: str = ""
    sample: str
    temperature: Optional[float] = None
    few_shot: Optional[list] = None
    format: Optional[dict] = None
    dictionary_scope: Optional[str] = None
    output_policy: Optional[str] = None
    safety_mode: Optional[str] = None
    max_completion_tokens: Optional[int] = None
    structured: Optional[dict] = None


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


class PersonaDraftStateRequest(BaseModel):
    structured: dict
    base_confirmed_version: int = 1


class PersonaConfirmRequest(BaseModel):
    structured: dict


class PersonaRenameRequest(BaseModel):
    new_name: str


@router.get("/personas/{name}/editor")
async def get_persona_editor_route(name: str):
    """Return confirmed structured data plus its separately persisted draft.

    Legacy prompts are decomposed conservatively for review, but the persona
    registry is not changed until /confirm is called.
    """
    entry = persona_service.get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    structured, migration = migrate_legacy_persona(name, entry)
    persona_id = structured["metadata"]["id"]
    return {
        "name": name,
        "confirmed": structured,
        "confirmed_version": int(entry.get("confirmed_revision", 1) or 1),
        "draft": persona_drafts.get_draft(persona_id),
        "migration": migration,
        "legacy_prompt": str(entry.get("prompt", "") or ""),
    }


@router.put("/personas/{name}/draft")
async def save_persona_draft_route(name: str, request: PersonaDraftStateRequest):
    entry = persona_service.get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    structured = normalize_structured_persona(request.structured, display_name=name)
    persona_id = structured["metadata"]["id"]
    draft = await run_in_threadpool(
        persona_drafts.save_draft,
        persona_id,
        structured,
        base_version=request.base_confirmed_version,
    )
    return {"ok": True, "draft": draft}


@router.delete("/personas/{name}/draft")
async def discard_persona_draft_route(name: str):
    entry = persona_service.get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    structured, _migration = migrate_legacy_persona(name, entry)
    deleted = await run_in_threadpool(persona_drafts.delete_draft, structured["metadata"]["id"])
    return {"ok": True, "discarded": deleted}


@router.post("/personas/{name}/confirm")
async def confirm_persona_draft_route(name: str, request: PersonaConfirmRequest):
    entry = persona_service.get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    structured = normalize_structured_persona(request.structured, display_name=name)
    ok_schema, errors = validate_structured_persona(structured)
    if not ok_schema:
        raise HTTPException(status_code=400, detail={"message": "Persona needs review.", "errors": errors})
    next_version = int(entry.get("confirmed_revision", 1) or 1) + 1
    structured["metadata"]["version"] = next_version
    migration = dict(entry.get("migration") or {})
    if not migration:
        _preview, migration = migrate_legacy_persona(name, entry)
    migration["confirmed"] = True
    payload = {
        "structured": structured,
        "migration": migration,
        "revision": next_version,
        "confirmed_revision": next_version,
    }
    ok, msg = persona_service.save_persona(name, payload)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    await run_in_threadpool(persona_drafts.delete_draft, structured["metadata"]["id"])
    return {"ok": True, "message": msg, "structured": structured, "confirmed_version": next_version}


@router.get("/personas/field-guidance/{field_path:path}")
async def persona_field_guidance_route(field_path: str):
    guidance = get_field_guidance(field_path)
    if guidance is None:
        raise HTTPException(status_code=404, detail=f"No guidance is defined for '{field_path}'.")
    return {"field_id": field_path, **guidance}


@router.post("/personas/{name}/rename")
async def rename_persona_route(name: str, request: PersonaRenameRequest):
    new_name = str(request.new_name or "").strip()
    if not new_name:
        raise HTTPException(status_code=400, detail="A new persona name is required.")
    if persona_service.get_persona(new_name) is not None:
        raise HTTPException(status_code=409, detail=f"Persona '{new_name}' already exists.")
    entry = persona_service.get_persona(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Persona '{name}' not found.")
    if name in persona_service.list_builtin_persona_names():
        raise HTTPException(status_code=400, detail="Built-in personas cannot be renamed.")
    entry = dict(entry)
    if isinstance(entry.get("structured"), dict):
        entry["structured"] = normalize_structured_persona(entry["structured"], display_name=new_name)
        entry["structured"]["metadata"]["display_name"] = new_name
    ok, msg = persona_service.save_persona(new_name, entry)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    ok, delete_msg = persona_service.delete_persona(name)
    if not ok:
        persona_service.delete_persona(new_name)
        raise HTTPException(status_code=400, detail=delete_msg)
    import server
    server.reconcile_persona_profile_references(name, replacement=new_name)
    return {"ok": True, "message": f"Renamed persona '{name}' to '{new_name}'.", "name": new_name}


class PersonaRefineRequest(BaseModel):
    prompt: str
    tone: Optional[str] = None
    rules: Optional[list] = None


@router.post("/personas/refine")
async def refine_persona_route(request: PersonaRefineRequest):
    """Wizard co-pilot: the downloaded local model rewrites the user's rough
    persona description into a clear prompt and reports what it understood and
    where it had to guess, so a dictated description doesn't get saved while
    secretly ambiguous."""
    draft = str(request.prompt or "").strip()
    if not draft:
        raise HTTPException(status_code=400, detail="A draft persona description is required.")
    import server
    engine = server.get_selected_llm_engine()
    try:
        result = await run_in_threadpool(
            engine.refine_persona_prompt,
            draft,
            request.tone,
            request.rules,
        )
    except Exception:
        logger.exception("Persona refine failed")
        raise HTTPException(
            status_code=500,
            detail="Persona refine failed. Check the application logs for details.",
        )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("message", "Persona helper unavailable."))
    return result


class PersonaDraftRequest(BaseModel):
    description: str


@router.post("/personas/draft")
async def draft_persona_route(request: PersonaDraftRequest):
    """Wizard from-scratch mode: the local model designs a complete persona
    (name, prompt, settings, few-shot examples) from a plain-language
    description. Returned for review in the wizard, never saved directly."""
    description = str(request.description or "").strip()
    if not description:
        raise HTTPException(status_code=400, detail="A persona description is required.")
    import server
    engine = server.get_selected_llm_engine()
    try:
        result = await run_in_threadpool(engine.draft_persona_from_description, description)
    except Exception:
        logger.exception("Persona draft failed")
        raise HTTPException(
            status_code=500,
            detail="Persona draft failed. Check the application logs for details.",
        )
    if not result.get("ok"):
        raise HTTPException(status_code=503, detail=result.get("message", "Persona helper unavailable."))
    return result


@router.delete("/personas/{name}")
async def delete_persona_route(name: str):
    ok, msg = persona_service.delete_persona(name)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    import server
    changed = server.reconcile_persona_profile_references(name, replacement="True Janitor")
    return {"message": msg, "active_fallback": bool(changed), "fallback_persona": "True Janitor"}


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
