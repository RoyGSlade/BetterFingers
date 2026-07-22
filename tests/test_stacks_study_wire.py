"""Study-room domain wiring, end to end (wave6b/slice-wiring, wavebasedgame.md
§3.2, docs/INFINITE_STACKS_STUDY_SLICE.md, docs/INFINITE_STACKS_BRAIN.md).

Drives the real domain reducer directly (same Harness pattern as
tests/test_stacks_shopwire.py / tests/test_stacks_herowire.py) so room/NPC
state stays inspectable for white-box assertions, while still exercising the
real handle() -> events -> reduce() pipeline: breach into a d8=3 study room,
inspect/move the rug, open the compartment, converse with Elara with the
compartment fact as evidence, satisfy the lattice recipe, reveal the stair,
and replay.
"""
from __future__ import annotations

import pytest

from backend.lan_playground.domain import reducer
from backend.lan_playground.domain import replay as replay_mod
from backend.lan_playground.domain.commands import Command, CommandError, CommandType
from backend.lan_playground.domain.events import EventType
from backend.lan_playground.domain.rng import StacksRNG
from backend.lan_playground.domain.state import ConnectorState, RunState

GENERAL_CARD_IDS = ["careful_approach", "steady_nerve"]
PERSONA_CARD_ID = "signature_flourish"

# Seed 6's first breach (after one hero completes character creation) lands
# on a `study` room seeded from the authored `gothic_living_study` template.
# Locked in by a one-off seed search (same style as
# tests/test_stacks_shopwire.py's NO_TREAT_SHOP_SEED/TREAT_SHOP_SEED).
STUDY_SEED = 6


class Harness:
    def __init__(self, run_id="run_studywire", seed=STUDY_SEED, chapter_floor_index=0):
        self.state = RunState.initial(run_id=run_id, seed=seed, chapter_floor_index=chapter_floor_index)
        self.rng = StacksRNG(seed)
        self.seq = 0
        self.event_log: list = []
        self._n = 0

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

    def open_direction_to(self, room_id, target_room_id):
        room = self.state.map.rooms[room_id]
        for d, c in room.connectors.items():
            if c == ConnectorState.OPEN:
                dx, dy = {"north": (0, 1), "south": (0, -1), "east": (1, 0), "west": (-1, 0)}[d.value]
                if f"room_{room.x + dx}_{room.y + dy}" == target_room_id:
                    return d
        return None

    def create_hero(self, hero_id, background_id="exiled_court_scribe", *, name=None):
        self.send(hero_id, CommandType.JOIN_RUN)
        self.send(hero_id, CommandType.ROLL_ATTRIBUTE_DICE)
        dice = self.state.heroes[hero_id].pending_dice
        assignment = {"force": dice[0], "finesse": dice[1], "insight": dice[2], "presence": dice[3]}
        self.send(
            hero_id,
            CommandType.CREATE_HERO,
            {
                "name": name or hero_id,
                "background_id": background_id,
                "attribute_assignment": assignment,
                "general_card_ids": list(GENERAL_CARD_IDS),
                "persona_card_id": PERSONA_CARD_ID,
            },
        )
        return self.state.heroes[hero_id]

    def breach_into_study(self, hero_id):
        entrance = self.state.map.entrance_room_id
        direction = self.door_direction(entrance)
        result = self.send(hero_id, CommandType.BREACH, {"direction": direction.value})
        family = next(e.payload["family"] for e in result.events if e.type == EventType.ROOM_BREACHED)
        assert family == "study", f"expected the documented seed's first breach to be a study, got {family}"
        return self.state.heroes[hero_id].room_id

    def refresh_energy(self):
        """Pass every currently-joined living hero to force a world-round
        boundary (Energy refresh) without touching room/study state. The
        round only advances once ALL living/conscious heroes have passed
        (S8.2), so this must cover every joined hero, not just the caller's
        acting one."""
        for hero_id, hero in list(self.state.heroes.items()):
            if hero.alive and hero.conscious and not hero.submitted_turn:
                self.send(hero_id, CommandType.PASS)


def _study_and_npc(h: Harness, hero_id: str):
    hero = h.state.heroes[hero_id]
    room = h.state.map.rooms[hero.room_id]
    return room.study, room.study.npc_id


# --------------------------------------------------------------------------- instantiate on breach


def test_breach_into_d8_3_instantiates_the_authored_study_room():
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    study = h.state.map.rooms[room_id].study

    assert study is not None
    assert study.room_template_id == "gothic_living_study"
    assert study.npc_id == "elara_vance"
    assert study.object_state_ids["study_rug"] == "rug_undisturbed"
    assert study.object_state_ids["hidden_compartment"] == "compartment_hidden"
    assert h.state.floor_lattice_recipe_id == "recipe_test_floor_study_only"


# --------------------------------------------------------------------------- interact


def test_interact_look_promotes_a_fact_without_changing_object_state():
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    result = h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_look"})

    assert any(e.type == EventType.FACT_EMITTED for e in result.events)
    assert any(e.type == EventType.FACT_PROMOTED for e in result.events)
    assert not any(e.type == EventType.OBJECT_STATE_CHANGED for e in result.events)
    study = h.state.map.rooms[room_id].study
    assert study.object_state_ids["study_rug"] == "rug_undisturbed"


def test_interact_move_rug_reveals_compartment_and_registers_lattice_on_open():
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")

    move_result = h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    study = h.state.map.rooms[room_id].study
    assert study.object_state_ids["study_rug"] == "rug_displaced"
    # Payoff-cascade: the hidden compartment promotes from hidden to noticed
    # as a direct consequence of the payoff interaction firing (docs/
    # INFINITE_STACKS_STUDY_SLICE.md §7 step 1).
    assert study.object_state_ids["hidden_compartment"] == "compartment_closed"
    assert not study.resolved

    h.refresh_energy()
    open_result = h.send("hero_a", CommandType.INTERACT, {"object_id": "hidden_compartment", "interaction_id": "compartment_open_action"})
    study = h.state.map.rooms[room_id].study
    assert study.object_state_ids["hidden_compartment"] == "compartment_open"
    assert study.resolved
    assert any(e.type == EventType.LATTICE_CONTRIBUTION_REGISTERED for e in open_result.events)
    assert any(e.type == EventType.LATTICE_RECIPE_SATISFIED for e in open_result.events)
    assert any(e.type == EventType.STAIR_REVEALED for e in open_result.events)
    assert h.state.stair_revealed
    assert h.state.resolved_lattice_contributions[room_id] == {"truth": 2, "memory": 1}


def test_interact_one_shot_interaction_cannot_fire_twice():
    h = Harness()
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    h.refresh_energy()
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})


def test_interact_illegal_state_is_rejected():
    """compartment_open_action is only legal in compartment_closed -- before
    the rug has been moved, the compartment is still compartment_hidden."""
    h = Harness()
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.INTERACT, {"object_id": "hidden_compartment", "interaction_id": "compartment_open_action"})


# --------------------------------------------------------------------------- zero-intent / unsupported


def test_interact_unsupported_verb_yields_response_and_content_gap_never_bare_error():
    h = Harness()
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    result = h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "gibberish_verb_xyz"})

    artifact_events = [e for e in result.events if e.type == EventType.RESPONSE_ARTIFACT_EMITTED]
    gap_events = [e for e in result.events if e.type == EventType.CONTENT_GAP_LOGGED]
    assert len(artifact_events) == 1
    assert artifact_events[0].payload["kind"] == "unsupported"
    assert len(gap_events) == 1
    assert gap_events[0].payload["reason"] == "no_handler"
    assert gap_events[0].payload["attempted_target"] == "study_rug"
    # Persisted as a domain event (director ruling, board note 31/32): the
    # record also lands on RunState.content_gaps, never a player projection.
    assert len(h.state.content_gaps) == 1
    assert h.state.content_gaps[0]["reason"] == "no_handler"


def test_interact_unknown_object_is_a_hard_unknown_target_error():
    """A genuinely nonexistent object (not just an unsupported verb on a real
    object) is a schema-level UNKNOWN_TARGET -- distinct from the zero-intent/
    unsupported-verb response path, which requires a real target."""
    h = Harness()
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.INTERACT, {"object_id": "totally_not_a_real_object", "interaction_id": "look"})


# --------------------------------------------------------------------------- converse / social check


def test_converse_without_evidence_uses_none_tier():
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    study, npc_id = _study_and_npc(h, "hero_a")

    result = h.send("hero_a", CommandType.CONVERSE, {"npc_id": npc_id})
    check_event = next(e for e in result.events if e.type == EventType.SOCIAL_CHECK_RESOLVED)
    assert check_event.payload["evidence_tier"] == "none"
    assert check_event.payload["npc_id"] == "elara_vance"
    assert check_event.payload["outcome"] in ("strong_success", "clean_success", "cost_progress", "setback")


def test_converse_with_compartment_evidence_promoted_gets_verifiable_tier_and_higher_modifier():
    h = Harness()
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")

    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    h.refresh_energy()
    h.send("hero_a", CommandType.INTERACT, {"object_id": "hidden_compartment", "interaction_id": "compartment_open_action"})
    h.refresh_energy()

    study = h.state.map.rooms[room_id].study
    assert "fact_compartment_contents_revealed" in study.promoted_fact_ids["hero_a"]

    result = h.send("hero_a", CommandType.CONVERSE, {"npc_id": study.npc_id})
    check_event = next(e for e in result.events if e.type == EventType.SOCIAL_CHECK_RESOLVED)
    assert check_event.payload["evidence_tier"] == "verifiable"
    assert check_event.payload["modifier"] > 0

    # Real check resolution goes through systems.checks.outcome_for_margin --
    # the payload's outcome must be one of that enum's values.
    from backend.lan_playground.systems import checks as checks_module

    assert check_event.payload["outcome"] in {o.value for o in checks_module.Outcome}


def test_converse_rejects_when_no_npc_present():
    h = Harness()
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    with pytest.raises(CommandError):
        h.send("hero_a", CommandType.CONVERSE, {"npc_id": "not_a_real_npc"})


def test_converse_disposition_or_objective_change_persists_on_npc_state():
    """Whichever rich-outcome branch the seeded pick lands on
    (disposition_change or objective_change), the resulting NPC state must be
    reflected on StudyRoomState after the command."""
    h = Harness(seed=STUDY_SEED)
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    study, npc_id = _study_and_npc(h, "hero_a")
    original_disposition = study.npc_disposition

    result = h.send("hero_a", CommandType.CONVERSE, {"npc_id": npc_id})
    check_event = next(e for e in result.events if e.type == EventType.SOCIAL_CHECK_RESOLVED)
    rich_outcome = check_event.payload["rich_outcome"]
    study = h.state.map.rooms[room_id].study

    if rich_outcome == "disposition_change":
        assert any(e.type == EventType.NPC_DISPOSITION_CHANGED for e in result.events)
        assert study.npc_disposition != original_disposition
    elif rich_outcome == "objective_change":
        assert any(e.type == EventType.NPC_OBJECTIVE_CHANGED for e in result.events)
        assert study.npc_objective_states


# --------------------------------------------------------------------------- appeal mechanism (director review fix)


def _converse_check_payload(payload_extra: dict) -> dict:
    """Run the identical scenario (same seed, same command sequence) up to a
    single converse whose payload carries `payload_extra`, and return the
    SOCIAL_CHECK_RESOLVED payload. Because the RNG stream is identical
    across runs, any difference between two calls' returned payloads is
    attributable solely to the payload difference."""
    h = Harness(seed=STUDY_SEED)
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    study, npc_id = _study_and_npc(h, "hero_a")
    result = h.send("hero_a", CommandType.CONVERSE, {"npc_id": npc_id, **payload_extra})
    return next(e for e in result.events if e.type == EventType.SOCIAL_CHECK_RESOLVED).payload


def test_client_claimed_motive_alignment_field_is_ignored():
    """Standing rule #5: no client-supplied modifiers, ever. A payload
    claiming the old `motive_alignment` field (up to +4 if honored) must
    produce the exact same check result as sending no field at all."""
    claimed = _converse_check_payload({"motive_alignment": "strongly_aligned"})
    baseline = _converse_check_payload({})
    assert claimed == baseline
    assert claimed["motive_alignment"] == "neutral"
    assert claimed["modifier"] == baseline["modifier"]


def test_appeal_to_disclosed_main_objective_improves_modifier():
    """Appealing to one of Elara's PARTY-scoped (i.e. openly disclosed by
    authored viewer_scope) main objectives is a roleplay choice the engine
    honors by deriving STRONGLY_ALIGNED at the bottom of the tier's range
    (+2 -- no primary/most-valued marker exists in her authored data, so
    nothing can justify the tier's upper values)."""
    baseline = _converse_check_payload({})
    appealed = _converse_check_payload({"appeal_objective_id": "objective_protect_the_letters"})

    assert appealed["motive_alignment"] == "strongly_aligned"
    assert appealed["appeal_objective_id"] == "objective_protect_the_letters"
    assert appealed["appeal_recognized"] is True
    assert appealed["modifier"] > baseline["modifier"]
    assert appealed["modifier"] - baseline["modifier"] == 2  # bottom of the +2..+4 tier, capped


def test_appeal_to_undisclosed_hidden_objective_grants_nothing():
    """Elara's hidden objective is ENGINE_ONLY-scoped -- never disclosed to
    any player viewer. Appealing to it grants nothing: you cannot leverage
    what you don't know."""
    baseline = _converse_check_payload({})
    appealed = _converse_check_payload({"appeal_objective_id": "objective_hidden_avoid_confronting_death"})

    assert appealed["motive_alignment"] == "neutral"
    assert appealed["appeal_recognized"] is False
    assert appealed["modifier"] == baseline["modifier"]


def test_unknown_appeal_id_degrades_to_neutral_never_an_error():
    """A garbage appeal id is NOT an error dead-end (§2.3 always-a-response):
    the converse still resolves (neutral motive) and still emits its
    response artifact."""
    h = Harness(seed=STUDY_SEED)
    h.create_hero("hero_a")
    h.breach_into_study("hero_a")
    study, npc_id = _study_and_npc(h, "hero_a")

    result = h.send("hero_a", CommandType.CONVERSE, {"npc_id": npc_id, "appeal_objective_id": "gibberish_objective_xyz"})
    check_event = next(e for e in result.events if e.type == EventType.SOCIAL_CHECK_RESOLVED)
    assert check_event.payload["motive_alignment"] == "neutral"
    assert check_event.payload["appeal_recognized"] is False
    assert any(e.type == EventType.RESPONSE_ARTIFACT_EMITTED for e in result.events)


# --------------------------------------------------------------------------- full E2E loop (exit gate)


def _run_full_e2e_scenario(seed: int = STUDY_SEED):
    h = Harness(seed=seed)
    h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")

    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_look"})
    h.refresh_energy()
    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    h.refresh_energy()
    h.send("hero_a", CommandType.INTERACT, {"object_id": "hidden_compartment", "interaction_id": "compartment_open_action"})
    h.refresh_energy()

    study = h.state.map.rooms[room_id].study
    # Converse WITH an appeal to a disclosed main objective, so the
    # seed-determinism and replay exit-gate tests below also prove the
    # appeal-derived motive path is fully deterministic/replayable.
    h.send(
        "hero_a",
        CommandType.CONVERSE,
        {"npc_id": study.npc_id, "appeal_objective_id": "objective_protect_the_letters"},
    )
    return h


def test_full_join_create_study_compartment_converse_lattice_stair_e2e():
    h = _run_full_e2e_scenario()
    room_id = h.state.heroes["hero_a"].room_id
    study = h.state.map.rooms[room_id].study

    assert study.resolved
    assert h.state.stair_revealed
    assert h.state.resolved_lattice_contributions[room_id] == {"truth": 2, "memory": 1}
    assert any(e.type == EventType.SOCIAL_CHECK_RESOLVED for e in h.event_log)
    assert any(e.type == EventType.STAIR_REVEALED for e in h.event_log)


def test_seed_deterministic_same_seed_twice_identical_event_logs():
    h1 = _run_full_e2e_scenario(seed=STUDY_SEED)
    h2 = _run_full_e2e_scenario(seed=STUDY_SEED)

    def strip_run_id(events):
        return [(e.event_id, e.caused_by, e.actor_hero_id, e.room_id, e.type, e.visibility, e.payload) for e in events]

    assert strip_run_id(h1.event_log) == strip_run_id(h2.event_log)


# --------------------------------------------------------------------------- cross-player privacy (exit gate)


def test_cross_player_disclosure_privacy_never_leaks_between_viewers():
    """A gated fact or hidden-state detail promoted for viewer A must never
    appear in viewer B's per-viewer promoted-fact/object ledger -- proven
    directly at the wiring seam (StudyRoomState's per-hero dicts), since no
    client-facing projection exists yet this part."""
    h = Harness(seed=STUDY_SEED)
    hero_a = h.create_hero("hero_a")
    room_id = h.breach_into_study("hero_a")
    hero_b_id = "hero_b"
    h.send(hero_b_id, CommandType.JOIN_RUN)
    # Move hero_b into the same room via direct state surgery is out of scope
    # for a domain-command-only harness; instead prove privacy the way the
    # engine actually enforces it -- per-hero promotion ledgers keyed by
    # hero_id, verified nobody but the acting hero (alone in the room) ever
    # gets an entry.
    h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    study = h.state.map.rooms[room_id].study

    assert "hero_a" in study.promoted_object_ids
    assert hero_b_id not in study.promoted_object_ids
    assert hero_b_id not in study.promoted_fact_ids

    h.refresh_energy()
    h.send("hero_a", CommandType.INTERACT, {"object_id": "hidden_compartment", "interaction_id": "compartment_open_action"})
    study = h.state.map.rooms[room_id].study

    assert "fact_compartment_contents_revealed" in study.promoted_fact_ids.get("hero_a", ())
    assert "fact_compartment_contents_revealed" not in study.promoted_fact_ids.get(hero_b_id, ())
    assert study.promoted_fact_ids.get(hero_b_id, ()) == ()
    assert study.promoted_object_ids.get(hero_b_id, ()) == ()

    # Every FACT_PROMOTED event is PRIVATE and names exactly one authorized
    # viewer_hero_id -- never hero_b's id for any of hero_a's promotions.
    for event in h.event_log:
        if event.type == EventType.FACT_PROMOTED:
            assert event.payload["viewer_hero_id"] == "hero_a"


def test_two_heroes_in_same_room_promotions_are_still_per_viewer():
    """When two heroes ARE in the same study room, an interaction promotes
    facts/objects to both of them (party-scoped per §3.3) -- but each
    promotion is still a separate PRIVATE, per-viewer ledger entry/event,
    never a single shared PUBLIC fact that erases the per-viewer boundary."""
    h = Harness(seed=STUDY_SEED)
    h.create_hero("hero_a")
    entrance_id = h.state.map.entrance_room_id
    room_id = h.breach_into_study("hero_a")

    h.create_hero("hero_b")
    # hero_a's breach already opened this connector (ConnectorState.OPEN on
    # both ends) -- hero_b walks through the same now-open connector via
    # MOVE (not BREACH, which only targets an unopened DOOR) to land in the
    # exact same room hero_a is in, deterministically.
    direction = h.open_direction_to(entrance_id, room_id)
    h.send("hero_b", CommandType.MOVE, {"direction": direction.value})
    assert h.state.heroes["hero_b"].room_id == room_id

    result = h.send("hero_a", CommandType.INTERACT, {"object_id": "study_rug", "interaction_id": "rug_move"})
    study = h.state.map.rooms[room_id].study

    # rug_move both reveals its own new state (study_rug) and cascades a
    # promotion onto the payoff-linked hidden_compartment -- both objects
    # promoted for both heroes currently in the room.
    assert "study_rug" in study.promoted_object_ids.get("hero_a", ())
    assert "hidden_compartment" in study.promoted_object_ids.get("hero_a", ())
    assert "hidden_compartment" in study.promoted_object_ids.get("hero_b", ())

    private_events = [e for e in result.events if e.type == EventType.FACT_PROMOTED]
    viewer_ids_seen = {e.payload["viewer_hero_id"] for e in private_events}
    assert viewer_ids_seen == {"hero_a", "hero_b"}
    for event in private_events:
        assert event.visibility.value == "private"


# --------------------------------------------------------------------------- replay (exit gate)


def test_replay_full_event_log_reproduces_identical_state_hash():
    h = _run_full_e2e_scenario()
    expected_hash = h.state.state_hash()

    replayed = replay_mod.replay(
        run_id=h.state.run_id,
        seed=h.state.seed,
        chapter_floor_index=h.state.chapter_floor_index,
        events=h.event_log,
    )
    assert replayed.state_hash() == expected_hash
    assert replay_mod.verify_replay(
        run_id=h.state.run_id,
        seed=h.state.seed,
        chapter_floor_index=h.state.chapter_floor_index,
        events=h.event_log,
        expected_hash=expected_hash,
    )
