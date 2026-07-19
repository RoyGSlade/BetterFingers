"""HTTP-facing room lifecycle wrapper around The Lost Meaning engine.

Board task #2 (LAN transport + BetterFingers orchestration), layered on
``backend.lan_playground.game`` (``GameRegistry``/``Room``, owned by board
task #1 -- see docs/LAN_GAME_SPEC.md once published). This module owns the
parts the HTTP transport layer needs that the pure engine deliberately does
not do itself:

- idle-room expiry/pruning (the engine has no concept of wall clock TTL)
- minting/serving a short public room code so the engine's own long
  ``room_<token>`` id never appears on the wire
- generating the three visible BetterFingers rewrite variants for a
  Spotlight hero's rough draft (``VariantGenerator``), and composing
  cosmetic, facts-only narration after a round resolves
  (``NarrationComposer``)
- a thin, isolated ``GameAdapter`` between every route in app.py and the
  engine's actual method names -- board task #1 (the engine) is landing in
  parallel, so every call from app.py goes through here, never directly to
  a ``game.Room`` instance, and the reconciliation surface stays exactly
  this one class.

Identity and auth remain entirely the engine's: ``Room.join()`` mints the
one real ``(player_id, token)`` pair per player; this module never mints a
second, competing token for a *player*. Every mutating call still requires
the caller's own ``(player_id, token)``.

Per the engine's published contract (board task #1), the engine itself now
owns rough_text/variants/approved_text/intent state and their viewer-aware
visibility (nothing is secret-until-approved on the *transport* side
anymore -- ``submit_rough_text``/``submit_variants``/``approve_message`` are
all engine calls, and ``public_state(viewer)`` is trusted to filter them).
This module's job is only to *generate* the three BetterFingers variants
(``VariantGenerator``) and the post-resolve cosmetic narration
(``NarrationComposer``) and hand the results to the engine -- never to cache
or gate their visibility itself. "Model calls are cosmetic and cannot
produce outcome facts" holds because ``resolve()`` only ever reads the
structured move/target/outcome/support/reaction facts recorded before
drafting starts, never the free text this module generates.

Nothing here ever logs or persists move/room/draft/narration/voice content.
"""

from __future__ import annotations

import threading
import time
from typing import Any, Callable, Mapping

from backend.lan_playground import game
from backend.lan_playground.security import constant_time_equals, generate_room_code
from backend.services.message_rescue import rescue_message

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


# Fixed, enumerable HTTP error codes for every game.GameError subclass,
# matching lost-meaning-engine's published exception set exactly (see
# collab room history / docs/LAN_GAME_SPEC.md once published). Kept here
# (not in game.py) so the pure engine never has to know about HTTP status
# codes or wire-format concerns. Built defensively via getattr so this
# module never fails to import if an exception class briefly doesn't exist
# yet -- unmatched GameError subclasses translate to the generic
# "engine_error" code (see translate_engine_error) rather than crashing
# this module at import time.
_ENGINE_ERROR_ATTR_CODES: tuple[tuple[str, str], ...] = (
    ("RoomFullError", "room_full"),
    ("InvalidPhaseError", "wrong_phase"),
    ("NotHostError", "not_host"),
    ("WrongTurnError", "wrong_turn"),
    ("UnknownPlayerError", "invalid_player_token"),
    ("InvalidTokenError", "invalid_player_token"),
    ("InactivePlayerError", "inactive_player"),
    ("AlreadySubmittedError", "already_submitted"),
    ("NotAllSubmittedError", "not_all_submitted"),
    ("InvalidMoveError", "invalid_move"),
    ("InvalidTargetError", "invalid_target"),
    ("InvalidSupportKindError", "invalid_support_kind"),
    ("InvalidReactionVerbError", "invalid_reaction_verb"),
    ("NoItemsRemainingError", "no_items_remaining"),
    ("InvalidVariantsError", "invalid_variants"),
)


def _build_engine_error_codes() -> dict[type, str]:
    codes: dict[type, str] = {}
    for attr, code in _ENGINE_ERROR_ATTR_CODES:
        exc_type = getattr(game, attr, None)
        if isinstance(exc_type, type):
            codes[exc_type] = code
    return codes


_ENGINE_ERROR_CODES: Mapping[type, str] = _build_engine_error_codes()


def translate_engine_error(exc: Exception) -> str:
    for exc_type, code in _ENGINE_ERROR_CODES.items():
        if isinstance(exc, exc_type):
            return code
    return "engine_error"


class RoomManager:
    """Owns room *lifecycle* (creation, lookup by short public code,
    idle-expiry) on top of a ``game.GameRegistry``. Does not duplicate any
    identity/auth/game-state concern the engine already owns -- draft/
    variant/narration content now lives entirely in the engine (see module
    docstring), so this class has no scratch caches of its own.
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
        # code -> {player_id: token}, used only by player_id_for_token().
        self._tokens: dict[str, dict[str, str]] = {}
        # code -> {round_index: narration_text}. The engine's set_flavor()
        # overlay is not read back into round_record/history by the current
        # engine (only encounter-flavor keys are), so narration is kept
        # here and merged into last_round/history by app.py's
        # _state_payload -- a shallow, read-only merge that never mutates
        # the engine's own round_record objects.
        self._narrations: dict[str, dict[int, str]] = {}
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
        ``room.join()`` so every player's token is identifiable via
        ``player_id_for_token`` regardless of join order or host
        succession."""
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

    def touch(self, code: str) -> None:
        with self._lock:
            if code in self._last_activity:
                self._last_activity[code] = self._clock()

    def prune_stale(self) -> list[str]:
        with self._lock:
            return self._prune_locked()

    def room_count(self) -> int:
        return len(self._rooms_by_code)

    # -- narration cache (cosmetic-only, keyed off the resolved round) ------

    def set_narration(self, code: str, round_index: int, text: str) -> None:
        with self._lock:
            self._narrations.setdefault(code, {})[round_index] = text

    def get_narration(self, code: str, round_index: int) -> str | None:
        with self._lock:
            return self._narrations.get(code, {}).get(round_index)

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
            self._narrations.pop(code, None)
        return stale


# --- BetterFingers orchestration (draft variants + facts-only narration) ------


def _clean_text(raw: str, max_chars: int) -> str:
    if not isinstance(raw, str):
        return ""
    cleaned = "".join(ch for ch in raw if ch in "\n\t" or (ch.isprintable() and ch != "\r"))
    cleaned = " ".join(cleaned.split()).strip().strip('"').strip()
    return cleaned[:max_chars]


def _compose_scene_context(scene: str, intent_hint: str) -> str | None:
    parts = []
    if scene:
        parts.append(f"Scene: {scene}")
    if intent_hint:
        parts.append(f"Hero's stated intent for this line: {intent_hint}")
    return "\n".join(parts) if parts else None


class VariantGenerator:
    """Turns a Spotlight hero's rough draft into exactly three visible
    BetterFingers variants via a single ``rescue_message()`` call (its
    ``variants`` dict is already faithful/clearer/alternate -- no need to
    call the model three times), returned as a plain ``list[str]`` of
    length exactly 3 -- the shape ``Room.submit_variants(player_id, token,
    variants)`` requires.

    Purely cosmetic and best-effort: the engine's ``resolve()`` never reads
    any of this text, only the structured move/target/outcome and
    support/reaction facts chosen through the room's own action calls
    before drafting ever starts. If the model is unavailable, errored, or a
    given variant was dropped (e.g. by the preservation safety net inside
    ``rescue_message``), that slot falls back to the hero's own raw
    rough_text -- and if the whole call fails, ``generate`` returns
    ``None`` so the caller can submit 3 identical copies of rough_text,
    exactly mirroring the engine's own deterministic companion fallback.
    """

    def __init__(
        self,
        *,
        call_fn: Callable[[list[dict[str, str]]], str] | None,
        persona_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
        engine_ready_fn: Callable[[], bool] | None = None,
        max_chars: int = 280,
    ):
        self._call_fn = call_fn
        self._persona_lookup = persona_lookup
        self._engine_ready_fn = engine_ready_fn
        self._max_chars = max_chars

    def available(self) -> bool:
        if self._call_fn is None:
            return False
        if self._engine_ready_fn is not None and not self._engine_ready_fn():
            return False
        return True

    def start(
        self, *, rough_text: str, scene: str = "", intent_hint: str = "", persona_name: str | None = None
    ) -> tuple[threading.Event, dict[str, Any]]:
        """Launches the (possibly slow) model call on a plain daemon
        thread -- never an event-loop executor -- and returns immediately
        with an Event the caller can bound-wait on and a result box.

        This deliberately avoids ``asyncio.wait_for(loop.run_in_executor(...))``:
        that pattern's timeout only stops the *awaiting* coroutine, not the
        underlying executor thread, and both ``asyncio.run()`` (used by
        FastAPI's TestClient per call) and a real event loop's own shutdown
        call ``loop.shutdown_default_executor()``, which blocks until every
        outstanding executor future actually finishes -- silently turning a
        supposedly-bounded timeout into an unbounded wait for the model
        call's real duration. A daemon thread outside the executor has no
        such handshake: the caller's bounded wait (see ``resolve``) always
        returns on time regardless of whether the model call itself ever
        finishes.
        """
        event = threading.Event()
        box: dict[str, Any] = {"variants": None}
        if not self.available():
            event.set()
            return event, box

        def _run() -> None:
            try:
                box["variants"] = self._generate_sync(
                    rough_text=rough_text, scene=scene, intent_hint=intent_hint, persona_name=persona_name
                )
            except Exception:
                pass  # box["variants"] stays None -> caller falls back
            finally:
                event.set()

        threading.Thread(target=_run, daemon=True).start()
        return event, box

    def generate(
        self, *, rough_text: str, scene: str = "", intent_hint: str = "", persona_name: str | None = None
    ) -> list[str] | None:
        """Synchronous convenience wrapper (used directly by tests/simple
        callers). Route handlers that need a bounded wall-clock bound
        should use ``start`` + a bounded ``Event.wait`` instead -- see
        module docstring on ``start``."""
        return self._generate_sync(
            rough_text=rough_text, scene=scene, intent_hint=intent_hint, persona_name=persona_name
        )

    def _generate_sync(
        self, *, rough_text: str, scene: str = "", intent_hint: str = "", persona_name: str | None = None
    ) -> list[str] | None:
        if not self.available():
            return None
        persona_obj = self._persona_lookup(persona_name) if (self._persona_lookup and persona_name) else None
        context_text = _compose_scene_context(scene, intent_hint)
        try:
            result = rescue_message(
                rough_text,
                None,
                context_text=context_text,
                persona=persona_obj,
                call_fn=self._call_fn,
            )
        except Exception:
            return None
        variants: list[str] = []
        for provenance in ("faithful", "clearer", "alternate"):
            text = _clean_text((result.variants or {}).get(provenance, ""), self._max_chars)
            variants.append(text or rough_text)
        return variants


def _facts_only_context(round_record: Mapping[str, Any]) -> str:
    """Render only the already-decided facts from a round_record as plain
    text -- deliberately excludes the hero's free-text approved message, so
    a narration model call can add color but has nothing beyond fixed
    game-state facts to build a sentence from; ``check_preservation`` inside
    rescue_message isn't in play here since narration doesn't go through
    rescue_message, so this function is the only thing standing between
    "cosmetic" and "could fabricate a new fact" -- keep it to the engine's
    fixed round_record shape only (round/encounter/action/true_target_id/
    revealed_clues/modifiers/die_roll/score/damage/hearts_before/after).
    """
    lines: list[str] = []
    encounter = round_record.get("encounter") or {}
    if encounter.get("name"):
        lines.append(f"encounter: {encounter['name']}")
    action = round_record.get("action") or {}
    for key in ("move", "move_id", "target_id", "desired_outcome"):
        if action.get(key):
            lines.append(f"{key}: {action[key]}")
    if round_record.get("true_target_id"):
        lines.append(f"true_target_id: {round_record['true_target_id']}")
    if round_record.get("revealed_clues"):
        lines.append(f"revealed_clues: {round_record['revealed_clues']}")
    for mod in round_record.get("modifiers") or []:
        label = mod.get("label") or mod.get("source")
        if label:
            value = mod.get("value")
            lines.append(f"modifier: {label} ({value:+}, affects {mod.get('affects', '?')})" if value is not None else f"modifier: {label}")
    for key in ("die_roll", "score", "damage", "hearts_before", "hearts_after"):
        if round_record.get(key) is not None:
            lines.append(f"{key}: {round_record[key]}")
    return "\n".join(lines)


def _deterministic_narration(round_record: Mapping[str, Any]) -> str:
    """Zero-model, template-only fallback so the game is fully playable with
    the local model completely offline -- built strictly from the same
    fixed facts a model-backed narration would be allowed to see."""
    encounter = round_record.get("encounter") or {}
    action = round_record.get("action") or {}
    move = action.get("move") or action.get("move_id") or "The hero's move"
    name = encounter.get("name") or "the encounter"
    damage = round_record.get("damage")
    score = round_record.get("score")
    if damage:
        sentence = f"{move} against {name} falls short -- {damage} damage taken."
    else:
        sentence = f"{move} against {name} lands cleanly."
    if score is not None:
        sentence += f" (score: {score})"
    return sentence


def _build_narration_messages(persona_obj: Mapping[str, Any] | None, facts_text: str) -> list[dict[str, str]]:
    persona_prompt = ""
    if persona_obj:
        persona_prompt = persona_obj.get("prompt") or persona_obj.get("system_prompt") or ""
    system = (
        f"{persona_prompt}\n\n" if persona_prompt else ""
    ) + (
        "You are narrating one resolved turn of a cooperative communication "
        "adventure game, in-character. You are given the ALREADY-DECIDED "
        "facts for this turn below -- describe only those facts in one or "
        "two short, vivid sentences. Do not invent a different outcome, "
        "score, or new fact; do not contradict anything given; do not add "
        "dialogue that implies a result other than the one stated. Reply "
        "with the narration only, no preamble, no quotes."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": facts_text or "(no additional facts)"},
    ]


class NarrationComposer:
    """Cosmetic-only narration for a just-resolved round, built strictly
    from that round's own established facts (see ``_facts_only_context``).
    Best-effort and bounded: on any model failure, timeout, or absence, it
    falls back to a deterministic templated sentence built from the exact
    same facts, so narration never blocks or changes behavior of the
    underlying game."""

    def __init__(
        self,
        *,
        call_fn: Callable[[list[dict[str, str]]], str] | None,
        persona_lookup: Callable[[str], Mapping[str, Any] | None] | None = None,
        engine_ready_fn: Callable[[], bool] | None = None,
        max_chars: int = 400,
    ):
        self._call_fn = call_fn
        self._persona_lookup = persona_lookup
        self._engine_ready_fn = engine_ready_fn
        self._max_chars = max_chars

    def start(self, *, round_record: Mapping[str, Any], persona_name: str | None = None) -> tuple[threading.Event, dict[str, Any]]:
        """Launches the model call on a plain daemon thread and returns
        immediately -- see ``VariantGenerator.start`` for why this (not
        ``asyncio.wait_for(loop.run_in_executor(...))``) is what actually
        makes a caller's bounded wait bounded."""
        event = threading.Event()
        box: dict[str, Any] = {"narration": None}
        if self._call_fn is None or (self._engine_ready_fn is not None and not self._engine_ready_fn()):
            event.set()
            return event, box

        def _run() -> None:
            try:
                box["narration"] = self._narrate_sync(round_record=round_record, persona_name=persona_name)
            except Exception:
                pass
            finally:
                event.set()

        threading.Thread(target=_run, daemon=True).start()
        return event, box

    def narrate(self, *, round_record: Mapping[str, Any], persona_name: str | None = None) -> str:
        return self._narrate_sync(round_record=round_record, persona_name=persona_name)

    def _narrate_sync(self, *, round_record: Mapping[str, Any], persona_name: str | None = None) -> str:
        fallback = _deterministic_narration(round_record)
        if self._call_fn is None:
            return fallback
        if self._engine_ready_fn is not None and not self._engine_ready_fn():
            return fallback
        persona_obj = self._persona_lookup(persona_name) if (self._persona_lookup and persona_name) else None
        messages = _build_narration_messages(persona_obj, _facts_only_context(round_record))
        try:
            raw = self._call_fn(messages)
        except Exception:
            return fallback
        cleaned = _clean_text(raw, self._max_chars)
        return cleaned or fallback

    def fallback(self, round_record: Mapping[str, Any]) -> str:
        """Public escape hatch for callers that must bound their own wait
        and need the exact same zero-model fallback text ``narrate`` itself
        would have used on failure/unavailability/timeout."""
        return _deterministic_narration(round_record)


# --- Engine call isolation ------------------------------------------------


class GameAdapter:
    """Every route in app.py calls the engine only through here, never a
    ``game.Room`` instance directly. When the engine's method
    names/signatures shift, only this class's method bodies need to
    change -- no route handler in app.py does.

    Method names below match the contract lost-meaning-engine published for
    board task #1 (see collab room history / docs/LAN_GAME_SPEC.md once
    published):

    Phases: lobby -> spotlight_action -> ally_support -> spotlight_draft ->
    ally_reaction -> reveal -> finished (+ replay -> lobby). Roster is
    fixed (4 HeroDefs); ``join`` binds each human to the next open hero
    slot, unclaimed/disconnected slots play as deterministic companions.
    """

    def __init__(self, room: "game.Room"):
        self.room = room

    def join(self, name: str) -> tuple[str, str]:
        return self.room.join(name)

    def disconnect(self, player_id: str, token: str) -> None:
        self.room.disconnect(player_id, token)

    def reconnect(self, player_id: str, token: str) -> None:
        self.room.reconnect(player_id, token)

    def verify_token(self, player_id: str, token: str) -> bool:
        return self.room.verify_token(player_id, token)

    def start(self, player_id: str, token: str) -> None:
        self.room.start(player_id, token)

    def submit_spotlight_action(
        self, player_id: str, token: str, move_id: str, target_id: str, desired_outcome: str
    ) -> None:
        self.room.submit_spotlight_action(player_id, token, move_id, target_id, desired_outcome)

    def submit_support(self, player_id: str, token: str, kind: str, detail: str) -> None:
        self.room.submit_support(player_id, token, kind, detail)

    def can_open_draft(self) -> bool:
        return self.room.can_open_draft()

    def open_draft(self, player_id: str, token: str) -> None:
        self.room.open_draft(player_id, token)

    def submit_rough_text(self, player_id: str, token: str, text: str) -> None:
        self.room.submit_rough_text(player_id, token, text)

    def submit_variants(self, player_id: str, token: str, variants: list[str]) -> None:
        self.room.submit_variants(player_id, token, variants)

    def approve_message(self, player_id: str, token: str, chosen_text: str, intent: str) -> None:
        self.room.approve_message(player_id, token, chosen_text, intent)

    def submit_reaction(
        self, player_id: str, token: str, verb: str, detail: str, move_id: str | None = None
    ) -> None:
        self.room.submit_reaction(player_id, token, verb, detail, move_id=move_id)

    def can_resolve(self) -> bool:
        return self.room.can_resolve()

    def resolve(self, player_id: str, token: str) -> dict:
        return self.room.resolve(player_id, token)

    def advance(self, player_id: str, token: str) -> None:
        self.room.advance(player_id, token)

    def replay(self, player_id: str, token: str, seed: int | None = None) -> None:
        self.room.replay(player_id, token, seed=seed)

    def update_voice_profile(self, player_id: str, token: str, metadata: Mapping[str, Any]) -> None:
        self.room.update_voice_profile(player_id, token, metadata)

    def set_flavor(self, key: str, text: str) -> None:
        self.room.set_flavor(key, text)

    def public_state(self, viewer_player_id: str | None = None) -> dict:
        return self.room.public_state(viewer_player_id)
