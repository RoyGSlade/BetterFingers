"""Spellcheck & Sorcery -- pure in-memory deterministic game engine (board #39).

A 1-4 player co-op card-board adventure layered on the LAN playground. Five
seeded absurd encounters, a shared pool of hearts, and a simultaneous-choice
"Charm / Scheme / Bonk" combat system that resolves deterministically from
the submitted approaches alone.

This module has zero I/O, zero LLM calls, and zero framework imports (no
FastAPI, no `server`, no persona services) -- exactly the shape of
backend/lan_playground/security.py, so it is trivially unit-testable and
safely importable from anywhere. The transport layer (board #40) wraps
`GameRegistry`/`Room` in HTTP routes; the persona-rewrite layer calls
`Room.set_flavor()` to overlay LLM prose *after* computing it elsewhere --
this module never generates or requests that prose itself, and nothing it
returns can be fed back in to change a score. Scoring only ever reads the
`approach` field (one of three fixed strings); free-text `move_text` and any
flavor override are display-only and are never inspected for content.

Identity model: `Room.join()` mints a public `player_id` and a secret
`token`, mirroring backend/lan_playground/security.py's access-code pattern
(the token is returned once, at join time, and compared with
`hmac.compare_digest`-equivalent constant-time comparison thereafter).
`Room.public_state()` never includes any player's token, and never includes
another player's choice for the round currently being chosen -- only that
they have (or have not) submitted.
"""

from __future__ import annotations

import random
import secrets
import threading
import time
from dataclasses import dataclass
from typing import Callable, Literal

Approach = Literal["charm", "scheme", "bonk"]
APPROACHES: tuple[Approach, ...] = ("charm", "scheme", "bonk")
Phase = Literal["lobby", "choosing", "reveal", "finished"]

MAX_PLAYERS = 4
STARTING_HEARTS = 3
PLAYER_NAME_MAX_CHARS = 40
MOVE_TEXT_MAX_CHARS = 140
FLAVOR_TEXT_MAX_CHARS = 400
DEFAULT_PLAYER_NAME = "Adventurer"


class GameError(Exception):
    """Base class for every engine-rejected action."""


class RoomFullError(GameError):
    pass


class InvalidPhaseError(GameError):
    pass


class NotHostError(GameError):
    pass


class UnknownPlayerError(GameError):
    pass


class InvalidTokenError(GameError):
    pass


class InactivePlayerError(GameError):
    pass


class AlreadySubmittedError(GameError):
    pass


class NotAllSubmittedError(GameError):
    pass


class InvalidApproachError(GameError):
    pass


def _sanitize_line(raw: str, max_chars: int, default: str = "") -> str:
    """Collapse to one printable line and bound length. Never raises."""
    text = "".join(" " if ch in "\n\r\t" else ch for ch in str(raw or "") if ch.isprintable() or ch in "\n\r\t")
    text = " ".join(text.split())
    text = text[:max_chars].strip()
    return text or default


@dataclass(frozen=True)
class Encounter:
    id: str
    name: str
    flavor: str
    weakness: Approach
    resistant: Approach

    @property
    def neutral(self) -> Approach:
        return next(a for a in APPROACHES if a not in (self.weakness, self.resistant))


# Five absurd encounters. The first four are shuffled from the room seed and
# the Red-Tape Dragon always waits at the final map stop. Each is weak to one approach (deals full
# effect), resistant to another (backfires on the party), and neutral to the
# third (always safe, never wrong -- the reliable fallback). All six
# possible (weakness, resistant) pairs but one are represented, so no two
# encounters play identically.
ENCOUNTERS: tuple[Encounter, ...] = (
    Encounter(
        "passive_aggressive_troll",
        "The Passive-Aggressive Troll",
        "A bridge clerk with a purple quill, seventeen unchecked boxes, and "
        "a smile that says your crossing request was filed in the wrong font.",
        weakness="scheme",
        resistant="bonk",
    ),
    Encounter(
        "goblin_hr_department",
        "The Goblin HR Department",
        "Five goblins, nine clipboards, and one tiny rubber stamp stand between "
        "the party and a legally compliant lunch break.",
        weakness="charm",
        resistant="scheme",
    ),
    Encounter(
        "suggestion_box_mimic",
        "The Suggestion-Box Mimic",
        "It promises anonymous feedback, then grows teeth, reads every note "
        "aloud, and asks whether you would describe morale as 'crunchy.'",
        weakness="bonk",
        resistant="charm",
    ),
    Encounter(
        "needlessly_complicated_riddle_bridge",
        "The Bridge of Needlessly Complicated Riddles",
        "Every fork demands a new answer, every answer unlocks two more forks, "
        "and the gargoyle insists the obvious route is 'not in scope.'",
        weakness="charm",
        resistant="bonk",
    ),
    Encounter(
        "red_tape_dragon",
        "The Red-Tape Dragon (Final Boss)",
        "Forged from forms, filing cabinets, wax seals, and procedures last "
        "updated three kingdoms ago. Its breath weapon is a mandatory survey.",
        weakness="scheme",
        resistant="charm",
    ),
)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_urlsafe(9)}"


@dataclass
class _Player:
    player_id: str
    token: str
    name: str
    is_host: bool = False
    active: bool = True


@dataclass
class _Submission:
    approach: Approach
    move_text: str


class Room:
    """One in-progress (or lobby, or finished) game. All methods are thread-safe."""

    def __init__(self, room_id: str, seed: int, clock: Callable[[], float] = time.time):
        self.room_id = room_id
        self.seed = seed
        self._clock = clock
        self._lock = threading.Lock()
        self._players: dict[str, _Player] = {}
        self._order: list[str] = []  # join order -- deterministic display/host-succession order
        self.host_id: str | None = None
        self.phase: Phase = "lobby"
        self.hearts = STARTING_HEARTS
        self.max_hearts = STARTING_HEARTS
        self._encounter_order = self._shuffled_encounter_order(seed)
        self.encounter_index = 0
        self._submissions: dict[str, _Submission] = {}
        self._rounds: list[dict] = []
        self._flavor: dict[str, str] = {}
        self.finished_victory: bool | None = None
        self.created_at = self._clock()

    @staticmethod
    def _shuffled_encounter_order(seed: int) -> list[int]:
        order = list(range(len(ENCOUNTERS) - 1))
        random.Random(seed).shuffle(order)
        order.append(len(ENCOUNTERS) - 1)
        return order

    def _current_encounter(self) -> Encounter:
        return ENCOUNTERS[self._encounter_order[self.encounter_index]]

    # -- identity --------------------------------------------------------

    def _authenticate(self, player_id: str, token: str) -> _Player:
        player = self._players.get(player_id)
        if player is None:
            raise UnknownPlayerError("unknown player")
        if not secrets.compare_digest(token or "", player.token):
            raise InvalidTokenError("invalid token")
        return player

    def verify_token(self, player_id: str, token: str) -> bool:
        """Read-only check for GET-style endpoints. Never raises."""
        player = self._players.get(player_id)
        return bool(player and secrets.compare_digest(token or "", player.token))

    # -- membership --------------------------------------------------------

    def join(self, name: str) -> tuple[str, str]:
        """Add a new player. Returns (player_id, token); the token is secret
        and returned only here -- callers must persist it client-side."""
        with self._lock:
            if self.phase != "lobby":
                raise InvalidPhaseError("room is not accepting new players")
            active_count = sum(1 for p in self._players.values() if p.active)
            if active_count >= MAX_PLAYERS:
                raise RoomFullError("room is full")
            player_id = _new_id("p")
            token = secrets.token_urlsafe(24)
            is_host = self.host_id is None
            self._players[player_id] = _Player(
                player_id, token, _sanitize_line(name, PLAYER_NAME_MAX_CHARS, DEFAULT_PLAYER_NAME), is_host=is_host
            )
            self._order.append(player_id)
            if is_host:
                self.host_id = player_id
            return player_id, token

    def disconnect(self, player_id: str, token: str) -> None:
        with self._lock:
            player = self._authenticate(player_id, token)
            player.active = False
            if player_id == self.host_id:
                self._promote_next_host_locked()

    def reconnect(self, player_id: str, token: str) -> None:
        with self._lock:
            player = self._authenticate(player_id, token)
            player.active = True

    def _promote_next_host_locked(self) -> None:
        # Only hands off the gavel if another active player exists; otherwise
        # the departed host keeps the role and reclaims it on reconnect --
        # this is what keeps a solo disconnect from deadlocking the room.
        for pid in self._order:
            candidate = self._players.get(pid)
            if candidate is not None and candidate.active:
                old_host = self._players.get(self.host_id)
                if old_host is not None:
                    old_host.is_host = False
                self.host_id = pid
                candidate.is_host = True
                return

    # -- lifecycle --------------------------------------------------------

    def start(self, player_id: str, token: str) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if player_id != self.host_id:
                raise NotHostError("only the host can start the game")
            if self.phase != "lobby":
                raise InvalidPhaseError("game already started")
            if not self._players:
                raise GameError("no players in room")
            self.phase = "choosing"

    def submit_choice(self, player_id: str, token: str, approach: str, move_text: str) -> None:
        with self._lock:
            player = self._authenticate(player_id, token)
            if self.phase != "choosing":
                raise InvalidPhaseError("not currently choosing")
            if not player.active:
                raise InactivePlayerError("disconnected players cannot submit")
            if approach not in APPROACHES:
                raise InvalidApproachError("approach must be one of charm/scheme/bonk")
            if player_id in self._submissions:
                raise AlreadySubmittedError("choice already submitted this round")
            self._submissions[player_id] = _Submission(approach, _sanitize_line(move_text, MOVE_TEXT_MAX_CHARS))

    def can_resolve(self) -> bool:
        with self._lock:
            return self._can_resolve_locked()

    def _can_resolve_locked(self) -> bool:
        active_ids = [pid for pid, p in self._players.items() if p.active]
        if not active_ids:
            return False
        return all(pid in self._submissions for pid in active_ids)

    def resolve(self, player_id: str, token: str) -> dict:
        """Reveal this round's choices and apply deterministic damage.

        successes = submissions matching the encounter's weakness.
        backfires = submissions matching the encounter's resistance.
        damage = max(0, backfires - successes), floored at 0 hearts.
        Every active player's move_text is cosmetic and never read for
        scoring -- only the `approach` field is.
        """
        with self._lock:
            self._authenticate(player_id, token)
            if player_id != self.host_id:
                raise NotHostError("only the host can resolve the round")
            if self.phase != "choosing":
                raise InvalidPhaseError("not currently choosing")
            if not self._can_resolve_locked():
                raise NotAllSubmittedError("not all active players have submitted")

            encounter = self._current_encounter()
            successes = 0
            backfires = 0
            revealed = []
            for pid in self._order:
                if pid not in self._submissions:
                    continue
                sub = self._submissions[pid]
                if sub.approach == encounter.weakness:
                    successes += 1
                elif sub.approach == encounter.resistant:
                    backfires += 1
                revealed.append(
                    {
                        "player_id": pid,
                        "name": self._players[pid].name,
                        "approach": sub.approach,
                        "move_text": self._flavor.get(f"move:{pid}:{self.encounter_index}", sub.move_text),
                    }
                )

            damage = max(0, backfires - successes)
            hearts_before = self.hearts
            self.hearts = max(0, self.hearts - damage)

            round_record = {
                "round": self.encounter_index,
                "encounter": self._encounter_public_locked(encounter),
                "choices": revealed,
                "successes": successes,
                "backfires": backfires,
                "damage": damage,
                "hearts_before": hearts_before,
                "hearts_after": self.hearts,
            }
            self._rounds.append(round_record)
            self._submissions = {}

            if self.hearts <= 0:
                self.phase = "finished"
                self.finished_victory = False
            else:
                self.phase = "reveal"
            return round_record

    def advance(self, player_id: str, token: str) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if player_id != self.host_id:
                raise NotHostError("only the host can advance the game")
            if self.phase != "reveal":
                raise InvalidPhaseError("not currently in reveal")
            if self.encounter_index + 1 >= len(self._encounter_order):
                self.phase = "finished"
                self.finished_victory = True
            else:
                self.encounter_index += 1
                self.phase = "choosing"

    def replay(self, player_id: str, token: str, seed: int | None = None) -> None:
        """Reset a finished room to a fresh lobby with the same roster.

        Reseeds deterministically (seed+1 by default) so a replay is a new,
        reproducible run rather than a random one -- pass an explicit `seed`
        to reproduce a specific run exactly.
        """
        with self._lock:
            self._authenticate(player_id, token)
            if player_id != self.host_id:
                raise NotHostError("only the host can start a replay")
            if self.phase != "finished":
                raise InvalidPhaseError("game is not finished")
            self.seed = seed if seed is not None else self.seed + 1
            self._encounter_order = self._shuffled_encounter_order(self.seed)
            self.encounter_index = 0
            self.hearts = self.max_hearts
            self._submissions = {}
            self._rounds = []
            self._flavor = {}
            self.finished_victory = None
            self.phase = "lobby"

    # -- cosmetic overlay --------------------------------------------------

    def set_flavor(self, key: str, text: str) -> None:
        """Attach display-only prose (e.g. a persona-rewritten line) under an
        arbitrary key, such as ``f"move:{player_id}:{encounter_index}"``.
        Purely cosmetic: nothing here is ever read by resolve()'s scoring,
        only by round rendering. Call before resolve() for a given round to
        have it baked into that round's revealed move_text."""
        with self._lock:
            self._flavor[key] = _sanitize_line(text, FLAVOR_TEXT_MAX_CHARS)

    # -- state export --------------------------------------------------------

    def _encounter_public_locked(self, encounter: Encounter) -> dict:
        return {
            "id": encounter.id,
            "name": encounter.name,
            "flavor": self._flavor.get(f"encounter:{encounter.id}", encounter.flavor),
        }

    def public_state(self, viewer_player_id: str | None = None) -> dict:
        """JSON-safe snapshot. Never includes any token, and never includes
        another player's choice for the round currently being chosen."""
        with self._lock:
            players_public = [
                {
                    "player_id": pid,
                    "name": self._players[pid].name,
                    "is_host": self._players[pid].is_host,
                    "active": self._players[pid].active,
                    "submitted": pid in self._submissions,
                }
                for pid in self._order
            ]
            current_encounter = (
                self._encounter_public_locked(self._current_encounter())
                if self.phase in ("choosing", "reveal")
                else None
            )
            state = {
                "room_id": self.room_id,
                "phase": self.phase,
                "hearts": self.hearts,
                "max_hearts": self.max_hearts,
                "host_id": self.host_id,
                "players": players_public,
                "round_index": self.encounter_index,
                "total_rounds": len(self._encounter_order),
                "encounter": current_encounter,
                "last_round": self._rounds[-1] if self._rounds else None,
                "history": list(self._rounds),
                "finished_victory": self.finished_victory,
                "you": None,
            }
            if viewer_player_id is not None and viewer_player_id in self._players:
                viewer = self._players[viewer_player_id]
                state["you"] = {
                    "player_id": viewer_player_id,
                    "is_host": viewer.is_host,
                    "active": viewer.active,
                    "submitted": viewer_player_id in self._submissions,
                }
            return state


class GameRegistry:
    """In-memory registry of live rooms, keyed by room_id.

    Pure/no I/O -- the transport layer (board #40) owns HTTP, QR/link
    generation, and any cross-room persistence; this class only tracks which
    Room objects currently exist.
    """

    def __init__(self, clock: Callable[[], float] = time.time):
        self._rooms: dict[str, Room] = {}
        self._clock = clock

    def create_room(self, host_name: str, seed: int | None = None) -> tuple[Room, str, str]:
        """Create a room and immediately join the creator as its host.
        Returns (room, host_player_id, host_token)."""
        room_id = _new_id("room")
        room = Room(room_id, seed if seed is not None else secrets.randbelow(2**31), clock=self._clock)
        host_id, host_token = room.join(host_name)
        self._rooms[room_id] = room
        return room, host_id, host_token

    def get(self, room_id: str) -> Room | None:
        return self._rooms.get(room_id)

    def remove(self, room_id: str) -> None:
        self._rooms.pop(room_id, None)

    def __len__(self) -> int:
        return len(self._rooms)
