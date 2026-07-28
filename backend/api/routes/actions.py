"""Restricted workflow routes (Wave 9, D-0011).

Thin FastAPI adapters over ``backend.domain.actions``,
``backend.services.action_validator`` and ``backend.services.workflow_store``.
Registered via ``app.include_router`` at the end of server.py like every other
extracted route module — that one line is integration-owned and is written out
in ``docs/release/WAVE9_INTEGRATION_DIFFS.md``; until it lands these routes
exist but are not mounted.

THE FLOW THESE ROUTES IMPLEMENT, in order, because the order is the safety
property:

    describe -> compile -> validate -> exact preview -> approve -> save
    (disabled or enabled) -> run, and only then

``POST /workflows/compile`` never writes anything: it is what the builder calls
while the user is still describing, so a refusal costs nothing and explains
itself. ``POST /workflows/save`` always stores ``approved=False``.
``POST /workflows/approve`` records the exact preview lines the user read.
``POST /workflows/run`` re-validates, re-previews and asks the store's
``can_run`` gate — it does not trust the approval flag alone, because the
registry can change under a workflow that nobody edited.

WHY THE REGISTRY ARRIVES IN THE REQUEST. The confirmed application registry is
owned by the Electron main process (``app/src/main/applicationRegistry.js``),
which is the side that can see the desktop, and the architecture boundary in the
release plan keeps OS-facing discovery there. So the caller passes the confirmed
registry with each validation call rather than Python reading a file the main
process owns. Passing an *unconfirmed* entry does not help a caller:
``index_registry`` keeps only ``confirmed`` entries.

EXECUTION IS NOT HERE. Nothing in this module launches anything. ``/run``
returns the validated plan and the run gate's verdict; the main process
performs the steps with argument arrays and posts the per-step status codes back
to ``/workflows/run/record``. Python never gains a code path that starts a
process on a user's machine.
"""

import logging
from typing import List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.domain.actions import (
    ALLOWED_ACTIONS,
    PROHIBITED_ACTIONS,
    SCHEMA_VERSION,
    compile_workflow,
)
from backend.services.action_validator import (
    RUN_STATUS_CODES,
    STEP_STATUS_CODES,
    preview_lines,
    summarize_run,
    validate_workflow,
)
from backend.services.workflow_store import WorkflowStore

router = APIRouter()
logger = logging.getLogger(__name__)

_ERROR_STATUS = {
    "invalid_id": 400,
    "invalid_summary": 400,
    "empty_preview": 400,
    "refused": 400,
    "not_found": 404,
    "cap_reached": 409,
    "disabled": 409,
    "not_approved": 409,
    "preview_changed": 409,
    "write_failed": 500,
}


def _store() -> WorkflowStore:
    # Fresh per call, like the app-context route's: the store re-reads from disk
    # on every method, so resolving the path per-instance means each request
    # picks up the current data root rather than one cached at import time.
    return WorkflowStore()


def _fail(result: dict):
    status = _ERROR_STATUS.get(result.get("error"), 400)
    detail = result.get("message") or result.get("reason") or result.get("error")
    raise HTTPException(status_code=status, detail=detail)


class WorkflowBody(BaseModel):
    id: Optional[str] = None
    name: Optional[str] = None
    trigger_phrases: Optional[List[str]] = None
    steps: Optional[List[dict]] = None


class ValidationContext(BaseModel):
    """Everything the validator needs about *this machine*, supplied by the
    caller. Absent lists mean "nothing is known", and the validator fails closed
    on them rather than assuming a target exists."""

    registry: List[dict] = Field(default_factory=list)
    profile_ids: List[str] = Field(default_factory=list)
    personas: List[str] = Field(default_factory=list)
    writing_presets: List[str] = Field(default_factory=list)
    folder_roots: Optional[List[str]] = None


class CompileRequest(BaseModel):
    workflow: WorkflowBody
    context: ValidationContext = Field(default_factory=ValidationContext)


class SaveRequest(BaseModel):
    workflow: WorkflowBody
    enabled: bool = False


class ApproveRequest(BaseModel):
    workflow_id: str
    preview: List[str] = Field(default_factory=list)


class EnableRequest(BaseModel):
    workflow_id: str
    enabled: bool


class RunRequest(BaseModel):
    workflow_id: str
    context: ValidationContext = Field(default_factory=ValidationContext)


class RecordRunRequest(BaseModel):
    workflow_id: str
    results: List[dict] = Field(default_factory=list)


def _validate(workflow: dict, context: ValidationContext):
    return validate_workflow(
        workflow,
        context.registry,
        known_profile_ids=context.profile_ids,
        known_personas=context.personas,
        known_writing_presets=context.writing_presets,
        allowed_folder_roots=context.folder_roots,
    )


@router.get("/workflows/vocabulary")
async def workflow_vocabulary_route():
    """The closed vocabulary, so the builder never hard-codes a list that can
    drift from the schema — including the prohibited verbs *and their reasons*,
    which is what lets the UI explain a refusal in the same words the backend
    would."""
    return {
        "ok": True,
        "schema_version": SCHEMA_VERSION,
        "allowed_actions": list(ALLOWED_ACTIONS),
        "prohibited_actions": dict(PROHIBITED_ACTIONS),
        "step_status_codes": list(STEP_STATUS_CODES),
        "run_status_codes": list(RUN_STATUS_CODES),
    }


@router.get("/workflows")
async def list_workflows_route():
    store = _store()
    return {"ok": True, "workflows": store.list_workflows()}


@router.post("/workflows/compile")
async def compile_workflow_route(request: CompileRequest):
    """Describe -> compile -> validate -> preview, with nothing written.

    Returns refusals from BOTH layers separately: the schema's (this verb is not
    something a workflow does) and the validator's (this target is not something
    you confirmed). They read differently to the user and fixing them is a
    different action, so collapsing them into one list would be a worse error
    message for no gain.
    """
    result = compile_workflow(request.workflow.model_dump())
    payload = result.to_dict()
    payload["preview"] = []
    payload["preview_lines"] = []
    payload["validation_refusals"] = []
    if result.ok:
        validation = _validate(result.workflow, request.context)
        payload["ok"] = validation.ok
        payload["preview"] = validation.preview
        payload["preview_lines"] = preview_lines(validation.preview)
        payload["validation_refusals"] = [r.to_dict() for r in validation.refusals]
    return payload


@router.post("/workflows/save")
async def save_workflow_route(request: SaveRequest):
    """Saved disabled or enabled — and always UNAPPROVED. Approval is a
    separate, explicit act against a preview the user read."""
    result = _store().save(request.workflow.model_dump(), enabled=request.enabled)
    if not result.get("ok"):
        if result.get("error") == "refused":
            # 400 with the refusals attached rather than a bare error: the
            # builder needs to show which step it will not perform.
            raise HTTPException(status_code=400, detail=result)
        _fail(result)
    return result


@router.post("/workflows/approve")
async def approve_workflow_route(request: ApproveRequest):
    result = _store().approve(request.workflow_id, request.preview)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/workflows/enable")
async def enable_workflow_route(request: EnableRequest):
    result = _store().set_enabled(request.workflow_id, request.enabled)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/workflows/delete")
async def delete_workflow_route(request: EnableRequest):
    result = _store().delete(request.workflow_id)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/workflows/run")
async def run_workflow_route(request: RunRequest):
    """The gate. Re-validates and re-previews before consulting ``can_run``.

    A workflow can become unrunnable without anybody editing it — the user
    removes the application it launches, or re-confirms it with a different
    launch method. Trusting the stored approval flag would run something the
    preview no longer describes, which is the exact failure approval exists to
    prevent.
    """
    store = _store()
    record = store.get(request.workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="That workflow no longer exists.")

    validation = _validate(record, request.context)
    lines = preview_lines(validation.preview)
    if not validation.ok:
        return {
            "ok": False,
            "error": "validation_failed",
            "reason": "Some steps no longer point at anything BetterFingers can open.",
            "refusals": [r.to_dict() for r in validation.refusals],
            "preview": validation.preview,
            "preview_lines": lines,
        }

    gate = store.can_run(request.workflow_id, lines)
    if not gate.get("ok"):
        return {
            "ok": False,
            "error": gate.get("error"),
            "reason": gate.get("reason"),
            "preview": validation.preview,
            "preview_lines": lines,
        }
    return {
        "ok": True,
        "workflow": record,
        "preview": validation.preview,
        "preview_lines": lines,
    }


@router.post("/workflows/run/record")
async def record_run_route(request: RecordRunRequest):
    """Per-step outcomes in, an honest summary out — and one history row.

    ``summarize_run`` is what makes "launched two of three" a *partial* rather
    than a success; the store then keeps the codes and nothing else.
    """
    store = _store()
    record = store.get(request.workflow_id)
    if record is None:
        raise HTTPException(status_code=404, detail="That workflow no longer exists.")
    summary = summarize_run(record, request.results)
    result = store.record_run(request.workflow_id, summary)
    if not result.get("ok"):
        _fail(result)
    return {"ok": True, "summary": summary, "run": result["run"]}


@router.get("/workflows/history")
async def workflow_history_route(workflow_id: str = "", limit: int = 20):
    return {"ok": True, "history": _store().history(workflow_id or None, limit)}
