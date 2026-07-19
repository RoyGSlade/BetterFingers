"""HTTP-facing room lifecycle wrapper around the Spellcheck & Sorcery engine.

Board task #40. Wraps ``backend.lan_playground.game`` (``GameRegistry``/
``Room``, owned by board task #39 -- see docs/LAN_GAME_SPEC.md) with the
parts the HTTP transport layer needs that the pure engine deliberately does
not do itself: idle-room expiry/pruning (the engine has no concept of wall
clock TTL), and best-effort background text "polish" of a submitted move
via the existing persona/LLM call_fn plumbing, applied through the engine's
own ``set_flavor()`` cosmetic overlay -- never by mutating ``approach`` or
``move_text`` directly.

Identity and auth are entirely the engine's: ``Room.join()``/
``GameRegistry.create_room()`` mint the one real ``(player_id, token)``
pair per player; this module never mints a second, competing token for a
*player*. Every mutating call still requires the caller's own
``(player_id, token)`` -- with one documented exception: this module
retains the host's own credentials server-side (never exposed on the wire
past the initial create-room response) solely so the transport layer can
auto-advance ``choosing -> reveal`` the instant every active player has
submitted, without requiring a client-side "resolve" button that nobody
asked for. See ``RoomManager.host_credentials``.

The public, wire-visible room id is a short human-typeable code minted by
this module (``generate_room_code``, matching the client's 8-char join
field) -- game.py's own long ``room_<token>`` id never appears on the wire,
only as this module's internal lookup key.

Nothing here ever logs or persists move/room content.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from backend.lan_playground import game
from backend.lan_playground.security import constant_time_equals, generate_room_code

DEFAULT_ROOM_TTL_S = 45 * 60.0
DEFAULT_MAX_ROOMS = 25
PUBLIC_CODE_LENGTH = 8


class RoomNotFoundError(Exception):
    """Room id doesn't exist or was pruned. Not a game.GameError -- this is
    purely an HTTP-layer routing concern (game.py has no room-lookup API of
    its own to fail; GameRegistry.get() just returns None)."""

    code = "room_not_found"


class TooManyRoomsError(Exception):
    code = "too_many_rooms"


# Fixed, enumerable HTTP error codes for every game.GameError subclass.
# Kept here (not in game.py) so the pure engine never has to know about
# HTTP status codes or wire-format concerns.
_ENGINE_ERROR_CODES: Mapping[type, str] = {
    game.RoomFullError: "room_full",
    game.InvalidPhaseError: "wrong_phase",
    game.NotHostError: "not_host",
    game.UnknownPlayerError: "invalid_player_token",
    game.InvalidTokenError: "invalid_player_token",
    game.InactivePlayerError: "inactive_player",
    game.AlreadySubmittedError: "already_submitted",
    game.NotAllSubmittedError: "not_all_submitted",
    game.InvalidApproachError: "invalid_approach",
}


def translate_engine_error(exc: Exception) -> str:
    for exc_type, code in _ENGINE_ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "engine_error"


class RoomManager:
    """Owns room *lifecycle* (creation, lookup by short public code,
    idle-expiry) on top of a ``game.GameRegistry``. Does not duplicate any
    identity/auth/game-state concern the engine already owns, except for a
    server-internal token cache used only to drive auto-resolve (see
    ``host_credentials``) -- never returned from any public/HTTP-facing
    method other than the original join/create response to that same
    caller.
    """

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        ttl_s: float = DEFAULT_ROOM_TTL_S,
        max_rooms: int = DEFAULT_MAX_ROOMS,
        registry: "game.GameRegistry | None" = None,
        public_code_length: int = PUBLIC_CODE_LENGTH,
    ):
        self._clock = clock
        self._ttl_s = ttl_s
        self._max_rooms = max_rooms
        self._public_code_length = public_code_length
        # game.GameRegistry itself takes a clock for Room.created_at, but
        # that's a *separate* concept from this module's idle-TTL pruning,
        # so it isn't shared here -- game.py's own clock stays time.time by
        # default unless the caller wires a matching one in explicitly.
        self._registry = registry if registry is not None else game.GameRegistry()
        self._rooms_by_code: dict[str, game.Room] = {}
        self._last_activity: dict[str, float] = {}
        # code -> {player_id: token}, used only by host_credentials() below.
        self._tokens: dict[str, dict[str, str]] = {}
        self._lock = threading.Lock()

    def create_room(self, *, host_name: str, seed: int | None = None) -> tuple[str, game.Room, str, str]:
        """Returns (public_code, room, host_player_id, host_token)."""
        with self._lock:
            self._prune_locked()
            if len(self._rooms_by_code) >= self._max_rooms:
                raise TooManyRoomsError("too_many_rooms")
            room, host_id, host_token = self._registry.create_room(host_name, seed=seed)
            code = self._fresh_code_locked()
            self._rooms_by_code[code] = room
            self._last_activity[code] = self._clock()
            self._tokens[code] = {host_id: host_token}
            return code, room, host_id, host_token

    def get_room(self, code: str) -> game.Room:
        with self._lock:
            self._prune_locked()
            room = self._rooms_by_code.get(code)
        if room is None:
            raise RoomNotFoundError("room_not_found")
        return room

    def record_token(self, code: str, player_id: str, token: str) -> None:
        """Called by the transport layer right after a successful
        ``room.join()`` so ``host_credentials`` stays correct even across
        host succession (the new host is someone who already joined earlier
        under a different token this module must already know)."""
        with self._lock:
            if code in self._tokens:
                self._tokens[code][player_id] = token

    def player_id_for_token(self, code: str, token: str) -> str | None:
        """Reverse lookup used by the transport layer: the client sends only
        a token header (no player_id), so this identifies which player_id
        it claims to be. Every candidate is compared with
        ``constant_time_equals`` (never a bare ``==``/dict-membership
        shortcut on the token itself) -- the room has at most 4 players, so
        this stays O(1)-in-practice while keeping the same timing-safe
        comparison as everywhere else in this package. Callers must still
        treat this as identification only, not authentication on its own --
        route handlers additionally call ``room.verify_token`` (the
        engine's own authority) before trusting the result.
        """
        if not token:
            return None
        with self._lock:
            candidates = list(self._tokens.get(code, {}).items())
        for player_id, candidate_token in candidates:
            if constant_time_equals(token, candidate_token):
                return player_id
        return None

    def host_credentials(self, code: str, room: game.Room) -> tuple[str, str] | None:
        """Best-effort: returns (host_id, host_token) for the room's
        *current* host, or None if this module never saw that player's
        token (should not happen in normal operation, but auto-resolve is
        an optimization, not a correctness requirement -- callers must
        treat None as "skip auto-resolve this cycle", never as an error).
        """
        host_id = room.host_id
        if host_id is None:
            return None
        with self._lock:
            token = self._tokens.get(code, {}).get(host_id)
        return (host_id, token) if token is not None else None

    def touch(self, code: str) -> None:
        with self._lock:
            if code in self._last_activity:
                self._last_activity[code] = self._clock()

    def prune_stale(self) -> list[str]:
        with self._lock:
            return self._prune_locked()

    def room_count(self) -> int:
        return len(self._rooms_by_code)

    def _fresh_code_locked(self) -> str:
        for _ in range(20):
            candidate = generate_room_code(self._public_code_length)
            if candidate not in self._rooms_by_code:
                return candidate
        raise TooManyRoomsError("too_many_rooms")  # astronomically unlikely

    def _prune_locked(self) -> list[str]:
        now = self._clock()
        stale = [code for code, last in self._last_activity.items() if now - last > self._ttl_s]
        for code in stale:
            room = self._rooms_by_code.pop(code, None)
            if room is not None:
                self._registry.remove(room.room_id)
            self._last_activity.pop(code, None)
            self._tokens.pop(code, None)
        return stale


# --- Move text polishing (BetterFingers rewrite integration) -------------------


class MovePolisher:
    """Fire-and-forget background refinement of a submitted move's text.

    ``start`` never blocks the caller (it launches a daemon thread and
    returns immediately -- the submit-move HTTP response does not wait on
    the model). ``resolve`` is used only when a round is actually about to
    be revealed: it waits up to whatever time budget remains from a fixed
    per-job timeout, then returns ``None`` if the model is unavailable,
    errors, produced nothing usable, or simply hasn't finished yet --
    never raises. The caller (app.py) only calls
    ``room.set_flavor(...)`` when this returns non-None; when it returns
    None, game.py's own default (the player's original raw move_text) is
    what reveals, so "model offline" and "model never asked" produce an
    identical, correct result with zero extra code on this module's part.
    """

    def __init__(
        self,
        *,
        call_fn: Callable[[list[dict[str, str]]], str] | None,
        persona_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
        engine_ready_fn: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        timeout_s: float = 12.0,
        max_output_chars: int = game.MOVE_TEXT_MAX_CHARS,
    ):
        self._call_fn = call_fn
        self._persona_lookup = persona_lookup
        self._engine_ready_fn = engine_ready_fn
        self._clock = clock
        self._timeout_s = timeout_s
        self._max_output_chars = max_output_chars
        self._lock = threading.Lock()
        self._jobs: dict[tuple, dict[str, Any]] = {}

    def start(self, key: tuple, *, persona: str | None, approach: str, move_text: str) -> None:
        if self._call_fn is None:
            return
        event = threading.Event()
        job = {"event": event, "result": None, "started_at": self._clock()}
        with self._lock:
            self._jobs[key] = job

        def _run() -> None:
            try:
                if self._engine_ready_fn is not None and not self._engine_ready_fn():
                    return
                persona_obj = self._persona_lookup(persona) if (self._persona_lookup and persona) else None
                messages = _build_polish_messages(persona_obj, approach, move_text)
                raw = self._call_fn(messages)
                polished = _clean_polish_output(raw, self._max_output_chars)
                if polished:
                    job["result"] = polished
            except Exception:
                pass  # None result -> caller falls back to game.py's own raw move_text
            finally:
                event.set()

        threading.Thread(target=_run, daemon=True).start()

    def resolve(self, key: tuple) -> str | None:
        with self._lock:
            job = self._jobs.pop(key, None)
        if job is None:
            return None
        elapsed = self._clock() - job["started_at"]
        remaining = max(0.0, self._timeout_s - elapsed)
        job["event"].wait(timeout=remaining)
        return job["result"]

    def resolve_many(self, keys: list[tuple]) -> dict[tuple, str | None]:
        """Like ``resolve`` for several keys, but waits on all of them
        concurrently so the total wall time is bounded by the single
        slowest job, not the sum -- used when a round auto-resolves and
        every active player's move might still have a polish job pending.
        """
        results: dict[tuple, str | None] = {}
        results_lock = threading.Lock()

        def _run(k: tuple) -> None:
            text = self.resolve(k)
            with results_lock:
                results[k] = text

        threads = [threading.Thread(target=_run, args=(k,), daemon=True) for k in keys]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        return results

    def discard(self, key: tuple) -> None:
        with self._lock:
            self._jobs.pop(key, None)


def _build_polish_messages(persona_obj: Mapping[str, Any] | None, approach: str, move_text: str) -> list[dict[str, str]]:
    persona_prompt = ""
    if persona_obj:
        persona_prompt = persona_obj.get("prompt") or persona_obj.get("system_prompt") or ""
    system = (
        f"{persona_prompt}\n\n" if persona_prompt else ""
    ) + (
        "You are narrating one player's turn in a silly, family-friendly party "
        "game. Rewrite their move as ONE short, funny in-character line "
        f"(under {game.MOVE_TEXT_MAX_CHARS} characters). The move's approach is "
        f"'{approach}'. Keep the player's original intent; do not invent new "
        "game outcomes, scores, damage, or facts -- you are only adding flavor "
        "to how it reads, never deciding what happens (that is fixed already, "
        "from the approach alone). Reply with the line only, no quotes, no "
        "preamble."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": move_text},
    ]


def _clean_polish_output(raw: str, max_chars: int) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = "".join(ch for ch in raw if ch in "\n\t" or (ch.isprintable() and ch != "\r"))
    cleaned = " ".join(cleaned.split()).strip().strip('"').strip()
    return cleaned[:max_chars]
