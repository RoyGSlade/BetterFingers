"""The Lost Meaning -- pure in-memory deterministic cooperative game engine.

A 1-4 player cooperative communication adventure layered on the LAN
playground. Four fixed heroes (each with a persona, an ability, a distinct
move deck, an exclusive signature move, and a private per-encounter clue)
face five absurd office-life encounters. Every round the rotating Spotlight
hero declares a move + target + desired outcome, teammates pledge support,
the Spotlight drafts a rough line that BetterFingers turns into three
candidate rewrites, the Spotlight edits and approves one message + intent,
teammates react (interpret/assist/challenge/protect), and the engine
resolves the round from a fully transparent modifier ledger plus one seeded
die -- no hidden state, no randomness outside that one die.

This module has zero I/O, zero LLM calls, and zero framework imports (no
FastAPI, no `server`, no persona services) -- exactly the shape of
backend/lan_playground/security.py, so it is trivially unit-testable and
safely importable from anywhere. The transport layer wraps
`GameRegistry`/`Room` in HTTP routes; the persona-rewrite layer calls
`submit_variants()` with three BetterFingers rewrites of the Spotlight's
rough text (or, offline/for a companion hero, three identical copies of the
canonical text -- the deterministic model-free fallback) and may call
`set_flavor()` to overlay cosmetic prose over an already-resolved round.
Nothing this module returns can be fed back in to change a score: resolution
only ever reads `move_id`/`target_id`/reaction `verb` fields (fixed enums)
and the one seeded die; all free text (`desired_outcome`, rough/variant/
approved text, intent, support/reaction detail, flavor overlays) is
display-only and never inspected for content.

Identity model: `Room.join()` mints a public `player_id` and a secret
`token` (mirroring backend/lan_playground/security.py's access-code
pattern) and binds the player to the next open hero slot. Any hero slot
without an active human controller (never claimed, or claimed by a
disconnected player) is a *companion*: the engine auto-plays that hero's
turn with a small set of deterministic, seed/round-derived choices so a
1-player game (or a game where someone drops) always has all four heroes
acting and the room never deadlocks waiting on a human who isn't there.

`Room.public_state()` never includes any player's token. A hero's move/
target/desired-outcome become public the instant the Spotlight declares
them (this is a transparent card game, not a hidden-choice one); a hero's
private clue is exposed only to that hero (via `you`), and support/reaction
*content* stays hidden from other players until `resolve()` bakes it into
the round record -- only a boolean "have they gone yet" is visible before
that, so nobody's pending choice leaks or is influenced by an ally's.
"""

from __future__ import annotations

import random
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Literal

Approach = Literal["charm", "scheme", "bonk"]
APPROACHES: tuple[Approach, ...] = ("charm", "scheme", "bonk")
Phase = Literal[
    "lobby",
    "spotlight_action",
    "ally_support",
    "spotlight_draft",
    "ally_reaction",
    "reveal",
    "finished",
]

SUPPORT_KINDS: tuple[str, ...] = ("clue", "item", "assist", "reaction")
REACTION_VERBS: tuple[str, ...] = ("interpret", "assist", "challenge", "protect")

STARTING_HEARTS = 3
ITEM_STARTING_COUNT = 1
PLAYER_NAME_MAX_CHARS = 40
DESIRED_OUTCOME_MAX_CHARS = 140
ROUGH_TEXT_MAX_CHARS = 280
VARIANT_TEXT_MAX_CHARS = 280
APPROVED_TEXT_MAX_CHARS = 280
INTENT_MAX_CHARS = 140
SUPPORT_DETAIL_MAX_CHARS = 140
REACTION_DETAIL_MAX_CHARS = 140
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


class WrongTurnError(GameError):
    """Raised when a player acts out of turn: not the current Spotlight
    hero when a Spotlight-only step is called, or the Spotlight hero trying
    to submit an ally-only step."""


class UnknownPlayerError(GameError):
    pass


class InvalidTokenError(GameError):
    pass


class AlreadySubmittedError(GameError):
    pass


class NotAllSubmittedError(GameError):
    pass


class InvalidMoveError(GameError):
    pass


class InvalidTargetError(GameError):
    pass


class InvalidSupportKindError(GameError):
    pass


class InvalidReactionVerbError(GameError):
    pass


class NoItemsRemainingError(GameError):
    pass


class InvalidVariantsError(GameError):
    pass


def _sanitize_line(raw: str, max_chars: int, default: str = "") -> str:
    """Collapse to one printable line and bound length. Never raises."""
    text = "".join(" " if ch in "\n\r\t" else ch for ch in str(raw or "") if ch.isprintable() or ch in "\n\r\t")
    text = " ".join(text.split())
    text = text[:max_chars].strip()
    return text or default


# --------------------------------------------------------------------------
# Moves. Schools remain Charm/Scheme/Bonk, but every card is a distinct move
# with its own flavor and its own reaction-verb affinities (which of
# interpret/assist/challenge/protect it's suited for when an ally cites it
# in `submit_reaction`; an empty tuple means the move is a pure Spotlight
# card with no reaction synergy). Any move may still be played as the
# Spotlight's primary action regardless of its verb tags.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Move:
    id: str
    name: str
    school: Approach
    verbs: tuple[str, ...]
    description: str


MOVES: dict[str, Move] = {
    m.id: m
    for m in (
        Move(
            "empathic_mirror",
            "Empathic Mirror",
            "charm",
            ("assist", "interpret"),
            "Reflect the target's own words back until they hear themselves.",
        ),
        Move(
            "disarming_honesty",
            "Disarming Honesty",
            "charm",
            ("assist", "challenge"),
            "Say the true, slightly awkward thing before anyone else can posture.",
        ),
        Move(
            "cross_reference",
            "Cross-Reference",
            "scheme",
            ("interpret",),
            "Pull up precedent and lay it next to the problem.",
        ),
        Move(
            "loophole_with_consequences",
            "Loophole with Consequences",
            "scheme",
            ("challenge",),
            "Find the technicality. Accept that it may technically bite back.",
        ),
        Move(
            "precision_bonk",
            "Precision Bonk",
            "bonk",
            (),
            "One controlled, exactly-placed thump. No more, no less.",
        ),
        Move(
            "defend_the_speaker",
            "Defend the Speaker",
            "bonk",
            ("protect",),
            "Step bodily between a teammate and the consequences of speaking up.",
        ),
        Move(
            "smash_the_right_thing",
            "Smash the Right Thing",
            "bonk",
            (),
            "Commit fully to a single target. Devastating if it's correct.",
        ),
        Move(
            "improvised_bonk",
            "Improvised Bonk",
            "bonk",
            ("assist", "protect"),
            "Whatever's at hand, swung with more heart than plan.",
        ),
    )
}


# --------------------------------------------------------------------------
# Heroes. Exactly four, always. Each has a persona, a passive ability
# (checked explicitly in resolve()), a three-move deck drawn from MOVES, and
# one signature move exclusive to them. join() binds players to hero slots
# in this fixed order; any slot left unclaimed (or whose player has
# disconnected) is played by the deterministic companion logic below.
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class HeroDef:
    id: str
    name: str
    persona: str
    ability_name: str
    ability_description: str
    deck: tuple[str, ...]
    signature_move: Move


HERO_ROSTER: tuple[HeroDef, ...] = (
    HeroDef(
        "bram_correctly",
        "Bram Correctly",
        "An overly-formal municipal clerk who fights bureaucracy with more bureaucracy, kindly.",
        "Steady Hand",
        "When Bram is Spotlight playing Precision Bonk or The Unimpeachable Memo, "
        "this round's backfire damage is reduced by 1.",
        ("empathic_mirror", "precision_bonk", "cross_reference"),
        Move(
            "unimpeachable_memo",
            "The Unimpeachable Memo",
            "scheme",
            ("interpret", "challenge"),
            "A memo so procedurally correct it cannot be argued with.",
        ),
    ),
    HeroDef(
        "nadia_quickwit",
        "Nadia Quickwit",
        "A fast-talking dispute-resolution specialist, sharp and a little chaotic.",
        "Loophole Sense",
        "When Nadia performs a challenge reaction, she gets +1 extra on top of the usual challenge bonus.",
        ("loophole_with_consequences", "disarming_honesty", "cross_reference"),
        Move(
            "airtight_rebuttal",
            "The Airtight Rebuttal",
            "scheme",
            ("challenge",),
            "A rebuttal with no gaps left to exploit.",
        ),
    ),
    HeroDef(
        "otis_barnstorm",
        "Otis Barnstorm",
        "A blunt, warm-hearted forklift-driver-turned-negotiator.",
        "Follow-Through",
        "When Otis is Spotlight and his move's school matches the encounter's weakness, he gets +1 extra.",
        ("precision_bonk", "smash_the_right_thing", "improvised_bonk"),
        Move(
            "one_true_thump",
            "The One True Thump",
            "bonk",
            (),
            "The thump every other thump was practice for.",
        ),
    ),
    HeroDef(
        "ilona_softword",
        "Ilona Softword",
        "A gentle, empathetic mediator and a master of tone.",
        "Read the Room",
        "When Ilona performs a protect reaction, its damage reduction is 2 instead of 1.",
        ("empathic_mirror", "defend_the_speaker", "disarming_honesty"),
        Move(
            "the_perfect_pause",
            "The Perfect Pause",
            "charm",
            ("protect", "assist"),
            "Silence held exactly long enough for the room to calm itself.",
        ),
    ),
)

HERO_BY_ID: dict[str, HeroDef] = {h.id: h for h in HERO_ROSTER}
MAX_PLAYERS = len(HERO_ROSTER)

ALL_MOVES: dict[str, Move] = dict(MOVES)
for _hero in HERO_ROSTER:
    ALL_MOVES[_hero.signature_move.id] = _hero.signature_move


@dataclass(frozen=True)
class Encounter:
    id: str
    name: str
    flavor: str
    weakness: Approach
    resistant: Approach
    targets: tuple[str, ...]
    true_target: str
    clues: dict[str, str]

    @property
    def neutral(self) -> Approach:
        return next(a for a in APPROACHES if a not in (self.weakness, self.resistant))


# Five absurd encounters, each weak to one school (+1), resistant to another
# (-1), neutral to the third (0), with 2-3 named targets (one of them the
# true_target) and one asymmetric private clue per hero hinting at it. The
# first four are shuffled from the room seed; the Red-Tape Dragon always
# occupies the final map stop.
ENCOUNTERS: tuple[Encounter, ...] = (
    Encounter(
        "passive_aggressive_troll",
        "The Passive-Aggressive Troll",
        "A bridge clerk with a purple quill, seventeen unchecked boxes, and "
        "a smile that says your crossing request was filed in the wrong font.",
        weakness="scheme",
        resistant="bonk",
        targets=("the seventeen boxes", "the purple quill", "the toll ledger"),
        true_target="the toll ledger",
        clues={
            "bram_correctly": "The quill only signs what the ledger already allows.",
            "nadia_quickwit": "Seventeen boxes, and every one cites the same ledger clause.",
            "otis_barnstorm": "Thumping the boxes just resets the count.",
            "ilona_softword": "The troll softens the moment someone reads the ledger aloud.",
        },
    ),
    Encounter(
        "goblin_hr_department",
        "The Goblin HR Department",
        "Five goblins, nine clipboards, and one tiny rubber stamp stand between "
        "the party and a legally compliant lunch break.",
        weakness="charm",
        resistant="scheme",
        targets=("the lunch-break form", "the compliance seminar sign-up", "the tiny rubber stamp"),
        true_target="the tiny rubber stamp",
        clues={
            "bram_correctly": "Every goblin defers to whoever's holding the stamp.",
            "nadia_quickwit": "The sign-up sheet is a decoy; nobody's ever attended the seminar.",
            "otis_barnstorm": "The form doesn't matter until it's stamped.",
            "ilona_softword": "Goblins relax the instant the stamp changes hands kindly.",
        },
    ),
    Encounter(
        "suggestion_box_mimic",
        "The Suggestion-Box Mimic",
        "It promises anonymous feedback, then grows teeth, reads every note "
        "aloud, and asks whether you would describe morale as 'crunchy.'",
        weakness="bonk",
        resistant="charm",
        targets=("the anonymous note pile", "the hinge of its lid", "the word 'crunchy'"),
        true_target="the hinge of its lid",
        clues={
            "bram_correctly": "It can't read notes if the lid won't open.",
            "nadia_quickwit": "It's stalling on 'crunchy' to keep the lid shut.",
            "otis_barnstorm": "One good knock on the hinge and the reading stops.",
            "ilona_softword": "Complimenting it only feeds more notes through the hinge.",
        },
    ),
    Encounter(
        "needlessly_complicated_riddle_bridge",
        "The Bridge of Needlessly Complicated Riddles",
        "Every fork demands a new answer, every answer unlocks two more forks, "
        "and the gargoyle insists the obvious route is 'not in scope.'",
        weakness="charm",
        resistant="bonk",
        targets=("the gargoyle's mood", "the newest fork", "the 'not in scope' stamp"),
        true_target="the gargoyle's mood",
        clues={
            "bram_correctly": "The forks stop multiplying once the gargoyle's satisfied.",
            "nadia_quickwit": "'Not in scope' is just what it says when it's in a bad mood.",
            "otis_barnstorm": "Force adds a fork; it doesn't remove one.",
            "ilona_softword": "A kind word actually reaches the gargoyle, not the stonework.",
        },
    ),
    Encounter(
        "red_tape_dragon",
        "The Red-Tape Dragon (Final Boss)",
        "Forged from forms, filing cabinets, wax seals, and procedures last "
        "updated three kingdoms ago. Its breath weapon is a mandatory survey.",
        weakness="scheme",
        resistant="charm",
        targets=("the filing cabinet's index", "the wax seal", "the mandatory survey"),
        true_target="the filing cabinet's index",
        clues={
            "bram_correctly": "The seal only matters if the index still recognizes it.",
            "nadia_quickwit": "The survey is generated fresh from whatever's indexed.",
            "otis_barnstorm": "Smashing the cabinet scatters the index further.",
            "ilona_softword": "The dragon calms only when its own index is set right, not when it's flattered.",
        },
    ),
)

_COMPANION_VERB_CYCLE: tuple[str, ...] = ("assist", "protect", "challenge", "interpret")


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
class _HeroSlot:
    hero_def: HeroDef
    player_id: str | None = None
    items_remaining: int = ITEM_STARTING_COUNT
    voice_profile: dict = field(default_factory=dict)


@dataclass
class _ActionRecord:
    hero_id: str
    move_id: str
    target_id: str
    desired_outcome: str
    rough_text: str | None = None
    variants: list[str] | None = None
    approved_text: str | None = None
    intent: str | None = None


@dataclass
class _SupportEntry:
    hero_id: str
    kind: str
    detail: str


@dataclass
class _ReactionEntry:
    hero_id: str
    verb: str
    detail: str
    move_id: str | None = None


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
        self._heroes: dict[str, _HeroSlot] = {h.id: _HeroSlot(h) for h in HERO_ROSTER}
        self._hero_order: list[str] = [h.id for h in HERO_ROSTER]
        self._player_hero: dict[str, str] = {}
        self._encounter_order = self._shuffled_encounter_order(seed)
        self.encounter_index = 0
        self._action: _ActionRecord | None = None
        self._support: dict[str, _SupportEntry] = {}
        self._reactions: dict[str, _ReactionEntry] = {}
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

    def _current_spotlight_hero_id(self) -> str:
        return self._hero_order[self.encounter_index % len(self._hero_order)]

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
        """Add a new player and bind them to the next open hero slot.
        Returns (player_id, token); the token is secret and returned only
        here -- callers must persist it client-side."""
        with self._lock:
            if self.phase != "lobby":
                raise InvalidPhaseError("room is not accepting new players")
            open_hero_id = next((hid for hid in self._hero_order if self._heroes[hid].player_id is None), None)
            if open_hero_id is None:
                raise RoomFullError("room is full")
            player_id = _new_id("p")
            token = secrets.token_urlsafe(24)
            is_host = self.host_id is None
            self._players[player_id] = _Player(
                player_id, token, _sanitize_line(name, PLAYER_NAME_MAX_CHARS, DEFAULT_PLAYER_NAME), is_host=is_host
            )
            self._order.append(player_id)
            self._heroes[open_hero_id].player_id = player_id
            self._player_hero[player_id] = open_hero_id
            if is_host:
                self.host_id = player_id
            return player_id, token

    def disconnect(self, player_id: str, token: str) -> None:
        with self._lock:
            player = self._authenticate(player_id, token)
            player.active = False
            if player_id == self.host_id:
                self._promote_next_host_locked()
            self._autoplay_current_phase_locked()

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

    def _hero_is_companion_locked(self, hero_id: str) -> bool:
        slot = self._heroes[hero_id]
        if slot.player_id is None:
            return True
        player = self._players.get(slot.player_id)
        return player is None or not player.active

    def _hero_name_locked(self, hero_id: str) -> str:
        return self._heroes[hero_id].hero_def.name

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
            self._start_round_locked()

    def _start_round_locked(self) -> None:
        self._action = None
        self._support = {}
        self._reactions = {}
        self.phase = "spotlight_action"
        self._autoplay_current_phase_locked()

    # -- autoplay (deterministic companion behavior) ----------------------

    def _autoplay_current_phase_locked(self) -> None:
        if self.phase == "spotlight_action":
            self._autoplay_spotlight_action_locked()
            if self.phase == "ally_support":
                self._autoplay_support_locked()
        elif self.phase == "ally_support":
            self._autoplay_support_locked()
        elif self.phase == "spotlight_draft":
            self._autoplay_draft_locked()
            if self.phase == "ally_reaction":
                self._autoplay_reaction_locked()
        elif self.phase == "ally_reaction":
            self._autoplay_reaction_locked()

    def _autoplay_spotlight_action_locked(self) -> None:
        hero_id = self._current_spotlight_hero_id()
        if self._action is not None or not self._hero_is_companion_locked(hero_id):
            return
        hero_def = self._heroes[hero_id].hero_def
        deck = hero_def.deck + (hero_def.signature_move.id,)
        move_id = deck[self.encounter_index % len(deck)]
        encounter = self._current_encounter()
        self._action = _ActionRecord(
            hero_id=hero_id,
            move_id=move_id,
            target_id=encounter.targets[0],
            desired_outcome=f"{hero_def.name} handles it directly.",
        )
        self.phase = "ally_support"

    def _autoplay_support_locked(self) -> None:
        spotlight_id = self._action.hero_id if self._action else None
        for hero_id in self._hero_order:
            if hero_id == spotlight_id or hero_id in self._support:
                continue
            if self._hero_is_companion_locked(hero_id):
                name = self._hero_name_locked(hero_id)
                self._support[hero_id] = _SupportEntry(hero_id, "assist", f"{name} lends a hand.")

    def _autoplay_draft_locked(self) -> None:
        hero_id = self._action.hero_id
        if self._action.approved_text is not None or not self._hero_is_companion_locked(hero_id):
            return
        hero_def = self._heroes[hero_id].hero_def
        text = f"{hero_def.name} states the plan plainly."
        self._action.rough_text = text
        self._action.variants = [text, text, text]
        self._action.approved_text = text
        self._action.intent = "resolve it"
        self.phase = "ally_reaction"

    def _autoplay_reaction_locked(self) -> None:
        spotlight_id = self._action.hero_id if self._action else None
        for hero_id in self._hero_order:
            if hero_id == spotlight_id or hero_id in self._reactions:
                continue
            if self._hero_is_companion_locked(hero_id):
                hero_def = self._heroes[hero_id].hero_def
                verb = _COMPANION_VERB_CYCLE[self.encounter_index % len(_COMPANION_VERB_CYCLE)]
                deck_moves = [MOVES[mid] for mid in hero_def.deck] + [hero_def.signature_move]
                candidates = [m for m in deck_moves if verb in m.verbs]
                move_id = candidates[0].id if candidates else None
                self._reactions[hero_id] = _ReactionEntry(
                    hero_id, verb, f"{hero_def.name} responds.", move_id
                )

    # -- spotlight action --------------------------------------------------

    def submit_spotlight_action(
        self, player_id: str, token: str, move_id: str, target_id: str, desired_outcome: str
    ) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if self.phase != "spotlight_action":
                raise InvalidPhaseError("not currently awaiting a spotlight action")
            hero_id = self._player_hero.get(player_id)
            if hero_id != self._current_spotlight_hero_id():
                raise WrongTurnError("it is not your spotlight turn")
            hero_def = self._heroes[hero_id].hero_def
            available = hero_def.deck + (hero_def.signature_move.id,)
            if move_id not in available:
                raise InvalidMoveError("move not available to this hero")
            encounter = self._current_encounter()
            if target_id not in encounter.targets:
                raise InvalidTargetError("target not valid for this encounter")
            self._action = _ActionRecord(
                hero_id=hero_id,
                move_id=move_id,
                target_id=target_id,
                desired_outcome=_sanitize_line(desired_outcome, DESIRED_OUTCOME_MAX_CHARS, "act"),
            )
            self.phase = "ally_support"
            self._autoplay_current_phase_locked()

    # -- ally support --------------------------------------------------

    def submit_support(self, player_id: str, token: str, kind: str, detail: str = "") -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if self.phase != "ally_support":
                raise InvalidPhaseError("not currently accepting support")
            hero_id = self._player_hero.get(player_id)
            if hero_id == self._action.hero_id:
                raise WrongTurnError("the spotlight hero already acted this round")
            if hero_id in self._support:
                raise AlreadySubmittedError("support already submitted this round")
            if kind not in SUPPORT_KINDS:
                raise InvalidSupportKindError("kind must be one of clue/item/assist/reaction")
            if kind == "item":
                slot = self._heroes[hero_id]
                if slot.items_remaining <= 0:
                    raise NoItemsRemainingError("no items remaining")
                slot.items_remaining -= 1
            self._support[hero_id] = _SupportEntry(
                hero_id, kind, _sanitize_line(detail, SUPPORT_DETAIL_MAX_CHARS, "")
            )

    def _support_complete_locked(self) -> bool:
        spotlight_id = self._action.hero_id
        return all(hid in self._support for hid in self._hero_order if hid != spotlight_id)

    def can_open_draft(self) -> bool:
        with self._lock:
            return self.phase == "ally_support" and self._support_complete_locked()

    def open_draft(self, player_id: str, token: str) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if player_id != self.host_id:
                raise NotHostError("only the host can open the draft")
            if self.phase != "ally_support":
                raise InvalidPhaseError("not currently in ally support")
            if not self._support_complete_locked():
                raise NotAllSubmittedError("not all active allies have submitted support")
            self.phase = "spotlight_draft"
            self._autoplay_current_phase_locked()

    # -- spotlight draft / BetterFingers rewrite pipeline -------------------

    def submit_rough_text(self, player_id: str, token: str, text: str) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if self.phase != "spotlight_draft":
                raise InvalidPhaseError("not currently drafting")
            if self._player_hero.get(player_id) != self._action.hero_id:
                raise WrongTurnError("only the spotlight hero drafts this round's message")
            if self._action.rough_text is not None:
                raise AlreadySubmittedError("rough text already submitted this round")
            self._action.rough_text = _sanitize_line(text, ROUGH_TEXT_MAX_CHARS, "We handle it.")

    def submit_variants(self, player_id: str, token: str, variants: list[str]) -> None:
        """Called by the transport layer with three BetterFingers rewrites
        of the rough text (or three identical copies of it -- the
        deterministic model-free fallback -- when the model is offline).
        Never generates or requests prose itself."""
        with self._lock:
            self._authenticate(player_id, token)
            if self.phase != "spotlight_draft":
                raise InvalidPhaseError("not currently drafting")
            if self._player_hero.get(player_id) != self._action.hero_id:
                raise WrongTurnError("only the spotlight hero's message can get variants")
            if self._action.rough_text is None:
                raise InvalidPhaseError("rough text not submitted yet")
            if self._action.variants is not None:
                raise AlreadySubmittedError("variants already generated this round")
            if not isinstance(variants, (list, tuple)) or len(variants) != 3:
                raise InvalidVariantsError("exactly three variants are required")
            fallback = self._action.rough_text
            self._action.variants = [_sanitize_line(v, VARIANT_TEXT_MAX_CHARS, fallback) for v in variants]

    def approve_message(self, player_id: str, token: str, chosen_text: str, intent: str) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if self.phase != "spotlight_draft":
                raise InvalidPhaseError("not currently drafting")
            if self._player_hero.get(player_id) != self._action.hero_id:
                raise WrongTurnError("only the spotlight hero approves this round's message")
            if self._action.variants is None:
                raise InvalidPhaseError("variants not generated yet")
            if self._action.approved_text is not None:
                raise AlreadySubmittedError("message already approved this round")
            self._action.approved_text = _sanitize_line(
                chosen_text, APPROVED_TEXT_MAX_CHARS, self._action.rough_text
            )
            self._action.intent = _sanitize_line(intent, INTENT_MAX_CHARS, "resolve it")
            self.phase = "ally_reaction"
            self._autoplay_current_phase_locked()

    # -- ally reactions --------------------------------------------------

    def submit_reaction(
        self,
        player_id: str,
        token: str,
        verb: str,
        detail: str = "",
        move_id: str | None = None,
    ) -> None:
        with self._lock:
            self._authenticate(player_id, token)
            if self.phase != "ally_reaction":
                raise InvalidPhaseError("not currently accepting reactions")
            hero_id = self._player_hero.get(player_id)
            if hero_id == self._action.hero_id:
                raise WrongTurnError("the spotlight hero does not react to their own action")
            if hero_id in self._reactions:
                raise AlreadySubmittedError("reaction already submitted this round")
            if verb not in REACTION_VERBS:
                raise InvalidReactionVerbError("verb must be one of interpret/assist/challenge/protect")
            if move_id is not None:
                hero_def = self._heroes[hero_id].hero_def
                if move_id not in (*hero_def.deck, hero_def.signature_move.id):
                    raise InvalidMoveError("move not available to this hero")
            self._reactions[hero_id] = _ReactionEntry(
                hero_id, verb, _sanitize_line(detail, REACTION_DETAIL_MAX_CHARS, ""), move_id
            )

    def _reactions_complete_locked(self) -> bool:
        spotlight_id = self._action.hero_id
        return all(hid in self._reactions for hid in self._hero_order if hid != spotlight_id)

    def can_resolve(self) -> bool:
        with self._lock:
            return self.phase == "ally_reaction" and self._reactions_complete_locked()

    # -- resolution --------------------------------------------------------

    def resolve(self, player_id: str, token: str) -> dict:
        """Reveal this round's support/reactions and apply deterministic
        damage from a fully transparent modifier ledger plus one seeded
        die. Every modifier (school match, target insight, hero abilities,
        support, reactions, card synergy, protect, challenge risk, the die)
        is recorded in the returned round_record. Free text is never read
        here -- only move_id/target_id/verb fields and the die."""
        with self._lock:
            self._authenticate(player_id, token)
            if player_id != self.host_id:
                raise NotHostError("only the host can resolve the round")
            if self.phase != "ally_reaction":
                raise InvalidPhaseError("not currently in ally reaction")
            if not self._reactions_complete_locked():
                raise NotAllSubmittedError("not all active allies have reacted")

            encounter = self._current_encounter()
            action = self._action
            hero_id = action.hero_id
            move = ALL_MOVES[action.move_id]

            modifiers: list[dict] = []

            # +-3, not +-1: with exactly 3 mandatory allies each round (every
            # reaction/support choice contributes >=1 toward safety, by
            # design -- nothing an ally can pick ever actively hurts the
            # party) plus per-hero abilities that only ever help, the
            # guaranteed floor of "worst die (-2) + 3 allies (+3)" needs real
            # room below it for a mismatched Spotlight move to matter at
            # all. +-3 keeps a well-supported weakness play very safe while
            # leaving real stakes for a resistant/wrong-target round.
            if move.school == encounter.weakness:
                base = 3
            elif move.school == encounter.resistant:
                base = -3
            else:
                base = 0
            modifiers.append(
                {"source": "school_match", "label": f"{move.name} vs {encounter.name}", "value": base, "affects": "score"}
            )

            target_bonus = 1 if action.target_id == encounter.true_target else 0
            modifiers.append(
                {"source": "target", "label": f"targeted {action.target_id}", "value": target_bonus, "affects": "score"}
            )

            if hero_id == "otis_barnstorm" and move.school == encounter.weakness:
                modifiers.append(
                    {"source": "ability:follow_through", "label": "Otis's Follow-Through", "value": 1, "affects": "score"}
                )

            revealed_clues: dict[str, str] = {}
            support_public = []
            for hid in self._hero_order:
                entry = self._support.get(hid)
                if entry is None:
                    continue
                name = self._hero_name_locked(hid)
                support_public.append({"hero_id": hid, "name": name, "kind": entry.kind, "detail": entry.detail})
                if entry.kind == "assist":
                    modifiers.append(
                        {"source": f"support:{hid}", "label": f"{name} assists", "value": 1, "affects": "score"}
                    )
                elif entry.kind == "item":
                    modifiers.append(
                        {"source": f"support:{hid}", "label": f"{name} spends an item", "value": 1, "affects": "score"}
                    )
                elif entry.kind == "clue":
                    modifiers.append(
                        {"source": f"support:{hid}", "label": f"{name} shares a clue", "value": 1, "affects": "score"}
                    )
                    revealed_clues[hid] = encounter.clues.get(hid, "")
                elif entry.kind == "reaction":
                    modifiers.append(
                        {"source": f"support:{hid}", "label": f"{name} reacts", "value": 0, "affects": "score"}
                    )

            num_challenges = 0
            protect_reduction = 0
            reactions_public = []
            for hid in self._hero_order:
                entry = self._reactions.get(hid)
                if entry is None:
                    continue
                name = self._hero_name_locked(hid)
                reactions_public.append(
                    {"hero_id": hid, "name": name, "verb": entry.verb, "detail": entry.detail, "move_id": entry.move_id}
                )
                if entry.verb == "assist":
                    modifiers.append(
                        {"source": f"reaction:{hid}", "label": f"{name} assists", "value": 1, "affects": "score"}
                    )
                elif entry.verb == "challenge":
                    num_challenges += 1
                    modifiers.append(
                        {"source": f"reaction:{hid}", "label": f"{name} challenges", "value": 1, "affects": "score"}
                    )
                    if hid == "nadia_quickwit":
                        modifiers.append(
                            {
                                "source": "ability:loophole_sense",
                                "label": "Nadia's Loophole Sense",
                                "value": 1,
                                "affects": "score",
                            }
                        )
                elif entry.verb == "protect":
                    reduction = 2 if hid == "ilona_softword" else 1
                    protect_reduction += reduction
                    modifiers.append(
                        {"source": f"reaction:{hid}", "label": f"{name} protects", "value": -reduction, "affects": "damage"}
                    )
                elif entry.verb == "interpret":
                    modifiers.append(
                        {"source": f"reaction:{hid}", "label": f"{name} interprets", "value": 1, "affects": "score"}
                    )
                    revealed_clues[hid] = encounter.clues.get(hid, "")

                if entry.move_id is not None:
                    cited = ALL_MOVES.get(entry.move_id)
                    if cited is not None and entry.verb in cited.verbs:
                        modifiers.append(
                            {
                                "source": f"synergy:{hid}",
                                "label": f"{name}'s {cited.name} fits",
                                "value": 1,
                                "affects": "score",
                            }
                        )

            rng = random.Random(self.seed * 1_000_003 + self.encounter_index)
            die_roll = rng.randint(1, 6)
            die_value = die_roll - 3
            modifiers.append(
                {"source": "die", "label": f"seeded die (rolled {die_roll})", "value": die_value, "affects": "score"}
            )

            if hero_id == "bram_correctly" and action.move_id in ("precision_bonk", "unimpeachable_memo"):
                modifiers.append(
                    {"source": "ability:steady_hand", "label": "Bram's Steady Hand", "value": -1, "affects": "damage"}
                )

            score = sum(m["value"] for m in modifiers if m["affects"] == "score")
            if score < 0 and num_challenges:
                modifiers.append(
                    {
                        "source": "challenge_risk",
                        "label": f"{num_challenges} challenge(s) raised the stakes",
                        "value": num_challenges,
                        "affects": "damage",
                    }
                )

            raw_damage = max(0, -score)
            damage_adjust = sum(m["value"] for m in modifiers if m["affects"] == "damage")
            damage = max(0, raw_damage + damage_adjust)

            hearts_before = self.hearts
            self.hearts = max(0, self.hearts - damage)

            round_record = {
                "round": self.encounter_index,
                "encounter": self._encounter_public_locked(encounter),
                "spotlight_hero_id": hero_id,
                "action": {
                    "hero_id": hero_id,
                    "move_id": move.id,
                    "move_name": move.name,
                    "school": move.school,
                    "target_id": action.target_id,
                    "desired_outcome": action.desired_outcome,
                    "approved_text": action.approved_text,
                    "intent": action.intent,
                },
                "support": support_public,
                "reactions": reactions_public,
                "true_target_id": encounter.true_target,
                "revealed_clues": [
                    {"hero_id": hid, "name": self._hero_name_locked(hid), "clue_text": text}
                    for hid, text in revealed_clues.items()
                ],
                "modifiers": modifiers,
                "die_roll": die_roll,
                "score": score,
                "damage": damage,
                "hearts_before": hearts_before,
                "hearts_after": self.hearts,
            }
            self._rounds.append(round_record)

            if self.hearts <= 0:
                self.phase = "finished"
                self.finished_victory = False
            else:
                self.phase = "reveal"
            return self._round_record_public_locked(round_record)

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
                self._start_round_locked()

    def replay(self, player_id: str, token: str, seed: int | None = None) -> None:
        """Reset a finished room to a fresh lobby with the same roster and
        hero assignments. Reseeds deterministically (seed+1 by default) so
        a replay is a new, reproducible run -- pass an explicit `seed` to
        reproduce a specific run exactly. Per-hero items reset to full;
        session-only voice-learning metadata is left untouched (it belongs
        to the player's session, not the run)."""
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
            self._action = None
            self._support = {}
            self._reactions = {}
            self._rounds = []
            self._flavor = {}
            self.finished_victory = None
            for slot in self._heroes.values():
                slot.items_remaining = ITEM_STARTING_COUNT
            self.phase = "lobby"

    # -- session-only voice-learning metadata --------------------------------

    def update_voice_profile(self, player_id: str, token: str, metadata: dict) -> None:
        """Bounded, numeric/boolean-only voice-adaptation metadata for the
        player's hero, held in memory for this session only -- this module
        has no I/O, so nothing here is ever persisted to disk, and raw
        audio is never accepted (only a fixed set of small summary
        scalars)."""
        with self._lock:
            self._authenticate(player_id, token)
            hero_id = self._player_hero[player_id]
            slot = self._heroes[hero_id]
            if "utterance_count" in metadata:
                try:
                    slot.voice_profile["utterance_count"] = max(0, min(9999, int(metadata["utterance_count"])))
                except (TypeError, ValueError):
                    pass
            if "confidence" in metadata:
                try:
                    slot.voice_profile["confidence"] = max(0.0, min(1.0, float(metadata["confidence"])))
                except (TypeError, ValueError):
                    pass
            if "calibrated" in metadata:
                slot.voice_profile["calibrated"] = bool(metadata["calibrated"])

    # -- cosmetic overlay --------------------------------------------------

    def set_flavor(self, key: str, text: str) -> None:
        """Attach display-only prose (e.g. a persona-rewritten line, or
        narration describing an already-resolved round) under an arbitrary
        key. Purely cosmetic: nothing here is ever read by resolve()'s
        scoring. Narration must only ever describe facts already recorded
        in a round_record -- call this after resolve() for that round so
        there is nothing left for it to influence."""
        with self._lock:
            self._flavor[key] = _sanitize_line(text, FLAVOR_TEXT_MAX_CHARS)

    # -- state export --------------------------------------------------------

    def _encounter_public_locked(self, encounter: Encounter) -> dict:
        return {
            "id": encounter.id,
            "name": encounter.name,
            "flavor": self._flavor.get(f"encounter:{encounter.id}", encounter.flavor),
            "targets": list(encounter.targets),
        }

    def _round_record_public_locked(self, record: dict) -> dict:
        """Overlay narration onto a stored round_record at read time, since
        `set_flavor(f"narration:{round}", text)` is meant to be called after
        resolve() -- the stored record itself is written once, at resolve()
        time, before any narration exists."""
        return {**record, "narration": self._flavor.get(f"narration:{record['round']}", "")}

    @staticmethod
    def _move_public(move: Move) -> dict:
        return {
            "id": move.id,
            "name": move.name,
            "school": move.school,
            "verbs": list(move.verbs),
            "description": move.description,
        }

    def _hero_public_locked(self, hero_id: str, viewer_player_id: str | None) -> dict:
        slot = self._heroes[hero_id]
        hero_def = slot.hero_def
        submitted = self._submitted_current_step_locked(hero_id)
        return {
            "hero_id": hero_id,
            "name": hero_def.name,
            "persona": hero_def.persona,
            "ability_name": hero_def.ability_name,
            "ability_description": hero_def.ability_description,
            "deck": [self._move_public(MOVES[mid]) for mid in hero_def.deck],
            "signature_move": self._move_public(hero_def.signature_move),
            "player_id": slot.player_id,
            "is_companion": self._hero_is_companion_locked(hero_id),
            "active": bool(self._players.get(slot.player_id).active) if slot.player_id else False,
            "items_remaining": slot.items_remaining,
            "voice_calibrated": bool(slot.voice_profile.get("calibrated", False)),
            "submitted_current_step": submitted,
        }

    def _submitted_current_step_locked(self, hero_id: str) -> bool:
        spotlight_id = self._action.hero_id if self._action else self._current_spotlight_hero_id()
        if self.phase == "spotlight_action":
            return True if hero_id != spotlight_id else self._action is not None
        if self.phase == "ally_support":
            return True if hero_id == spotlight_id else hero_id in self._support
        if self.phase == "ally_reaction":
            return True if hero_id == spotlight_id else hero_id in self._reactions
        return True

    def _pending_step_locked(self, viewer_player_id: str | None) -> str | None:
        is_host = viewer_player_id is not None and viewer_player_id == self.host_id
        hero_id = self._player_hero.get(viewer_player_id) if viewer_player_id else None
        if self.phase == "lobby":
            return "start" if is_host else None
        if self.phase == "spotlight_action":
            if hero_id == self._current_spotlight_hero_id() and self._action is None:
                return "declare_action"
            return None
        if self.phase == "ally_support":
            if hero_id is not None and hero_id != self._action.hero_id and hero_id not in self._support:
                return "submit_support"
            if is_host and self._support_complete_locked():
                return "open_draft"
            return None
        if self.phase == "spotlight_draft":
            if hero_id == self._action.hero_id:
                if self._action.rough_text is None:
                    return "submit_rough_text"
                if self._action.variants is None:
                    return "awaiting_variants"
                if self._action.approved_text is None:
                    return "approve_message"
            return None
        if self.phase == "ally_reaction":
            if hero_id is not None and hero_id != self._action.hero_id and hero_id not in self._reactions:
                return "submit_reaction"
            if is_host and self._reactions_complete_locked():
                return "resolve"
            return None
        if self.phase == "reveal":
            return "advance" if is_host else None
        if self.phase == "finished":
            return "replay" if is_host else None
        return None

    def public_state(self, viewer_player_id: str | None = None) -> dict:
        """JSON-safe snapshot. Never includes any token. A hero's move/
        target/desired-outcome are public as soon as declared (current
        action below); support/reaction content stays hidden until
        resolve() reveals it in last_round/history -- only whether a hero
        has gone yet is visible before that."""
        with self._lock:
            players_public = [
                {
                    "player_id": pid,
                    "name": self._players[pid].name,
                    "is_host": self._players[pid].is_host,
                    "active": self._players[pid].active,
                    "hero_id": self._player_hero.get(pid),
                }
                for pid in self._order
            ]
            heroes_public = [self._hero_public_locked(hid, viewer_player_id) for hid in self._hero_order]
            current_encounter = (
                self._encounter_public_locked(self._current_encounter())
                if self.phase != "lobby" and self.phase != "finished"
                else None
            )
            current_action = None
            if self._action is not None:
                move = ALL_MOVES[self._action.move_id]
                current_action = {
                    "hero_id": self._action.hero_id,
                    "move": self._move_public(move),
                    "target_id": self._action.target_id,
                    "desired_outcome": self._action.desired_outcome,
                    "approved_text": self._action.approved_text,
                    "intent": self._action.intent,
                }
            state = {
                "room_id": self.room_id,
                "phase": self.phase,
                "hearts": self.hearts,
                "max_hearts": self.max_hearts,
                "host_id": self.host_id,
                "spotlight_hero_id": self._current_spotlight_hero_id() if self.phase != "lobby" else None,
                "players": players_public,
                "heroes": heroes_public,
                "round_index": self.encounter_index,
                "total_rounds": len(self._encounter_order),
                "encounter": current_encounter,
                "current_action": current_action,
                "last_round": self._round_record_public_locked(self._rounds[-1]) if self._rounds else None,
                "history": [self._round_record_public_locked(r) for r in self._rounds],
                "finished_victory": self.finished_victory,
                "you": None,
            }
            if viewer_player_id is not None and viewer_player_id in self._players:
                viewer = self._players[viewer_player_id]
                hero_id = self._player_hero.get(viewer_player_id)
                encounter = self._current_encounter() if self.phase not in ("lobby",) else None
                draft = None
                if self._action is not None and hero_id == self._action.hero_id and self.phase == "spotlight_draft":
                    draft = {
                        "rough_text": self._action.rough_text,
                        "variants": self._action.variants,
                        "approved_text": self._action.approved_text,
                        "intent": self._action.intent,
                    }
                state["you"] = {
                    "player_id": viewer_player_id,
                    "is_host": viewer.is_host,
                    "active": viewer.active,
                    "hero_id": hero_id,
                    "private_clue": encounter.clues.get(hero_id) if encounter and hero_id else None,
                    "draft": draft,
                    "voice_profile": dict(self._heroes[hero_id].voice_profile) if hero_id else {},
                    "items_remaining": self._heroes[hero_id].items_remaining if hero_id else 0,
                    "pending_step": self._pending_step_locked(viewer_player_id),
                }
            return state


class GameRegistry:
    """In-memory registry of live rooms, keyed by room_id.

    Pure/no I/O -- the transport layer owns HTTP, QR/link generation, and
    any cross-room persistence; this class only tracks which Room objects
    currently exist.
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
