"""Versioned content schemas for The Lost Meaning: Infinite Stacks (board task #2).

Defines the authored-content data model for backgrounds, skills, cards, items,
conditions, enemies, and puzzle instances. Content is data; mechanics live in
`backend/lan_playground/systems/` (engine lane). This module only describes the
*shape* content must take and the minimal invariants every piece of content must
satisfy before it can be loaded (`loader.py`) or CI-validated (`validators.py`).

Ground rules from infinite_stacks.md §23.1:
  - IDs are stable and globally unique within their type; mechanics reference IDs,
    never display names.
  - Display prose always has an authored fallback (`Prose.fallback`) plus an
    accessible-text equivalent (`Prose.accessible`) so the game is fully playable
    without generated text and without visual-only cues (§24.4, §25).
  - Secret fields declare their authorized viewer scope (`ViewerScope`) rather than
    relying on callers to remember what is private.
  - Every effect compiles to a known op the engine (or a future engine phase) can
    handle -- never arbitrary code (`Effect.compile`, `KNOWN_OPS`).

Effect-op wire shape matches docs/INFINITE_STACKS_CONTRACTS.md §5 exactly
(`{"op": str, "args": dict}`) so the compiled IR needs zero changes when
`systems/` grows real handlers for ops that are `PLANNED` this wave -- only an
op's `OpStatus` in `KNOWN_OPS` flips from `PLANNED`/`STUB` to `LIVE`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Mapping, Sequence

CONTENT_SCHEMA_VERSION = 1

_ID_RE = re.compile(r"^[a-z][a-z0-9_]*$")


class ContentError(ValueError):
    """Raised when authored content violates the schema contract."""


def validate_id(value: str, *, kind: str) -> str:
    if not isinstance(value, str) or not _ID_RE.match(value):
        raise ContentError(
            f"{kind} id {value!r} must be a lowercase snake_case string matching "
            f"{_ID_RE.pattern!r}"
        )
    return value


# ---------------------------------------------------------------------------
# Attributes and skills (§11.1-11.2)
# ---------------------------------------------------------------------------

ATTRIBUTE_IDS = frozenset({"force", "finesse", "insight", "presence"})
SKILL_IDS = frozenset({"bonk", "scheme", "tinker", "read", "wordcraft"})


# ---------------------------------------------------------------------------
# Prose: authored fallback + accessible text (§13.3, §23.2, §24.4, §25)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Prose:
    """Display prose with a mandatory authored fallback and accessible text.

    `fallback` is what renders when generated text is unavailable or fails
    schema validation (§20.3). `accessible` is a text equivalent that does not
    depend on color, imagery, or spatial layout (§25) -- it may equal
    `fallback` when the fallback is already plain descriptive text.
    """

    fallback: str
    accessible: str

    def __post_init__(self) -> None:
        if not self.fallback.strip():
            raise ContentError("Prose.fallback must not be empty")
        if not self.accessible.strip():
            raise ContentError("Prose.accessible must not be empty")


# ---------------------------------------------------------------------------
# Viewer scope for secret fields (§23.1, §21.3)
# ---------------------------------------------------------------------------


class ViewerScope(str, Enum):
    PUBLIC = "public"        # visible in every viewer's projection
    OWNER = "owner"          # visible only to the hero/slot the field is assigned to
    PARTY = "party"          # visible to every hero currently in the run
    ENGINE_ONLY = "engine_only"  # never projected to any player view (e.g. puzzle solution)


@dataclass(frozen=True)
class SecretField:
    """A field whose visibility must be declared, never assumed (§23.1, §23.2)."""

    value: Any
    viewer_scope: ViewerScope


# ---------------------------------------------------------------------------
# Effect IR: content ops compile to the engine's event-dict wire shape
# ---------------------------------------------------------------------------


class OpStatus(str, Enum):
    LIVE = "live"        # systems/ ships a real, wired handler this wave
    STUB = "stub"        # named in the contract as this wave's authoring vocabulary;
                         # no systems/ dispatcher exists yet (see note below)
    PLANNED = "planned"  # declared by content; no systems/ handler yet (later phase)


@dataclass(frozen=True)
class OpSpec:
    required_args: tuple[str, ...]
    status: OpStatus


# Wave-1 ops (`reveal_room`, `grant_check`, `spend_energy`, `emit_fact`) come
# verbatim from docs/INFINITE_STACKS_CONTRACTS.md §5. WAVE 2 UPDATE (2026-07-19,
# stacks-effects, board task #5): all four now have real, wired handlers in
# `systems/effects.py` (`dispatch()`), reachable through the reducer via
# systems/puzzles.py's Mystery Chamber success/failure consequences, and are
# therefore LIVE. (Wave-1 note for history: they were STUB for one wave --
# `systems/` genuinely shipped no dispatcher of any kind before this.)
# The remaining ops are this content pack's declared vocabulary for cards, items,
# conditions, and enemies (Phase 3-5 per infinite_stacks.md §27); engine explicitly
# scopes combat/cards/inventory out of this wave too (contracts doc §10), so these
# are PLANNED rather than unknown. Extend this table -- never special-case an op
# name inside a card/item/enemy definition.
KNOWN_OPS: dict[str, OpSpec] = {
    "reveal_room": OpSpec(("connector",), OpStatus.LIVE),
    "spend_energy": OpSpec(("amount",), OpStatus.LIVE),
    "grant_check": OpSpec(("attribute", "skill", "dc"), OpStatus.LIVE),
    "emit_fact": OpSpec(("fact_id",), OpStatus.LIVE),
    "damage": OpSpec(("amount",), OpStatus.PLANNED),
    "heal": OpSpec(("amount",), OpStatus.PLANNED),
    "modify_hp": OpSpec(("amount",), OpStatus.PLANNED),
    "apply_condition": OpSpec(("condition_id",), OpStatus.PLANNED),
    "remove_condition": OpSpec(("condition_id",), OpStatus.PLANNED),
    "grant_advantage": OpSpec((), OpStatus.PLANNED),
    "grant_disadvantage": OpSpec((), OpStatus.PLANNED),
    "move_target": OpSpec(("distance",), OpStatus.PLANNED),
    "block_damage": OpSpec(("amount",), OpStatus.PLANNED),
    "stabilize": OpSpec((), OpStatus.PLANNED),
    "reveal_tell": OpSpec((), OpStatus.PLANNED),
    "reveal_clue": OpSpec(("clue_id",), OpStatus.PLANNED),
    "combine_effects": OpSpec(("slots",), OpStatus.PLANNED),
    "grant_card": OpSpec(("card_id",), OpStatus.PLANNED),
    "exhaust_card": OpSpec(("card_id",), OpStatus.PLANNED),
    "custom_narrative": OpSpec((), OpStatus.PLANNED),
}


@dataclass(frozen=True)
class Effect:
    """One effect op. Compiles 1:1 to the engine's event-dict IR (§5 of the
    contracts doc): `{"op": str, "args": dict}`."""

    op: str
    args: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.op not in KNOWN_OPS:
            raise ContentError(f"effect op {self.op!r} has no known handler (unknown op)")
        missing = [k for k in KNOWN_OPS[self.op].required_args if k not in self.args]
        if missing:
            raise ContentError(f"effect op {self.op!r} missing required args: {missing}")

    def compile(self) -> dict[str, Any]:
        return {"op": self.op, "args": dict(self.args)}


def compile_effects(effects: Sequence[Effect]) -> list[dict[str, Any]]:
    """Compile a list of Effects into the event-dict IR.

    This is the single seam between content and the engine's op vocabulary --
    only this function and `KNOWN_OPS` need to change when ops are renamed.
    """

    return [effect.compile() for effect in effects]


def _effects_from_raw(raw: Sequence[Mapping[str, Any]] | None) -> tuple[Effect, ...]:
    if not raw:
        return ()
    return tuple(Effect(op=item["op"], args=item.get("args", {})) for item in raw)


# ---------------------------------------------------------------------------
# Skills (§11.2)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Skill:
    id: str
    name: str
    prose: Prose
    typical_uses: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="skill")
        if self.id not in SKILL_IDS:
            raise ContentError(f"skill id {self.id!r} is not one of {sorted(SKILL_IDS)}")


# ---------------------------------------------------------------------------
# Backgrounds (§11.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignatureAbility:
    id: str
    name: str
    prose: Prose
    frequency: str  # e.g. "once_per_floor", "once_per_room", "once_per_fight"
    effects: tuple[Effect, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="signature_ability")


@dataclass(frozen=True)
class Background:
    id: str
    name: str
    prose: Prose
    attribute_bonus: str
    skill_ranks: Mapping[str, int]
    starting_item_ids: tuple[str, ...]
    signature_ability: SignatureAbility

    def __post_init__(self) -> None:
        validate_id(self.id, kind="background")
        if self.attribute_bonus not in ATTRIBUTE_IDS:
            raise ContentError(
                f"background {self.id!r} attribute_bonus {self.attribute_bonus!r} "
                f"not in {sorted(ATTRIBUTE_IDS)}"
            )
        if not self.skill_ranks:
            raise ContentError(f"background {self.id!r} must grant at least one skill rank")
        for skill_id, rank in self.skill_ranks.items():
            if skill_id not in SKILL_IDS:
                raise ContentError(f"background {self.id!r} references unknown skill {skill_id!r}")
            if rank not in (0, 1, 2, 3):
                raise ContentError(f"background {self.id!r} skill rank {rank!r} must be 0-3")


# ---------------------------------------------------------------------------
# Cards (§13.2-13.3)
# ---------------------------------------------------------------------------


class CardTiming(str, Enum):
    MAIN_ACTION = "main_action"
    QUICK_INTERACTION = "quick_interaction"
    REACTION = "reaction"
    FREE_SPEECH = "free_speech"


class CardEndState(str, Enum):
    DISCARD = "discard"
    EXHAUST = "exhaust"


@dataclass(frozen=True)
class CheckOutcomes:
    """Degrees of outcome per §12.3, keyed to check margin bands."""

    strong_success: tuple[Effect, ...] = ()  # margin >= +5
    success: tuple[Effect, ...] = ()  # margin 0..+4
    cost: tuple[Effect, ...] = ()  # margin -1..-4
    setback: tuple[Effect, ...] = ()  # margin <= -5


@dataclass(frozen=True)
class CardCheck:
    attribute: str
    skill: str
    dc: int
    outcomes: CheckOutcomes

    def __post_init__(self) -> None:
        if self.attribute not in ATTRIBUTE_IDS:
            raise ContentError(f"card check attribute {self.attribute!r} invalid")
        if self.skill not in SKILL_IDS:
            raise ContentError(f"card check skill {self.skill!r} invalid")
        if self.dc <= 0:
            raise ContentError("card check dc must be positive")


@dataclass(frozen=True)
class Card:
    id: str
    name: str
    prose: Prose
    accessible_text: str
    timing: CardTiming
    range: str
    legal_targets: tuple[str, ...]
    required_state: tuple[str, ...] = ()
    base_effects: tuple[Effect, ...] = ()
    check: CardCheck | None = None
    combination_tags: tuple[str, ...] = ()
    end_state: CardEndState = CardEndState.DISCARD
    source: str = "general"

    def __post_init__(self) -> None:
        validate_id(self.id, kind="card")
        if not self.accessible_text.strip():
            raise ContentError(f"card {self.id!r} missing accessible_text (§13.3, §25)")
        if not self.legal_targets:
            raise ContentError(f"card {self.id!r} must declare at least one legal target")
        if self.check is None and not self.base_effects:
            raise ContentError(
                f"card {self.id!r} must declare an exact base effect or a check+outcome table"
            )


# ---------------------------------------------------------------------------
# Items (§13.5-13.6)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Item:
    id: str
    name: str
    prose: Prose
    slot_cost: int = 1
    consumable: bool = False
    granted_card_ids: tuple[str, ...] = ()
    passive_effects: tuple[Effect, ...] = ()
    use_effects: tuple[Effect, ...] = ()
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="item")
        if self.slot_cost < 1:
            raise ContentError(f"item {self.id!r} slot_cost must be >= 1")
        if not (self.granted_card_ids or self.passive_effects or self.use_effects):
            raise ContentError(
                f"item {self.id!r} must grant a card, a passive effect, or a use effect "
                "(§13.4: items change options, not just numbers)"
            )


# ---------------------------------------------------------------------------
# Conditions / statuses (§16.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Treatment:
    id: str
    prose: Prose
    effects: tuple[Effect, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="treatment")


@dataclass(frozen=True)
class Condition:
    id: str
    name: str
    prose: Prose
    primary_effect: Effect
    duration: str
    treatments: tuple[Treatment, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="condition")
        if not self.duration.strip():
            raise ContentError(f"condition {self.id!r} must declare a visible duration")
        if not self.treatments:
            raise ContentError(f"condition {self.id!r} has no treatment path (§16.4)")


# ---------------------------------------------------------------------------
# Enemies (§14.6, §15.1)
# ---------------------------------------------------------------------------


class ThreatTier(str, Enum):
    MINION = "minion"
    STANDARD = "standard"
    SPECIALIST = "specialist"
    ELITE = "elite"


THREAT_COST_BY_TIER = {
    ThreatTier.MINION: 1,
    ThreatTier.STANDARD: 2,
    ThreatTier.SPECIALIST: 3,
    # elite is authored in-range (4-5), see Enemy.__post_init__
}


@dataclass(frozen=True)
class EnemyIntent:
    id: str
    prose: Prose  # the telegraph: fallback + accessible text, shown before the enemy acts
    trigger: str
    effects: tuple[Effect, ...]
    counterplay: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="enemy_intent")
        if not self.trigger.strip():
            raise ContentError(f"enemy intent {self.id!r} must declare a trigger condition")
        if not self.counterplay.strip():
            raise ContentError(
                f"enemy intent {self.id!r} has no counterplay text (§14.6: readable intent, "
                "not a hidden script)"
            )


@dataclass(frozen=True)
class Enemy:
    id: str
    name: str
    family: str
    prose: Prose
    threat_tier: ThreatTier
    threat_cost: int
    hp: int
    defense: int
    intents: tuple[EnemyIntent, ...]
    resists: tuple[str, ...] = ()
    weaknesses: tuple[str, ...] = ()
    non_elimination_routes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="enemy")
        if not self.family.strip():
            raise ContentError(f"enemy {self.id!r} must declare a family")
        if self.hp <= 0:
            raise ContentError(f"enemy {self.id!r} hp must be positive")
        if not self.intents:
            raise ContentError(f"enemy {self.id!r} has no readable intent (§14.6)")
        if self.threat_tier is ThreatTier.ELITE:
            if not (4 <= self.threat_cost <= 5):
                raise ContentError(f"enemy {self.id!r} elite threat_cost must be 4-5 (§15.1)")
        else:
            expected = THREAT_COST_BY_TIER[self.threat_tier]
            if self.threat_cost != expected:
                raise ContentError(
                    f"enemy {self.id!r} threat_cost {self.threat_cost} must equal "
                    f"{expected} for tier {self.threat_tier.value!r} (§15.1)"
                )


# ---------------------------------------------------------------------------
# Puzzle instances (§10.1) and the four-object structure (§10.2)
# ---------------------------------------------------------------------------


class PuzzleObjectRole(str, Enum):
    ANCHOR = "anchor"  # proves one dependable fact
    KEY = "key"  # directly manipulates or identifies the solution
    CONTRADICTION = "contradiction"  # reveals a fact is conditional/false/context-dependent
    RED_HERRING = "red_herring"  # plausible, informative, not required


@dataclass(frozen=True)
class PuzzleObject:
    id: str
    role: PuzzleObjectRole
    prose: Prose
    clue_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="puzzle_object")


@dataclass(frozen=True)
class PuzzleClue:
    id: str
    prose: Prose
    viewer_scope: ViewerScope
    reveals: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_id(self.id, kind="puzzle_clue")


@dataclass(frozen=True)
class PuzzleTemplateMeta:
    """Registry metadata for a puzzle template. The generator/solver functions
    themselves are code (`content/puzzles/`), never data -- the LLM and content
    packs may name and describe a template's facts but never own its solution
    (infinite_stacks.md §10.1, §20.2)."""

    id: str
    family: str
    name: str
    prose: Prose
    difficulty_range: tuple[int, int] = (1, 5)

    def __post_init__(self) -> None:
        validate_id(self.id, kind="puzzle_template")
        lo, hi = self.difficulty_range
        if not (1 <= lo <= hi <= 5):
            raise ContentError(f"puzzle template {self.id!r} difficulty_range must be within 1-5")


@dataclass(frozen=True)
class PuzzleInstance:
    """Exactly the §10.1 field set. `solution` and `private_clue_assignments` are
    ENGINE_ONLY / OWNER-scoped respectively -- never present in a public
    projection (§21.3, §23.2)."""

    id: str
    template_id: str
    seed: int
    difficulty: int
    objects: tuple[PuzzleObject, ...]
    clues: tuple[PuzzleClue, ...]
    private_clue_assignments: Mapping[str, tuple[str, ...]]
    solution: Any
    accepted_solutions: tuple[Any, ...]
    hint_steps: tuple[Prose, ...]
    attempt_limit: int | None
    failure_events: tuple[Effect, ...]
    success_events: tuple[Effect, ...]
    reward_table: str
    validator_version: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="puzzle_instance")
        validate_id(self.template_id, kind="puzzle_template")
        if not (1 <= self.difficulty <= 5):
            raise ContentError(f"puzzle instance {self.id!r} difficulty must be 1-5")
        roles = {obj.role for obj in self.objects}
        required_roles = {
            PuzzleObjectRole.ANCHOR,
            PuzzleObjectRole.KEY,
            PuzzleObjectRole.CONTRADICTION,
            PuzzleObjectRole.RED_HERRING,
        }
        missing_roles = required_roles - roles
        if missing_roles:
            raise ContentError(
                f"puzzle instance {self.id!r} missing required object roles: "
                f"{sorted(r.value for r in missing_roles)} (§10.2 four-object structure)"
            )
        if self.solution not in self.accepted_solutions:
            raise ContentError(
                f"puzzle instance {self.id!r} solution must be included in accepted_solutions"
            )
        if not self.hint_steps:
            raise ContentError(f"puzzle instance {self.id!r} must declare hint_steps (§10.4)")
        if not self.failure_events:
            raise ContentError(
                f"puzzle instance {self.id!r} must declare a fail-forward consequence (§9.1, §10.4)"
            )
        clue_ids = {c.id for c in self.clues}
        for obj in self.objects:
            unknown = set(obj.clue_ids) - clue_ids
            if unknown:
                raise ContentError(
                    f"puzzle instance {self.id!r} object {obj.id!r} references unknown "
                    f"clue ids: {sorted(unknown)}"
                )


# ---------------------------------------------------------------------------
# Accomplishments (§17.2, §17.6) -- minimal shape used only by the
# "permanent reward from an unbounded repeatable" validator rule (§23.2).
# Not part of this wave's authored content target; kept small on purpose.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Accomplishment:
    id: str
    name: str
    prose: Prose
    repeatable: bool
    repeat_cap: int | None  # None means unbounded
    trophy_marks: int
    permanent_unlock_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.id, kind="accomplishment")
        if self.trophy_marks < 0:
            raise ContentError(f"accomplishment {self.id!r} trophy_marks must be >= 0")


# ---------------------------------------------------------------------------
# The loaded content pack
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ContentPack:
    """A fully loaded, self-consistent content pack (before cross-file
    validators.py checks run)."""

    schema_version: int
    pack_id: str
    backgrounds: Mapping[str, Background] = field(default_factory=dict)
    skills: Mapping[str, Skill] = field(default_factory=dict)
    cards: Mapping[str, Card] = field(default_factory=dict)
    items: Mapping[str, Item] = field(default_factory=dict)
    conditions: Mapping[str, Condition] = field(default_factory=dict)
    enemies: Mapping[str, Enemy] = field(default_factory=dict)
    puzzle_templates: Mapping[str, PuzzleTemplateMeta] = field(default_factory=dict)
