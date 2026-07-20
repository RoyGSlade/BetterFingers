"""Wires the pure `backend.lan_playground.combat` package into the domain
reducer (infinite_stacks.md §14-16; docs/INFINITE_STACKS_COMBAT.md).

Combat stays pure and is never edited here: this module is the sole bridge.
It (de)serializes `ConflictEncounterState` snapshots into real `combat.models`
objects via systems/combat_wire.py, calls the pure combat/** functions (which
mutate those live objects and return raw combat-event dicts), and folds the
results back into plain, JSON-safe dicts. Every RNG draw happens inside the
`handle_*`/`build_*` functions below (the `handle()` contract, §9 of the
contracts doc); the `apply_conflict_*` appliers only replay already-decided
results, mirroring the same "carry the whole resulting sub-state" pattern
`MAP_GENERATED` already uses for map generation.

No hero-sheet system exists yet (Phase 3 out of scope, matching effects.py's
`grant_check`), so every hero fights with the same flat default Attributes
(matching HeroState's existing hp=8+2*2=12 default) and no skill ranks. Per
director ruling (2026-07-19 17:15), no numeric combat modifier is ever
accepted from a command payload -- accuracy/damage bonuses, advantage
sources, and maneuver parameters are always server-computed defaults, never
a raw value from the wire. `combat_wire.hero_combatant_from_state` accepts
verified `Weapon`/equipment-bonus arguments for exactly this reason -- see
docs/INFINITE_STACKS_COMBAT.md §3/§13 for the equipment-modifier contract
herowire resolves source ids against.

Status tick damage (bleeding/burning) is wired at the combat-round boundary
inside `combat/encounter.py::advance_round` (called from
`build_round_advance_combat_events` below), always through
`lifecycle.apply_damage` -- `combat/statuses.py` itself still never touches
HP directly.

Wave-4 note: `combat/actions.py::attack()` now supports a true mid-resolution
reaction interrupt window (`reaction_hook`, see docs/INFINITE_STACKS_COMBAT.md
§7) for Block/Dodge/Protect/Counter. No live caller in this file passes one
yet -- every attack a hero currently faces from an enemy resolves as a flat,
unconditional content-authored effect (`combat/intents.py`'s `damage` op has
no to-hit roll of its own), so there is no attack-roll moment for a hero to
interrupt. `handle_combat_reaction` below remains the caller-supplied-context
path for Escape/Prepared Trigger and for reacting to intent-driven damage;
wiring intent-driven enemy attacks through a real to-hit roll (and therefore
through the interrupt window) is future-wave scope, since it would change
`combat/intents.py`'s accepted wave-2 contract and content authoring.
"""
from __future__ import annotations

import functools

from ..combat import actions as combat_actions
from ..combat import encounter as combat_encounter
from ..combat import initiative as combat_initiative
from ..combat import intents as combat_intents
from ..combat import lifecycle as combat_lifecycle
from ..combat import maneuvers as combat_maneuvers
from ..combat import reactions as combat_reactions
from ..combat import threat as combat_threat
from ..combat.models import EnemyCombatant, HeroCombatant, LifeState
from ..content import loader as content_loader
from . import heroes_wire
from ..domain.commands import Command, CommandError, ErrorCode
from ..domain.events import Event, EventType, Visibility, make_event_id
from ..domain.state import LIFE_STATE_DEAD, LIFE_STATE_DOWNED, ConflictEncounterState, HeroState, RunState
from . import abilities as ability_systems
from . import combat_wire as wire

_ENEMY_ROSTER_ORDER = ("goblin_firestarter", "goblin_bruiser", "punctuation_spider")
_REINFORCEMENT_DELAY_ROUNDS = 3
_DEFAULT_BLOCK_AMOUNT = 2  # documented default -- no items/cards exist yet to source it from (§32 spirit)
_MANEUVER_FNS = {
    "disarm": combat_maneuvers.disarm,
    "trip": combat_maneuvers.trip,
    "drive_back": combat_maneuvers.drive_back,
    "break": combat_maneuvers.break_object,
    "crushing_blow": combat_maneuvers.crushing_blow,
    "rattle": combat_maneuvers.rattle,
}
_ATTRIBUTES = ("force", "finesse", "insight", "presence")


def _hero(state: RunState, hero_id: str | None) -> HeroState:
    if hero_id is None or hero_id not in state.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown hero {hero_id}")
    return state.heroes[hero_id]


@functools.lru_cache(maxsize=1)
def _core_pack():
    return content_loader.load_core_pack()


def _enemy_defs() -> list:
    pack = _core_pack()
    return [pack.enemies[eid] for eid in _ENEMY_ROSTER_ORDER if eid in pack.enemies]


def _intents_for(def_id: str):
    pack = _core_pack()
    _, intent_defs = combat_intents.build_enemy_combatant(pack.enemies[def_id], instance_id="_probe")
    return intent_defs


# ---------------------------------------------------------------- turn-order / enemy AI


def _active_order_ids(live: combat_encounter.Encounter) -> list[str]:
    living_ids = {h.hero_id for h in live.heroes.values() if h.life_state == LifeState.ALIVE}
    living_ids |= {e.instance_id for e in live.enemies.values() if e.alive}
    return [e.combatant_id for e in combat_initiative.active_order(live.order, living_ids)]


def _next_active_id(live: combat_encounter.Encounter, current_id: str | None) -> str | None:
    active_ids = _active_order_ids(live)
    if current_id not in active_ids:
        return active_ids[0] if active_ids else None
    idx = active_ids.index(current_id)
    if idx + 1 < len(active_ids):
        return active_ids[idx + 1]
    return None  # this round is settled for this encounter


def _target_for_enemy(live: combat_encounter.Encounter) -> HeroCombatant | None:
    candidates = [h for h in live.heroes.values() if h.life_state == LifeState.ALIVE]
    if not candidates:
        return None
    return min(candidates, key=lambda h: (h.hp, h.hero_id))


def _eligible_protectors(live: combat_encounter.Encounter, defender_hero_id: str) -> list[HeroCombatant]:
    """§14.5 Protect candidates for a pending reaction window: every OTHER
    living hero with a reaction still available. No adjacency/position gate
    exists in this wave's room model (combat `position` is a flat int used
    for repositioning flavor, not a spatial range), matching how
    `_target_for_enemy` already ignores position for target selection."""
    return [
        h for hid, h in sorted(live.heroes.items())
        if hid != defender_hero_id and h.life_state == LifeState.ALIVE and h.reaction_available
    ]


def _pending_reaction_to_dict(
    result: "combat_intents.IntentEffectsResult", enemy: EnemyCombatant, intent: "combat_intents.EnemyIntentDef"
) -> dict:
    pending = result.pending
    window = pending.window
    return {
        "reaction_id": result.events[-1]["event_id"],
        "attacker_id": enemy.instance_id,
        "defender_id": window.defender.hero_id,
        "protector_ids": sorted(p.hero_id for p in window.protectors),
        "hit": window.hit,
        "margin": window.margin,
        "incoming_attack_total": window.incoming_attack_total,
        "provisional_damage": window.provisional_damage,
        "action_label": pending.action_label,
        "source_intent_id": intent.id,
        "remaining_effects": [dict(op) for op in result.remaining_effects],
    }


def _run_enemy_intent_effects(
    live: combat_encounter.Encounter,
    rng,
    enemy: EnemyCombatant,
    target: HeroCombatant | None,
    intent: "combat_intents.EnemyIntentDef",
    caused_by: str,
    facts: set[str],
) -> tuple[list[dict], set[str], dict | None]:
    """Resolves one enemy intent's effect ops, routing any `damage` op
    through the live §14.5 pending-reaction window (task #16). Returns
    (events, facts, pending_reaction_dict_or_None) -- a non-None pending
    dict means the caller must stop advancing the encounter (current actor
    stays the attacking enemy, its turn isn't over) until `resolve_reaction`
    resumes it."""
    protectors = _eligible_protectors(live, target.hero_id) if target is not None else []
    result = combat_intents.resolve_intent_effects(
        intent, enemy, target, combat_round=live.combat_round, sequencer=live.sequencer, caused_by=caused_by,
        rng=rng, reaction_hook=combat_actions.PENDING_REACTION, protectors=protectors,
    )
    executed_count = len(intent.effects) - len(result.remaining_effects) if result.pending else len(intent.effects)
    for op_spec in intent.effects[:executed_count]:
        if op_spec["op"] == "emit_fact":
            facts.add(op_spec["args"]["fact_id"])
    if result.pending is not None:
        return list(result.events), facts, _pending_reaction_to_dict(result, enemy, intent)
    return list(result.events), facts, None


def _begin_hero_turn(live: combat_encounter.Encounter, hero_id: str, caused_by: str) -> tuple[list[dict], dict]:
    _, event = combat_actions.start_turn(hero_id, combat_round=live.combat_round, sequencer=live.sequencer, caused_by=caused_by)
    return [event], wire.fresh_turn_budget()


def _cascade_enemy_turns(
    live: combat_encounter.Encounter, rng, facts: set[str], caused_by: str, current_actor_id: str | None
) -> tuple[list[dict], str | None, set[str], str | None, dict | None]:
    """Auto-resolve every consecutive enemy turn (no player decides enemy
    tactics, per combat/encounter.py's own design) until it's a hero's turn,
    the round settles (no more active combatants), the fight ends, or an
    enemy attack opens a live pending-reaction window (task #16) -- in that
    last case, iteration stops immediately (other enemies simply wait, like
    a paused mid-swing) and the 5th return value carries the pending dict."""
    events: list[dict] = []
    outcome: str | None = None
    while current_actor_id is not None:
        if current_actor_id in live.heroes:
            break
        enemy = live.enemies.get(current_actor_id)
        if enemy is None or not enemy.alive:
            current_actor_id = _next_active_id(live, current_actor_id)
            continue
        _, turn_event = combat_actions.start_turn(
            current_actor_id, combat_round=live.combat_round, sequencer=live.sequencer, caused_by=caused_by
        )
        events.append(turn_event)
        target = _target_for_enemy(live)
        intent_defs = _intents_for(enemy.def_id)
        chosen = combat_intents.select_intent(intent_defs, frozenset(facts))
        events.extend(
            combat_intents.telegraph_intent(
                enemy, chosen, combat_round=live.combat_round, sequencer=live.sequencer, caused_by=caused_by
            )
        )
        intent_events, facts, pending = _run_enemy_intent_effects(live, rng, enemy, target, chosen, caused_by, facts)
        events.extend(intent_events)
        if pending is not None:
            return events, current_actor_id, facts, None, pending
        if combat_encounter.is_victory(live) or combat_encounter.is_party_wiped(live):
            outcome = "victory" if combat_encounter.is_victory(live) else "party_wiped"
            current_actor_id = None
            break
        current_actor_id = _next_active_id(live, current_actor_id)
    return events, current_actor_id, facts, outcome, None


# ---------------------------------------------------------------- threat / enemy roster


def _select_enemies(budget_total: int) -> tuple[EnemyCombatant | None, list[EnemyCombatant]]:
    defs = _enemy_defs()
    if not defs:
        return None, []
    immediate_def = defs[0]
    immediate, _ = combat_intents.build_enemy_combatant(immediate_def, instance_id=f"{immediate_def.id}_0")
    reinforcement_candidates = [
        combat_intents.build_enemy_combatant(d, instance_id=f"{d.id}_{i + 1}")[0] for i, d in enumerate(defs[1:])
    ]
    if immediate.threat_cost > budget_total:
        return None, [immediate] + reinforcement_candidates
    return immediate, reinforcement_candidates


# ---------------------------------------------------------------- result-event assembly


def _build_result_event(
    *,
    command_id: str,
    actor_hero_id: str | None,
    state: RunState,
    room_id: str,
    live: combat_encounter.Encounter,
    current_actor_id: str | None,
    turn_budget: dict,
    pending_joiners: list[str],
    combat_evts: list[dict],
    new_facts: set[str],
    seq: int,
    pending_reaction: dict | None = None,
) -> Event:
    room = state.map.rooms[room_id]
    prior_life = {hid: h["life_state"] for hid, h in room.encounter.heroes.items()}
    hero_updates: dict[str, dict] = {}
    newly_dead: list[str] = []
    for hid, hc in live.heroes.items():
        hero_updates[hid] = {
            "hp": hc.hp,
            "life_state": hc.life_state.value,
            "death_failures": hc.death_failures,
            "stabilization_successes": hc.stabilization_successes,
        }
        if prior_life.get(hid) != LIFE_STATE_DEAD and hc.life_state.value == LIFE_STATE_DEAD:
            newly_dead.append(hid)

    status = "active"
    if combat_encounter.is_victory(live):
        status = "victory"
    elif combat_encounter.is_party_wiped(live):
        status = "party_wiped"

    snapshot = wire.snapshot_from_live(
        live,
        status=status,
        current_actor_id=(current_actor_id if status == "active" else None),
        turn_budget=(turn_budget if status == "active" else {}),
        threat_budget=room.encounter.threat_budget,
        pending_joiner_hero_ids=(pending_joiners if status == "active" else []),
        room_id=room_id,
        pending_reaction=(pending_reaction if status == "active" else None),
    )
    event_type = EventType.CONFLICT_ENCOUNTER_ENDED if status != "active" else EventType.CONFLICT_TURN_RESOLVED
    payload: dict = {
        "room_id": room_id,
        "encounter": snapshot.to_dict(),
        "combat_events": combat_evts,
        "hero_updates": hero_updates,
        "newly_dead_hero_ids": newly_dead,
        "new_facts": sorted(new_facts),
    }
    if event_type is EventType.CONFLICT_ENCOUNTER_ENDED:
        payload["outcome"] = status
    return Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command_id,
        type=event_type,
        visibility=Visibility.PUBLIC,
        actor_hero_id=actor_hero_id,
        room_id=room_id,
        payload=payload,
    )


# ---------------------------------------------------------------- start on breach (§14.1)


def build_start_encounter_events(
    command: Command, state: RunState, rng, room_id: str, breaching_hero_id: str, seq: int
) -> tuple[Event, ...]:
    """Called from systems/exploration.py's handle_breach exactly when the
    rolled family is `conflict`. Threat is sized from the *total living
    party* (§15.1), never just the breaching hero -- a lone entrant still
    faces the full-party budget, with the fairness counterweight being
    delayed reinforcements (§15.2) rather than a smaller fight."""
    hero_state = state.heroes[breaching_hero_id]
    budget = combat_threat.calculate_threat_budget(state.total_living_heroes())
    encounter_id = f"enc_{rng.randint(0, 2**31 - 1):08x}"

    # Real equipment reaches the fight: resolve verified weapon/bonus values
    # from HeroState (heroes_wire owns the source-id -> concrete-value step,
    # per the wave-3 no-raw-wire-numbers ruling) so resolution matches what
    # the legal_attacks catalog displays.
    hero_combatant = wire.hero_combatant_from_state(
        hero_state, **heroes_wire.resolve_hero_combat_equipment(hero_state)
    )
    immediate, reinforcement_candidates = _select_enemies(budget.total)
    immediate_list = [immediate] if immediate is not None else []

    live, combat_evts_seq = combat_encounter.start_encounter(
        encounter_id, [hero_combatant], immediate_list, rng, caused_by=command.command_id
    )
    combat_evts = list(combat_evts_seq)
    combat_evts.extend(
        combat_threat.emit_threat_budget(
            budget, combat_round=live.combat_round, sequencer=live.sequencer, caused_by=command.command_id
        )
    )

    remaining_budget = budget.total - combat_threat.roster_cost(immediate_list)
    if reinforcement_candidates and remaining_budget > 0:
        wave, sched_evts = combat_threat.schedule_reinforcements(
            remaining_budget,
            reinforcement_candidates,
            arrival_combat_round=live.combat_round + _REINFORCEMENT_DELAY_ROUNDS,
            combat_round=live.combat_round,
            sequencer=live.sequencer,
            caused_by=command.command_id,
        )
        live.reinforcement_waves.append(wave)
        combat_evts.extend(sched_evts)

    facts = set(state.facts)
    active_ids = _active_order_ids(live)
    current_actor_id = active_ids[0] if active_ids else None
    cascade_evts, current_actor_id, facts, outcome, pending_reaction = _cascade_enemy_turns(
        live, rng, facts, command.command_id, current_actor_id
    )
    combat_evts.extend(cascade_evts)

    turn_budget: dict = {}
    if pending_reaction is None and current_actor_id is not None and outcome is None:
        begin_evts, turn_budget = _begin_hero_turn(live, current_actor_id, command.command_id)
        combat_evts.extend(begin_evts)

    threat_budget_dict = {
        "total_living_heroes": budget.total_living_heroes,
        "floor_danger": budget.floor_danger,
        "corruption_modifier": budget.corruption_modifier,
        "objective_modifier": budget.objective_modifier,
        "total": budget.total,
    }
    status = outcome or "active"
    snapshot = wire.snapshot_from_live(
        live,
        status=status,
        current_actor_id=(current_actor_id if status == "active" else None),
        turn_budget=(turn_budget if status == "active" else {}),
        threat_budget=threat_budget_dict,
        pending_joiner_hero_ids=[],
        room_id=room_id,
        pending_reaction=(pending_reaction if status == "active" else None),
    )
    hero_updates = {
        hid: {
            "hp": hc.hp,
            "life_state": hc.life_state.value,
            "death_failures": hc.death_failures,
            "stabilization_successes": hc.stabilization_successes,
        }
        for hid, hc in live.heroes.items()
    }
    event_type = EventType.CONFLICT_ENCOUNTER_ENDED if status != "active" else EventType.CONFLICT_ENCOUNTER_STARTED
    payload: dict = {
        "room_id": room_id,
        "encounter": snapshot.to_dict(),
        "combat_events": combat_evts,
        "hero_updates": hero_updates,
        "newly_dead_hero_ids": [],
        "new_facts": sorted(facts - set(state.facts)),
    }
    if event_type is EventType.CONFLICT_ENCOUNTER_ENDED:
        payload["outcome"] = status
    events = [
        Event(
            event_id=make_event_id(state.world_round, seq),
            run_id=state.run_id,
            world_round=state.world_round,
            caused_by=command.command_id,
            type=event_type,
            visibility=Visibility.PUBLIC,
            actor_hero_id=breaching_hero_id,
            room_id=room_id,
            payload=payload,
        ),
    ]
    # §11.3 once_per_fight signature abilities refresh at the fight boundary
    # (heroes_wire published this hook in wave 4; the encounter start is the
    # fight boundary for every hero present at it).
    if event_type is EventType.CONFLICT_ENCOUNTER_STARTED:
        events.extend(
            heroes_wire.build_fight_boundary_refresh_events(
                state, breaching_hero_id, seq + len(events), command.command_id
            )
        )
        # Wave-6 (board task #21, playtest E1): trigger=="on_encounter_start"
        # abilities fire automatically once the fight actually begins.
        events.extend(
            heroes_wire.build_encounter_start_ability_events(
                state, breaching_hero_id, room_id, seq + len(events), command, rng
            )
        )
    return tuple(events)


# ---------------------------------------------------------------- round-advance hook (§7.4/§14.1)


def build_round_advance_combat_events(state: RunState, rng, command_id: str, seq: int) -> tuple[Event, ...]:
    """Called from systems/turns.py exactly when a world round is about to
    advance: every active encounter's combat round advances in lockstep
    (one combat round == one world round, §7.4/§14.1) -- pending joiners
    integrate, due reinforcements arrive, reactions refresh, Downed heroes
    take their death checks, and any leading enemy turns of the new round
    auto-resolve, all before WORLD_ROUND_ADVANCED itself fires."""
    if state.map is None:
        return ()
    events: list[Event] = []
    for room_id in sorted(state.map.rooms):
        room = state.map.rooms[room_id]
        enc = room.encounter
        if enc is None or enc.status != "active":
            continue
        live = wire.build_live_encounter(enc)
        joiners = [
            wire.hero_combatant_from_state(
                state.heroes[hid], **heroes_wire.resolve_hero_combat_equipment(state.heroes[hid])
            )
            for hid in enc.pending_joiner_hero_ids
            if hid in state.heroes and state.heroes[hid].alive
        ]
        combat_evts = list(
            combat_encounter.advance_round(live, rng, joiners=(joiners or None), caused_by=command_id)
        )
        facts = set(state.facts)
        active_ids = _active_order_ids(live)
        current_actor_id = active_ids[0] if active_ids else None
        cascade_evts, current_actor_id, facts, outcome, pending_reaction = _cascade_enemy_turns(
            live, rng, facts, command_id, current_actor_id
        )
        combat_evts.extend(cascade_evts)
        turn_budget: dict = {}
        if pending_reaction is None and current_actor_id is not None and outcome is None:
            begin_evts, turn_budget = _begin_hero_turn(live, current_actor_id, command_id)
            combat_evts.extend(begin_evts)
        events.append(
            _build_result_event(
                command_id=command_id,
                actor_hero_id=None,
                state=state,
                room_id=room_id,
                live=live,
                current_actor_id=current_actor_id,
                turn_budget=turn_budget,
                pending_joiners=[],
                combat_evts=combat_evts,
                new_facts=(facts - set(state.facts)),
                pending_reaction=pending_reaction,
                seq=seq + len(events),
            )
        )
    return tuple(events)


# ---------------------------------------------------------------- shared validation helpers


def _active_encounter_room(state: RunState, hero_id: str | None):
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    if room.encounter is None or room.encounter.status != "active":
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"no active encounter in {hero.room_id}")
    if hero_id not in room.encounter.heroes:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is not part of the encounter in {hero.room_id}")
    if room.encounter.pending_reaction is not None:
        raise CommandError(
            ErrorCode.ILLEGAL_ACTION, f"encounter in {hero.room_id} has a pending reaction awaiting resolution"
        )
    return room, room.encounter


def _require_current_actor(enc: ConflictEncounterState, hero_id: str) -> None:
    if enc.current_actor_id != hero_id:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"it is not {hero_id}'s combat turn")


def _require_main_action_free(enc: ConflictEncounterState, hero_id: str) -> None:
    if enc.turn_budget.get("main_action_used"):
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already used their main action this turn")


def _require_attribute(attribute) -> str:
    if attribute not in _ATTRIBUTES:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"invalid attribute {attribute!r}")
    return attribute


# ---------------------------------------------------------------- combat_attack


def validate_combat_attack(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    _require_main_action_free(enc, hero_id)
    target_id = payload.get("target_id")
    if target_id not in enc.enemies or not enc.enemies[target_id]["alive"]:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown or defeated attack target {target_id!r}")
    attribute = _require_attribute(payload.get("attribute"))
    return room, enc, target_id, attribute, payload.get("skill")


def handle_combat_attack(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc, target_id, attribute, skill = validate_combat_attack(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    budget = wire.turn_budget_obj(hero_id, enc.turn_budget)
    result = combat_actions.attack(
        live.heroes[hero_id],
        live.enemies[target_id],
        attribute=attribute,
        skill=skill,
        rng=rng,
        combat_round=live.combat_round,
        sequencer=live.sequencer,
        caused_by=command.command_id,
        budget=budget,
    )
    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=wire.turn_budget_to_dict(budget),
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=list(result.events),
            new_facts=set(),
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- combat_maneuver


def validate_combat_maneuver(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    _require_main_action_free(enc, hero_id)
    maneuver = payload.get("maneuver")
    if maneuver not in _MANEUVER_FNS:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown maneuver {maneuver!r}")
    target_id = payload.get("target_id")
    if target_id not in enc.enemies or not enc.enemies[target_id]["alive"]:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown or defeated maneuver target {target_id!r}")
    attribute = _require_attribute(payload.get("attribute"))
    return room, enc, maneuver, target_id, attribute, payload.get("skill")


def handle_combat_maneuver(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc, maneuver, target_id, attribute, skill = validate_combat_maneuver(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    budget = wire.turn_budget_obj(hero_id, enc.turn_budget)
    fn = _MANEUVER_FNS[maneuver]
    result = fn(
        live.heroes[hero_id],
        live.enemies[target_id],
        attribute=attribute,
        skill=skill,
        rng=rng,
        combat_round=live.combat_round,
        sequencer=live.sequencer,
        caused_by=command.command_id,
        budget=budget,
    )
    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=wire.turn_budget_to_dict(budget),
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=list(result.events),
            new_facts=set(),
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- combat_move / combat_quick_interaction


def validate_combat_move(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    if enc.turn_budget.get("moved"):
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already moved this combat turn")
    if not isinstance(payload.get("target_position"), int):
        raise CommandError(ErrorCode.SCHEMA_ERROR, "target_position must be an int")
    return room, enc


def handle_combat_move(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc = validate_combat_move(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    budget = wire.turn_budget_obj(hero_id, enc.turn_budget)
    combat_evts = combat_actions.move(
        live.heroes[hero_id],
        int(command.payload["target_position"]),
        budget,
        combat_round=live.combat_round,
        sequencer=live.sequencer,
        caused_by=command.command_id,
    )
    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=wire.turn_budget_to_dict(budget),
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=list(combat_evts),
            new_facts=set(),
            seq=seq,
        ),
    )


def validate_combat_quick_interaction(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    if enc.turn_budget.get("quick_interaction_used"):
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} already used a quick interaction this turn")
    return room, enc


def handle_combat_quick_interaction(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc = validate_combat_quick_interaction(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    budget = wire.turn_budget_obj(hero_id, enc.turn_budget)
    description = str(command.payload.get("description", "quick interaction"))[:200]
    combat_evts = combat_actions.quick_interaction(
        live.heroes[hero_id],
        budget,
        combat_round=live.combat_round,
        sequencer=live.sequencer,
        caused_by=command.command_id,
        description=description,
    )
    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=wire.turn_budget_to_dict(budget),
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=list(combat_evts),
            new_facts=set(),
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- combat_stabilize (§16.2-16.3)


def validate_combat_stabilize(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    _require_main_action_free(enc, hero_id)
    target_id = payload.get("target_hero_id")
    if target_id not in enc.heroes:
        raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown ally {target_id!r}")
    if enc.heroes[target_id]["life_state"] != LIFE_STATE_DOWNED:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{target_id} is not Downed")
    return room, enc, target_id


def handle_combat_stabilize(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc, target_id = validate_combat_stabilize(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    budget = wire.turn_budget_obj(hero_id, enc.turn_budget)
    budget.mark_main_action()
    combat_evts = combat_lifecycle.stabilize_directly(
        live.heroes[target_id],
        combat_round=live.combat_round,
        sequencer=live.sequencer,
        caused_by=command.command_id,
        actor_id=hero_id,
    )
    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=wire.turn_budget_to_dict(budget),
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=list(combat_evts),
            new_facts=set(),
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- combat_barricade (§15.2 delay route)


def validate_combat_barricade(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    _require_main_action_free(enc, hero_id)
    if not any(not w["arrived"] for w in enc.reinforcement_waves):
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "no pending reinforcements to delay")
    extra = payload.get("extra_delay_rounds")
    if not isinstance(extra, int) or extra <= 0:
        raise CommandError(ErrorCode.SCHEMA_ERROR, "extra_delay_rounds must be a positive int")
    return room, enc, extra


def handle_combat_barricade(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc, extra = validate_combat_barricade(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    budget = wire.turn_budget_obj(hero_id, enc.turn_budget)
    budget.mark_main_action()
    combat_evts: list[dict] = []
    for wave in live.reinforcement_waves:
        if not wave.arrived:
            combat_evts.extend(
                combat_threat.delay_reinforcements(
                    wave,
                    extra,
                    hero_id=hero_id,
                    combat_round=live.combat_round,
                    sequencer=live.sequencer,
                    caused_by=command.command_id,
                )
            )
    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=wire.turn_budget_to_dict(budget),
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=combat_evts,
            new_facts=set(),
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- combat_reaction (§14.5)


def validate_combat_reaction(state: RunState, hero_id, payload):
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    enc = room.encounter
    if enc is None or enc.status != "active" or hero_id not in enc.heroes:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is not an active encounter combatant")
    if not enc.heroes[hero_id]["reaction_available"]:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} has no reaction available this round")
    reaction = payload.get("reaction")
    if reaction not in ("dodge", "block", "protect", "counter", "escape"):
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown reaction {reaction!r}")
    return room, enc, reaction


def handle_combat_reaction(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc, reaction = validate_combat_reaction(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    hero = live.heroes[hero_id]
    payload = command.payload

    if reaction == "dodge":
        _, combat_evts = combat_reactions.dodge(
            hero,
            int(payload.get("incoming_attack_total", 0)),
            rng,
            combat_round=live.combat_round,
            sequencer=live.sequencer,
            caused_by=command.command_id,
            new_position=payload.get("new_position"),
        )
    elif reaction == "block":
        _, combat_evts = combat_reactions.block(
            hero,
            int(payload.get("incoming_damage", 0)),
            item_id=str(payload.get("item_id") or hero.held_item or "weapon"),
            block_amount=_DEFAULT_BLOCK_AMOUNT,
            rng=rng,
            combat_round=live.combat_round,
            sequencer=live.sequencer,
            caused_by=command.command_id,
        )
    elif reaction == "protect":
        ally_id = payload.get("ally_hero_id")
        if ally_id not in live.heroes:
            raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown ally {ally_id!r}")
        combat_evts = combat_reactions.protect(
            hero, live.heroes[ally_id], combat_round=live.combat_round, sequencer=live.sequencer, caused_by=command.command_id
        )
    elif reaction == "counter":
        attacker_id = payload.get("attacker_id")
        attacker = live.enemies.get(attacker_id) or live.heroes.get(attacker_id)
        if attacker is None:
            raise CommandError(ErrorCode.UNKNOWN_TARGET, f"unknown attacker {attacker_id!r}")
        _, combat_evts = combat_reactions.counter(
            hero,
            attacker,
            int(payload.get("incoming_attack_margin", 0)),
            permitted=bool(payload.get("permitted", False)),
            attribute=str(payload.get("attribute", "force")),
            skill=payload.get("skill"),
            rng=rng,
            combat_round=live.combat_round,
            sequencer=live.sequencer,
            caused_by=command.command_id,
        )
    else:  # escape
        _, combat_evts = combat_reactions.escape(
            hero,
            int(payload.get("hold_dc", 11)),
            attribute=str(payload.get("attribute", "finesse")),
            rng=rng,
            combat_round=live.combat_round,
            sequencer=live.sequencer,
            caused_by=command.command_id,
        )

    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=enc.current_actor_id,
            turn_budget=enc.turn_budget,
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=list(combat_evts),
            new_facts=set(),
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- combat_end_turn


def validate_combat_end_turn(state: RunState, hero_id, payload):
    room, enc = _active_encounter_room(state, hero_id)
    _require_current_actor(enc, hero_id)
    return room, enc


def handle_combat_end_turn(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc = validate_combat_end_turn(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    facts = set(state.facts)

    next_id = _next_active_id(live, hero_id)
    cascade_evts, next_id, facts, outcome, pending_reaction = _cascade_enemy_turns(
        live, rng, facts, command.command_id, next_id
    )
    turn_budget: dict = {}
    if pending_reaction is None and next_id is not None and outcome is None:
        begin_evts, turn_budget = _begin_hero_turn(live, next_id, command.command_id)
        cascade_evts = list(cascade_evts) + begin_evts

    turn_submitted = Event(
        event_id=make_event_id(state.world_round, seq),
        run_id=state.run_id,
        world_round=state.world_round,
        caused_by=command.command_id,
        type=EventType.TURN_SUBMITTED,
        visibility=Visibility.PUBLIC,
        actor_hero_id=hero_id,
        room_id=room.room_id,
        payload={},
    )
    result_event = _build_result_event(
        command_id=command.command_id,
        actor_hero_id=hero_id,
        state=state,
        room_id=room.room_id,
        live=live,
        current_actor_id=next_id,
        turn_budget=turn_budget,
        pending_joiners=enc.pending_joiner_hero_ids,
        combat_evts=list(cascade_evts),
        new_facts=(facts - set(state.facts)),
        pending_reaction=pending_reaction,
        seq=seq + 1,
    )
    return (turn_submitted, result_event)


# ---------------------------------------------------------------- resolve_reaction (§14.5/§21.3-21.4, task #16)
#
# Answers a pending reaction window opened by an enemy attack-type intent
# (see `_run_enemy_intent_effects` above). Deliberately bypasses
# `_active_encounter_room` (which now *rejects* any command while a
# reaction is pending) -- reacting is the one thing allowed to happen off
# the current actor's turn, mirroring the pre-existing standalone
# `combat_reaction` command's own off-turn precedent. No numeric bonuses
# are ever accepted from the wire: block_amount/wear_chance/counter-
# permission are the same server-derived defaults used everywhere else in
# this file.

_RESOLVE_REACTION_CHOICES = ("dodge", "block", "protect", "counter", "pass")


def validate_resolve_reaction(state: RunState, hero_id, payload):
    hero = _hero(state, hero_id)
    room = state.map.rooms[hero.room_id]
    enc = room.encounter
    if enc is None or enc.status != "active" or enc.pending_reaction is None:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} has no pending reaction to resolve")
    pending = enc.pending_reaction
    if payload.get("reaction_id") != pending["reaction_id"]:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "stale or unknown reaction_id")
    reaction = payload.get("reaction")
    if reaction not in _RESOLVE_REACTION_CHOICES:
        raise CommandError(ErrorCode.SCHEMA_ERROR, f"unknown reaction {reaction!r}")
    is_defender = hero_id == pending["defender_id"]
    is_protector = hero_id in pending["protector_ids"]
    if not (is_defender or is_protector):
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"{hero_id} is not eligible to answer this pending reaction")
    if reaction == "protect" and not is_protector:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "only a listed protector may choose protect")
    if reaction in ("dodge", "block", "counter") and not is_defender:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, f"only the defending hero may choose {reaction}")
    if reaction == "counter" and pending["margin"] > -5:
        raise CommandError(ErrorCode.ILLEGAL_ACTION, "counter requires the incoming attack to have missed by 5 or more")
    return room, enc, pending, reaction


def handle_resolve_reaction(command: Command, state: RunState, rng, seq: int) -> tuple[Event, ...]:
    hero_id = command.hero_id
    room, enc, pending, reaction = validate_resolve_reaction(state, hero_id, command.payload)
    live = wire.build_live_encounter(enc)
    attacker = live.enemies[pending["attacker_id"]]
    defender = live.heroes[pending["defender_id"]]
    protectors = tuple(live.heroes[pid] for pid in pending["protector_ids"] if pid in live.heroes)
    payload = command.payload

    window = combat_actions.ReactionWindow(
        attacker=attacker,
        defender=defender,
        protectors=protectors,
        hit=pending["hit"],
        margin=pending["margin"],
        incoming_attack_total=pending["incoming_attack_total"],
        provisional_damage=pending["provisional_damage"],
        rng=rng,
        combat_round=live.combat_round,
        sequencer=live.sequencer,
        caused_by=command.command_id,
    )
    pending_attack = combat_actions.PendingAttack(events=[], window=window, action_label=pending["action_label"])

    outcome = None
    if reaction == "dodge":
        success, r_events = combat_reactions.dodge(
            defender, pending["incoming_attack_total"], rng, combat_round=live.combat_round,
            sequencer=live.sequencer, caused_by=command.command_id, new_position=payload.get("new_position"),
        )
        outcome = combat_actions.ReactionOutcome(
            events=r_events,
            hit=(False if success else pending["hit"]),
            damage=(0 if success else pending["provisional_damage"]),
        )
    elif reaction == "block":
        reduced, r_events = combat_reactions.block(
            defender, pending["provisional_damage"],
            item_id=str(payload.get("item_id") or defender.held_item or "weapon"),
            block_amount=_DEFAULT_BLOCK_AMOUNT, rng=rng, combat_round=live.combat_round,
            sequencer=live.sequencer, caused_by=command.command_id,
        )
        outcome = combat_actions.ReactionOutcome(events=r_events, hit=pending["hit"], damage=reduced)
    elif reaction == "protect":
        protector = live.heroes[hero_id]
        r_events = combat_reactions.protect(
            protector, defender, combat_round=live.combat_round, sequencer=live.sequencer, caused_by=command.command_id,
        )
        outcome = combat_actions.ReactionOutcome(
            events=r_events, hit=pending["hit"], damage=pending["provisional_damage"], damage_target=protector,
        )
    elif reaction == "counter":
        _, r_events = combat_reactions.counter(
            defender, attacker, pending["margin"], permitted=True, attribute="force", skill=None, rng=rng,
            combat_round=live.combat_round, sequencer=live.sequencer, caused_by=command.command_id,
        )
        outcome = combat_actions.ReactionOutcome(events=r_events, hit=pending["hit"], damage=pending["provisional_damage"])
    # reaction == "pass": outcome stays None -- §21.4 safe default, reaction not consumed.

    result = combat_actions.resolve_pending_attack(pending_attack, outcome)
    combat_evts = list(result.events)
    facts = set(state.facts)

    remaining_effects = pending.get("remaining_effects") or []
    next_pending: dict | None = None
    if remaining_effects:
        resume_intent = combat_intents.EnemyIntentDef(
            id=pending["source_intent_id"], trigger="", effects=tuple(remaining_effects),
            counterplay="", telegraph_text="", accessible_text="",
        )
        resume_events, facts, next_pending = _run_enemy_intent_effects(
            live, rng, attacker, defender, resume_intent, command.command_id, facts
        )
        combat_evts.extend(resume_events)

    current_actor_id = enc.current_actor_id  # the attacking enemy, unless resolution re-pends on it
    turn_budget = enc.turn_budget
    if next_pending is None:
        next_id = _next_active_id(live, pending["attacker_id"])
        cascade_evts, next_id, facts, outcome_status, next_pending = _cascade_enemy_turns(
            live, rng, facts, command.command_id, next_id
        )
        combat_evts.extend(cascade_evts)
        current_actor_id = next_id
        turn_budget = {}
        if next_pending is None and next_id is not None and outcome_status is None:
            begin_evts, turn_budget = _begin_hero_turn(live, next_id, command.command_id)
            combat_evts.extend(begin_evts)

    return (
        _build_result_event(
            command_id=command.command_id,
            actor_hero_id=hero_id,
            state=state,
            room_id=room.room_id,
            live=live,
            current_actor_id=current_actor_id,
            turn_budget=turn_budget,
            pending_joiners=enc.pending_joiner_hero_ids,
            combat_evts=combat_evts,
            new_facts=(facts - set(state.facts)),
            pending_reaction=next_pending,
            seq=seq,
        ),
    )


# ---------------------------------------------------------------- appliers
# combat_end_turn's TURN_SUBMITTED event reuses systems/turns.py's existing
# applier (apply_turn_submitted) -- nothing to register here for that type.


def _apply_conflict_event(state: RunState, event: Event) -> RunState:
    room = state.map.rooms[event.payload["room_id"]]
    room.encounter = ConflictEncounterState.from_dict(event.payload["encounter"])
    if room.encounter.status != "active":
        # Wave-6 (board task #21, playtest A5): until_end_of_encounter active
        # effects expire the moment THIS encounter ends (victory/party_wiped),
        # not at the next world-round boundary -- scoped to encounter_id so a
        # split party's other still-active encounter is unaffected.
        for hid in room.encounter.heroes:
            hero = state.heroes.get(hid)
            if hero is not None:
                hero.active_effects = ability_systems.expire_boundary(
                    hero.active_effects, boundary="encounter", encounter_id=room.encounter.encounter_id
                )
    for hid, updates in event.payload["hero_updates"].items():
        hero = state.heroes[hid]
        hero.hp = updates["hp"]
        hero.death_failures = updates["death_failures"]
        hero.stabilization_successes = updates["stabilization_successes"]
        hero.sync_life_state(updates["life_state"])
    for hid in event.payload["newly_dead_hero_ids"]:
        hero = state.heroes[hid]
        if hero.carried_item_ids:
            room.body_item_ids[hid] = hero.carried_item_ids
            hero.carried_item_ids = ()
    for fact_id in event.payload.get("new_facts", []):
        if fact_id not in state.facts:
            state.facts = state.facts + (fact_id,)
    return state


def apply_joined_conflict_room(state: RunState, event: Event) -> RunState:
    room = state.map.rooms[event.room_id]
    hero_id = event.payload["hero_id"]
    if room.encounter is not None and hero_id not in room.encounter.heroes:
        if hero_id not in room.encounter.pending_joiner_hero_ids:
            room.encounter.pending_joiner_hero_ids.append(hero_id)
    return state


EVENT_APPLIERS = {
    EventType.CONFLICT_ENCOUNTER_STARTED: _apply_conflict_event,
    EventType.CONFLICT_TURN_RESOLVED: _apply_conflict_event,
    EventType.CONFLICT_ENCOUNTER_ENDED: _apply_conflict_event,
    EventType.JOINED_CONFLICT_ROOM: apply_joined_conflict_room,
}
