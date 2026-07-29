"""Controller and Stream Deck routes (Wave 10).

Thin FastAPI adapters over ``backend.domain.input_actions``,
``backend.stores.controller_bindings``, ``backend.stores.stream_deck_config``
and ``backend.services.input_dispatch``. Registered with one
``app.include_router`` line at the end of server.py, exactly like the Wave 9
action routes; that line and the handler wiring are integration-owned and are
written out in ``docs/release/WAVE10_INTEGRATION_DIFFS.md``.

THE SHAPE OF THIS MODULE IS THE POINT. There is exactly one dispatch route,
``POST /input/dispatch``, and every non-voice device reaches it: the Stream Deck
plugin posts to it directly, and the in-process controller engine calls the same
``InputActionDispatcher.dispatch`` the route calls. Two routes -- say, one for
controllers and one for decks -- would be two places for the emergency stop to
be filtered differently, and it is the second one nobody tests.

THE DISPATCHER IS A PROCESS SINGLETON, and it must be: its handler table is
wired once at startup against the same runtime functions the keyboard uses.
``set_dispatcher`` is the integration seam. Before it is called the default
dispatcher has no handlers, so every route here works and every action honestly
reports ``unavailable`` -- an unmounted build behaves like an unfinished one
rather than a broken one.

WHAT IS DELIBERATELY NOT HERE. No route runs a workflow. ``workflow.run``
reaches the dispatcher's ``request_workflow`` handler, which asks the Electron
main process to take Wave 9's approval path; see input_dispatch.py's header.
"""

import logging
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from backend.domain.input_actions import DEVICE_KINDS, vocabulary
from backend.services.input_dispatch import (
    DISPATCH_STATUS_CODES,
    InputActionDispatcher,
    rehearsal_dispatcher,
)
from backend.stores.app_profiles import AppProfileStore
from backend.stores.controller_bindings import (
    ControllerBindingStore,
    coverage,
    resolve_bindings,
)
from backend.stores.stream_deck_config import StreamDeckConfigStore, qualification

router = APIRouter()
logger = logging.getLogger(__name__)

_ERROR_STATUS = {
    "refused": 400,
    "invalid_device": 400,
    "not_found": 404,
    "cap_reached": 409,
    "write_failed": 500,
}

_dispatcher = InputActionDispatcher()

#: The wizard's dispatcher. A module-level singleton like the real one, so its
#: recent-press log is readable by the wizard between requests -- and never
#: swapped by ``set_dispatcher``, because the point of it is that nobody can
#: give it handlers.
_REHEARSAL = rehearsal_dispatcher()


def set_dispatcher(dispatcher: InputActionDispatcher) -> None:
    """Integration seam: server.py hands over the dispatcher whose handlers point
    at the same runtime functions the keyboard and the dashboard call."""
    global _dispatcher
    _dispatcher = dispatcher


def get_dispatcher() -> InputActionDispatcher:
    return _dispatcher


def _bindings() -> ControllerBindingStore:
    # Fresh per call, like the Wave 9 workflow routes: the store re-reads from
    # disk on every method, so a per-request instance picks up the current data
    # root rather than one cached at import time.
    return ControllerBindingStore()


def _decks() -> StreamDeckConfigStore:
    return StreamDeckConfigStore()


def _fail(result: dict):
    status = _ERROR_STATUS.get(result.get("error"), 400)
    raise HTTPException(status_code=status,
                        detail=result.get("reason") or result.get("error") or "refused")


def _profile_layer(profile_id: str) -> dict:
    """The per-application layer, read from Wave 7's profile — not from a second
    table. An unknown profile id contributes nothing rather than raising: a
    controller press must not 404 because a profile was deleted while a game was
    running."""
    if not profile_id:
        return {}
    profile = AppProfileStore().get(profile_id)
    if not profile:
        return {}
    return profile.get("bindings") or {}


# --- Vocabulary and resolution ----------------------------------------------


@router.get("/input/vocabulary")
async def input_vocabulary_route():
    """The closed action list, plus what THIS build can actually perform.

    ``available`` is the honest half: a setup UI that offers every id in
    ``actions`` would let a user bind a button that reports ``unavailable`` the
    first time they press it in a game.
    """
    payload = vocabulary()
    payload["ok"] = True
    payload["available"] = get_dispatcher().available_actions()
    payload["dispatch_status_codes"] = list(DISPATCH_STATUS_CODES)
    return payload


@router.get("/input/bindings")
async def input_bindings_route(device_key: str = "", profile_id: str = ""):
    """The three layers, and what they fold to.

    Returns the layers separately as well as resolved, because "why does this
    button do that?" is the question a binding UI exists to answer and it cannot
    be answered from the resolved map alone.
    """
    store = _bindings()
    data = store.read()
    profile_layer = _profile_layer(profile_id)
    resolved = resolve_bindings(data, device_key, profile_layer)
    return {
        "ok": True,
        "enabled": data["enabled"],
        "debounce_ms": data["debounce_ms"],
        "layers": {
            "global": data["global"],
            "device": data["devices"].get(device_key, {}),
            "application_profile": profile_layer,
        },
        "devices": sorted(data["devices"]),
        "resolved": resolved,
        "coverage": coverage(resolved),
        "device_kinds": list(DEVICE_KINDS),
    }


class SetBindingRequest(BaseModel):
    action_id: str
    binding: dict = Field(default_factory=dict)
    device_key: str = ""


@router.post("/input/bindings/set")
async def set_binding_route(request: SetBindingRequest):
    result = _bindings().set_binding(request.action_id, request.binding, request.device_key)
    if not result.get("ok"):
        _fail(result)
    return result


class ClearBindingRequest(BaseModel):
    action_id: str
    device_key: str = ""


@router.post("/input/bindings/clear")
async def clear_binding_route(request: ClearBindingRequest):
    result = _bindings().clear_binding(request.action_id, request.device_key)
    if not result.get("ok"):
        _fail(result)
    return result


class InputSettingsRequest(BaseModel):
    enabled: Optional[bool] = None
    debounce_ms: Optional[int] = None


@router.post("/input/settings")
async def input_settings_route(request: InputSettingsRequest):
    store = _bindings()
    if request.debounce_ms is not None:
        result = store.set_debounce_ms(request.debounce_ms)
        if not result.get("ok"):
            _fail(result)
    if request.enabled is not None:
        result = store.set_enabled(request.enabled)
        if not result.get("ok"):
            _fail(result)
    data = store.read()
    return {"ok": True, "enabled": data["enabled"], "debounce_ms": data["debounce_ms"]}


# --- The one dispatch route --------------------------------------------------


class DispatchRequest(BaseModel):
    action_id: str
    param: str = ""
    source: str = ""
    device_key: str = ""
    #: True when this press begins a HOLD the sender will end with the matching
    #: release id. The Stream Deck plugin sets it on keyDown for a holdable
    #: action; it is what lets an unplugged deck release exactly what it held.
    hold: bool = False
    #: The game setup wizard's test step. A rehearsal press is answered by a
    #: dispatcher with NO handlers, so there is nothing for it to reach -- not a
    #: flag that suppresses an effect, but an object that has no effect to
    #: suppress. See input_dispatch.rehearsal_dispatcher.
    rehearsal: bool = False


@router.post("/input/dispatch")
async def input_dispatch_route(request: DispatchRequest):
    """Every non-voice device arrives here.

    Always 200 with a status code, never a 4xx for a refusal. A Stream Deck key
    press is not an API call a developer is debugging -- it is a person pressing
    a button, and the plugin's job is to show them a code on the key, which it
    can only do if it gets one back. HTTP-level failures stay HTTP-level.

    A rehearsal press is answered by a DIFFERENT dispatcher -- one built with an
    empty handler table -- rather than by this one with a flag set. The
    difference matters: a flag is something a later edit can invert, and an
    object with no callables is not.
    """
    dispatcher = _REHEARSAL if request.rehearsal else get_dispatcher()
    return dispatcher.dispatch(
        request.action_id,
        param=request.param,
        source=request.source or "",
        device_key=request.device_key or "",
        # A rehearsal never registers a hold: there is nothing held, because
        # nothing started.
        hold=bool(request.hold) and not request.rehearsal,
    )


# --- Recording a binding -----------------------------------------------------
#
# The setup wizard's "press a button now". The ENGINE does the listening,
# because it is the thing with the events; these routes are a start/poll/cancel
# handle on it. A build with no engine wired reports ``unavailable`` rather than
# pretending to listen, which is what makes the wizard honest on a machine with
# no joystick support compiled in.

_capture_source = None


def set_capture_source(engine) -> None:
    """Integration seam: server.py hands over the live ControllerEngine."""
    global _capture_source
    _capture_source = engine


@router.post("/input/capture/start")
async def input_capture_start_route():
    if _capture_source is None:
        return {"ok": False, "error": "unavailable",
                "reason": "BetterFingers is not watching a controller in this build."}
    return _capture_source.begin_capture()


@router.get("/input/capture/result")
async def input_capture_result_route():
    """``binding`` is null until the user has let go of everything.

    Answering mid-press would turn the first token of a two-button chord into a
    single binding, and the user would have no way to tell that the wizard
    stopped listening halfway through what they pressed.
    """
    if _capture_source is None:
        return {"ok": False, "error": "unavailable", "capturing": False, "binding": None}
    return {
        "ok": True,
        "capturing": _capture_source.capturing,
        "binding": _capture_source.capture_result(),
    }


@router.post("/input/capture/cancel")
async def input_capture_cancel_route():
    if _capture_source is None:
        return {"ok": True, "capturing": False}
    return _capture_source.cancel_capture()


@router.get("/input/recent")
async def input_recent_route(limit: int = 20):
    """Codes only — what the support report and the setup wizard's live readout
    show. No parameter values, so a persona name never lands in a log."""
    return {"ok": True, "recent": get_dispatcher().recent(limit)}


# --- Stream Deck -------------------------------------------------------------


@router.get("/stream-deck")
async def stream_deck_route():
    summary = _decks().summary()
    summary["ok"] = True
    return summary


class PairRequest(BaseModel):
    token: str


@router.post("/stream-deck/pair")
async def stream_deck_pair_route(request: PairRequest):
    """Record that the plugin holding this token is the paired deck.

    Only a fingerprint is stored. This does not grant access — the request that
    got here already passed the server's bearer check, like every other request.
    """
    result = _decks().pair(request.token)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/stream-deck/unpair")
async def stream_deck_unpair_route():
    result = _decks().unpair()
    if not result.get("ok"):
        _fail(result)
    return result


class DeckEnabledRequest(BaseModel):
    enabled: bool


@router.post("/stream-deck/enabled")
async def stream_deck_enabled_route(request: DeckEnabledRequest):
    result = _decks().set_enabled(request.enabled)
    if not result.get("ok"):
        _fail(result)
    get_dispatcher().set_kind_enabled("stream_deck", request.enabled)
    return result


class DeckKeyRequest(BaseModel):
    context: str
    action: str = ""
    action_id: str = ""
    settings: dict = Field(default_factory=dict)
    device: str = ""
    title: str = ""
    coordinates: dict = Field(default_factory=dict)


@router.post("/stream-deck/key")
async def stream_deck_key_route(request: DeckKeyRequest):
    """The plugin reporting a key that exists. A mirror write, never a source of
    truth — see the store's header."""
    payload = request.model_dump()
    result = _decks().record_key(payload.pop("context"), payload)
    if not result.get("ok"):
        _fail(result)
    return result


class DeckContextRequest(BaseModel):
    context: str


@router.post("/stream-deck/key/forget")
async def stream_deck_forget_key_route(request: DeckContextRequest):
    result = _decks().forget_key(request.context)
    if not result.get("ok"):
        _fail(result)
    return result


class DeckDeviceRequest(BaseModel):
    device: str
    name: str = ""
    size: dict = Field(default_factory=dict)
    connected: bool = True


@router.post("/stream-deck/device")
async def stream_deck_device_route(request: DeckDeviceRequest):
    payload = request.model_dump()
    result = _decks().record_device(payload.pop("device"), payload)
    if not result.get("ok"):
        _fail(result)
    return result


@router.post("/stream-deck/device/disconnected")
async def stream_deck_device_gone_route(request: DeckDeviceRequest):
    """A deck vanished.

    The keys stay mirrored (an unplugged deck is the same deck), but anything a
    key was HOLDING is released through the dispatcher's normal release path --
    the same path an unplugged controller uses, per D-0026. There is no second
    release mechanism.
    """
    result = _decks().device_disconnected(request.device)
    result["released"] = get_dispatcher().release_device(
        f"stream_deck:{request.device}", reason="device_lost",
    )
    return result


@router.get("/stream-deck/qualification")
async def stream_deck_qualification_route():
    """Honest status, reachable from the UI so it cannot be lost between the
    code and the release notes."""
    payload = qualification()
    payload["ok"] = True
    return payload
