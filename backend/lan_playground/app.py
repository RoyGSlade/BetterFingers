"""LAN persona rewrite playground + The Lost Meaning game -- ASGI app factory.

A tiny, isolated FastAPI app: pick a persona, paste text, optionally add a
custom rewrite instruction, get back raw/refined comparison output (the
original board #33 surface) -- plus the 1-4 player LAN co-op game "Spellcheck
& Sorcery: The Lost Meaning" (board task #2), a communication adventure where
BetterFingers rewrites a rotating Spotlight hero's rough draft into three
transparent variants, and every round resolves deterministically from
already-established facts, never from free text. No microphone/TTS/audio, no
persistence, no request-body or model-output logging.

``create_app`` takes every side-effecting dependency (access code, allowed
hosts, persona lookup/allowlist, the LLM call_fn, an engine-ready probe) as
an explicit parameter -- exactly the factory-with-injected-dependencies
shape used by backend/api/routes/message_rescue.py -- so the whole app is
unit-testable with fakes, no real model/server.py/network required.
``build_default_app`` is the production wiring, used only by
tools/lan_playground.py; it lazily imports ``server`` and the backend
services at call time so importing this module never pulls in server.py's
full startup surface.

Nothing in this module calls ``logging``, and no request text, persona
prompt content, draft/narration content, or model output is ever put into a
log line or an HTTPException detail (details are fixed, enumerable strings
only).

Every game route below calls the engine only through
``backend.lan_playground.rooms.GameAdapter`` -- see that module's docstring
for why (board task #1's engine is landing in parallel; this isolates the
reconciliation surface to one class).
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from fastapi import Depends, FastAPI, Header, HTTPException, Path as PathParam, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from starlette.middleware.base import BaseHTTPMiddleware

from backend.domain.contracts import to_dict
from backend.lan_playground import game, rooms
from backend.lan_playground.qr import render_qr_svg
from backend.lan_playground.security import (
    SECURITY_HEADERS,
    RateLimiter,
    constant_time_equals,
    host_header_allowed,
    origin_allowed,
    sanitize_custom_instruction,
)
from backend.services.message_rescue import rescue_message

DEFAULT_PORT = 8850
STATIC_DIR = Path(__file__).parent / "static"
ART_DIR = Path(__file__).resolve().parents[2] / "gameassets" / "Spellcheck_and_Sorcery_Art_Pack"
ART_ASSETS = {
    "key-art.png": ART_DIR / "01_Core_Key_Art" / "01_Game_Key_Art_Bureaucratic_Dragon_16x9.png",
    "map.png": ART_DIR / "02_Map_and_Encounters" / "03_Five_Stop_Fantasy_Map_16x9.png",
    "victory.png": ART_DIR / "04_End_Screens" / "12_Victory_Tableau_16x9.png",
    "defeat.png": ART_DIR / "04_End_Screens" / "13_Defeat_Tableau_16x9.png",
    "game-icon.png": ART_DIR / "01_Core_Key_Art" / "02_Game_Icon_Quill_and_Wooden_Sword_Square_v2.png",
    # Encounter art is keyed by the engine's Encounter.id -- unchanged by
    # the Lost Meaning redesign (same 5 encounters/ids in game.py).
    "encounter-troll.png": ART_DIR / "02_Map_and_Encounters" / "04_Passive_Aggressive_Troll_v2.png",
    "encounter-goblins.png": ART_DIR / "02_Map_and_Encounters" / "05_Goblin_HR_Department_v2.png",
    "encounter-mimic.png": ART_DIR / "02_Map_and_Encounters" / "06_Mimic_Suggestion_Box_v2.png",
    "encounter-bridge.png": ART_DIR / "02_Map_and_Encounters" / "07_Bridge_of_Needlessly_Complicated_Riddles_16x9.png",
    "encounter-dragon.png": ART_DIR / "02_Map_and_Encounters" / "08_Final_Boss_Red_Tape_Dragon_v2.png",
}

TRANSCRIPT_MAX_CHARS = 6_000
CUSTOM_INSTRUCTION_MAX_CHARS = 400
PERSONA_NAME_MAX_CHARS = 200
REQUEST_ID_PATTERN = r"^[a-zA-Z0-9_-]{8,64}$"

DEFAULT_GENERATE_TIMEOUT_S = 75.0
DEFAULT_MAX_OUTPUT_TOKENS = 500
DEFAULT_MAX_CONCURRENCY = 2
DEFAULT_RATE_LIMIT_PER_MIN = 12

DEFAULT_ROOM_CREATE_RATE_LIMIT_PER_MIN = 6
DEFAULT_ROOM_JOIN_RATE_LIMIT_PER_MIN = 20
DEFAULT_ROOM_STATE_RATE_LIMIT_PER_MIN = 90
DEFAULT_ROOM_ACTION_RATE_LIMIT_PER_MIN = 30
DEFAULT_ROOM_DRAFT_RATE_LIMIT_PER_MIN = 10
DEFAULT_DRAFT_TIMEOUT_S = 20.0
DEFAULT_NARRATION_TIMEOUT_S = 12.0

# game.py's own room_id is never put on the wire -- rooms.RoomManager mints a
# short public code instead (matches the client's 8-char join field).
GAME_ROOM_CODE_PATTERN = r"^[A-Z0-9]{4,16}$"

# Transport-layer field bounds for the game routes. Mirrors
# backend.lan_playground.game's own bounds exactly (PLAYER_NAME_MAX_CHARS,
# DESIRED_OUTCOME_MAX_CHARS, ROUGH_TEXT_MAX_CHARS, APPROVED_TEXT_MAX_CHARS,
# INTENT_MAX_CHARS, SUPPORT_DETAIL_MAX_CHARS, REACTION_DETAIL_MAX_CHARS) as
# of the engine's board task #1 handoff -- kept as local literals (not
# imported) so app.py can't fail to import on an engine constant rename;
# reconcile if game.py's bounds change.
PLAYER_NAME_MAX_CHARS = 40
MOVE_ID_MAX_CHARS = 64
TARGET_ID_MAX_CHARS = 64
DESIRED_OUTCOME_MAX_CHARS = 140
ASSIST_TYPE_MAX_CHARS = 32
REACTION_TYPE_MAX_CHARS = 32
CONTRIBUTION_TEXT_MAX_CHARS = 140
DRAFT_TEXT_MAX_CHARS = 280
FINAL_TEXT_MAX_CHARS = 280
INTENT_MAX_CHARS = 140
INTERPRETATION_TEXT_MAX_CHARS = 140


class RewriteRequest(BaseModel):
    persona: str = Field(..., min_length=1, max_length=PERSONA_NAME_MAX_CHARS)
    text: str = Field(..., min_length=1, max_length=TRANSCRIPT_MAX_CHARS)
    custom_instruction: str = Field("", max_length=CUSTOM_INSTRUCTION_MAX_CHARS)


class CreateRoomRequest(BaseModel):
    host_name: str = Field(..., min_length=1, max_length=PLAYER_NAME_MAX_CHARS)
    seed: int | None = None


class JoinRoomRequest(BaseModel):
    display_name: str = Field(..., min_length=1, max_length=PLAYER_NAME_MAX_CHARS)
    join_code: str = Field("", max_length=32)  # accepted for client symmetry; the path segment is authoritative


class SpotlightActionRequest(BaseModel):
    move_id: str = Field(..., min_length=1, max_length=MOVE_ID_MAX_CHARS)
    target_id: str = Field("", max_length=TARGET_ID_MAX_CHARS)
    desired_outcome: str = Field(..., min_length=1, max_length=DESIRED_OUTCOME_MAX_CHARS)


class SupportRequest(BaseModel):
    kind: str = Field(..., min_length=1, max_length=ASSIST_TYPE_MAX_CHARS)  # clue|item|assist|reaction
    detail: str = Field("", max_length=CONTRIBUTION_TEXT_MAX_CHARS)


class SubmitDraftRequest(BaseModel):
    rough_text: str = Field(..., min_length=1, max_length=DRAFT_TEXT_MAX_CHARS)
    intent_hint: str = Field("", max_length=INTENT_MAX_CHARS)
    persona: str = Field("", max_length=PERSONA_NAME_MAX_CHARS)


class ApproveMessageRequest(BaseModel):
    chosen_text: str = Field(..., min_length=1, max_length=FINAL_TEXT_MAX_CHARS)
    intent: str = Field(..., min_length=1, max_length=INTENT_MAX_CHARS)


class ReactRequest(BaseModel):
    verb: str = Field(..., min_length=1, max_length=REACTION_TYPE_MAX_CHARS)  # interpret|assist|challenge|protect
    detail: str = Field("", max_length=INTERPRETATION_TEXT_MAX_CHARS)
    move_id: str = Field("", max_length=MOVE_ID_MAX_CHARS)


class VoiceProfileRequest(BaseModel):
    utterance_count: int = Field(0, ge=0, le=9_999)
    confidence: float = Field(0.0, ge=0.0, le=1.0)
    calibrated: bool = False


_GAME_ERROR_STATUS = {
    "room_full": 409,
    "wrong_phase": 409,
    "not_host": 403,
    "wrong_turn": 403,
    "invalid_player_token": 401,
    "inactive_player": 409,
    "already_submitted": 409,
    "not_all_submitted": 409,
    "invalid_move": 422,
    "invalid_target": 422,
    "invalid_support_kind": 422,
    "invalid_reaction_verb": 422,
    "no_items_remaining": 409,
    "invalid_variants": 422,
    "engine_error": 500,
}


def _raise_for_engine_error(exc: game.GameError) -> None:
    code = rooms.translate_engine_error(exc)
    raise HTTPException(status_code=_GAME_ERROR_STATUS.get(code, 400), detail=code)


class _GenerationCancelled(Exception):
    pass


def _merge_persona_with_instruction(
    base_persona: Mapping[str, Any] | None, custom_instruction: str
) -> Mapping[str, Any] | None:
    """Append a bounded, clearly-subordinate style note to the persona prompt.

    The base persona's own preservation rules stay first in the system
    message, and the deterministic check_preservation() pass inside
    rescue_message runs on the model's output regardless of what this note
    says -- this composition cannot itself bypass that safety net.
    """
    if not custom_instruction:
        return base_persona
    base_prompt = ""
    if base_persona:
        base_prompt = base_persona.get("prompt") or base_persona.get("system_prompt") or ""
    merged_prompt = (
        f"{base_prompt}\n\n"
        "Additional user style request (tone/style only -- you must still follow "
        "every preservation rule above; never invent facts, numbers, names, dates, "
        "or commitments that are not present in the original message to satisfy "
        f"this request):\n{custom_instruction}"
    ).strip()
    merged = dict(base_persona) if base_persona else {}
    merged["prompt"] = merged_prompt
    return merged


def create_app(
    *,
    access_code: str,
    allowed_hosts: set[str],
    allowed_origins: set[str],
    call_fn: Callable[[list[dict[str, str]]], str],
    persona_lookup: Callable[[str], Mapping[str, Any] | None],
    persona_allowlist: Callable[[], list[str]],
    engine_ready_fn: Callable[[], bool] | None = None,
    clock: Callable[[], float] = time.monotonic,
    generate_timeout_s: float = DEFAULT_GENERATE_TIMEOUT_S,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN,
    static_dir: Path = STATIC_DIR,
    room_manager: "rooms.RoomManager | None" = None,
    variant_generator: "rooms.VariantGenerator | None" = None,
    narration_composer: "rooms.NarrationComposer | None" = None,
    draft_timeout_s: float = DEFAULT_DRAFT_TIMEOUT_S,
    narration_timeout_s: float = DEFAULT_NARRATION_TIMEOUT_S,
    room_create_rate_limit_per_min: int = DEFAULT_ROOM_CREATE_RATE_LIMIT_PER_MIN,
    room_join_rate_limit_per_min: int = DEFAULT_ROOM_JOIN_RATE_LIMIT_PER_MIN,
    room_state_rate_limit_per_min: int = DEFAULT_ROOM_STATE_RATE_LIMIT_PER_MIN,
    room_action_rate_limit_per_min: int = DEFAULT_ROOM_ACTION_RATE_LIMIT_PER_MIN,
    room_draft_rate_limit_per_min: int = DEFAULT_ROOM_DRAFT_RATE_LIMIT_PER_MIN,
) -> FastAPI:
    app = FastAPI(
        title="BetterFingers LAN Playground",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    _lock = threading.Lock()
    _cancel_events: dict[str, threading.Event] = {}
    _inflight = 0
    _rate_limiter = RateLimiter(max_requests=rate_limit_per_min, window_s=60.0)

    # --- The Lost Meaning room service (board task #2) ------------------------

    _room_manager = room_manager if room_manager is not None else rooms.RoomManager(clock=clock)
    _variant_generator = (
        variant_generator
        if variant_generator is not None
        else rooms.VariantGenerator(call_fn=call_fn, persona_lookup=persona_lookup, engine_ready_fn=engine_ready_fn)
    )
    _narration_composer = (
        narration_composer
        if narration_composer is not None
        else rooms.NarrationComposer(call_fn=call_fn, persona_lookup=persona_lookup, engine_ready_fn=engine_ready_fn)
    )
    _room_create_limiter = RateLimiter(max_requests=room_create_rate_limit_per_min, window_s=60.0)
    _room_join_limiter = RateLimiter(max_requests=room_join_rate_limit_per_min, window_s=60.0)
    _room_state_limiter = RateLimiter(max_requests=room_state_rate_limit_per_min, window_s=60.0)
    _room_action_limiter = RateLimiter(max_requests=room_action_rate_limit_per_min, window_s=60.0)
    _room_draft_limiter = RateLimiter(max_requests=room_draft_rate_limit_per_min, window_s=60.0)

    # --- cross-cutting request policy (Host/Origin allowlist + security headers) ---

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
            if request.url.path.startswith("/art/") and response.status_code == 200:
                # Art contains no room/access state and is immutable for the
                # lifetime of the process. Let phones cache these large local
                # files while all HTML/API responses remain fail-safe no-store.
                response.headers["Cache-Control"] = "public, max-age=3600"
            return response

    app.add_middleware(_PolicyMiddleware)

    def _client_key(request: Request) -> str:
        return request.client.host if request.client else "unknown"

    def _require_access_code(x_access_code: str = Header(default="")) -> None:
        if not constant_time_equals(x_access_code, access_code):
            raise HTTPException(status_code=401, detail="invalid_access_code")

    def _require_rate_limit(request: Request) -> None:
        if not _rate_limiter.allow(_client_key(request), now=clock()):
            raise HTTPException(status_code=429, detail="rate_limited")

    def _rate_limit_dep(limiter: RateLimiter):
        def _dep(request: Request) -> None:
            if not limiter.allow(_client_key(request), now=clock()):
                raise HTTPException(status_code=429, detail="rate_limited")

        return _dep

    _require_room_create_rate_limit = _rate_limit_dep(_room_create_limiter)
    _require_room_join_rate_limit = _rate_limit_dep(_room_join_limiter)
    _require_room_state_rate_limit = _rate_limit_dep(_room_state_limiter)
    _require_room_action_rate_limit = _rate_limit_dep(_room_action_limiter)
    _require_room_draft_rate_limit = _rate_limit_dep(_room_draft_limiter)

    def _get_room_or_404(room_id: str) -> "game.Room":
        try:
            return _room_manager.get_room(room_id)
        except rooms.RoomNotFoundError:
            raise HTTPException(status_code=404, detail="room_not_found")

    def _authenticate_player(
        code: str, room: "game.Room", x_host_token: str, x_player_token: str
    ) -> tuple[str, str]:
        token = x_host_token or x_player_token
        if not token:
            raise HTTPException(status_code=401, detail="invalid_player_token")
        player_id = _room_manager.player_id_for_token(code, token)
        if player_id is None or not room.verify_token(player_id, token):
            raise HTTPException(status_code=401, detail="invalid_player_token")
        return player_id, token

    def _build_join_url(request: Request, code: str) -> str:
        host_header = request.headers.get("host", "")
        scheme = request.url.scheme
        return f"{scheme}://{host_header}/?code={access_code}&room={code}"

    def _scene_hint(state: dict) -> str:
        """Best-effort prompt context for the draft-variant model call --
        never a security/visibility boundary (the engine's own
        public_state already filters everything secret before this
        function ever sees it), just flavor for BetterFingers to write
        with. Missing/renamed keys degrade to less context, never an
        error."""
        encounter = state.get("encounter") or {}
        parts = [p for p in (encounter.get("name"), encounter.get("flavor")) if p]
        return " -- ".join(parts)

    def _inject_narration(code: str, round_record: dict | None) -> dict | None:
        if not isinstance(round_record, dict) or round_record.get("narration"):
            return round_record  # already has one (e.g. the engine starts reading its own flavor overlay later) -- never overwrite
        round_key = round_record.get("round")
        narration = _room_manager.get_narration(code, round_key) if round_key is not None else None
        if narration is None:
            return round_record
        return {**round_record, "narration": narration}

    def _state_payload(room: "game.Room", code: str, viewer_player_id: str | None, request: Request) -> dict:
        # The engine's own public_state(viewer) does 100% of the
        # secrecy/visibility filtering (draft/support/reaction content,
        # private clues, etc.) -- this module only adds the join/QR fields
        # the engine has no concept of, plus the narration merge below
        # (game.py's set_flavor() overlay isn't read back into
        # round_record/history by the engine, only encounter-flavor keys
        # are -- see rooms.RoomManager narration cache).
        adapter = rooms.GameAdapter(room)
        state = adapter.public_state(viewer_player_id)
        state["room_id"] = code
        if state.get("phase") == "lobby":
            join_url = _build_join_url(request, code)
            state["join_code"] = code
            state["join_url"] = join_url
            state["join_qr_svg"] = render_qr_svg(join_url)
        state["last_round"] = _inject_narration(code, state.get("last_round"))
        history = state.get("history")
        if isinstance(history, list):
            state["history"] = [_inject_narration(code, rec) for rec in history]
        return state

    # --- static shell (fixed filenames only -- no directory listing/traversal) ---

    @app.get("/")
    async def index_route():
        return FileResponse(static_dir / "index.html", media_type="text/html")

    @app.get("/app.js")
    async def app_js_route():
        return FileResponse(static_dir / "app.js", media_type="application/javascript")

    @app.get("/style.css")
    async def style_css_route():
        return FileResponse(static_dir / "style.css", media_type="text/css")

    @app.get("/art/{asset_name}")
    async def art_route(asset_name: str = PathParam(..., pattern=r"^[a-z-]+\.png$")):
        # Fixed allowlist only: generated game art is served locally without
        # turning its source directory into a browsable/static mount.
        asset_path = ART_ASSETS.get(asset_name)
        if asset_path is None or not asset_path.is_file():
            raise HTTPException(status_code=404, detail="art_not_found")
        return FileResponse(asset_path, media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})

    @app.get("/api/health")
    async def health_route():
        return {"ok": True}

    # --- API surface (access-code gated) ---

    @app.get("/api/personas", dependencies=[Depends(_require_access_code)])
    async def personas_route():
        names = await asyncio.get_event_loop().run_in_executor(None, persona_allowlist)
        return {"personas": sorted(names)}

    @app.post(
        "/api/rewrite/{request_id}",
        dependencies=[Depends(_require_access_code), Depends(_require_rate_limit)],
    )
    async def rewrite_route(
        body: RewriteRequest,
        request_id: str = PathParam(..., pattern=REQUEST_ID_PATTERN),
    ):
        nonlocal _inflight
        with _lock:
            if _inflight >= max_concurrency:
                raise HTTPException(status_code=429, detail="too_many_concurrent_requests")
            _inflight += 1
            cancel_event = threading.Event()
            _cancel_events[request_id] = cancel_event

        try:
            if engine_ready_fn is not None:
                ready = await asyncio.get_event_loop().run_in_executor(None, engine_ready_fn)
                if not ready:
                    return {
                        "id": request_id,
                        "status": "model_unavailable",
                        "raw": body.text,
                        "variants": {"faithful": body.text, "clearer": "", "alternate": ""},
                        "preservation_checks": [],
                        "warnings": ["local_model_not_running"],
                    }

            allowlisted = await asyncio.get_event_loop().run_in_executor(None, persona_allowlist)
            if body.persona not in allowlisted:
                raise HTTPException(status_code=422, detail="persona_not_allowed")

            base_persona = await asyncio.get_event_loop().run_in_executor(None, persona_lookup, body.persona)
            custom_instruction = sanitize_custom_instruction(body.custom_instruction, CUSTOM_INSTRUCTION_MAX_CHARS)
            persona_obj = _merge_persona_with_instruction(base_persona, custom_instruction)

            def guarded_call_fn(messages: list[dict[str, str]]) -> str:
                if cancel_event.is_set():
                    raise _GenerationCancelled("cancelled before model call")
                return call_fn(messages)

            timed_out = False
            result = None
            try:
                result = await asyncio.wait_for(
                    asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: rescue_message(
                            body.text,
                            None,
                            context_text=None,
                            persona=persona_obj,
                            examples=None,
                            call_fn=guarded_call_fn,
                        ),
                    ),
                    timeout=generate_timeout_s,
                )
            except asyncio.TimeoutError:
                timed_out = True
            finally:
                with _lock:
                    cancelled = cancel_event.is_set()
                    _cancel_events.pop(request_id, None)

            if cancelled:
                return {"id": request_id, "status": "cancelled", "raw": body.text}
            if timed_out:
                return {"id": request_id, "status": "timeout", "raw": body.text}
            payload = to_dict(result)
            payload["id"] = request_id
            payload["status"] = "done"
            payload["raw"] = body.text
            return payload
        finally:
            with _lock:
                _inflight -= 1

    @app.post("/api/rewrite/{request_id}/cancel", dependencies=[Depends(_require_access_code)])
    async def cancel_route(request_id: str = PathParam(..., pattern=REQUEST_ID_PATTERN)):
        with _lock:
            event = _cancel_events.get(request_id)
        if event is None:
            raise HTTPException(status_code=404, detail="unknown_or_finished_request")
        event.set()
        return {"id": request_id, "status": "cancel_requested"}

    # --- The Lost Meaning room API (board task #2) -----------------------------
    # Every route below is additionally gated by the same site-wide
    # X-Access-Code + Host/Origin policy every other route in this app uses
    # (see _PolicyMiddleware/_require_access_code above) -- room/player
    # tokens are a *second*, per-room layer on top, not a replacement.

    @app.post(
        "/api/game/rooms",
        status_code=201,
        dependencies=[Depends(_require_access_code), Depends(_require_room_create_rate_limit)],
    )
    async def create_room_route(body: CreateRoomRequest, request: Request):
        try:
            code, room, host_id, host_token = _room_manager.create_room(host_name=body.host_name, seed=body.seed)
        except rooms.TooManyRoomsError:
            raise HTTPException(status_code=503, detail="too_many_rooms")
        join_url = _build_join_url(request, code)
        return JSONResponse(
            status_code=201,
            content={
                "room_id": code,
                "host_token": host_token,
                "player_id": host_id,
                "join_code": code,
                "join_url": join_url,
                "join_qr_svg": render_qr_svg(join_url),
                "state": _state_payload(room, code, host_id, request),
            },
        )

    @app.post(
        "/api/game/rooms/{room_id}/join",
        dependencies=[Depends(_require_access_code), Depends(_require_room_join_rate_limit)],
    )
    async def join_room_route(
        body: JoinRoomRequest, request: Request, room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN)
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        try:
            player_id, token = adapter.join(body.display_name)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.record_token(room_id, player_id, token)
        _room_manager.touch(room_id)
        join_url = _build_join_url(request, room_id)
        return {
            "room_id": room_id,
            "player_token": token,
            "player_id": player_id,
            "join_code": room_id,
            "join_url": join_url,
            "join_qr_svg": render_qr_svg(join_url),
            "state": _state_payload(room, room_id, player_id, request),
        }

    @app.get(
        "/api/game/rooms/{room_id}/state",
        dependencies=[Depends(_require_access_code), Depends(_require_room_state_rate_limit)],
    )
    async def room_state_route(
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        player_id, _token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        _room_manager.touch(room_id)
        return _state_payload(room, room_id, player_id, request)

    @app.post(
        "/api/game/rooms/{room_id}/start",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def start_room_route(
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.start(player_id, token)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return _state_payload(room, room_id, player_id, request)

    @app.post(
        "/api/game/rooms/{room_id}/spotlight",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def spotlight_action_route(
        body: SpotlightActionRequest,
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.submit_spotlight_action(player_id, token, body.move_id, body.target_id, body.desired_outcome)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/support",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def support_route(
        body: SupportRequest,
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.submit_support(player_id, token, body.kind, body.detail)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/open-draft",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def open_draft_route(
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.open_draft(player_id, token)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/draft",
        dependencies=[Depends(_require_access_code), Depends(_require_room_draft_rate_limit)],
    )
    async def draft_route(
        body: SubmitDraftRequest,
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        # submit_rough_text is spotlight-only/phase-gated by the engine
        # itself (WrongTurnError/InvalidPhaseError) -- calling it first
        # means a non-spotlight or off-phase caller is rejected *before*
        # this route ever spends a model call on their behalf.
        try:
            adapter.submit_rough_text(player_id, token, body.rough_text)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        scene = _scene_hint(adapter.public_state(player_id))
        # Runs the model call on its own daemon thread (VariantGenerator.start)
        # rather than asyncio.wait_for(loop.run_in_executor(...)) -- the
        # latter's timeout only stops the *awaiting* coroutine, not the
        # executor thread, and both asyncio.run() (TestClient) and a real
        # loop's shutdown_default_executor() block until every outstanding
        # executor future finishes, silently turning the timeout unbounded.
        # event.wait(timeout) is itself bounded, so waiting on *that* in the
        # executor is safe.
        event, box = _variant_generator.start(
            rough_text=body.rough_text,
            scene=scene,
            intent_hint=body.intent_hint,
            persona_name=body.persona or None,
        )
        await asyncio.get_event_loop().run_in_executor(None, event.wait, draft_timeout_s)
        variants = box["variants"]
        # Model unavailable/errored/timed out -> 3 identical copies of the
        # hero's own raw text, mirroring the engine's own deterministic
        # companion fallback so "model offline" is always fully playable.
        variants = variants or [body.rough_text, body.rough_text, body.rough_text]
        try:
            adapter.submit_variants(player_id, token, variants)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/approve",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def approve_route(
        body: ApproveMessageRequest,
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.approve_message(player_id, token, body.chosen_text, body.intent)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/react",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def react_route(
        body: ReactRequest,
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.submit_reaction(player_id, token, body.verb, body.detail, move_id=body.move_id or None)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/voice-profile",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def voice_profile_route(
        body: VoiceProfileRequest,
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        metadata = {
            "utterance_count": body.utterance_count,
            "confidence": body.confidence,
            "calibrated": body.calibrated,
        }
        try:
            adapter.update_voice_profile(player_id, token, metadata)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/resolve",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def resolve_route(
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            round_record = adapter.resolve(player_id, token)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        # See draft_route's comment: bounded via a daemon thread + a
        # self-bounded Event.wait, not asyncio.wait_for(run_in_executor(...)).
        event, box = _narration_composer.start(round_record=round_record)
        await asyncio.get_event_loop().run_in_executor(None, event.wait, narration_timeout_s)
        narration = box["narration"] if box["narration"] is not None else _narration_composer.fallback(round_record)
        round_key = round_record.get("round")
        if round_key is not None:
            # set_flavor() is the engine-documented overlay call (kept in
            # case a future engine revision reads it back into
            # round_record); RoomManager's narration cache is what
            # _state_payload actually merges into last_round/history today
            # -- see _inject_narration.
            adapter.set_flavor(f"narration:{round_key}", narration)
            _room_manager.set_narration(room_id, round_key, narration)
        _room_manager.touch(room_id)
        return {"state": _state_payload(room, room_id, player_id, request)}

    @app.post(
        "/api/game/rooms/{room_id}/advance",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def advance_room_route(
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.advance(player_id, token)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return _state_payload(room, room_id, player_id, request)

    @app.post(
        "/api/game/rooms/{room_id}/replay",
        dependencies=[Depends(_require_access_code), Depends(_require_room_action_rate_limit)],
    )
    async def replay_room_route(
        request: Request,
        room_id: str = PathParam(..., pattern=GAME_ROOM_CODE_PATTERN),
        x_host_token: str = Header(default=""),
        x_player_token: str = Header(default=""),
    ):
        room = _get_room_or_404(room_id)
        adapter = rooms.GameAdapter(room)
        player_id, token = _authenticate_player(room_id, room, x_host_token, x_player_token)
        try:
            adapter.replay(player_id, token)
        except game.GameError as exc:
            _raise_for_engine_error(exc)
        _room_manager.touch(room_id)
        return _state_payload(room, room_id, player_id, request)

    return app


# --- Default production wiring -------------------------------------------------
# Mirrors backend/api/routes/message_rescue.py: `import server` and the
# backend services happen only inside these closures, at call time, so
# importing backend.lan_playground.app never pulls in server.py's startup
# surface (Whisper/TTS/model manager). Used only by tools/lan_playground.py.


def _default_engine_ready() -> bool:
    try:
        import server

        engine = server.get_selected_llm_engine()
        if engine is None:
            return False
        return bool(engine.ensure_ready())
    except Exception:
        return False


def _build_default_call_fn(max_output_tokens: int) -> Callable[[list[dict[str, str]]], str]:
    def call_fn(messages: list[dict[str, str]]) -> str:
        import server
        from backend.services.rescue_llm_adapter import build_llm_call_fn

        engine = server.get_selected_llm_engine()
        adapter = build_llm_call_fn(engine, max_output_tokens=max_output_tokens)
        return adapter(messages)

    return call_fn


def _default_persona_lookup(name: str) -> Mapping[str, Any] | None:
    from backend.services import personas as persona_service

    return persona_service.get_persona(name)


def _default_persona_allowlist() -> list[str]:
    from backend.services import personas as persona_service

    # Only built-in personas are exposed to LAN guests -- a user's own
    # custom-authored personas may contain private wording and are not
    # implicitly consented to be shown to friends on the network.
    return list(persona_service.list_builtin_persona_names())


def build_default_app(
    *,
    access_code: str,
    allowed_hosts: set[str],
    allowed_origins: set[str],
    generate_timeout_s: float = DEFAULT_GENERATE_TIMEOUT_S,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    max_concurrency: int = DEFAULT_MAX_CONCURRENCY,
    rate_limit_per_min: int = DEFAULT_RATE_LIMIT_PER_MIN,
) -> FastAPI:
    return create_app(
        access_code=access_code,
        allowed_hosts=allowed_hosts,
        allowed_origins=allowed_origins,
        call_fn=_build_default_call_fn(max_output_tokens),
        persona_lookup=_default_persona_lookup,
        persona_allowlist=_default_persona_allowlist,
        engine_ready_fn=_default_engine_ready,
        generate_timeout_s=generate_timeout_s,
        max_concurrency=max_concurrency,
        rate_limit_per_min=rate_limit_per_min,
    )
