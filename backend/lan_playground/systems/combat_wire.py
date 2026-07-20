"""(De)serialization between `ConflictEncounterState` (JSON-safe dicts,
domain/state.py) and the pure `backend.lan_playground.combat` package's live
dataclasses. Split out of systems/combat.py to keep that module under the
infinite_stacks.md §22.2 soft 500-line cap -- this file is the only place
that knows the field-by-field shape of HeroCombatant/EnemyCombatant/etc;
systems/combat.py calls `build_live_encounter`/`snapshot_from_live` and never
touches combat.models fields directly itself.
"""
from __future__ import annotations

from ..combat import encounter as combat_encounter
from ..combat import events as combat_events_mod
from ..combat import initiative as combat_initiative
from ..combat import threat as combat_threat
from ..combat.actions import TurnBudget
from ..combat.models import Attributes, EnemyCombatant, HeroCombatant, LifeState, StatusInstance, Weapon
from ..domain.state import ConflictEncounterState, HeroState

DEFAULT_ATTRIBUTE = 2  # matches HeroState defaults: max_hp = 8 + 2*2 = 12 (§11.1)


def _attributes_to_dict(a: Attributes) -> dict:
    return {"force": a.force, "finesse": a.finesse, "insight": a.insight, "presence": a.presence}


def _attributes_from_dict(d: dict) -> Attributes:
    return Attributes(force=d["force"], finesse=d["finesse"], insight=d["insight"], presence=d["presence"])


def _weapon_to_dict(w: Weapon) -> dict:
    return {"die_faces": w.die_faces, "damage_bonus": w.damage_bonus, "accuracy_bonus": w.accuracy_bonus}


def _weapon_from_dict(d: dict) -> Weapon:
    return Weapon(die_faces=d["die_faces"], damage_bonus=d["damage_bonus"], accuracy_bonus=d["accuracy_bonus"])


def _status_to_dict(s: StatusInstance) -> dict:
    return {
        "status_id": s.status_id,
        "applied_round": s.applied_round,
        "rounds_remaining": s.rounds_remaining,
        "escalated": s.escalated,
    }


def _status_from_dict(d: dict) -> StatusInstance:
    return StatusInstance(
        status_id=d["status_id"],
        applied_round=d["applied_round"],
        rounds_remaining=d["rounds_remaining"],
        escalated=d["escalated"],
    )


def _statuses_to_dict(statuses: dict) -> dict:
    return {k: _status_to_dict(v) for k, v in statuses.items()}


def _statuses_from_dict(d: dict) -> dict:
    return {k: _status_from_dict(v) for k, v in d.items()}


def hero_combatant_to_dict(h: HeroCombatant) -> dict:
    return {
        "hero_id": h.hero_id,
        "name": h.name,
        "attributes": _attributes_to_dict(h.attributes),
        "max_hp": h.max_hp,
        "skills": dict(h.skills),
        "equipment_defense_bonus": h.equipment_defense_bonus,
        "equipment_accuracy_bonus": h.equipment_accuracy_bonus,
        "equipment_damage_bonus": h.equipment_damage_bonus,
        "weapon": _weapon_to_dict(h.weapon),
        "hp": h.hp,
        "life_state": h.life_state.value,
        "stabilization_successes": h.stabilization_successes,
        "death_failures": h.death_failures,
        "reaction_available": h.reaction_available,
        "position": h.position,
        "held_item": h.held_item,
        "prepared_trigger": h.prepared_trigger,
        "exposed_until_next_turn": h.exposed_until_next_turn,
        "statuses": _statuses_to_dict(h.statuses),
    }


def hero_combatant_from_dict(d: dict) -> HeroCombatant:
    return HeroCombatant(
        hero_id=d["hero_id"],
        name=d["name"],
        attributes=_attributes_from_dict(d["attributes"]),
        max_hp=d["max_hp"],
        skills=dict(d["skills"]),
        equipment_defense_bonus=d["equipment_defense_bonus"],
        equipment_accuracy_bonus=d["equipment_accuracy_bonus"],
        equipment_damage_bonus=d["equipment_damage_bonus"],
        weapon=_weapon_from_dict(d["weapon"]),
        hp=d["hp"],
        life_state=LifeState(d["life_state"]),
        stabilization_successes=d["stabilization_successes"],
        death_failures=d["death_failures"],
        reaction_available=d["reaction_available"],
        position=d["position"],
        held_item=d["held_item"],
        prepared_trigger=d["prepared_trigger"],
        exposed_until_next_turn=d["exposed_until_next_turn"],
        statuses=_statuses_from_dict(d["statuses"]),
    )


def enemy_combatant_to_dict(e: EnemyCombatant) -> dict:
    return {
        "instance_id": e.instance_id,
        "def_id": e.def_id,
        "name": e.name,
        "family": e.family,
        "max_hp": e.max_hp,
        "defense": e.defense,
        "threat_cost": e.threat_cost,
        "threat_tier": e.threat_tier,
        "initiative_bonus": e.initiative_bonus,
        "hp": e.hp,
        "resists": list(e.resists),
        "weaknesses": list(e.weaknesses),
        "converts": dict(e.converts),
        "alive": e.alive,
        "position": e.position,
        "statuses": _statuses_to_dict(e.statuses),
    }


def enemy_combatant_from_dict(d: dict) -> EnemyCombatant:
    return EnemyCombatant(
        instance_id=d["instance_id"],
        def_id=d["def_id"],
        name=d["name"],
        family=d["family"],
        max_hp=d["max_hp"],
        defense=d["defense"],
        threat_cost=d["threat_cost"],
        threat_tier=d["threat_tier"],
        initiative_bonus=d["initiative_bonus"],
        hp=d["hp"],
        resists=tuple(d["resists"]),
        weaknesses=tuple(d["weaknesses"]),
        converts=dict(d["converts"]),
        alive=d["alive"],
        position=d["position"],
        statuses=_statuses_from_dict(d["statuses"]),
    )


def _entry_to_dict(e) -> dict:
    return {"combatant_id": e.combatant_id, "is_hero": e.is_hero, "roll": e.roll, "bonus": e.bonus, "total": e.total}


def _entry_from_dict(d: dict) -> combat_initiative.InitiativeEntry:
    return combat_initiative.InitiativeEntry(
        combatant_id=d["combatant_id"], is_hero=d["is_hero"], roll=d["roll"], bonus=d["bonus"], total=d["total"]
    )


def _wave_to_dict(w) -> dict:
    return {
        "enemies": [enemy_combatant_to_dict(e) for e in w.enemies],
        "arrival_combat_round": w.arrival_combat_round,
        "cost": w.cost,
        "arrived": w.arrived,
    }


def _wave_from_dict(d: dict) -> combat_threat.ReinforcementWave:
    return combat_threat.ReinforcementWave(
        enemies=[enemy_combatant_from_dict(e) for e in d["enemies"]],
        arrival_combat_round=d["arrival_combat_round"],
        cost=d["cost"],
        arrived=d["arrived"],
    )


def hero_combatant_from_state(
    hero: HeroState,
    *,
    attributes: Attributes | None = None,
    skills: dict[str, int] | None = None,
    weapon: Weapon | None = None,
    equipment_defense_bonus: int = 0,
    equipment_accuracy_bonus: int = 0,
    equipment_damage_bonus: int = 0,
) -> HeroCombatant:
    """Builds a `HeroCombatant` for a fresh/rejoining encounter. Every
    equipment-derived argument defaults to a flat zero/no-op -- callers
    (herowire, once HeroState carries hero-sheet/inventory data) pass
    already-resolved, already-verified concrete values (a real `Weapon`,
    real bonus ints) here; this function never accepts a raw item/source id
    and never resolves one itself (per the wave-3 director ruling: no
    numeric combat modifier comes from the wire unverified)."""
    attrs = attributes or Attributes(
        force=DEFAULT_ATTRIBUTE, finesse=DEFAULT_ATTRIBUTE, insight=DEFAULT_ATTRIBUTE, presence=DEFAULT_ATTRIBUTE
    )
    return HeroCombatant(
        hero_id=hero.hero_id,
        name=hero.hero_id,
        attributes=attrs,
        max_hp=hero.max_hp,
        skills=dict(skills or {}),
        equipment_defense_bonus=equipment_defense_bonus,
        equipment_accuracy_bonus=equipment_accuracy_bonus,
        equipment_damage_bonus=equipment_damage_bonus,
        weapon=weapon or Weapon(),
        hp=hero.hp,
        life_state=LifeState(hero.life_state),
        stabilization_successes=hero.stabilization_successes,
        death_failures=hero.death_failures,
    )


def build_live_encounter(snap: ConflictEncounterState) -> combat_encounter.Encounter:
    sequencer = combat_events_mod.EventSequencer(snap.encounter_id)
    sequencer._seq = snap.sequencer_seq
    return combat_encounter.Encounter(
        encounter_id=snap.encounter_id,
        heroes={hid: hero_combatant_from_dict(h) for hid, h in snap.heroes.items()},
        enemies={eid: enemy_combatant_from_dict(e) for eid, e in snap.enemies.items()},
        sequencer=sequencer,
        combat_round=snap.combat_round,
        order=[_entry_from_dict(e) for e in snap.order],
        reinforcement_waves=[_wave_from_dict(w) for w in snap.reinforcement_waves],
    )


def snapshot_from_live(
    live: combat_encounter.Encounter,
    *,
    status: str,
    current_actor_id: str | None,
    turn_budget: dict,
    threat_budget: dict,
    pending_joiner_hero_ids: list,
    room_id: str,
) -> ConflictEncounterState:
    return ConflictEncounterState(
        encounter_id=live.encounter_id,
        room_id=room_id,
        status=status,
        combat_round=live.combat_round,
        heroes={hid: hero_combatant_to_dict(h) for hid, h in live.heroes.items()},
        enemies={eid: enemy_combatant_to_dict(e) for eid, e in live.enemies.items()},
        order=[_entry_to_dict(e) for e in live.order],
        current_actor_id=current_actor_id,
        reinforcement_waves=[_wave_to_dict(w) for w in live.reinforcement_waves],
        turn_budget=dict(turn_budget),
        threat_budget=dict(threat_budget),
        pending_joiner_hero_ids=list(pending_joiner_hero_ids),
        sequencer_seq=live.sequencer._seq,
    )


def fresh_turn_budget() -> dict:
    return {"moved": False, "quick_interaction_used": False, "main_action_used": False}


def turn_budget_obj(hero_id: str, d: dict) -> TurnBudget:
    return TurnBudget(
        hero_id=hero_id,
        moved=d.get("moved", False),
        quick_interaction_used=d.get("quick_interaction_used", False),
        main_action_used=d.get("main_action_used", False),
    )


def turn_budget_to_dict(b: TurnBudget) -> dict:
    return {"moved": b.moved, "quick_interaction_used": b.quick_interaction_used, "main_action_used": b.main_action_used}
