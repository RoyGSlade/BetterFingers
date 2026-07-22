"""Room/object template schemas (wave 6B, board note #30).

Covers `wavebasedgame.md` §3.3 (room/object templates) and §3.8 (books, as
one authorable `RoomObject` interaction target). Pure data + construction-time
validation, same discipline as `schemas.py`: content is data referencing IDs,
every declared effect compiles to a `schemas.KNOWN_OPS` entry (unknown ops
are rejected at construction, never at runtime), and secret/gated fields
declare their `ViewerScope` rather than relying on callers to remember.

Object instances (§3.3): every physical object is its own versioned
instance -- states, visibility tiers, state transitions, triggers, 0/1/many
supported intents, multiple uses, deterministic effects. Furniture and set
dressing get real secondary interactions (`ObjectInteraction`), not flavor
text alone.

Room templates (§3.3): archetype/purpose/layout, objects, atmosphere,
visible facts, subtle inconsistencies, secrets, clue graph, mechanisms,
interactables, NPC links, subobjectives, hazards, encounter hooks,
persistence flags, lattice contribution (`content.lattice`), and narration
facts (the bounded fact set a Narrator packet may draw from -- see §3.5/§20.3
for why this must be a closed, declared set rather than "whatever the room
object happens to expose").

Placement-backward-from-payoff (§29 mitigation, restated by §3.3): a room
template declares its `payoff_interaction` explicitly -- the one distinctive
interaction/consequence the room was built around -- rather than leaving
"why does this room exist" implicit in a pile of objects. `RoomTemplate`
requires that field to reference a real `ObjectInteraction` on a real
`RoomObject` in the same room, so the payoff can never silently rot into a
dangling reference as the room's objects change.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .schemas import ContentError, Effect, Prose, ViewerScope, validate_id
from .lattice import LatticeContribution

# ---------------------------------------------------------------------------
# Intents an object interaction can support (§3.3: "0/1/many supported
# intents"). This mirrors the Interpreter's intent vocabulary (§3.5) at the
# level content can name today -- the brain/ package (lane A, out of scope
# here) owns the full Interpreter intent-candidate shape; this is just the
# closed set of verbs an *object* can declare it responds to, so construction
# fails loudly on a typo instead of silently never matching anything.
# ---------------------------------------------------------------------------

OBJECT_INTENT_VERBS = frozenset(
    {
        "look",
        "inspect",
        "move",
        "open",
        "close",
        "search",
        "take",
        "use",
        "read",
        "light",
        "extinguish",
        "sit",
        "hide",
        "listen",
        "smell",
        "combine",
    }
)


# ---------------------------------------------------------------------------
# Object instances (§3.3)
# ---------------------------------------------------------------------------


class ObjectVisibility(str, Enum):
    """Visibility tiers an object state can be in. FREE is always narratable;
    NOTICED requires a prior discovery (a check, another interaction, or an
    engine-declared reveal); HIDDEN is never narrated until promoted to
    NOTICED or FREE by a real state transition -- never by prose alone
    (§20.2: the LLM may not reveal secret information not authorized for the
    requesting viewer)."""

    FREE = "free"
    NOTICED = "noticed"
    HIDDEN = "hidden"


@dataclass(frozen=True)
class ObjectState:
    """One named state an object can be in (e.g. "rug_undisturbed",
    "rug_displaced"). `visibility` gates whether this state's `prose` may be
    narrated to a viewer who has not yet met the visibility condition; the
    engine (future wiring wave) owns actually tracking who has "noticed"
    what -- this dataclass only declares the tier."""

    id: str
    prose: Prose
    visibility: ObjectVisibility

    def __post_init__(self) -> None:
        validate_id(self.id, kind="object_state")


@dataclass(frozen=True)
class StateTransition:
    """A deterministic move from one object state to another, fired by a
    named trigger. `effects` compile through the same `Effect`/`KNOWN_OPS`
    seam every other content type uses -- construction rejects any op the
    engine doesn't know (§20.2, §3.3)."""

    id: str
    from_state: str
    to_state: str
    trigger: str
    effects: tuple[Effect, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.id, kind="state_transition")
        if not self.from_state.strip():
            raise ContentError(f"state transition {self.id!r} must declare from_state")
        if not self.to_state.strip():
            raise ContentError(f"state transition {self.id!r} must declare to_state")
        if not self.trigger.strip():
            raise ContentError(f"state transition {self.id!r} must declare a trigger")


@dataclass(frozen=True)
class ObjectInteraction:
    """One supported intent on an object: which verb it responds to, in
    which of the object's states it is legal, and what it deterministically
    does. §3.3 requires furniture/set dressing to carry *real* secondary
    interactions -- this is that contract: an interaction with no effects
    and no state_transition_id is rejected, so a "flavor-only" entry can
    never masquerade as a supported intent."""

    id: str
    verb: str
    legal_states: tuple[str, ...]
    prose: Prose
    effects: tuple[Effect, ...] = ()
    state_transition_id: str | None = None
    repeatable: bool = True  # "multiple uses" (§3.3) unless explicitly one-shot
    reveals_state: str | None = None  # promotes a HIDDEN/NOTICED object state, if any

    def __post_init__(self) -> None:
        validate_id(self.id, kind="object_interaction")
        if self.verb not in OBJECT_INTENT_VERBS:
            raise ContentError(
                f"object interaction {self.id!r} verb {self.verb!r} not in {sorted(OBJECT_INTENT_VERBS)}"
            )
        if not self.legal_states:
            raise ContentError(f"object interaction {self.id!r} must declare at least one legal_states entry")
        if not self.effects and not self.state_transition_id:
            raise ContentError(
                f"object interaction {self.id!r} must have a real effect or state transition "
                "(§3.3: secondary interactions must be real, not flavor text alone)"
            )


@dataclass(frozen=True)
class BookProvenance:
    """§3.8/§18.3: structured facts + provenance. A book's individual
    `facts` are the authoritative record; any misleading passage must be
    explicitly flagged as authored fiction or an unreliable narrator rather
    than left to look like an accidental hallucination."""

    fact_id: str
    statement: str
    is_reliable: bool  # False marks explicitly-authored fiction/unreliable-narrator text
    source: str  # who/what asserts this fact in-world (author, subject, event id, ...)

    def __post_init__(self) -> None:
        validate_id(self.fact_id, kind="book_fact")
        if not self.statement.strip():
            raise ContentError(f"book fact {self.fact_id!r} must declare a statement")
        if not self.source.strip():
            raise ContentError(f"book fact {self.fact_id!r} must declare a source (§18.3 provenance)")


@dataclass(frozen=True)
class BookContent:
    """A book/note object's structured record (§3.8, §18.3). Distinct from
    `ContentPack`-level `Book` machinery (not modeled this wave -- see
    docs/INFINITE_STACKS_STUDY_SLICE.md open questions): this is the minimal
    per-object shape needed so a Study room's books can carry real secondary
    interactions (read) backed by facts rather than free text."""

    id: str
    title: str
    facts: tuple[BookProvenance, ...]

    def __post_init__(self) -> None:
        validate_id(self.id, kind="book_content")
        if not self.title.strip():
            raise ContentError(f"book {self.id!r} must declare a title")
        if not self.facts:
            raise ContentError(f"book {self.id!r} must declare at least one structured fact (§18.3)")
        for f in self.facts:
            if not f.is_reliable and not any(tag in f.source.lower() for tag in ("fiction", "unreliable")):
                raise ContentError(
                    f"book {self.id!r} fact {f.fact_id!r} is marked is_reliable=False but its source "
                    f"{f.source!r} does not self-flag as authored fiction/unreliable narrator (§3.8/§18.3: "
                    "misleading text must be explicitly authored, never an accidental hallucination)"
                )


@dataclass(frozen=True)
class RoomObject:
    """A physical object instance in a room (§3.3): versioned via `states`,
    with declared `interactions` (0/1/many supported intents) and
    `transitions` between named states. Furniture/set dressing (fireplace,
    rug, desk, chairs, decor, books) authors real interactions here, not
    just a `prose` blob."""

    id: str
    version: int
    name: str
    initial_state: str
    states: tuple[ObjectState, ...]
    interactions: tuple[ObjectInteraction, ...]
    transitions: tuple[StateTransition, ...] = ()
    book: BookContent | None = None

    def __post_init__(self) -> None:
        validate_id(self.id, kind="room_object")
        if self.version < 1:
            raise ContentError(f"room object {self.id!r} version must be >= 1")
        if not self.states:
            raise ContentError(f"room object {self.id!r} must declare at least one state")
        state_ids = {s.id for s in self.states}
        if self.initial_state not in state_ids:
            raise ContentError(
                f"room object {self.id!r} initial_state {self.initial_state!r} not among declared states {sorted(state_ids)}"
            )
        for interaction in self.interactions:
            unknown = set(interaction.legal_states) - state_ids
            if unknown:
                raise ContentError(
                    f"room object {self.id!r} interaction {interaction.id!r} references unknown states {sorted(unknown)}"
                )
            if interaction.reveals_state is not None and interaction.reveals_state not in state_ids:
                raise ContentError(
                    f"room object {self.id!r} interaction {interaction.id!r} reveals unknown state "
                    f"{interaction.reveals_state!r}"
                )
        transition_ids = {t.id for t in self.transitions}
        for interaction in self.interactions:
            if interaction.state_transition_id is not None and interaction.state_transition_id not in transition_ids:
                raise ContentError(
                    f"room object {self.id!r} interaction {interaction.id!r} references unknown "
                    f"state_transition_id {interaction.state_transition_id!r}"
                )
        for transition in self.transitions:
            if transition.from_state not in state_ids:
                raise ContentError(
                    f"room object {self.id!r} transition {transition.id!r} from_state "
                    f"{transition.from_state!r} not among declared states"
                )
            if transition.to_state not in state_ids:
                raise ContentError(
                    f"room object {self.id!r} transition {transition.id!r} to_state "
                    f"{transition.to_state!r} not among declared states"
                )

    def state_by_id(self, state_id: str) -> ObjectState:
        for s in self.states:
            if s.id == state_id:
                return s
        raise ContentError(f"room object {self.id!r} has no state {state_id!r}")


# ---------------------------------------------------------------------------
# Room template (§3.3)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ClueLink:
    """One edge in a room's clue graph: an object/interaction that reveals a
    named clue, optionally gated behind another clue already being known."""

    clue_id: str
    source_object_id: str
    source_interaction_id: str
    requires_clue_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_id(self.clue_id, kind="clue")


@dataclass(frozen=True)
class Secret:
    """A room secret: an id, the fact it protects, and the viewer scope it is
    authored at until revealed. Distinct from a `ClueLink` in that a secret
    need not be part of the puzzle-style clue graph (e.g. an NPC's private
    history) -- both may reference the same underlying fact id."""

    id: str
    fact_id: str
    prose: Prose
    viewer_scope: ViewerScope
    revealed_by_interaction_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.id, kind="secret")
        validate_id(self.fact_id, kind="fact")


@dataclass(frozen=True)
class SubObjective:
    id: str
    prose: Prose
    reward_fact_id: str | None = None

    def __post_init__(self) -> None:
        validate_id(self.id, kind="subobjective")


@dataclass(frozen=True)
class Hazard:
    id: str
    prose: Prose
    trigger: str
    effects: tuple[Effect, ...]

    def __post_init__(self) -> None:
        validate_id(self.id, kind="hazard")
        if not self.trigger.strip():
            raise ContentError(f"hazard {self.id!r} must declare a trigger")
        if not self.effects:
            raise ContentError(f"hazard {self.id!r} must declare at least one effect")


@dataclass(frozen=True)
class EncounterHook:
    """A pointer to a non-room-family mechanic a room can trigger (e.g. a
    Conflict encounter, a Social Encounter with a linked NPC). This module
    does not model Conflict/Social payloads itself (out of scope -- owned by
    `combat`/a future social package); it only records the hook id + which
    kind of encounter it points at so a room template stays declarative."""

    id: str
    kind: str  # e.g. "conflict", "social", "puzzle"
    trigger: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="encounter_hook")
        if not self.kind.strip():
            raise ContentError(f"encounter hook {self.id!r} must declare a kind")
        if not self.trigger.strip():
            raise ContentError(f"encounter hook {self.id!r} must declare a trigger")


@dataclass(frozen=True)
class NarrationFact:
    """One fact a Narrator packet (§3.5/§20.3) is authorized to draw from for
    this room, at a given viewer scope. This is the bounded fact set --
    generation requests declare `authorized_facts`; this dataclass is the
    authoring side of that same contract, scoped to the room."""

    fact_id: str
    prose: Prose
    viewer_scope: ViewerScope

    def __post_init__(self) -> None:
        validate_id(self.fact_id, kind="fact")


@dataclass(frozen=True)
class PayoffInteraction:
    """The distinctive interaction/consequence a room was designed backward
    from (§29 mitigation, §3.3). Required on every `RoomTemplate` so a room
    reads as intentional rather than shuffled -- validated to reference a
    real object + interaction id declared in the same room."""

    object_id: str
    interaction_id: str
    description: str

    def __post_init__(self) -> None:
        validate_id(self.object_id, kind="room_object")
        validate_id(self.interaction_id, kind="object_interaction")
        if not self.description.strip():
            raise ContentError("payoff interaction must declare a description")


@dataclass(frozen=True)
class RoomTemplate:
    id: str
    archetype: str  # one of the §7.2 d8 room families, e.g. "study"
    purpose: str
    layout: str
    atmosphere: str
    condition: str
    cleanliness: str
    objects: tuple[RoomObject, ...]
    visible_facts: tuple[NarrationFact, ...]
    subtle_inconsistencies: tuple[NarrationFact, ...]
    secrets: tuple[Secret, ...]
    clue_graph: tuple[ClueLink, ...]
    npc_ids: tuple[str, ...]
    subobjectives: tuple[SubObjective, ...]
    hazards: tuple[Hazard, ...]
    encounter_hooks: tuple[EncounterHook, ...]
    lattice_contribution: LatticeContribution
    payoff_interaction: PayoffInteraction
    narration_facts: tuple[NarrationFact, ...]
    persistent: bool = True  # persistence flag: does room state survive across visits

    def __post_init__(self) -> None:
        validate_id(self.id, kind="room_template")
        for field_name, value in (
            ("archetype", self.archetype),
            ("purpose", self.purpose),
            ("layout", self.layout),
            ("atmosphere", self.atmosphere),
            ("condition", self.condition),
            ("cleanliness", self.cleanliness),
        ):
            if not value.strip():
                raise ContentError(f"room template {self.id!r} must declare {field_name}")
        if not self.objects:
            raise ContentError(f"room template {self.id!r} must declare at least one object")

        all_object_ids = [obj.id for obj in self.objects]
        object_ids = set(all_object_ids)
        if len(all_object_ids) != len(object_ids):
            duplicates = {oid for oid in all_object_ids if all_object_ids.count(oid) > 1}
            raise ContentError(f"room template {self.id!r} has duplicate object ids: {sorted(duplicates)}")

        # Payoff interaction must reference a real object + interaction pair
        # declared in this room (§29: the payoff must never dangle).
        payoff_obj = next((o for o in self.objects if o.id == self.payoff_interaction.object_id), None)
        if payoff_obj is None:
            raise ContentError(
                f"room template {self.id!r} payoff_interaction references unknown object "
                f"{self.payoff_interaction.object_id!r}"
            )
        interaction_ids = {i.id for i in payoff_obj.interactions}
        if self.payoff_interaction.interaction_id not in interaction_ids:
            raise ContentError(
                f"room template {self.id!r} payoff_interaction references unknown interaction "
                f"{self.payoff_interaction.interaction_id!r} on object {payoff_obj.id!r}"
            )

        # Clue graph must only reference real objects/interactions and, when
        # gated, real prior clue ids declared elsewhere in the same graph.
        all_clue_ids = {link.clue_id for link in self.clue_graph}
        for link in self.clue_graph:
            if link.source_object_id not in object_ids:
                raise ContentError(
                    f"room template {self.id!r} clue {link.clue_id!r} references unknown object "
                    f"{link.source_object_id!r}"
                )
            source_obj = next(o for o in self.objects if o.id == link.source_object_id)
            if link.source_interaction_id not in {i.id for i in source_obj.interactions}:
                raise ContentError(
                    f"room template {self.id!r} clue {link.clue_id!r} references unknown interaction "
                    f"{link.source_interaction_id!r} on object {link.source_object_id!r}"
                )
            unknown_deps = set(link.requires_clue_ids) - all_clue_ids
            if unknown_deps:
                raise ContentError(
                    f"room template {self.id!r} clue {link.clue_id!r} requires unknown clue ids: "
                    f"{sorted(unknown_deps)}"
                )

        # Secrets that declare a revealing interaction must reference a real
        # object+interaction pair too (defense-in-depth against a dangling
        # secret that visibility rules alone wouldn't catch).
        for secret in self.secrets:
            if secret.revealed_by_interaction_id is not None:
                found = any(
                    secret.revealed_by_interaction_id in {i.id for i in obj.interactions} for obj in self.objects
                )
                if not found:
                    raise ContentError(
                        f"room template {self.id!r} secret {secret.id!r} references unknown "
                        f"revealed_by_interaction_id {secret.revealed_by_interaction_id!r}"
                    )
