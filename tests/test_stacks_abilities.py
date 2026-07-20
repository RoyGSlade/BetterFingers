"""Abilities system + active-effect durations + knowledge-slot exemption +
avatar/color + connector-cost projections (wave 6 playtest response, board
task #21; docs/PLAYTEST_FINDINGS_2026-07-19.md items A5/E1/E4/F1/C1).

Drives the real domain reducer directly (same Harness pattern as
tests/test_stacks_herowire.py / tests/test_stacks_conflict.py). Real content
this wave: packs/core/abilities.yaml (stacks-carddesign, board task #20) has
exactly 4 abilities -- keen_observer (general, on_room_enter, unlimited),
plain_speaking (general, manual, once_per_room), trophy_notes
(retired_monster_hunter, manual, once_per_fight), veteran_instinct
(retired_monster_hunter, on_encounter_start, unlimited) -- all grant_check
only (LIVE).
"""
from __future__ import annotations

import pytest

from backend.lan_playground import stacks_engine
from backend.lan_playground.content import loader as content_loader
from backend.lan_playground.domain import reducer
from backend.lan_playground.domain.commands import Command, CommandError, CommandType
from backend.lan_playground.domain.events import Event, EventType, Visibility
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import (
    AVATAR_COLORS,
    AVATAR_IDS,
    AbilityState,
    ActiveEffectState,
    ConnectorState,
    RunState,
)
from backend.lan_playground.systems import abilities as ability_systems
from backend.lan_playground.systems import heroes_wire

PACK = content_loader.load_core_pack()
GENERAL_CARD_IDS = ["careful_approach", "steady_nerve"]
PERSONA_CARD_ID = "signature_flourish"

# Seed 12: retired_monster_hunter's first breach after full character
# creation (which consumes RNG for dice + deck shuffle before the breach's
# own d8 draw) lands in a `conflict` room -- found by brute-force search,
# verified stable by inspection.
CONFLICT_SEED = 12


class Harness:
    def __init__(self, run_id="run_abilities", seed=1, chapter_floor_index=0):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self._n = 0
        self.event_log: list = []

    def send(self, hero_id, ctype, payload=None):
        self._n += 1
        cmd = Command(
            command_id=f"cmd_{self._n}",
            idempotency_key=f"cmd_{self._n}",
            run_id=self.state.run_id,
            type=ctype,
            hero_id=hero_id,
            expected_revision=self.state.revision,
            payload=payload or {},
        )
        result = reducer.apply(cmd, self.state, self.rng, viewer=hero_id, seq=self.seq)
        self.state = result.state
        self.seq = result.next_seq
        self.event_log.extend(result.events)
        return result

    def door_direction(self, room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.DOOR:
                return d
        return None

    def create_hero(self, hero_id, background_id, *, name=None, avatar_id=None, color=None):
        self.send(hero_id, CommandType.JOIN_RUN)
        self.send(hero_id, CommandType.ROLL_ATTRIBUTE_DICE)
        dice = self.state.heroes[hero_id].pending_dice
        assignment = {"force": dice[0], "finesse": dice[1], "insight": dice[2], "presence": dice[3]}
        payload = {
            "name": name or hero_id,
            "background_id": background_id,
            "attribute_assignment": assignment,
            "general_card_ids": list(GENERAL_CARD_IDS),
            "persona_card_id": PERSONA_CARD_ID,
        }
        if avatar_id is not None:
            payload["avatar_id"] = avatar_id
        if color is not None:
            payload["color"] = color
        self.send(hero_id, CommandType.CREATE_HERO, payload)
        return self.state.heroes[hero_id]


# --------------------------------------------------------------------------- systems/abilities.py units


def test_initial_ability_state_manual_charge_scopes():
    class FakeDef:
        id = "test_ability"

    for frequency, scope in (("once_per_floor", "floor"), ("once_per_room", "room"), ("once_per_fight", "fight")):
        FakeDef.frequency = frequency
        FakeDef.trigger = "manual"
        a = ability_systems.initial_ability_state(FakeDef)
        assert a.charges_remaining == 1
        assert a.max_charges == 1
        assert ability_systems.scope_for_frequency(a.frequency) == scope


def test_initial_ability_state_unlimited_frequency_has_no_charges():
    class FakeDef:
        id = "always_on"
        trigger = "passive"
        frequency = "unlimited"

    a = ability_systems.initial_ability_state(FakeDef)
    assert a.charges_remaining is None
    assert a.max_charges is None
    assert ability_systems.scope_for_frequency(a.frequency) is None


def test_scope_for_frequency_rejects_unknown():
    with pytest.raises(ability_systems.AbilityError):
        ability_systems.scope_for_frequency("once_per_blue_moon")


def test_spend_charge_exhausts_and_raises():
    a = AbilityState(ability_id="x", trigger="manual", frequency="once_per_room", charges_remaining=1, max_charges=1)
    spent = ability_systems.spend_charge(a)
    assert spent.charges_remaining == 0
    with pytest.raises(ability_systems.AbilityError):
        ability_systems.spend_charge(spent)


def test_spend_charge_on_unlimited_ability_is_a_noop():
    a = AbilityState(ability_id="x", trigger="on_room_enter", frequency="unlimited", charges_remaining=None, max_charges=None)
    assert ability_systems.spend_charge(a) == a


def test_refresh_boundary_only_refreshes_matching_scope():
    abilities = {
        "room_ability": AbilityState(ability_id="room_ability", trigger="manual", frequency="once_per_room", charges_remaining=0, max_charges=1),
        "fight_ability": AbilityState(ability_id="fight_ability", trigger="manual", frequency="once_per_fight", charges_remaining=0, max_charges=1),
    }
    refreshed = ability_systems.refresh_boundary(abilities, "room")
    assert refreshed["room_ability"].charges_remaining == 1
    assert refreshed["fight_ability"].charges_remaining == 0  # untouched -- different scope


# --------------------------------------------------------------------------- real content wiring


def test_every_hero_gets_the_general_abilities_regardless_of_background():
    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    assert "keen_observer" in hero.abilities
    assert "plain_speaking" in hero.abilities
    assert "trophy_notes" not in hero.abilities  # background-scoped to retired_monster_hunter
    assert "veteran_instinct" not in hero.abilities


def test_background_scoped_abilities_only_granted_to_that_background():
    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "retired_monster_hunter")
    assert "trophy_notes" in hero.abilities
    assert "veteran_instinct" in hero.abilities
    assert hero.abilities["trophy_notes"].charges_remaining == 1
    assert hero.abilities["veteran_instinct"].charges_remaining is None  # unlimited, on_encounter_start


def test_keen_observer_on_room_enter_fires_automatically_on_every_breach():
    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    direction = h.door_direction(hero.room_id)
    assert direction is not None
    result = h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    checks = [e for e in result.events if e.type == EventType.CHECK_RESOLVED]
    assert any(c.payload["attribute"] == "insight" and c.payload["skill"] == "read" and c.payload["dc"] == 11 for c in checks)
    # unlimited frequency: no charge to consume, ability stays exactly as-is
    hero = h.state.heroes["hero_a"]
    assert hero.abilities["keen_observer"].charges_remaining is None


def test_use_ability_rejects_unknown_ability_id():
    h = Harness(seed=2)
    h.create_hero("hero_a", "exiled_court_scribe")
    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "not_real"})
    assert exc.value.code.value == "unknown_target"


def test_use_ability_rejects_non_manual_trigger():
    h = Harness(seed=2)
    h.create_hero("hero_a", "exiled_court_scribe")
    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "keen_observer"})
    assert exc.value.code.value == "illegal_action"


def test_plain_speaking_manual_ability_spends_and_refreshes_at_room_boundary():
    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    assert hero.abilities["plain_speaking"].charges_remaining == 1

    result = h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "plain_speaking"})
    types = [e.type for e in result.events]
    assert EventType.ABILITY_USED in types
    check = next(e for e in result.events if e.type == EventType.CHECK_RESOLVED)
    assert check.payload["attribute"] == "presence" and check.payload["skill"] == "wordcraft" and check.payload["dc"] == 8

    hero = h.state.heroes["hero_a"]
    assert hero.abilities["plain_speaking"].charges_remaining == 0

    with pytest.raises(CommandError) as exc:
        h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "plain_speaking"})
    assert exc.value.code.value == "illegal_action"

    # breaching is a room boundary -- once_per_room ability charges refresh
    direction = h.door_direction(hero.room_id)
    result = h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    assert any(e.type == EventType.ABILITY_CHARGE_REFRESHED and e.payload["boundary"] == "room" for e in result.events)
    hero = h.state.heroes["hero_a"]
    assert hero.abilities["plain_speaking"].charges_remaining == 1
    h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "plain_speaking"})  # no longer raises


def test_trophy_notes_once_per_fight_refreshes_when_the_fight_starts():
    # Seed 5: spending trophy_notes first (an extra grant_check RNG draw)
    # then breaching still lands in `conflict` -- found by brute-force search
    # over the exact command sequence below, verified stable by inspection.
    trophy_notes_conflict_seed = 5
    h = Harness(seed=trophy_notes_conflict_seed)
    hero = h.create_hero("hero_a", "retired_monster_hunter")
    assert hero.abilities["trophy_notes"].charges_remaining == 1

    h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "trophy_notes"})
    hero = h.state.heroes["hero_a"]
    assert hero.abilities["trophy_notes"].charges_remaining == 0

    direction = h.door_direction(hero.room_id)
    result = h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
    assert family == "conflict", f"expected seed {trophy_notes_conflict_seed} to land in conflict, got {family}"
    assert any(e.type == EventType.ABILITY_CHARGE_REFRESHED and e.payload["boundary"] == "fight" for e in result.events)

    hero = h.state.heroes["hero_a"]
    assert hero.abilities["trophy_notes"].charges_remaining == 1


def test_veteran_instinct_on_encounter_start_fires_automatically():
    h = Harness(seed=CONFLICT_SEED)
    hero = h.create_hero("hero_a", "retired_monster_hunter")
    direction = h.door_direction(hero.room_id)
    result = h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
    assert family == "conflict"
    checks = [e for e in result.events if e.type == EventType.CHECK_RESOLVED]
    assert any(c.payload["attribute"] == "finesse" and c.payload["skill"] == "read" and c.payload["dc"] == 8 for c in checks)


# --------------------------------------------------------------------------- active-effect durations


def test_use_ability_leaves_an_until_end_of_turn_active_effect_that_expires_on_pass():
    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "plain_speaking"})
    hero = h.state.heroes["hero_a"]
    assert len(hero.active_effects) == 1
    effect = hero.active_effects[0]
    assert effect.duration == "until_end_of_turn"
    assert effect.source_id == "plain_speaking"

    h.send("hero_a", CommandType.PASS)
    hero = h.state.heroes["hero_a"]
    assert hero.active_effects == ()


def test_until_end_of_round_active_effect_expires_at_world_round_advance():
    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    injected = ActiveEffectState(
        effect_id="fx1", source_id="test", label="Test Buff", duration="until_end_of_round", applied_world_round=1
    )
    hero.active_effects = (injected,)
    assert h.state.heroes["hero_a"].active_effects == (injected,)

    h.send("hero_a", CommandType.PASS)  # only living hero -- round completes
    hero = h.state.heroes["hero_a"]
    assert hero.active_effects == ()
    assert h.state.world_round == 2


def test_until_end_of_encounter_active_effect_survives_a_round_boundary_but_not_encounter_end():
    h = Harness(seed=CONFLICT_SEED)
    hero = h.create_hero("hero_a", "retired_monster_hunter")
    direction = h.door_direction(hero.room_id)
    h.send("hero_a", CommandType.BREACH, {"direction": direction.value})
    hero = h.state.heroes["hero_a"]
    room_id = hero.room_id
    encounter = h.state.map.rooms[room_id].encounter
    assert encounter is not None and encounter.status == "active"

    injected = ActiveEffectState(
        effect_id="fx2",
        source_id="test",
        label="Combat Buff",
        duration="until_end_of_encounter",
        applied_world_round=h.state.world_round,
        encounter_id=encounter.encounter_id,
    )
    hero.active_effects = hero.active_effects + (injected,)

    # a round boundary alone must NOT expire an until_end_of_encounter effect.
    # hero_a is mid-encounter (PASS is illegal there -- combat has its own
    # turn-submission commands), so drive the boundary directly through the
    # same WORLD_ROUND_ADVANCED event turns.py's real applier handles.
    round_event = Event(
        event_id="evt_synthetic_round",
        run_id=h.state.run_id,
        world_round=h.state.world_round,
        caused_by="synthetic",
        type=EventType.WORLD_ROUND_ADVANCED,
        visibility=Visibility.PUBLIC,
        payload={"completed_round": h.state.world_round, "next_round": h.state.world_round + 1},
    )
    h.state = reducer.reduce(h.state, round_event)
    hero = h.state.heroes["hero_a"]
    assert any(e.effect_id == "fx2" for e in hero.active_effects)

    # synthesize the encounter actually ending (victory) -- exercises the
    # real combat.py applier registered for CONFLICT_ENCOUNTER_ENDED
    room = h.state.map.rooms[room_id]
    ended_dict = dict(room.encounter.to_dict())
    ended_dict["status"] = "victory"
    ended_event = Event(
        event_id="evt_synthetic",
        run_id=h.state.run_id,
        world_round=h.state.world_round,
        caused_by="synthetic",
        type=EventType.CONFLICT_ENCOUNTER_ENDED,
        visibility=Visibility.PUBLIC,
        room_id=room_id,
        payload={
            "room_id": room_id,
            "encounter": ended_dict,
            "combat_events": [],
            "hero_updates": {},
            "newly_dead_hero_ids": [],
            "new_facts": [],
            "outcome": "victory",
        },
    )
    h.state = reducer.reduce(h.state, ended_event)
    hero = h.state.heroes["hero_a"]
    assert not any(e.effect_id == "fx2" for e in hero.active_effects)


# --------------------------------------------------------------------------- knowledge-tag zero carry slots (E4)


def test_knowledge_tagged_item_consumes_zero_carry_slots_end_to_end():
    family_notes = PACK.items["family_notes"]
    assert family_notes.knowledge is True
    assert family_notes.slot_cost == 0

    h = Harness(seed=2)
    hero = h.create_hero("hero_a", "retired_monster_hunter")  # starts with family_notes
    assert "family_notes" in hero.inventory.items
    # zero slots used by a starting inventory that includes a knowledge item
    # plus battered_buckler (slot_cost 1) -- only the non-knowledge item counts
    assert hero.inventory.used_slots(PACK.items) == 1
    assert hero.inventory.free_slots(PACK.items) == hero.inventory.carry_slots - 1


# --------------------------------------------------------------------------- avatar/color (F1)


def test_create_hero_auto_assigns_distinct_avatar_and_color_per_hero():
    h = Harness(seed=3)
    hero_a = h.create_hero("hero_a", "exiled_court_scribe")
    hero_b = h.create_hero("hero_b", "back_alley_fixer")
    assert hero_a.avatar_id in AVATAR_IDS
    assert hero_b.avatar_id in AVATAR_IDS
    assert hero_a.color in AVATAR_COLORS
    assert hero_b.color in AVATAR_COLORS
    assert hero_a.avatar_id != hero_b.avatar_id
    assert hero_a.color != hero_b.color


def test_create_hero_rejects_avatar_id_outside_the_fixed_list():
    h = Harness(seed=3)
    with pytest.raises(CommandError) as exc:
        h.create_hero("hero_a", "exiled_court_scribe", avatar_id=999)
    assert exc.value.code.value == "schema_error"


def test_create_hero_rejects_color_outside_the_fixed_list():
    h = Harness(seed=3)
    with pytest.raises(CommandError) as exc:
        h.create_hero("hero_a", "exiled_court_scribe", color="mauve")
    assert exc.value.code.value == "schema_error"


def test_create_hero_rejects_avatar_or_color_already_used_this_run():
    h = Harness(seed=3)
    h.create_hero("hero_a", "exiled_court_scribe", avatar_id=1, color="gold")
    with pytest.raises(CommandError) as exc:
        h.create_hero("hero_b", "back_alley_fixer", avatar_id=1, color="crimson")
    assert exc.value.code.value == "illegal_action"
    with pytest.raises(CommandError) as exc:
        h.create_hero("hero_c", "back_alley_fixer", avatar_id=2, color="gold")
    assert exc.value.code.value == "illegal_action"


# --------------------------------------------------------------------------- projections (wire shapes)


def test_legal_actions_move_and_breach_costs_present_only_when_legal():
    adapter = stacks_engine.StacksEngineAdapter()
    wire_state = adapter.create_run(seed=5)
    adapter.apply(wire_state, _join_cmd(wire_state, "hero_a"))
    legal = adapter.legal_actions(wire_state, "hero_a")
    assert legal["breach_costs"], "expected at least one legal breach direction from the entrance"
    for direction in legal["can_breach_directions"]:
        assert legal["breach_costs"][direction] == 3
    for room_id in legal["can_move_to"]:
        assert legal["move_costs"][room_id] == 1


def test_project_exposes_hero_abilities_active_effects_and_avatar():
    adapter = stacks_engine.StacksEngineAdapter()
    wire_state = adapter.create_run(seed=6)
    adapter.apply(wire_state, _join_cmd(wire_state, "hero_a"))
    adapter.apply(wire_state, _cmd(wire_state, "hero_a", CommandType.ROLL_ATTRIBUTE_DICE.value, {}))
    dice = adapter.project(wire_state, "hero_a")["heroes"]["hero_a"]["pending_dice"]
    assignment = {"force": dice[0], "finesse": dice[1], "insight": dice[2], "presence": dice[3]}
    adapter.apply(
        wire_state,
        _cmd(
            wire_state,
            "hero_a",
            CommandType.CREATE_HERO.value,
            {
                "name": "hero_a",
                "background_id": "exiled_court_scribe",
                "attribute_assignment": assignment,
                "general_card_ids": list(GENERAL_CARD_IDS),
                "persona_card_id": PERSONA_CARD_ID,
            },
        ),
    )
    view = adapter.project(wire_state, "hero_a")
    hero_view = view["heroes"]["hero_a"]
    assert isinstance(hero_view["abilities"], list) and hero_view["abilities"]
    ability_entry = next(a for a in hero_view["abilities"] if a["id"] == "plain_speaking")
    assert set(ability_entry) == {"id", "name", "fallback", "accessible", "trigger", "frequency", "available"}
    assert ability_entry["available"] is True
    assert hero_view["active_effects"] == []
    assert hero_view["avatar_id"] in AVATAR_IDS
    assert hero_view["color"] in AVATAR_COLORS

    catalog = adapter.content_catalog()
    assert "plain_speaking" in catalog["abilities"]
    assert catalog["token_options"]["avatar_ids"] == list(AVATAR_IDS)
    assert catalog["token_options"]["colors"] == list(AVATAR_COLORS)


def _join_cmd(wire_state, hero_id):
    return _cmd(wire_state, hero_id, CommandType.JOIN_RUN.value, {"display_name": hero_id})


def _cmd(wire_state, hero_id, ctype, payload):
    from backend.lan_playground.stacks_protocol import Command as WireCommand

    return WireCommand(
        command_id=f"cmd_{hero_id}_{ctype}",
        idempotency_key=f"cmd_{hero_id}_{ctype}",
        run_id=wire_state.run_id,
        hero_id=hero_id,
        encounter_id=None,
        expected_revision=wire_state.revision,
        type=ctype,
        payload=payload,
    )


# --------------------------------------------------------------------------- replay determinism


def test_abilities_and_active_effects_replay_to_the_same_state_hash():
    from backend.lan_playground.domain import replay as replay_mod

    h = Harness(run_id="run_replay_abilities", seed=9)
    hero = h.create_hero("hero_a", "exiled_court_scribe")
    h.send("hero_a", CommandType.USE_ABILITY, {"ability_id": "plain_speaking"})
    direction = h.door_direction(hero.room_id)
    h.send("hero_a", CommandType.BREACH, {"direction": direction.value})

    live_hash = h.state.state_hash()
    replayed = replay_mod.replay(run_id="run_replay_abilities", seed=9, chapter_floor_index=0, events=h.event_log)
    assert replayed.state_hash() == live_hash
    assert replayed.heroes["hero_a"].abilities == h.state.heroes["hero_a"].abilities
    assert replayed.heroes["hero_a"].active_effects == h.state.heroes["hero_a"].active_effects
    assert replayed.heroes["hero_a"].avatar_id == h.state.heroes["hero_a"].avatar_id
    assert replayed.heroes["hero_a"].color == h.state.heroes["hero_a"].color
