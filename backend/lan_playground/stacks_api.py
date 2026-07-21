"""The Lost Meaning: Infinite Stacks -- room WebSocket transport (board task #3).

Implements infinite_stacks.md SS21.2/22.1/22.5: authoritative revisioned RunState,
idempotent commands, expected-revision conflict handling (a stale command gets a
current legal-action summary, never a bare error), public events + viewer-filtered
private projections, reconnect-from-snapshot-plus-missed-events, and a REST snapshot
fallback. It reuses the existing LAN security model from
``backend.lan_playground.security`` (access code, Host/Origin allowlist, constant-time
comparisons, rate limiting) -- that module is not modified.

Every call into "the engine" (validate/handle/reduce/project, per SS22.1 and
docs/INFINITE_STACKS_CONTRACTS.md) is isolated behind ``StacksEngineAdapter``
(stacks_engine.py), the one class that wraps engine calls. This module owns only
transport concerns: room/session bookkeeping (``StacksRoomManager``), the WebSocket
connection hub, REST request/response shapes, and the FastAPI app factory. Command/
event/state shapes live in stacks_protocol.py; viewer-filtered projection logic lives
in stacks_projections.py -- this three-way split (plus stacks_engine.py) replaced a
single 1196-line file that exceeded the infinite_stacks.md S22.2 soft 500-line cap.

Nothing in this module calls ``logging`` and no player-authored text (display names,
future compose drafts) is put into a log line or exception detail.
"""

from __future__ import annotations

import asyncio
import random
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Callable

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from backend.lan_playground.security import (
    SECURITY_HEADERS,
    RateLimiter,
    constant_time_equals,
    generate_room_code,
    generate_token,
    host_header_allowed,
    origin_allowed,
)
from backend.lan_playground.stacks_engine import StacksEngineAdapter
from backend.lan_playground.stacks_projections import event_wire
from backend.lan_playground.stacks_protocol import (
    ApplyResult,
    Command,
    CommandError,
    DISPLAY_NAME_MAX_CHARS,
    Event,
    RunNotFoundError,
    RunState,
)

STATIC_DIR = Path(__file__).parent / "static"

# S21.4 reaction-decision timer: when a Conflict encounter pauses into a
# pending reaction, the transport layer (never the reducer -- wave-5 director
# ruling) owns the wall-clock countdown and injects a server-originated
# resolve_reaction "pass" through the ordinary command pipeline on expiry, so
# the command log stays the single source of truth and replay holds.
REACTION_DECISION_SECONDS = 30.0

DEFAULT_ROOM_CREATE_RATE_LIMIT_PER_MIN = 6
DEFAULT_ROOM_JOIN_RATE_LIMIT_PER_MIN = 20
DEFAULT_ROOM_SNAPSHOT_RATE_LIMIT_PER_MIN = 90
DEFAULT_WS_CONNECT_RATE_LIMIT_PER_MIN = 30
DEFAULT_CONTENT_CATALOG_RATE_LIMIT_PER_MIN = 30


# --------------------------------------------------------------------------
# Room/session bookkeeping (transport-only: tokens, connections, presence --
# NOT engine calls, kept separate from StacksEngineAdapter on purpose).
# --------------------------------------------------------------------------


class StacksRoomManager:
    def __init__(self, adapter: StacksEngineAdapter, clock: Callable[[], float] = time.monotonic):
        self._adapter = adapter
        self._clock = clock
        self._lock = threading.Lock()
        self._states: dict[str, RunState] = {}
        self._tokens: dict[str, dict[str, str]] = {}  # room_code -> token -> hero_id

    def create_room(self, host_name: str, seed: int | None) -> tuple[str, RunState, str, str]:
        with self._lock:
            code = generate_room_code()
            while code in self._states:
                code = generate_room_code()
            state = self._adapter.create_run(seed=seed if seed is not None else random.SystemRandom().randrange(1, 2**31))
            hero_id = _slug_hero_id(host_name, state)
            command = Command(
                command_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
                run_id=state.run_id,
                hero_id=hero_id,
                encounter_id=None,
                expected_revision=state.revision,
                type="join_run",
                payload={"display_name": host_name},
            )
            self._adapter.apply(state, command)
            token = generate_token()
            self._states[code] = state
            self._tokens[code] = {token: hero_id}
            return code, state, hero_id, token

    def join_room(self, code: str, display_name: str) -> tuple[RunState, str, str]:
        with self._lock:
            state = self._require_state(code)
            hero_id = _slug_hero_id(display_name, state)
            command = Command(
                command_id=str(uuid.uuid4()),
                idempotency_key=str(uuid.uuid4()),
                run_id=state.run_id,
                hero_id=hero_id,
                encounter_id=None,
                expected_revision=state.revision,
                type="join_run",
                payload={"display_name": display_name},
            )
            self._adapter.apply(state, command)
            token = generate_token()
            self._tokens[code][token] = hero_id
            return state, hero_id, token

    def hero_id_for_token(self, code: str, token: str) -> str | None:
        with self._lock:
            return self._tokens.get(code, {}).get(token)

    def get_state(self, code: str) -> RunState:
        with self._lock:
            return self._require_state(code)

    def apply(self, code: str, command: Command) -> ApplyResult:
        with self._lock:
            state = self._require_state(code)
            return self._adapter.apply(state, command)

    def apply_authoritative(self, code: str, command: Command) -> ApplyResult:
        # Server-originated command (§21.4 reaction-timeout auto-pass, §21.5
        # disconnected-companion actions) -- see StacksEngineAdapter.
        # apply_authoritative's docstring for why this bypasses the normal
        # viewer==hero_id check.
        with self._lock:
            state = self._require_state(code)
            return self._adapter.apply_authoritative(state, command)

    def project(self, code: str, viewer: str | None) -> dict[str, Any]:
        with self._lock:
            state = self._require_state(code)
            return self._adapter.project(state, viewer)

    def events_since(self, code: str, viewer: str | None, since_revision: int) -> list[Event]:
        with self._lock:
            state = self._require_state(code)
            return self._adapter.events_since(state, viewer, since_revision)

    def legal_actions(self, code: str, hero_id: str | None) -> dict[str, Any]:
        with self._lock:
            state = self._require_state(code)
            return self._adapter.legal_actions(state, hero_id)

    def content_catalog(self) -> dict[str, Any]:
        # Static reference content (background/card/item definitions, §11) --
        # no run state involved, so no lock/room lookup needed.
        return self._adapter.content_catalog()

    def set_presence(self, code: str, hero_id: str, *, connected: bool | None = None, ready: bool | None = None) -> None:
        with self._lock:
            state = self._states.get(code)
            if state is None or hero_id not in state.heroes:
                return
            hero = state.heroes[hero_id]
            if connected is not None:
                hero.connected = connected
            if ready is not None:
                hero.ready = ready

    def _require_state(self, code: str) -> RunState:
        state = self._states.get(code)
        if state is None:
            raise RunNotFoundError(code)
        return state


def _slug_hero_id(display_name: str, state: RunState) -> str:
    base = "".join(ch for ch in display_name.lower() if ch.isalnum()) or "hero"
    base = base[:24]
    candidate = f"hero_{base}"
    n = 2
    while candidate in state.heroes:
        candidate = f"hero_{base}{n}"
        n += 1
    return candidate


# --------------------------------------------------------------------------
# WebSocket connection hub: broadcasts viewer-filtered events to live sockets.
# --------------------------------------------------------------------------


class ConnectionHub:
    def __init__(self):
        self._lock = threading.Lock()
        # room_code -> hero_id -> set[WebSocket]
        self._sockets: dict[str, dict[str, set[WebSocket]]] = {}

    def add(self, code: str, hero_id: str, ws: WebSocket) -> None:
        with self._lock:
            self._sockets.setdefault(code, {}).setdefault(hero_id, set()).add(ws)

    def remove(self, code: str, hero_id: str, ws: WebSocket) -> None:
        with self._lock:
            room = self._sockets.get(code)
            if not room or hero_id not in room:
                return
            room[hero_id].discard(ws)
            if not room[hero_id]:
                del room[hero_id]
            if not room:
                self._sockets.pop(code, None)

    def is_connected(self, code: str, hero_id: str) -> bool:
        with self._lock:
            return bool(self._sockets.get(code, {}).get(hero_id))

    async def broadcast_event(self, code: str, event: Event, revision: int) -> None:
        with self._lock:
            room = dict(self._sockets.get(code, {}))
        for hero_id, sockets in room.items():
            if not event.visible_to_viewer(hero_id):
                continue
            payload = event_wire(event)
            for ws in list(sockets):
                try:
                    await ws.send_json({"kind": "event", "event": payload, "revision": revision})
                except Exception:
                    pass

    async def broadcast_presence(self, code: str, hero_id: str, *, connected: bool | None, ready: bool | None) -> None:
        with self._lock:
            room = dict(self._sockets.get(code, {}))
        message = {"kind": "presence", "hero_id": hero_id, "connected": connected, "ready": ready}
        for sockets in room.values():
            for ws in list(sockets):
                try:
                    await ws.send_json(message)
                except Exception:
                    pass


# --------------------------------------------------------------------------
# REST request bodies
# --------------------------------------------------------------------------


class ReactionAutoPass:
    """S21.4 decision timer for pending combat reactions (wave-5 task #16).

    ``scan_and_schedule`` is called after every successful command apply; for
    each encounter currently paused on a ``pending_reaction`` it arms one
    asyncio timer keyed by (room code, room id, reaction_id). On expiry the
    timer re-checks state and, if the same reaction is still unanswered,
    injects a server-originated ``resolve_reaction`` "pass" via
    ``StacksRoomManager.apply_authoritative`` -- an ordinary logged command,
    so determinism and replay are untouched (the reducer never sees a clock).
    A reaction answered by a player (or a protector) before expiry simply
    causes the fired timer to observe a different/absent reaction_id and do
    nothing. Disconnected heroes are handled by the same injection acting as
    the S21.5 companion default.
    """

    def __init__(self, manager: StacksRoomManager, hub: ConnectionHub, delay_seconds: float = REACTION_DECISION_SECONDS):
        self._manager = manager
        self._hub = hub
        self._delay = delay_seconds
        self._scheduled: set[tuple[str, str, str]] = set()

    def scan_and_schedule(self, code: str) -> None:
        try:
            view = self._manager.project(code, None)
        except RunNotFoundError:
            return
        for room_id, conflict in (view.get("conflict") or {}).items():
            pending = conflict.get("pending_reaction")
            if not pending or pending.get("reaction_id") is None:
                continue
            key = (code, room_id, str(pending["reaction_id"]))
            if key in self._scheduled:
                continue
            self._scheduled.add(key)
            asyncio.create_task(self._auto_pass(key, conflict.get("encounter_id")))

    async def _auto_pass(self, key: tuple[str, str, str], encounter_id: str | None) -> None:
        code, room_id, reaction_id = key
        try:
            await asyncio.sleep(self._delay)
            # One retry: a player command can race us between projection and
            # apply, bumping the revision -- re-check and try once more.
            for _ in range(2):
                try:
                    view = self._manager.project(code, None)
                    run_id = self._manager.get_state(code).run_id
                except RunNotFoundError:
                    return
                conflict = (view.get("conflict") or {}).get(room_id) or {}
                pending = conflict.get("pending_reaction")
                if not pending or str(pending.get("reaction_id")) != reaction_id:
                    return  # answered or encounter ended before the timer fired
                command = Command(
                    command_id=uuid.uuid4().hex,
                    idempotency_key=f"autopass_{reaction_id}_{uuid.uuid4().hex[:8]}",
                    run_id=run_id,
                    hero_id=str(pending.get("defender_id")),
                    encounter_id=conflict.get("encounter_id") or encounter_id,
                    expected_revision=int(view["revision"]),
                    type="resolve_reaction",
                    payload={"reaction_id": reaction_id, "reaction": "pass"},
                )
                try:
                    result = self._manager.apply_authoritative(code, command)
                except CommandError:
                    continue
                for event in result.events:
                    await self._hub.broadcast_event(code, event, result.revision)
                return
        finally:
            self._scheduled.discard(key)


class CreateRoomRequest(BaseModel):
    host_name: str = Field(..., min_length=1, max_length=DISPLAY_NAME_MAX_CHARS)
    seed: int | None = None


class JoinRoomRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=DISPLAY_NAME_MAX_CHARS)


_COMMAND_ERROR_STATUS = {
    "stale_revision": 409,
    "illegal_action": 422,
    "not_your_turn": 403,
    "unknown_target": 404,
    "schema_error": 400,
}


class CommandRequest(BaseModel):
    command_id: str = Field(..., min_length=1, max_length=64)
    idempotency_key: str = Field(..., min_length=1, max_length=64)
    encounter_id: str | None = None
    expected_revision: int = Field(..., ge=0)
    type: str = Field(..., min_length=1, max_length=32)
    payload: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# FastAPI app factory
# --------------------------------------------------------------------------


def create_stacks_app(
    *,
    access_code: str,
    allowed_hosts: set[str],
    allowed_origins: set[str],
    room_manager: StacksRoomManager | None = None,
    clock: Callable[[], float] = time.monotonic,
    static_dir: Path = STATIC_DIR,
    room_create_rate_limit_per_min: int = DEFAULT_ROOM_CREATE_RATE_LIMIT_PER_MIN,
    room_join_rate_limit_per_min: int = DEFAULT_ROOM_JOIN_RATE_LIMIT_PER_MIN,
    room_snapshot_rate_limit_per_min: int = DEFAULT_ROOM_SNAPSHOT_RATE_LIMIT_PER_MIN,
    ws_connect_rate_limit_per_min: int = DEFAULT_WS_CONNECT_RATE_LIMIT_PER_MIN,
    content_catalog_rate_limit_per_min: int = DEFAULT_CONTENT_CATALOG_RATE_LIMIT_PER_MIN,
    reaction_decision_seconds: float = REACTION_DECISION_SECONDS,
) -> FastAPI:
    app = FastAPI(title="Infinite Stacks Transport", docs_url=None, redoc_url=None, openapi_url=None)

    manager = room_manager if room_manager is not None else StacksRoomManager(StacksEngineAdapter(), clock=clock)
    hub = ConnectionHub()
    reaction_autopass = ReactionAutoPass(manager, hub, delay_seconds=reaction_decision_seconds)
    create_limiter = RateLimiter(max_requests=room_create_rate_limit_per_min, window_s=60.0)
    join_limiter = RateLimiter(max_requests=room_join_rate_limit_per_min, window_s=60.0)
    snapshot_limiter = RateLimiter(max_requests=room_snapshot_rate_limit_per_min, window_s=60.0)
    ws_limiter = RateLimiter(max_requests=ws_connect_rate_limit_per_min, window_s=60.0)
    content_catalog_limiter = RateLimiter(max_requests=content_catalog_rate_limit_per_min, window_s=60.0)

    class _PolicyMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            host_header = request.headers.get("host", "")
            if not host_header_allowed(host_header, allowed_hosts):
                return JSONResponse(status_code=421, content={"detail": "unrecognized_host"})
            origin_header = request.headers.get("origin")
            if not origin_allowed(origin_header, allowed_origins):
                return JSONResponse(status_code=403, content={"detail": "origin_not_allowed"})
            response = await call_next(request)
            for key, value in SECURITY_HEADERS.items():
                response.headers[key] = value
            return response

    app.add_middleware(_PolicyMiddleware)

    def _client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _require_access_code(x_access_code: str = Header(default="")) -> None:
        if not constant_time_equals(x_access_code, access_code):
            raise HTTPException(status_code=401, detail="invalid_access_code")

    def _authenticate(code: str, x_player_token: str) -> str:
        hero_id = manager.hero_id_for_token(code, x_player_token)
        if hero_id is None:
            raise HTTPException(status_code=401, detail="invalid_player_token")
        return hero_id

    @app.get("/api/stacks/content-catalog", dependencies=[Depends(_require_access_code)])
    async def get_content_catalog(request: Request):
        # Static background/card/item reference data (§11) for the
        # character-builder screen -- access-code gated like every other
        # route, but no player token: it names no run or hero.
        if not content_catalog_limiter.allow(_client_key(request), now=clock()):
            raise HTTPException(status_code=429, detail="rate_limited")
        return manager.content_catalog()

    @app.post("/api/stacks/rooms", dependencies=[Depends(_require_access_code)])
    async def create_room(body: CreateRoomRequest, request: Request):
        if not create_limiter.allow(_client_key(request), now=clock()):
            raise HTTPException(status_code=429, detail="rate_limited")
        code, state, hero_id, token = manager.create_room(body.host_name, body.seed)
        return {
            "room_code": code,
            "run_id": state.run_id,
            "hero_id": hero_id,
            "player_token": token,
            "revision": state.revision,
        }

    @app.post("/api/stacks/rooms/{code}/join", dependencies=[Depends(_require_access_code)])
    async def join_room(code: str, body: JoinRoomRequest, request: Request):
        if not join_limiter.allow(_client_key(request), now=clock()):
            raise HTTPException(status_code=429, detail="rate_limited")
        try:
            state, hero_id, token = manager.join_room(code, body.display_name)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="room_not_found")
        return {"run_id": state.run_id, "hero_id": hero_id, "player_token": token, "revision": state.revision}

    @app.get("/api/stacks/rooms/{code}/snapshot", dependencies=[Depends(_require_access_code)])
    async def get_snapshot(
        code: str,
        request: Request,
        x_player_token: str = Header(default=""),
    ):
        if not snapshot_limiter.allow(_client_key(request), now=clock()):
            raise HTTPException(status_code=429, detail="rate_limited")
        try:
            hero_id = _authenticate(code, x_player_token)
            view = manager.project(code, hero_id)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="room_not_found")
        return {"revision": view["revision"], "view": view}

    @app.post("/api/stacks/rooms/{code}/commands", dependencies=[Depends(_require_access_code)])
    async def submit_command(
        code: str,
        body: CommandRequest,
        request: Request,
        x_player_token: str = Header(default=""),
    ):
        try:
            hero_id = _authenticate(code, x_player_token)
            command = Command(
                command_id=body.command_id,
                idempotency_key=body.idempotency_key,
                run_id=manager.get_state(code).run_id,
                hero_id=hero_id,
                encounter_id=body.encounter_id,
                expected_revision=body.expected_revision,
                type=body.type,
                payload=body.payload,
            )
            result = manager.apply(code, command)
        except RunNotFoundError:
            raise HTTPException(status_code=404, detail="room_not_found")
        except CommandError as exc:
            status = _COMMAND_ERROR_STATUS.get(exc.code, 400)
            raise HTTPException(status_code=status, detail={"code": exc.code, "legal_actions": exc.legal_actions})
        for event in result.events:
            await hub.broadcast_event(code, event, result.revision)
        reaction_autopass.scan_and_schedule(code)
        return {"revision": result.revision, "replayed": result.replayed, "events": [event_wire(e) for e in result.events]}

    @app.websocket("/ws/stacks/{code}")
    async def stacks_ws(
        websocket: WebSocket,
        code: str,
        access_code_param: str = Query(default="", alias="access_code"),
        token: str = Query(default=""),
        since_revision: int = Query(default=0),
    ):
        # Browsers cannot set custom request headers on a WebSocket handshake,
        # so the access code and player token travel as query params here --
        # everything else (Host/Origin allowlist) is checked the same way as
        # the REST routes above.
        host_header = websocket.headers.get("host", "")
        origin_header = websocket.headers.get("origin")
        if not host_header_allowed(host_header, allowed_hosts) or not origin_allowed(origin_header, allowed_origins):
            await websocket.close(code=4403)
            return
        if not constant_time_equals(access_code_param, access_code):
            await websocket.close(code=4401)
            return
        if not ws_limiter.allow(websocket.client.host if websocket.client else "unknown", now=clock()):
            await websocket.close(code=4429)
            return
        hero_id = manager.hero_id_for_token(code, token)
        if hero_id is None:
            await websocket.close(code=4401)
            return
        try:
            manager.get_state(code)
        except RunNotFoundError:
            await websocket.close(code=4404)
            return

        await websocket.accept()
        manager.set_presence(code, hero_id, connected=True)
        await hub.broadcast_presence(code, hero_id, connected=True, ready=None)
        hub.add(code, hero_id, websocket)
        try:
            view = manager.project(code, hero_id)
            missed = manager.events_since(code, hero_id, since_revision)
            await websocket.send_json(
                {
                    "kind": "reconnect_summary",
                    "since_revision": since_revision,
                    "missed_events": [event_wire(e) for e in missed],
                    "snapshot": {"revision": view["revision"], "view": view},
                }
            )
            while True:
                message = await websocket.receive_json()
                await _handle_ws_message(
                    message, code=code, hero_id=hero_id, manager=manager, hub=hub, websocket=websocket, reaction_autopass=reaction_autopass
                )
        except WebSocketDisconnect:
            pass
        finally:
            hub.remove(code, hero_id, websocket)
            manager.set_presence(code, hero_id, connected=False)
            await hub.broadcast_presence(code, hero_id, connected=False, ready=None)

    @app.get("/stacks.html")
    async def stacks_html():
        return FileResponse(static_dir / "stacks.html")

    app.mount("/src", StaticFiles(directory=static_dir / "src"), name="stacks-src")

    return app


async def _handle_ws_message(
    message: dict[str, Any],
    *,
    code: str,
    hero_id: str,
    manager: StacksRoomManager,
    hub: ConnectionHub,
    websocket: WebSocket,
    reaction_autopass: ReactionAutoPass | None = None,
) -> None:
    kind = message.get("kind")
    if kind == "presence":
        ready = message.get("ready")
        manager.set_presence(code, hero_id, ready=bool(ready) if ready is not None else None)
        await hub.broadcast_presence(code, hero_id, connected=None, ready=bool(ready) if ready is not None else None)
        return
    if kind != "command":
        await websocket.send_json({"kind": "command_error", "code": "schema_error", "message": "unknown_message_kind"})
        return
    raw = message.get("command") or {}
    try:
        command = Command(
            command_id=str(raw.get("command_id", "")),
            idempotency_key=str(raw.get("idempotency_key", "")),
            run_id=manager.get_state(code).run_id,
            hero_id=hero_id,
            encounter_id=raw.get("encounter_id"),
            expected_revision=int(raw.get("expected_revision", -1)),
            type=str(raw.get("type", "")),
            payload=dict(raw.get("payload") or {}),
        )
        result = manager.apply(code, command)
    except CommandError as exc:
        await websocket.send_json(
            {
                "kind": "command_error",
                "command_id": raw.get("command_id"),
                "idempotency_key": raw.get("idempotency_key"),
                "code": exc.code,
                "legal_actions": exc.legal_actions,
                "message": exc.message,
            }
        )
        return
    await websocket.send_json(
        {
            "kind": "command_ack",
            "command_id": command.command_id,
            "idempotency_key": command.idempotency_key,
            "revision": result.revision,
            "replayed": result.replayed,
        }
    )
    for event in result.events:
        await hub.broadcast_event(code, event, result.revision)
    if reaction_autopass is not None:
        reaction_autopass.scan_and_schedule(code)
