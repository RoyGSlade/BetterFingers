"""Character creation: attribute dice, assignment, and derived stats
(infinite_stacks.md §11.1).

Zero I/O, zero domain/systems imports. `ATTRIBUTE_NAMES`/`SKILL_NAMES` match
`combat.models.ATTRIBUTE_NAMES`/`SKILL_NAMES` verbatim (not imported --
duplicated on purpose, same reasoning `combat/models.py` gives for not
depending on `content.schemas.Enemy`: this package must stay decoupled from a
sibling wave's module even though the vocabulary happens to line up, so wave-4
wiring is a values match rather than an import dependency) so a wave-4 adapter
can build a `combat.models.HeroCombatant` from a `HeroSheet` with a plain
field-by-field copy.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Mapping

from .rng import HeroesRNG, roll_d4

ATTRIBUTE_NAMES = ("force", "finesse", "insight", "presence")
SKILL_NAMES = ("bonk", "scheme", "tinker", "read", "wordcraft")

MAX_ATTRIBUTE = 5  # background bonus caps at 5 (§11.3)


class CreationError(ValueError):
    """Raised when a creation step violates the §11.1 rules."""


@dataclass(frozen=True)
class DiceRoll:
    """Four simultaneously-rolled, visible d4 results, in roll order -- the
    exact data the visible-dice UI renders before the player assigns them."""

    values: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        if len(self.values) != 4:
            raise CreationError("DiceRoll must contain exactly four dice")
        for v in self.values:
            if not (1 <= v <= 4):
                raise CreationError(f"attribute die result {v!r} out of d4 range 1-4")


def roll_attribute_dice(rng: HeroesRNG) -> DiceRoll:
    """Roll four visible d4s simultaneously (§11.1). Deterministic under a
    seeded `HeroesRNG` -- same seed always produces the same four values in
    the same order."""

    return DiceRoll(values=(roll_d4(rng), roll_d4(rng), roll_d4(rng), roll_d4(rng)))


@dataclass(frozen=True)
class Attributes:
    force: int
    finesse: int
    insight: int
    presence: int

    def get(self, name: str) -> int:
        return getattr(self, name)

    def with_bonus(self, attribute: str, amount: int = 1, *, cap: int = MAX_ATTRIBUTE) -> "Attributes":
        if attribute not in ATTRIBUTE_NAMES:
            raise CreationError(f"unknown attribute {attribute!r}")
        values = {name: self.get(name) for name in ATTRIBUTE_NAMES}
        values[attribute] = min(cap, values[attribute] + amount)
        return Attributes(**values)


def assign_attributes(dice: DiceRoll, assignment: Mapping[str, int]) -> Attributes:
    """Assign one rolled die to each attribute (§11.1: "player assigns one die
    to each attribute"). `assignment` must be a bijection from
    `ATTRIBUTE_NAMES` onto the four rolled values -- every die used exactly
    once, no attribute skipped, no value invented."""

    if set(assignment) != set(ATTRIBUTE_NAMES):
        raise CreationError(
            f"assignment must cover exactly {sorted(ATTRIBUTE_NAMES)}, got {sorted(assignment)}"
        )
    remaining = list(dice.values)
    for attribute, value in assignment.items():
        if value not in remaining:
            raise CreationError(
                f"attribute {attribute!r} assigned die value {value!r} not among "
                f"remaining rolled dice {remaining} (each die can only be used once)"
            )
        remaining.remove(value)
    return Attributes(**{name: assignment[name] for name in ATTRIBUTE_NAMES})


@dataclass(frozen=True)
class DerivedStats:
    max_hp: int
    defense: int
    initiative_modifier: int
    carry_slots: int


def compute_derived_stats(attributes: Attributes, *, equipment_defense_bonus: int = 0) -> DerivedStats:
    """§11.1 derived-stat formulas, verbatim:
    Maximum HP = 8 + (Force * 2); Defense = 10 + Finesse + equipment;
    Initiative = d20 + Finesse + situational modifiers (the die roll itself is
    combat's job -- this returns the Finesse modifier combat rolls against,
    matching `combat.models.HeroCombatant.initiative_bonus`); Carry slots = 4 + Force.
    """

    return DerivedStats(
        max_hp=8 + attributes.force * 2,
        defense=10 + attributes.finesse + equipment_defense_bonus,
        initiative_modifier=attributes.finesse,
        carry_slots=4 + attributes.force,
    )


@dataclass(frozen=True)
class HeroSheet:
    """The full creation output for one hero: rolled dice (for UI replay),
    final attributes (post background bonus), skills, derived stats, and
    background/starting-item bookkeeping. Field names deliberately mirror
    `combat.models.HeroCombatant`/`Attributes` so wave-4 wiring is a
    straight copy, not a translation layer."""

    hero_id: str
    name: str
    background_id: str
    dice: DiceRoll
    attributes: Attributes
    skills: Mapping[str, int] = field(default_factory=dict)
    starting_item_ids: tuple[str, ...] = ()

    @property
    def derived(self) -> DerivedStats:
        return compute_derived_stats(self.attributes)
