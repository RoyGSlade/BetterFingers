"""Application-context status + profile management (Wave 7).

Thin FastAPI adapters over ``backend.services.app_context`` and
``backend.stores.app_profiles``. Registered via ``app.include_router`` at the
end of server.py like every other extracted route module -- that one line is
integration-owned and is written out in
``docs/release/WAVE7_INTEGRATION_DIFFS.md``; until it lands these routes exist
but are not mounted.

``GET /app-context/status`` is the route the status bar polls. It re-detects by
default, in a threadpool: detection shells out to ``xdotool`` with a 2s timeout,
and running that on the event loop would starve ``/health`` and invite Electron's
restart watchdog -- the same reason contact compile runs off-loop. Pass
``refresh=false`` for the last known state with no detection at all.

Nothing here reads or returns anything about a recipient, a contact, or a
conversation; the snapshot vocabulary is closed in the service and tested there.
"""

import logging

from fastapi import APIRouter, HTTPException
from fastapi.concurrency import run_in_threadpool
from pydantic import BaseModel
from typing import Optional

from backend.domain.gaming_policy import GAMING_POLICY
from backend.services.app_context import get_service
from backend.stores.app_profiles import (
    BUILTIN_PROFILE_IDS,
    INJECTION_POLICIES,
    PERFORMANCE_PRESETS,
    AppProfileStore,
)

router = APIRouter()
logger = logging.getLogger(__name__)

# Maps the stores' structured {"ok": False, "error": ...} results to HTTP
# status. Exhaustive over their documented codes -- anything unlisted is a code
# change that should surface as a 400, not a 500 pretending to be a fault.
_ERROR_STATUS = {
    "invalid_id": 400,
    "invalid_app_key": 400,
    "unknown_application": 409,
    "not_found": 404,
    "cap_reached": 409,
    "write_failed": 500,
}


def _store() -> AppProfileStore:
    # Fresh per call, like the contacts route's: the store re-reads from disk on
    # every method, and resolving the path per-instance means each request picks
    # up the current data root rather than one cached at import time.
    return AppProfileStore()


def _fail(result: dict):
    status = _ERROR_STATUS.get(result.get("error"), 400)
    raise HTTPException(status_code=status, detail=result.get("message") or result.get("error"))


class OverrideRequest(BaseModel):
    # Empty string and null both mean "stop overriding" -- a first-class state,
    # not an absence to be filled.
    profile_id: Optional[str] = None


class PinRequest(BaseModel):
    profile_id: Optional[str] = None


@router.get("/app-context/status")
async def app_context_status_route(refresh: bool = True):
    service = get_service()
    context = await run_in_threadpool(service.poll) if refresh else service.current()
    return {"ok": True, "context": context}


@router.get("/app-context/profiles")
async def app_context_profiles_route():
    """Every profile plus the vocabularies a UI needs to render the controls,
    so the renderer never hard-codes a list that can drift from the store."""
    store = _store()
    return {
        "ok": True,
        "profiles": store.list_profiles(),
        "builtin_ids": list(BUILTIN_PROFILE_IDS),
        "pinned": store.pinned_map(),
        "performance_presets": list(PERFORMANCE_PRESETS),
        "injection_policies": list(INJECTION_POLICIES),
        "gaming_policy": dict(GAMING_POLICY),
    }


class ProfileRequest(BaseModel):
    """One profile document, as ``sanitize_profile`` will read it.

    Deliberately typed as a free dict rather than field by field: the store's
    ``PROFILE_FIELDS`` tuple is the one authority on what a profile may carry,
    and a pydantic model listing the same fields would be a second one that can
    disagree with it. Anything not in that tuple is DROPPED and REPORTED back --
    which is how a caller trying to stash a recipient or a conversation summary
    on a profile is told rather than believing it worked.
    """

    profile: dict


@router.post("/app-context/profiles")
async def app_context_save_profile_route(request: ProfileRequest):
    """Create or replace one profile (Wave 10).

    WHY THIS LANDS IN WAVE 10 AND NOT WAVE 7. Wave 7 shipped the profile store,
    the schema and the read routes, and left writing to a later wave because
    nothing yet needed to write one. Wave 10's game setup wizard does: the
    per-application binding layer lives in ``profile["bindings"]``, so a wizard
    that cannot save a profile cannot deliver deliverable 2 at all.

    The response carries the store's ``dropped_fields`` verbatim. A UI that
    ignores it is a UI that silently loses a field the user set, so it is
    returned rather than logged.
    """
    result = _store().save(request.profile)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/app-context/override")
async def app_context_override_route(request: OverrideRequest):
    """Temporary override. Not persisted -- see the service's set_override."""
    result = get_service().set_override(request.profile_id or "")
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/app-context/pin")
async def app_context_pin_route(request: PinRequest):
    """"Always use this profile for this application." Durable; a null/empty
    profile_id unpins."""
    result = get_service().pin_current(request.profile_id or "")
    if not result.get("ok"):
        _fail(result)
    return result
