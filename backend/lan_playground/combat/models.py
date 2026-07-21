"""Shared combatant/status dataclasses (infinite_stacks.md §11.1, §14, §16).

Deliberately independent of backend.lan_playground.content.schemas.Enemy: that
schema has no `converts` hook and no attribute block for enemies (needed for
initiative/attacks), and depending on it here would couple this pure package
to the content lane's authoring format. `intents.py` bridges the two -- it
builds an `EnemyCombatant` from a real content Enemy definition.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

ATTRIBUTE_NAMES = ("force", "finesse", "insight", "presence")
SKILL_NAMES = ("bonk", "scheme", "tinker", "read", "wordcraft")


class LifeState(str, Enum):
    ALIVE = "alive"
    DOWNED = "downed"      # 0 HP, not yet Stable (§16.1)
    STABLE = "stable"      # stopped dying, still unconscious until revived (§16.1/16.3)
    DEAD = "dead"          # permanent (§16.1/16.2)


@dataclass
class StatusInstance:
    status_id: str
    applied_round: int
    rounds_remaining: int | None = None   # None = lasts until treated/source removed
    escalated: bool = False


@dataclass
class Attributes:
    force: int = 1
    finesse: int = 1
    insight: int = 1
    presence: int = 1

    def get(self, name: str) -> int:
        return getattr(self, name)


@dataclass
class Weapon:
    die_faces: int = 6          # d4/d6/d8/rare d10 (§14.3)
    damage_bonus: int = 0       # explicit card/item damage bonus
    accuracy_bonus: int = 0     # explicit card/item bonus folded into the attack roll

    def __post_init__(self) -> None:
        if self.die_faces not in (4, 6, 8, 10):
            raise ValueError(f"weapon die must be d4/d6/d8/d10, got d{self.die_faces}")


@dataclass
class HeroCombatant:
    hero_id: str
    name: str
    attributes: Attributes
    max_hp: int
    skills: dict[str, int] = field(default_factory=dict)
    equipment_defense_bonus: int = 0
    equipment_accuracy_bonus: int = 0  # non-weapon item/accessory accuracy bonus (§13, verified by the caller)
    equipment_damage_bonus: int = 0    # non-weapon item/accessory damage bonus (§13, verified by the caller)
    weapon: Weapon = field(default_factory=Weapon)
    hp: int | None = None
    life_state: LifeState = LifeState.ALIVE
    stabilization_successes: int = 0
    death_failures: int = 0
    reaction_available: bool = True
    position: int = 0
    held_item: str | None = "weapon"
    prepared_trigger: dict | None = None
    exposed_until_next_turn: bool = False   # Crushing Blow (§14.4) exposure on a failed swing
    statuses: dict[str, StatusInstance] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hp is None:
            self.hp = self.max_hp

    @property
    def defense(self) -> int:
        return 10 + self.attributes.finesse + self.equipment_defense_bonus

    @property
    def initiative_bonus(self) -> int:
        return self.attributes.finesse

    @property
    def is_active(self) -> bool:
        """Can take a normal turn (not Downed/Stable/Dead)."""
        return self.life_state == LifeState.ALIVE

    @property
    def is_living(self) -> bool:
        return self.life_state in (LifeState.ALIVE, LifeState.DOWNED, LifeState.STABLE)

    def skill_rank(self, skill: str) -> int:
        return self.skills.get(skill, 0)


@dataclass
class EnemyCombatant:
    instance_id: str
    def_id: str
    name: str
    family: str
    max_hp: int
    defense: int
    threat_cost: int
    threat_tier: str
    initiative_bonus: int = 0
    accuracy_bonus: int = 0           # §14.3 to-hit contribution for enemy attack-type intents (wave 5, task #16)
    hp: int | None = None
    resists: tuple[str, ...] = ()     # maneuver names this enemy resists outright
    weaknesses: tuple[str, ...] = ()  # maneuver names that expose an extra weakness
    converts: dict[str, str] = field(default_factory=dict)  # maneuver name -> converted effect id
    alive: bool = True
    position: int = 0
    statuses: dict[str, StatusInstance] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.hp is None:
            self.hp = self.max_hp

    def resists_maneuver(self, maneuver: str) -> bool:
        return maneuver in self.resists

    def is_weak_to_maneuver(self, maneuver: str) -> bool:
        return maneuver in self.weaknesses

    def converted_effect(self, maneuver: str) -> str | None:
        return self.converts.get(maneuver)
