"""NPC template schemas (wave 6B, board note #30).

Covers `wavebasedgame.md` §3.4 (NPC templates), extending
`infinite_stacks.md` §9.7 (Social Encounter) and §19.3 (NPC communication)
with the cast-level structure neither section specified on its own.

The central discipline is **provenance-backed knowledge and disclosure**:
every knowledge atom an NPC can express records who could plausibly know it
and how (`KnowledgeAtom.provenance`), and every atom declares a
`ViewerScope`-flavored disclosure layer (`free` vs `gated`). The engine (a
future wiring wave) is responsible for actually enforcing that a model
prompt for this NPC only ever receives currently-disclosed atoms; this
module's job is to make a **construction-time** guarantee that a gated fact
can never be *reachable* from the free layer in the first place -- see
`NPCTemplate.__post_init__`'s disclosure-leak check, mirrored by the
`check_no_disclosure_leak` validator for defense-in-depth at the pack level.

An NPC has three main objectives and one hidden objective (§3.4); the hidden
objective's existence is public in content (so tests/authors can reason
about it) but its VALUE would only ever be revealed to a viewer through the
same `ViewerScope` discipline everything else in `content/` uses.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .schemas import ContentError, Prose, ViewerScope, validate_id

# ---------------------------------------------------------------------------
# Disclosure layers (§3.4: "free vs. gated information", "disclosure layers")
# ---------------------------------------------------------------------------


class DisclosureLayer(str, Enum):
    FREE = "free"  # the model may express this without any gating check
    GATED = "gated"  # requires a server-validated unlock before it may be expressed


@dataclass(frozen=True)
class Provenance:
    """Who could plausibly know a fact, and how (§2 locked decision 2,
    §3.4). Every `KnowledgeAtom` must declare at least one of these."""

    knower_id: str  # an npc id, "player", or a named role ("anyone_in_room", ...)
    method: str  # how they could know it: "witnessed", "told_by:<id>", "deduced", ...

    def __post_init__(self) -> None:
        if not self.knower_id.strip():
            raise ContentError("provenance must declare a knower_id")
        if not self.method.strip():
            raise ContentError(f"provenance for knower {self.knower_id!r} must declare a method")


@dataclass(frozen=True)
class KnowledgeAtom:
    """One fact an NPC can express, with provenance and a disclosure layer.

    `is_true` distinguishes a true belief from a lie the NPC may tell; a lie
    (`is_true=False`) must still declare provenance for *why the NPC would
    say this* (e.g. self-serving, protecting someone, genuinely mistaken),
    and must be counted by the NPC's `lies` collection, not silently mixed
    into `beliefs`.
    """

    id: str
    statement: str
    is_true: bool
    provenance: tuple[Provenance, ...]
    disclosure: DisclosureLayer

    def __post_init__(self) -> None:
        validate_id(self.id, kind="knowledge_atom")
        if not self.statement.strip():
            raise ContentError(f"knowledge atom {self.id!r} must declare a statement")
        if not self.provenance:
            raise ContentError(
                f"knowledge atom {self.id!r} must declare at least one provenance entry "
                "(who could know this, and how)"
            )


@dataclass(frozen=True)
class Tell:
    """A behavioral tell (§3.4): an observable signal an attentive player can
    notice, distinct from the underlying fact it hints at. Tells are always
    FREE-layer (they are the point of noticing something), but the fact they
    point to may itself be gated."""

    id: str
    prose: Prose
    hints_at_atom_id: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="tell")
        validate_id(self.hints_at_atom_id, kind="knowledge_atom")


class ObjectiveKind(str, Enum):
    MAIN = "main"
    HIDDEN = "hidden"


@dataclass(frozen=True)
class Objective:
    id: str
    kind: ObjectiveKind
    prose: Prose
    viewer_scope: ViewerScope

    def __post_init__(self) -> None:
        validate_id(self.id, kind="objective")
        if self.kind is ObjectiveKind.HIDDEN and self.viewer_scope is ViewerScope.PUBLIC:
            raise ContentError(
                f"objective {self.id!r} is HIDDEN but declares viewer_scope PUBLIC "
                "(a hidden objective's value must not be publicly scoped)"
            )


@dataclass(frozen=True)
class InventoryEntry:
    item_id: str
    quantity: int = 1
    viewer_scope: ViewerScope = ViewerScope.PUBLIC

    def __post_init__(self) -> None:
        validate_id(self.item_id, kind="item")
        if self.quantity < 1:
            raise ContentError(f"inventory entry for {self.item_id!r} quantity must be >= 1")


@dataclass(frozen=True)
class Relationship:
    other_npc_id: str
    kind: str  # e.g. "distrusts", "employs", "sibling_of", "owes_debt_to"
    prose: Prose

    def __post_init__(self) -> None:
        validate_id(self.other_npc_id, kind="npc")
        if not self.kind.strip():
            raise ContentError(f"relationship to {self.other_npc_id!r} must declare a kind")


@dataclass(frozen=True)
class Trigger:
    id: str
    condition: str
    effect_description: str

    def __post_init__(self) -> None:
        validate_id(self.id, kind="npc_trigger")
        if not self.condition.strip():
            raise ContentError(f"npc trigger {self.id!r} must declare a condition")
        if not self.effect_description.strip():
            raise ContentError(f"npc trigger {self.id!r} must declare an effect_description")


@dataclass(frozen=True)
class EmotionalPhysicalState:
    disposition: str  # e.g. "wary", "friendly", "hostile" -- not uniformly neutral (§3.4)
    physical_state: str  # e.g. "healthy", "injured", "restrained"

    def __post_init__(self) -> None:
        if not self.disposition.strip():
            raise ContentError("NPC state must declare a disposition")
        if not self.physical_state.strip():
            raise ContentError("NPC state must declare a physical_state")


@dataclass(frozen=True)
class NPCTemplate:
    id: str
    archetype_pool: tuple[str, ...]
    age: str
    sex_gender_presentation: str
    visual_traits: tuple[str, ...]
    persona_voice: Prose
    stats: Mapping[str, int]
    boundaries: tuple[str, ...]
    preferences: tuple[str, ...]
    fears: tuple[str, ...]
    knowledge: tuple[KnowledgeAtom, ...]
    lies: tuple[str, ...]  # subset of knowledge ids where is_true is False
    tells: tuple[Tell, ...]
    inventory: tuple[InventoryEntry, ...]
    relationships: tuple[Relationship, ...]
    objectives: tuple[Objective, ...]
    triggers: tuple[Trigger, ...]
    state: EmotionalPhysicalState

    def __post_init__(self) -> None:
        validate_id(self.id, kind="npc_template")
        if not self.archetype_pool:
            raise ContentError(f"npc {self.id!r} must declare at least one archetype")
        if not self.age.strip():
            raise ContentError(f"npc {self.id!r} must declare age")
        if not self.sex_gender_presentation.strip():
            raise ContentError(f"npc {self.id!r} must declare sex_gender_presentation")
        if not self.visual_traits:
            raise ContentError(f"npc {self.id!r} must declare at least one visual trait")
        if not self.stats:
            raise ContentError(f"npc {self.id!r} must declare at least one stat")
        if not self.boundaries:
            raise ContentError(f"npc {self.id!r} must declare at least one boundary")
        if not self.fears:
            raise ContentError(f"npc {self.id!r} must declare at least one fear")
        if not self.knowledge:
            raise ContentError(f"npc {self.id!r} must declare at least one knowledge atom")

        knowledge_ids = {atom.id for atom in self.knowledge}

        # lies must reference real knowledge atoms whose is_true is False,
        # and every is_true=False atom must be listed in lies (never
        # silently mixed into the "true belief" pool).
        false_atom_ids = {atom.id for atom in self.knowledge if not atom.is_true}
        unknown_lies = set(self.lies) - knowledge_ids
        if unknown_lies:
            raise ContentError(f"npc {self.id!r} lies reference unknown knowledge atoms: {sorted(unknown_lies)}")
        lies_not_false = set(self.lies) - false_atom_ids
        if lies_not_false:
            raise ContentError(
                f"npc {self.id!r} lists {sorted(lies_not_false)} in lies but those atoms have is_true=True"
            )
        false_not_listed = false_atom_ids - set(self.lies)
        if false_not_listed:
            raise ContentError(
                f"npc {self.id!r} has is_true=False knowledge atoms not listed in lies: {sorted(false_not_listed)}"
            )
        if not self.lies:
            raise ContentError(f"npc {self.id!r} must declare at least one lie (§3.4)")

        for tell in self.tells:
            if tell.hints_at_atom_id not in knowledge_ids:
                raise ContentError(
                    f"npc {self.id!r} tell {tell.id!r} references unknown knowledge atom "
                    f"{tell.hints_at_atom_id!r}"
                )
        if not self.tells:
            raise ContentError(f"npc {self.id!r} must declare at least one tell (§3.4)")

        main_objectives = [o for o in self.objectives if o.kind is ObjectiveKind.MAIN]
        hidden_objectives = [o for o in self.objectives if o.kind is ObjectiveKind.HIDDEN]
        if len(main_objectives) != 3:
            raise ContentError(
                f"npc {self.id!r} must declare exactly 3 main objectives, got {len(main_objectives)}"
            )
        if len(hidden_objectives) != 1:
            raise ContentError(
                f"npc {self.id!r} must declare exactly 1 hidden objective, got {len(hidden_objectives)}"
            )

        # --- Disclosure-leak check (construction-time, per director's task
        # brief): a GATED knowledge atom must not be reachable purely from
        # FREE-layer information. We model "reachable from free" narrowly
        # but concretely: a GATED atom leaks if a FREE tell points directly
        # at it (the tell would let any player infer the gated fact without
        # ever passing whatever gate unlocks it), or if the atom is
        # (self-contradictorily) declared both FREE and also gates itself.
        free_ids = {atom.id for atom in self.knowledge if atom.disclosure is DisclosureLayer.FREE}
        gated_ids = {atom.id for atom in self.knowledge if atom.disclosure is DisclosureLayer.GATED}
        for tell in self.tells:
            if tell.hints_at_atom_id in gated_ids:
                raise ContentError(
                    f"npc {self.id!r} tell {tell.id!r} is FREE-layer but hints_at_atom_id "
                    f"{tell.hints_at_atom_id!r} is GATED -- disclosure leak: a gated fact must be "
                    "unreachable from the free disclosure layer"
                )
        overlap = free_ids & gated_ids
        if overlap:
            raise ContentError(f"npc {self.id!r} knowledge atoms cannot be both FREE and GATED: {sorted(overlap)}")

        for rel in self.relationships:
            if rel.other_npc_id == self.id:
                raise ContentError(f"npc {self.id!r} cannot declare a relationship to itself")
