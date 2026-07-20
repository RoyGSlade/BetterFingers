"""Generalized ability charges + active-effect durations (infinite_stacks.md
§11.3; wave 6 playtest response, board task #21, docs/PLAYTEST_FINDINGS_
2026-07-19.md items A5/E1/E4/F1).

Generalizes `heroes.backgrounds.SignatureCharge` (a single once-per-X charge
tied only to a hero's background) into an arbitrary per-hero collection keyed
by ability_id, so content beyond the one background signature ability --
passive traits, room/encounter auto-triggers, and additional player-invoked
abilities -- has a home. `heroes/backgrounds.py` itself is untouched (heroes/
package stays read-only); this module is domain/systems-side and never
imports heroes/** or content/**, consuming only the plain
`AbilityLike`-shaped duck type below (mirrors how `heroes.backgrounds`
consumes `BackgroundLike`/`SignatureAbilityLike` without importing
`content.schemas`).

Vocabulary posted to the collab room 2026-07-20: `trigger` is one of
"manual" | "passive" | "on_room_enter" | "on_encounter_start" (the only four
the engine dispatches this wave); `frequency` is "unlimited" (no charge
tracking) or "once_per_floor" | "once_per_room" | "once_per_fight" (charge
scopes, reusing `heroes.backgrounds.SignatureCharge`'s exact vocabulary --
always paired with trigger=="manual").
"""
from __future__ import annotations

from typing import Protocol

from ..domain.state import ActiveEffectState, AbilityState

_CHARGES_BY_FREQUENCY = {
    "once_per_floor": 1,
    "once_per_room": 1,
    "once_per_fight": 1,
}

# frequency -> the boundary name systems/heroes_wire.py's refresh builders use
# ("floor"/"room"/"fight"), matching heroes.backgrounds.SignatureCharge's
# `frequency.removeprefix("once_per_")` convention exactly.
_SCOPE_BY_FREQUENCY = {
    "once_per_floor": "floor",
    "once_per_room": "room",
    "once_per_fight": "fight",
}

EXECUTABLE_TRIGGERS = frozenset({"manual", "passive", "on_room_enter", "on_encounter_start"})


class AbilityError(ValueError):
    pass


class AbilityLike(Protocol):
    """Structural shape this module needs from an ability definition --
    matches `content.schemas.Ability` (stacks-carddesign, posted 2026-07-20)
    duck-typed so no import of that module is required."""

    id: str
    trigger: str
    frequency: str


def scope_for_frequency(frequency: str) -> str | None:
    """None for "unlimited" (no charge scope); raises for anything else
    unrecognized so a typo in content never silently becomes an infinite-use
    ability."""

    if frequency == "unlimited":
        return None
    scope = _SCOPE_BY_FREQUENCY.get(frequency)
    if scope is None:
        raise AbilityError(f"unknown ability frequency {frequency!r}")
    return scope


def initial_ability_state(ability_def: AbilityLike) -> AbilityState:
    scope = scope_for_frequency(ability_def.frequency)
    if scope is None:
        return AbilityState(
            ability_id=ability_def.id,
            trigger=ability_def.trigger,
            frequency=ability_def.frequency,
            charges_remaining=None,
            max_charges=None,
        )
    max_charges = _CHARGES_BY_FREQUENCY[ability_def.frequency]
    return AbilityState(
        ability_id=ability_def.id,
        trigger=ability_def.trigger,
        frequency=ability_def.frequency,
        charges_remaining=max_charges,
        max_charges=max_charges,
    )


def spend_charge(ability: AbilityState) -> AbilityState:
    if ability.max_charges is None:
        # "unlimited" frequency abilities (passive/on_room_enter/
        # on_encounter_start) never deplete -- this is only reached if a
        # future caller invokes spend on a non-manual ability, which is a
        # caller bug, not a player-facing error.
        return ability
    if ability.charges_remaining is None or ability.charges_remaining <= 0:
        raise AbilityError(
            f"ability {ability.ability_id!r} has no charges remaining this "
            f"{ability.frequency.removeprefix('once_per_')}"
        )
    return AbilityState(
        ability_id=ability.ability_id,
        trigger=ability.trigger,
        frequency=ability.frequency,
        charges_remaining=ability.charges_remaining - 1,
        max_charges=ability.max_charges,
    )


def refreshed(ability: AbilityState) -> AbilityState:
    if ability.max_charges is None:
        return ability
    return AbilityState(
        ability_id=ability.ability_id,
        trigger=ability.trigger,
        frequency=ability.frequency,
        charges_remaining=ability.max_charges,
        max_charges=ability.max_charges,
    )


def refresh_boundary(abilities: dict[str, AbilityState], boundary: str) -> dict[str, AbilityState]:
    """Return a NEW dict with every ability whose scope matches `boundary`
    ("floor"|"room"|"fight") refreshed to full charges; every other ability
    passes through unchanged. Abilities with no scope (unlimited-frequency)
    are always no-ops here."""

    return {
        aid: (refreshed(a) if scope_for_frequency(a.frequency) == boundary else a)
        for aid, a in abilities.items()
    }


def any_scope_matches(abilities: dict[str, AbilityState], boundary: str) -> bool:
    return any(scope_for_frequency(a.frequency) == boundary for a in abilities.values())


# ---------------------------------------------------------------- active effects

def apply_active_effect(
    active_effects: tuple[ActiveEffectState, ...],
    *,
    effect_id: str,
    source_id: str,
    label: str,
    duration: str,
    world_round: int,
    encounter_id: str | None = None,
) -> tuple[ActiveEffectState, ...]:
    from ..domain.state import ACTIVE_EFFECT_DURATIONS

    if duration not in ACTIVE_EFFECT_DURATIONS:
        raise AbilityError(f"unknown active-effect duration {duration!r}")
    new_effect = ActiveEffectState(
        effect_id=effect_id,
        source_id=source_id,
        label=label,
        duration=duration,
        applied_world_round=world_round,
        encounter_id=encounter_id,
    )
    return active_effects + (new_effect,)


_DURATION_BY_BOUNDARY = {
    "turn": "until_end_of_turn",
    "round": "until_end_of_round",
    "encounter": "until_end_of_encounter",
}


def expire_boundary(
    active_effects: tuple[ActiveEffectState, ...],
    *,
    boundary: str,
    encounter_id: str | None = None,
) -> tuple[ActiveEffectState, ...]:
    """`boundary` is "turn"|"round"|"encounter". For "encounter", only
    effects tied to `encounter_id` expire -- a split party's other active
    encounter (or an effect applied outside any encounter) is unaffected."""

    duration = _DURATION_BY_BOUNDARY[boundary]

    def keep(effect: ActiveEffectState) -> bool:
        if effect.duration != duration:
            return True
        if duration == "until_end_of_encounter":
            return effect.encounter_id != encounter_id
        return False

    return tuple(e for e in active_effects if keep(e))
