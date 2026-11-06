"""Privacy routes lifted out of server.py (R9): the privacy report, the export
bundle, the wipe and its mode preview, the factory reset and its verification,
and the learned-persona-examples clear/verify pair (8 routes).

Only the THIN ROUTE HANDLERS moved. Everything that decides what gets deleted,
and in what order, stays in server.py and is called as ``s.<helper>``:

* ``_perform_privacy_wipe`` (the quiescence protocol: wake listener, recorder,
  pipeline gate, output drain, TTS/clone drain, in-memory queues, registry
  sweep, postconditions) and ``_perform_factory_reset``;
* the guards: ``privacy_wipe_in_progress``, ``output_coordinator``,
  ``_reject_if_wiping``, ``_drain_*``;
* ``get_privacy_report``, ``_build_privacy_export``,
  ``_persona_learning_disclosure``;
* ``_WIPE_ERROR_STATUS`` / ``_wipe_status_code`` (the honest HTTP-status map, also
  asserted directly by tests) and ``FACTORY_RESET_CONFIRMATION`` (also read by
  tests and by the renderer through ``/privacy/modes``).

No ``global`` statement exists anywhere in this area (not in the 8 handlers and
not in the helpers that stay), and nothing here assigns a server name:
``privacy_wipe_in_progress`` is a ``threading.Event`` that only server helpers
``set()`` / ``clear()``. Each handler passes exactly the arguments it passed
before (``_perform_privacy_wipe(request.wipe_voices, request.mode)`` positionally,
``_perform_factory_reset(request.delete_downloaded_models)``), and each destructive
route still runs its helper in the threadpool and maps the result to the same
HTTP status through the same server-side map.

The two request models are used only by these routes, so they live here.
``PrivacyWipeRequest``'s default mode reads ``data_registry`` (a pure constants
module), imported at the top of this file for the class body; the handlers
themselves still read it as ``s.data_registry`` at call time.

Same strangler shape as the earlier routers: ``server`` is imported lazily inside
each handler (``import server as s``) because server.py imports this module near
the end of its own load, and every server name is read as ``s.<name>`` at call
time so ``patch.object(server, ...)`` in tests still lands. Registered via
``app.include_router`` at the end of server.py.
"""
from typing import Optional

from fastapi import APIRouter
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from starlette.responses import JSONResponse

from backend.api.models import ApprovalTicketModel
from backend.privacy import data_registry
from backend.services import approvals, persona_learning

# Round 4, item 3 (Codex re-check 3, finding 3). Every wipe below deletes learned persona
# examples (and the larger modes the personas and their few-shot lists too), so each needs a
# ticket minted by main after a native dialog that showed its scope. A renderer boolean, or the
# factory-reset phrase on its own, is not a tap: a compromised renderer supplies either itself.


def _refused(exc: approvals.ApprovalError) -> JSONResponse:
    return JSONResponse(status_code=approvals.http_status_for(exc.code), content={
        "ok": False, "error": exc.code, "message": exc.message})


def _ticket(model) -> Optional[dict]:
    return model.model_dump() if model is not None else None


def _mode_scope(s, mode: str) -> list:
    """The category ids a mode deletes, in registry order: what the dialog listed."""
    return [category.id for category in s.data_categories.get_registry().in_mode(mode)]


def _verify_wipe(s, ticket, mode: str, *, wipe_voices: bool = False, delete_models: bool = False):
    approvals.verify(ticket, purpose=approvals.PURPOSE_PRIVACY_WIPE, subject=mode,
                     bind=approvals.privacy_wipe_bind(mode, _mode_scope(s, mode),
                                                      wipe_voices=wipe_voices, delete_models=delete_models))


class LearningClearAllRequest(BaseModel):
    approval: Optional[ApprovalTicketModel] = None

router = APIRouter()


@router.get("/privacy/export")
async def privacy_export():
    """Export the user's own data — one bundle, generated from the registry."""
    import server as s

    return await run_in_threadpool(s._build_privacy_export)


@router.get("/privacy/persona-learning/preview")
async def privacy_persona_learning_preview():
    """Every persona's learned examples, for the native dialog the global clear needs (round 4):
    main shows the scope from this and binds its ticket to the digest of exactly this collection."""
    rows = await run_in_threadpool(persona_learning.snapshot)
    return {"ok": True, "personas": [
        {"name": name, "examples": [{"raw": raw, "out": out} for raw, out in items]} for name, items in rows]}


@router.delete("/privacy/persona-learning")
async def privacy_clear_persona_learning(request: Optional[LearningClearAllRequest] = None):
    """Delete every learned example for every persona, then verify.

    Goes through the registry's category wipe (which goes through
    PersonaLearningStore.clear_all()) rather than unlinking the file, so the
    store's atomic-write and dedupe invariants hold and the result is checked
    by re-reading rather than trusted. Keys are dropped, not blacklisted — a
    later approved example recreates them.
    """
    import server as s

    category = s.data_categories.get_registry().get("persona_learning")
    ticket = _ticket(request.approval) if request else None

    def _clear():
        # Verified and wiped under the store lock, against the collection stored right now: an
        # example learned after the dialog voids the ticket instead of being deleted unseen.
        with persona_learning.store_lock():
            collection = approvals.learned_collection_digest(persona_learning.snapshot())
            approvals.verify(ticket, purpose=approvals.PURPOSE_LEARNED_CLEAR_ALL, subject="all",
                             bind=approvals.learned_clear_all_bind(collection))
            wipe = category.wipe()
            verification = category.verify()
        return {
            "ok": verification.ok,
            "wiped": wipe.ok,
            "message": (wipe.message if verification.ok else
                        "Examples remain after clearing; nothing is being claimed "
                        "that did not happen."),
            "remaining": verification.remaining,
            "detail": verification.detail,
        }

    try:
        result = await run_in_threadpool(_clear)
    except approvals.ApprovalError as exc:
        return _refused(exc)
    return JSONResponse(status_code=200 if result["ok"] else 500, content=result)


@router.get("/privacy/persona-learning/verify")
async def privacy_persona_learning_verify():
    """Prove the learned-examples store is empty by re-reading it.

    "Clear all" returning ok is the store's claim about its own write; this is
    the independent check the privacy screen shows next to it.
    """
    import server as s

    category = s.data_categories.get_registry().get("persona_learning")
    result = category.verify()
    return {"ok": result.ok, "remaining": result.remaining, "detail": result.detail}


@router.get("/privacy")
async def privacy_report():
    import server as s

    return s.get_privacy_report()


class PrivacyWipeRequest(BaseModel):
    wipe_voices: bool = False
    # Defaults to the lightest mode, which is exactly what the shipped button
    # has always done. Widening the default would silently delete personas,
    # dictionaries and macros for anyone whose client predates this field.
    mode: str = data_registry.WIPE_MODE_CONVERSATIONS
    approval: Optional[ApprovalTicketModel] = None


class FactoryResetRequest(BaseModel):
    """A factory reset is unrecoverable, so the request has to carry proof the
    user meant it. ``confirm`` must be the exact phrase — a boolean flag is
    one stray ``true`` in a client away from erasing an install."""

    confirm: str = ""
    delete_downloaded_models: bool = False
    approval: Optional[ApprovalTicketModel] = None


@router.post("/privacy/wipe")
async def privacy_wipe(request: PrivacyWipeRequest = PrivacyWipeRequest()):
    """Delete app-generated conversational data: drafts, the draft-history
    file, the searchable history database (C8), and persisted raw-audio
    recordings (C6), plus in-memory queues. Also drains any active TTS
    playback and voice-clone conversion and clears the synthesized-audio
    cache unconditionally (it holds spoken user text regardless of the
    wipe_voices toggle). Models and profiles are intentionally NOT touched;
    cloned voice samples are removed only when explicitly requested. Note:
    without at-rest encryption this is logical deletion — nothing readable
    remains through the app or its files, but SSD-level forensic erasure is
    not promised.

    Returns an honest HTTP status (see _wipe_status_code): a wipe that did not
    fully succeed never reports 200."""
    import server as s

    if request.mode in data_registry.WIPE_MODES:
        try:
            _verify_wipe(s, _ticket(request.approval), request.mode, wipe_voices=request.wipe_voices)
        except approvals.ApprovalError as exc:
            return _refused(exc)
    result = await run_in_threadpool(s._perform_privacy_wipe, request.wipe_voices, request.mode)
    return JSONResponse(status_code=s._wipe_status_code(result), content=result)


@router.get("/privacy/modes")
async def privacy_wipe_modes():
    """What each mode would delete, right now, with real sizes.

    The confirmation dialog reads this instead of carrying its own copy of the
    list. That is the whole point: the sentence the user agrees to and the
    sweep that runs are generated from one inventory.
    """
    import server as s

    registry = s.data_categories.get_registry()
    return {
        "ok": True,
        "modes": {mode: s.data_lifecycle.preview_mode(registry, mode)
                  for mode in sorted(s.data_registry.WIPE_MODES)},
        "factory_reset_confirmation": s.FACTORY_RESET_CONFIRMATION,
    }


@router.post("/privacy/factory-reset")
async def privacy_factory_reset(request: FactoryResetRequest):
    """Erase every declared store — Python-owned and Electron-owned — and then
    prove it by re-reading the disk.

    ``data_registry`` has declared WIPE_MODE_FACTORY_RESET since phase 2.1 and
    nothing performed it; this is that executor. Requires the exact
    confirmation phrase (see FactoryResetRequest) because it is unrecoverable:
    it removes the onboarding consent record, the overlay state, application
    profiles, workflows, personas, dictionaries, macros and settings, not only
    conversation data.
    """
    import server as s

    if request.confirm != s.FACTORY_RESET_CONFIRMATION:
        return JSONResponse(status_code=400, content={
            "ok": False, "error": "confirmation_required",
            "message": (f"A factory reset requires confirm={s.FACTORY_RESET_CONFIRMATION!r}. "
                        "Nothing was deleted."),
        })
    try:
        _verify_wipe(s, _ticket(request.approval), data_registry.WIPE_MODE_FACTORY_RESET,
                     delete_models=request.delete_downloaded_models)
    except approvals.ApprovalError as exc:
        return _refused(exc)
    result = await run_in_threadpool(s._perform_factory_reset,
                                     request.delete_downloaded_models)
    status = 200 if result.get("ok") else s._WIPE_ERROR_STATUS.get(result.get("error"), 500)
    return JSONResponse(status_code=status, content=result)


@router.get("/privacy/factory-reset/verify")
async def privacy_factory_reset_verify():
    """Re-read the disk and report whether a factory reset actually landed.

    Deliberately a separate GET with no deletion path: the Settings surface
    offers "check again" after a failed reset, and a user re-checking must not
    be able to trigger a second erase.
    """
    import server as s

    registry = s.data_categories.get_registry()
    return await run_in_threadpool(s.data_lifecycle.verify_factory_reset, registry)
